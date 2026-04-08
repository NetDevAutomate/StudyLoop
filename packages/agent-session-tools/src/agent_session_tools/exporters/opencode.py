"""OpenCode CLI session exporter.

Storage layout (~/.local/share/opencode/storage/):
  session/{projectID}/{sessionID}.json  — session metadata
  message/{sessionID}/{messageID}.json  — message metadata (role, model, tokens)
  part/{messageID}/{partID}.json        — content parts (text, tool, patch, etc.)
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .base import ExportStats, commit_batch

OPENCODE_DIR = Path.home() / ".local" / "share" / "opencode" / "storage"


class OpenCodeExporter:
    """Exporter for OpenCode CLI sessions."""

    source_name = "opencode"

    def is_available(self) -> bool:
        return (OPENCODE_DIR / "session").exists()

    def export_all(
        self, conn: sqlite3.Connection, incremental: bool = True, batch_size: int = 50
    ) -> ExportStats:
        if not self.is_available():
            return ExportStats()

        stats = ExportStats()
        batch = []
        batch_messages = []

        session_dir = OPENCODE_DIR / "session"
        for session_file in session_dir.rglob("*.json"):
            try:
                session_data = json.loads(session_file.read_text())
            except (json.JSONDecodeError, OSError):
                stats.errors += 1
                continue

            session_id = session_data.get("id", "")
            if not session_id:
                stats.errors += 1
                continue

            # Parse timestamps (milliseconds) before the incremental check
            time_info = session_data.get("time", {})
            created_at = _ms_to_iso(time_info.get("created"))
            updated_at = _ms_to_iso(time_info.get("updated"))

            # Check if already imported (updated_at comparison)
            existing = conn.execute(
                "SELECT updated_at FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()

            if existing and incremental:
                if existing["updated_at"] == updated_at:
                    stats.skipped += 1
                    continue
                # Session was updated — delete old messages and re-import
                conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
                status = "updated"
            else:
                status = "added"

            # Collect messages for this session
            messages = self._collect_messages(session_id)
            if not messages:
                stats.skipped += 1
                continue

            batch.append(
                {
                    "id": session_id,
                    "source": "opencode",
                    "project_path": session_data.get("directory", ""),
                    "git_branch": None,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "metadata": json.dumps(
                        {
                            "title": session_data.get("title", ""),
                            "version": session_data.get("version", ""),
                        }
                    ),
                    "status": status,
                }
            )
            batch_messages.extend(messages)

            if len(batch) >= batch_size:
                commit_batch(conn, batch, batch_messages, stats)
                batch = []
                batch_messages = []

        if batch:
            commit_batch(conn, batch, batch_messages, stats)

        return stats

    def _collect_messages(self, session_id: str) -> list[dict]:
        """Collect messages and their text parts for a session."""
        msg_dir = OPENCODE_DIR / "message" / session_id
        if not msg_dir.exists():
            return []

        messages = []
        for msg_file in sorted(msg_dir.glob("*.json")):
            try:
                msg = json.loads(msg_file.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            msg_id = msg.get("id", "")
            if not msg_id:
                continue

            # Assemble content from text parts
            content = self._get_text_content(msg_id)
            if not content:
                continue

            time_info = msg.get("time", {})
            tokens = msg.get("tokens", {})

            messages.append(
                {
                    "id": msg_id,
                    "session_id": session_id,
                    "role": msg.get("role", "unknown"),
                    "content": content,
                    "model": msg.get("modelID"),
                    "timestamp": _ms_to_iso(time_info.get("created")),
                    "metadata": json.dumps(
                        {
                            "provider": msg.get("providerID"),
                            "tokens_in": tokens.get("input", 0),
                            "tokens_out": tokens.get("output", 0),
                            "cost": msg.get("cost", 0),
                        }
                    ),
                    "seq": 0,  # will be set below
                }
            )

        # Set sequence numbers
        for idx, m in enumerate(messages):
            m["seq"] = idx + 1

        return messages

    def _get_text_content(self, message_id: str) -> str:
        """Concatenate text parts for a message."""
        part_dir = OPENCODE_DIR / "part" / message_id
        if not part_dir.exists():
            return ""

        texts = []
        for part_file in sorted(part_dir.glob("*.json")):
            try:
                part = json.loads(part_file.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if part.get("type") == "text" and part.get("text"):
                texts.append(part["text"])

        return "\n".join(texts)


def _ms_to_iso(ms: int | None) -> str | None:
    """Convert millisecond timestamp to ISO format."""
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000).isoformat()
    except (ValueError, TypeError, OSError):
        return None
