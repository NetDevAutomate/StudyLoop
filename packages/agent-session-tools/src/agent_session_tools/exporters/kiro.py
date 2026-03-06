"""Kiro CLI session exporter."""

import json
import sqlite3
import uuid
from pathlib import Path

from .base import ExportStats

# Kiro CLI database location
KIRO_DB = Path.home() / "Library/Application Support/kiro-cli/data.sqlite3"


def commit_batch(
    conn: sqlite3.Connection, batch: list, batch_messages: list, stats: ExportStats
) -> None:
    """Commit a batch of sessions and messages."""
    if not batch:
        return

    conn.executemany(
        """
        INSERT OR REPLACE INTO sessions
        (id, source, project_path, created_at, updated_at)
        VALUES (:id, :source, :project_path, NULL, NULL)
        """,
        batch,
    )

    if batch_messages:
        conn.executemany(
            """
            INSERT OR REPLACE INTO messages
            (id, session_id, role, content, model, timestamp, metadata, seq)
            VALUES (:id, :session_id, :role, :content, :model, :timestamp, :metadata, :seq)
            """,
            batch_messages,
        )

    stats.added += len(batch)
    conn.commit()


class KiroCliExporter:
    """Exporter for Kiro CLI sessions."""

    source_name = "kiro_cli"

    def is_available(self) -> bool:
        """Check if Kiro CLI data is available."""
        return KIRO_DB.exists()

    def export_all(
        self, conn: sqlite3.Connection, incremental: bool = True, batch_size: int = 50
    ) -> ExportStats:
        """Export all sessions with batching."""
        if not self.is_available():
            return ExportStats()

        stats = ExportStats()
        batch = []
        batch_messages = []

        with sqlite3.connect(KIRO_DB) as kiro_conn:
            kiro_conn.row_factory = sqlite3.Row

            for row in kiro_conn.execute("SELECT key, value FROM conversations"):
                project_path = row["key"]
                try:
                    data = json.loads(row["value"])
                except json.JSONDecodeError:
                    stats.errors += 1
                    continue

                session_id = f"kiro_{data.get('conversation_id', str(uuid.uuid4()))}"

                # Check if already imported
                if (
                    incremental
                    and conn.execute(
                        "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
                    ).fetchone()
                ):
                    stats.skipped += 1
                    continue

                # Extract messages from conversation history
                history = data.get("history", [])
                if not history:
                    stats.skipped += 1
                    continue

                messages = []
                for idx, msg in enumerate(history):
                    # Skip non-dict entries (malformed data)
                    if not isinstance(msg, dict):
                        continue
                    content = msg.get("content")
                    if content:
                        messages.append(
                            {
                                "id": str(uuid.uuid4()),
                                "session_id": session_id,
                                "role": msg.get("role", "unknown"),
                                "content": content,
                                "model": None,
                                "timestamp": None,
                                "metadata": json.dumps({}),
                                "seq": idx + 1,
                            }
                        )

                if messages:
                    session_data = {
                        "id": session_id,
                        "source": "kiro_cli",
                        "project_path": project_path,
                        "status": "added",
                    }
                    batch.append(session_data)
                    batch_messages.extend(messages)
                    if len(batch) >= batch_size:
                        commit_batch(conn, batch, batch_messages, stats)
                        batch = []
                        batch_messages = []

        # Commit final batch
        if batch:
            commit_batch(conn, batch, batch_messages, stats)

        return stats
