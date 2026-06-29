"""OpenAI Codex CLI session exporter.

Codex CLI (github.com/openai/codex) stores conversation rollouts as JSONL files
under a **date-nested** tree::

    ~/.codex/sessions/YYYY/MM/DD/rollout-<ISO-ts>-<uuid>.jsonl

Each file is one session.  Lines are tagged events; we consume two shapes:

``session_meta`` (first line) — session-level metadata::

    {"timestamp": "...", "type": "session_meta",
     "payload": {"id": "<uuid>", "cwd": "/path/to/project",
                 "git": {"branch": "main", "commit_hash": "...", ...},
                 "model_provider": "...", ...}}

``response_item`` with ``payload.type == "message"`` — a conversation turn::

    {"timestamp": "...", "type": "response_item",
     "payload": {"type": "message", "role": "user" | "assistant" | "developer",
                 "content": [{"type": "input_text" | "output_text", "text": "..."}],
                 "model": "<model-id>" | null}}

Other ``response_item`` payload types (``reasoning``, ``function_call``,
``function_call_output``, ``custom_tool_call*``) and other top-level types
(``event_msg``, ``turn_context``) are skipped — only real message turns are
stored.  The ``developer`` role is the injected system prompt (large, noise for
a learning corpus) and is skipped; only ``user`` and ``assistant`` are kept.

The per-message timestamp lives on the **envelope** (``obj["timestamp"]``), not
the payload.

**Deduplication**: fingerprint-skip (``mtime:size``) like ``claude.py``.  Real
rollouts carry no stable per-message id, so message ids are derived as
``<session_id>-<seq>`` (deterministic + idempotent) and existing messages are
deleted before a changed file is re-imported, so a re-import never duplicates
or strands rows.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..utils import file_fingerprint
from .base import ExportStats, commit_batch

# Codex CLI session directory (rollout files live in a YYYY/MM/DD subtree)
CODEX_SESSIONS_DIR = Path.home() / ".codex" / "sessions"

# Roles worth storing — the injected "developer"/"system" prompt is dropped.
_STORED_ROLES = {"user", "assistant"}


def _parse_timestamp(ts: str | int | float | None) -> str | None:
    """Normalise a timestamp to an ISO-8601 string, or return None."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    return str(ts)


def _flatten_content(content: object) -> str | None:
    """Flatten a Codex message ``content`` value to plain text.

    ``content`` is an untrusted JSON value. Handles:
    - str — returned as-is
    - list of content parts — any part carrying a ``text`` key (``input_text``,
      ``output_text``, ``text``) contributes its text; other parts (tool calls,
      images) become ``[tool:<name>]`` markers when a name is present.
    - None — returns None
    - anything else — coerced to ``str`` (defensive against malformed rollouts)
    """
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if "text" in item and isinstance(item["text"], str):
                    parts.append(item["text"])
                else:
                    name = item.get("name") or item.get("function", {}).get("name", "")
                    if name:
                        parts.append(f"[tool:{name}]")
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts) if parts else None
    return str(content)


class CodexExporter:
    """Exporter for OpenAI Codex CLI JSONL session rollouts.

    Mirrors ``ClaudeCodeExporter``: fingerprint-based incremental dedup, batched
    commits, silent per-line/per-file error tolerance.
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
        """Export every rollout file found anywhere under ``sessions_dir``.

        Rollout files live in a ``YYYY/MM/DD`` subtree, so discovery is
        recursive.  Batch commits fire every ``batch_size`` sessions.
        """
        if not self.is_available():
            return ExportStats()

        stats = ExportStats()
        batch: list[dict] = []
        batch_messages: list[dict] = []

        for rollout_file in sorted(self.sessions_dir.rglob("rollout-*.jsonl")):
            try:
                session_data, msgs, reason = self._process_rollout(
                    conn, rollout_file, incremental
                )
                if session_data:
                    batch.append(session_data)
                    batch_messages.extend(msgs)
                    if len(batch) >= batch_size:
                        commit_batch(conn, batch, batch_messages, stats)
                        batch = []
                        batch_messages = []
                elif reason == "skipped":
                    stats.skipped += 1
                elif reason == "empty":
                    stats.empty += 1
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
    ) -> tuple[dict | None, list[dict], str | None]:
        """Parse one rollout JSONL file → ``(session, messages, reason)``.

        ``reason`` explains a ``None`` session: ``"skipped"`` (fingerprint match)
        or ``"empty"`` (no parseable message turns). It is ``None`` when a
        session is returned for import.
        """
        session_id = f"codex_{rollout_file.stem}"
        fingerprint = file_fingerprint(rollout_file)

        if incremental:
            existing = conn.execute(
                "SELECT import_fingerprint FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if existing and existing[0] == fingerprint:
                return None, [], "skipped"

        messages: list[dict] = []
        first_ts: str | None = None
        last_ts: str | None = None
        project_path: str | None = None
        git_branch: str | None = None

        with open(rollout_file, encoding="utf-8") as fh:
            for raw_line in fh:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    obj = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                otype = obj.get("type")

                if otype == "session_meta":
                    payload = obj.get("payload", {}) or {}
                    project_path = payload.get("cwd") or project_path
                    git = payload.get("git") or {}
                    if isinstance(git, dict):
                        git_branch = git.get("branch") or git_branch
                    continue

                if otype != "response_item":
                    continue

                payload = obj.get("payload", {}) or {}
                if payload.get("type") != "message":
                    continue

                role = payload.get("role")
                if role not in _STORED_ROLES:
                    continue

                content = _flatten_content(payload.get("content"))
                if not content:
                    continue

                ts = _parse_timestamp(obj.get("timestamp"))
                if ts:
                    if first_ts is None:
                        first_ts = ts
                    last_ts = ts

                messages.append(
                    {
                        "role": role,
                        "content": content,
                        "model": payload.get("model"),
                        "timestamp": ts,
                    }
                )

        if not messages:
            return None, [], "empty"

        is_update = conn.execute(
            "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if is_update:
            # Message ids are positional; drop the old set so a shrunk or
            # rewritten rollout cannot strand stale rows.
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))

        session_data: dict = {
            "id": session_id,
            "source": "codex",
            "project_path": project_path or str(rollout_file.parent),
            "git_branch": git_branch,
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
                "id": f"{session_id}-{idx + 1}",
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

        return session_data, message_rows, None
