"""Grok CLI session exporter.

Grok CLI (xAI's terminal coding agent, ``grok``) stores each session as a
directory under a **URL-encoded-cwd** parent::

    ~/.grok/sessions/<url-encoded-cwd>/<session-uuid>/
        summary.json        — session metadata (id, cwd, timestamps, model, title)
        chat_history.jsonl   — the conversation (one message object per line)
        events.jsonl, updates.jsonl, system_prompt.txt, ...  (not consumed)

``summary.json`` is the authoritative metadata source::

    {"info": {"id": "<uuid>", "cwd": "/abs/path"},
     "created_at": "ISO-8601", "updated_at": "ISO-8601",
     "current_model_id": "grok-bedrock", "generated_title": "...",
     "head_branch": "main", ...}

``chat_history.jsonl`` lines are role-discriminated by ``type``::

    {"type": "system" | "user" | "assistant" | "tool_result",
     "content": "<str>" | [{"type": "text", "text": "..."}],
     "model_id": "xai.grok-4.3",        # assistant only
     "tool_calls": [...],               # assistant only (not stored as text)
     "synthetic_reason": "..."}         # injected-message marker

Only ``user`` and ``assistant`` turns are stored; ``system`` (the prompt) and
``tool_result`` (raw tool output) are skipped for a clean learning corpus.
Chat lines carry no per-message timestamp, so message timestamps are left null
and session timestamps come from ``summary.json``.

**Deduplication**: ``updated_at`` comparison like ``opencode.py``/``gemini.py``
— when a session's ``updated_at`` changes, its messages are deleted and
re-imported.
"""

import json
import sqlite3
from pathlib import Path

from .base import ExportStats, commit_batch

# Grok CLI session root
GROK_DIR = Path.home() / ".grok" / "sessions"

# Roles worth storing — system prompt and raw tool output are dropped.
_STORED_ROLES = {"user", "assistant"}


def _flatten_content(content: object) -> str | None:
    """Flatten a Grok message ``content`` value to plain text.

    ``content`` is either a plain string or a list of ``{"type": "text",
    "text": ...}`` parts (the only part shape Grok emits in chat_history).
    Returns None when no text is present.
    """
    if content is None:
        return None
    if isinstance(content, str):
        return content or None
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts) if parts else None
    return str(content)


class GrokExporter:
    """Exporter for xAI Grok CLI sessions."""

    source_name = "grok"

    def __init__(self, sessions_dir: Path | None = None) -> None:
        """Initialise the Grok exporter.

        Args:
            sessions_dir: Override the default ``~/.grok/sessions/`` directory.
        """
        self.sessions_dir = sessions_dir or GROK_DIR

    def is_available(self) -> bool:
        """Return True only when the Grok sessions directory exists."""
        return self.sessions_dir.exists()

    def export_all(
        self, conn: sqlite3.Connection, incremental: bool = True, batch_size: int = 50
    ) -> ExportStats:
        """Export every session directory found under ``sessions_dir``.

        A session is any directory containing ``summary.json``; discovery is
        recursive because sessions are nested one level under a URL-encoded-cwd
        parent. Batch commits fire every ``batch_size`` sessions.
        """
        if not self.is_available():
            return ExportStats()

        stats = ExportStats()
        batch: list[dict] = []
        batch_messages: list[dict] = []

        for summary_file in sorted(self.sessions_dir.rglob("summary.json")):
            try:
                session_data, msgs, reason = self._process_session(
                    conn, summary_file, incremental
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

    def _process_session(
        self,
        conn: sqlite3.Connection,
        summary_file: Path,
        incremental: bool,
    ) -> tuple[dict | None, list[dict], str | None]:
        """Parse one session directory → ``(session, messages, reason)``.

        ``reason`` explains a ``None`` session: ``"skipped"`` (``updated_at``
        unchanged) or ``"empty"`` (no user/assistant turns). It is ``None`` when
        a session is returned for import.
        """
        # A malformed summary.json raises here and is counted as an error by
        # export_all's per-session except.
        summary = json.loads(summary_file.read_text())

        info = summary.get("info", {}) or {}
        raw_id = info.get("id") or summary_file.parent.name
        session_id = f"grok_{raw_id}"
        created_at = summary.get("created_at")
        updated_at = summary.get("updated_at")

        existing = conn.execute(
            "SELECT updated_at FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if existing and incremental:
            if existing["updated_at"] == updated_at:
                return None, [], "skipped"
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            status = "updated"
        else:
            status = "added"

        messages = self._collect_messages(session_id, summary_file.parent)
        if not messages:
            return None, [], "empty"

        session_data = {
            "id": session_id,
            "source": "grok",
            "project_path": info.get("cwd") or summary.get("git_root_dir") or "",
            "git_branch": summary.get("head_branch"),
            "created_at": created_at,
            "updated_at": updated_at,
            "metadata": json.dumps(
                {
                    "title": summary.get("generated_title")
                    or summary.get("session_summary", ""),
                    "model": summary.get("current_model_id", ""),
                }
            ),
            "status": status,
        }

        return session_data, messages, None

    def _collect_messages(self, session_id: str, session_dir: Path) -> list[dict]:
        """Read ``chat_history.jsonl`` and return stored message rows."""
        chat_file = session_dir / "chat_history.jsonl"
        if not chat_file.exists():
            return []

        messages: list[dict] = []
        seq = 0
        with open(chat_file, encoding="utf-8") as fh:
            for raw_line in fh:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    obj = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                role = obj.get("type")
                if role not in _STORED_ROLES:
                    continue

                content = _flatten_content(obj.get("content"))
                if not content:
                    continue

                seq += 1
                messages.append(
                    {
                        "id": f"{session_id}-{seq}",
                        "session_id": session_id,
                        "role": role,
                        "content": content,
                        "model": obj.get("model_id"),
                        "timestamp": None,  # chat_history has no per-message ts
                        "metadata": json.dumps({}),
                        "seq": seq,
                    }
                )

        return messages
