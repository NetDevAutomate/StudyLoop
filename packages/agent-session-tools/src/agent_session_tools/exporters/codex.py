"""OpenAI Codex CLI session exporter.

Codex CLI (github.com/openai/codex) stores conversation rollouts as JSONL files
under ``~/.codex/sessions/``.  Each file represents one session and is named
``<session-id>.jsonl`` (the filename stem is used as the stable session ID).

**Assumed on-disk format** (no live data available on this machine — see note below)
====================================================================================
Each line is a JSON object representing one conversation event.  The fields we
consume are:

    {
        "id":        "<uuid>",          # optional — random UUID generated if absent
        "role":      "user" | "assistant" | "system",
        "content":   "<message text>",  # primary text field
        "text":      "<message text>",  # fallback if 'content' is absent
        "timestamp": "<ISO-8601 or unix-float>",  # optional
        "model":     "<model-id>"       # optional, typically on assistant turns
    }

Content may alternatively be an array of ``{"type": "text", "text": "…"}`` objects
(matching the OpenAI Chat Completions content-part format); these are flattened to
plain text separated by newlines.

Session-level metadata may appear in the first line as a ``type: "session_start"``
object with a ``project_path`` field; this is extracted when present but is not
required.

**Why these assumptions?**
The Codex CLI source (as of the May 2026 release) shows its logging module writing
one JSON object per line in this shape.  If real sessions use different field names
(e.g. ``"message"`` instead of ``"content"``), update ``_parse_line()`` — the rest
of the exporter is unaffected.

**Deduplication**: fingerprint-skip (``mtime:size``) matching ``claude.py``.
"""

import json
import sqlite3
import uuid
from pathlib import Path

from ..utils import file_fingerprint
from .base import ExportStats, commit_batch

# Codex CLI session directory
CODEX_SESSIONS_DIR = Path.home() / ".codex" / "sessions"


def _parse_timestamp(ts: str | int | float | None) -> str | None:
    """Normalise a timestamp to ISO-8601 string, or return None."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        from datetime import datetime, timezone

        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    return str(ts)


def _flatten_content(content: str | list | None, text_fallback: str | None) -> str | None:
    """Flatten a content value to plain text.

    Handles three shapes:
    - str  — returned as-is
    - list of {"type":"text","text":"…"} parts — joined with newlines
    - None — falls back to text_fallback, then returns None
    """
    if content is None:
        content = text_fallback
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                else:
                    # Preserve tool_call / function markers as readable tokens
                    name = item.get("name") or item.get("function", {}).get("name", "")
                    if name:
                        parts.append(f"[tool:{name}]")
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts) if parts else None
    # Unexpected type — coerce to string
    return str(content)


def _parse_line(raw: dict) -> dict | None:
    """Parse one JSONL line into a normalised message dict.

    Returns None for lines that are metadata-only (e.g. session_start events)
    and should not be stored as messages.
    """
    # Skip non-message event types
    event_type = raw.get("type")
    if event_type in ("session_start", "session_end", "metadata"):
        return None

    role = raw.get("role")
    if not role:
        return None

    content = _flatten_content(raw.get("content"), raw.get("text"))

    return {
        "id": raw.get("id") or str(uuid.uuid4()),
        "role": role,
        "content": content,
        "model": raw.get("model"),
        "timestamp": _parse_timestamp(raw.get("timestamp")),
    }


class CodexExporter:
    """Exporter for OpenAI Codex CLI JSONL session rollouts.

    Mirrors the ``ClaudeCodeExporter`` pattern: fingerprint-based incremental
    deduplication, batched commits, silent per-line error tolerance.
    """

    source_name = "codex"

    def __init__(self, sessions_dir: Path | None = None) -> None:
        """Initialise the Codex exporter.

        Args:
            sessions_dir: Override the default ``~/.codex/sessions/`` directory.
                          Useful for unit tests pointing at a synthetic fixture.
        """
        self.sessions_dir = sessions_dir or CODEX_SESSIONS_DIR

    def is_available(self) -> bool:
        """Return True only when the Codex sessions directory exists."""
        return self.sessions_dir.exists()

    def export_all(
        self, conn: sqlite3.Connection, incremental: bool = True, batch_size: int = 50
    ) -> ExportStats:
        """Export all rollout files found under ``sessions_dir``.

        Each ``.jsonl`` file is treated as one session.  Files are processed in
        filesystem order; batch commits fire every ``batch_size`` sessions.
        """
        if not self.is_available():
            return ExportStats()

        stats = ExportStats()
        batch: list[dict] = []
        batch_messages: list[dict] = []

        for rollout_file in sorted(self.sessions_dir.glob("*.jsonl")):
            try:
                session_data, msgs = self._process_rollout(conn, rollout_file, incremental)
                if session_data:
                    batch.append(session_data)
                    batch_messages.extend(msgs)
                    if len(batch) >= batch_size:
                        commit_batch(conn, batch, batch_messages, stats)
                        batch = []
                        batch_messages = []
            except Exception:
                stats.errors += 1

        if batch:
            commit_batch(conn, batch, batch_messages, stats)

        return stats

    def _process_rollout(
        self,
        conn: sqlite3.Connection,
        rollout_file: Path,
        incremental: bool,
    ) -> tuple[dict | None, list[dict]]:
        """Parse one rollout JSONL file and return (session_dict, messages_list).

        Returns ``(None, [])`` when the file should be skipped (fingerprint match
        or no parseable messages).
        """
        session_id = f"codex_{rollout_file.stem}"
        fingerprint = file_fingerprint(rollout_file)

        if incremental:
            existing = conn.execute(
                "SELECT import_fingerprint FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if existing and existing[0] == fingerprint:
                return None, []

        messages: list[dict] = []
        first_ts: str | None = None
        last_ts: str | None = None
        project_path: str | None = None

        with open(rollout_file, encoding="utf-8") as fh:
            for raw_line in fh:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    obj = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                # Extract session-level metadata from a session_start event
                if obj.get("type") == "session_start":
                    project_path = obj.get("project_path") or project_path
                    continue

                msg = _parse_line(obj)
                if msg is None:
                    continue

                ts = msg["timestamp"]
                if ts:
                    if first_ts is None:
                        first_ts = ts
                    last_ts = ts

                messages.append(msg)

        if not messages:
            return None, []

        is_update = conn.execute(
            "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()

        session_data: dict = {
            "id": session_id,
            "source": "codex",
            "project_path": project_path or str(rollout_file.parent),
            "git_branch": None,
            "created_at": first_ts,
            "updated_at": last_ts,
            "import_fingerprint": fingerprint,
            "metadata": json.dumps(
                {"fingerprint": fingerprint, "rollout_file": rollout_file.name}
            ),
            "status": "updated" if is_update else "added",
        }

        message_rows = [
            {
                "id": m["id"],
                "session_id": session_id,
                "role": m["role"],
                "content": m["content"],
                "model": m["model"],
                "timestamp": m["timestamp"],
                "metadata": json.dumps({}),
                "seq": idx + 1,
            }
            for idx, m in enumerate(messages)
        ]

        return session_data, message_rows
