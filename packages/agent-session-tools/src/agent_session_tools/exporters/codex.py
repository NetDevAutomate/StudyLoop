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
``<session_id>-<seq>`` (deterministic + idempotent) and changed files are reconciled atomically by the shared batch writer,
so unchanged message IDs retain their evidence links.
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..utils import file_fingerprint
from ..context.capture import capture_run
from .base import ExportStats, commit_batch, flush_batch
from .native import NativeCollector, codex_record

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
                    function = item.get("function")
                    name = item.get("name") or (
                        function.get("name", "") if isinstance(function, dict) else ""
                    )
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
        self.sessions_dir = sessions_dir or (
            Path(os.environ.get("CODEX_HOME", str(CODEX_SESSIONS_DIR.parent)))
            / "sessions"
        )
        self.archived_dir = self.sessions_dir.parent / "archived_sessions"

    def is_available(self) -> bool:
        """Return True only when the Codex sessions directory exists."""
        return self.sessions_dir.exists() or self.archived_dir.exists()

    @capture_run("codex-native-v1")
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

        rollouts = set(self.sessions_dir.rglob("rollout-*.jsonl"))
        rollouts.update(self.archived_dir.rglob("rollout-*.jsonl"))
        for rollout_file in sorted(rollouts):
            try:
                session_data, msgs, reason = self._process_rollout(
                    conn, rollout_file, incremental
                )
                if session_data:
                    batch.append(session_data)
                    batch_messages.extend(msgs)
                    if len(batch) >= batch_size:
                        ready, ready_messages = batch, batch_messages
                        batch, batch_messages = [], []
                        commit_batch(conn, ready, ready_messages, stats)
                elif reason == "skipped":
                    stats.skipped += 1
                elif reason == "empty":
                    stats.empty += 1
            except Exception as exc:
                stats.errors += 1
                logging.getLogger(__name__).warning(
                    "Session export deferred (%s): %s", type(exc).__name__, exc
                )

        flush_batch(conn, batch, batch_messages, stats, source=self.source_name)

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
        fingerprint = "codex-v3:" + file_fingerprint(rollout_file)

        if incremental:
            existing = conn.execute(
                "SELECT import_fingerprint FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if existing and existing[0] == fingerprint:
                return None, [], "skipped"

        native = NativeCollector(
            session_id, self.source_name, str(rollout_file.resolve()), "codex-native-v1"
        )
        messages: list[dict] = []
        first_ts: str | None = None
        last_ts: str | None = None
        project_path: str | None = None
        git_branch: str | None = None
        current_model: str | None = None
        source_metadata: dict = {}

        with open(rollout_file, encoding="utf-8") as fh:
            for line_number, raw_line in enumerate(fh, 1):
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    obj = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        "Malformed transcript JSON; source retained for retry"
                    ) from exc

                if not isinstance(obj, dict):
                    continue
                otype = obj.get("type")
                if not isinstance(obj.get("payload", {}), dict):
                    continue

                native_start = len(native.sources)
                codex_record(native, obj, line_number)

                if otype == "session_meta":
                    payload = obj.get("payload", {}) or {}
                    source_metadata.update(
                        {
                            k: payload[k]
                            for k in (
                                "id",
                                "source",
                                "originator",
                                "model_provider",
                                "git",
                            )
                            if k in payload
                        }
                    )
                    project_path = payload.get("cwd") or project_path
                    git = payload.get("git") or {}
                    if isinstance(git, dict):
                        git_branch = git.get("branch") or git_branch
                    continue

                if otype == "turn_context":
                    current_model = obj["payload"].get("model") or current_model
                    project_path = project_path or obj["payload"].get("cwd")
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
                        "native_sources": native.sources[native_start:],
                        "role": role,
                        "content": content,
                        "model": payload.get("model")
                        or (current_model if role == "assistant" else None),
                        "timestamp": ts,
                        "metadata": {
                            "source_line": line_number,
                            "channel": payload.get("channel"),
                            "source_message_id": payload.get("id"),
                        },
                    }
                )

        if fingerprint != "codex-v3:" + file_fingerprint(rollout_file):
            raise ValueError("Transcript changed during export; retry when stable")

        if not messages and not native.sources:
            return None, [], "empty"

        is_update = conn.execute(
            "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()

        session_data: dict = {
            "id": session_id,
            "native_sources": native.sources,
            "source": "codex",
            "project_path": project_path or str(rollout_file.parent),
            "git_branch": git_branch,
            "created_at": first_ts,
            "updated_at": last_ts,
            "import_fingerprint": fingerprint,
            "metadata": json.dumps(
                {
                    "fingerprint": fingerprint,
                    "rollout_file": rollout_file.name,
                    "source_file": str(rollout_file),
                    "session_meta": source_metadata,
                }
            ),
            "status": "updated" if is_update else "added",
            "replace_messages": True,
        }

        message_rows = [
            {
                "id": f"{session_id}-{idx + 1}",
                "native_sources": m["native_sources"],
                "session_id": session_id,
                "role": m["role"],
                "content": m["content"],
                "model": m["model"],
                "timestamp": m["timestamp"],
                "metadata": json.dumps(m["metadata"]),
                "seq": idx + 1,
            }
            for idx, m in enumerate(messages)
        ]

        return session_data, message_rows, None
