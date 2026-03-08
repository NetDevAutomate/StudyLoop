"""Gemini CLI session exporter."""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from .base import ExportStats, commit_batch

# Gemini CLI directories
GEMINI_DIR = Path.home() / ".gemini" / "tmp"


class GeminiCliExporter:
    """Exporter for Gemini CLI sessions."""

    source_name = "gemini_cli"

    def is_available(self) -> bool:
        """Check if Gemini CLI data is available."""
        return GEMINI_DIR.exists()

    def export_all(
        self, conn: sqlite3.Connection, incremental: bool = True, batch_size: int = 50
    ) -> ExportStats:
        """Export all sessions with batch commits."""
        if not self.is_available():
            return ExportStats(added=0, updated=0, skipped=0, errors=0)

        stats = ExportStats()
        batch = []
        batch_messages = []

        for chat_dir in GEMINI_DIR.rglob("*/chats"):
            if not chat_dir.is_dir():
                continue

            for session_file in chat_dir.glob("session-*.json"):
                try:
                    result = self._parse_session_file(session_file)
                    if not result:
                        stats.errors += 1
                        continue

                    session_id, project_path, messages, created_at, updated_at = result

                    # Check if already imported
                    if (
                        incremental
                        and conn.execute(
                            "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
                        ).fetchone()
                    ):
                        stats.skipped += 1
                        continue

                    if not messages:
                        stats.skipped += 1
                        continue

                    session_data = {
                        "id": session_id,
                        "source": "gemini_cli",
                        "project_path": project_path,
                        "created_at": created_at,
                        "updated_at": updated_at,
                        "metadata": json.dumps({}),
                        "status": "added",
                    }
                    batch.append(session_data)
                    batch_messages.extend(messages)
                    if len(batch) >= batch_size:
                        commit_batch(conn, batch, batch_messages, stats)
                        batch = []
                        batch_messages = []
                except Exception:
                    stats.errors += 1

        # Commit final batch
        if batch:
            commit_batch(conn, batch, batch_messages, stats)

        return stats

    def _parse_session_file(
        self, session_file: Path
    ) -> tuple[str, str, list[dict], str | None, str | None] | None:
        """Parse session file and return session data."""
        try:
            with open(session_file) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

        session_id = f"gemini_{data.get('sessionId', str(uuid.uuid4()))}"
        project_path = data.get("projectHash", "")
        created_at = data.get("startTime")
        updated_at = data.get("lastUpdated")

        messages = []
        for idx, msg in enumerate(data.get("messages", [])):
            # Convert timestamp from milliseconds (may be string or int)
            ts_ms = msg.get("timestamp")
            try:
                timestamp = (
                    datetime.fromtimestamp(int(ts_ms) / 1000).isoformat()
                    if ts_ms
                    else None
                )
            except (ValueError, TypeError):
                timestamp = None

            content = msg.get("content", "")
            if isinstance(content, list):
                # Join multiple content parts
                content = "\n".join(str(part) for part in content)

            messages.append(
                {
                    "id": msg.get("id", str(uuid.uuid4())),
                    "session_id": session_id,
                    "role": msg.get("type", "unknown").replace("gemini", "assistant"),
                    "content": content,
                    "model": msg.get("model"),
                    "timestamp": timestamp,
                    "metadata": json.dumps(
                        {"tokens": msg.get("tokens"), "thoughts": msg.get("thoughts")}
                    ),
                    "seq": idx + 1,
                }
            )

        return session_id, project_path, messages, created_at, updated_at
