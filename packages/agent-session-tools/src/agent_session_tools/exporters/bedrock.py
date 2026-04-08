"""Bedrock Proxy session exporter.

Imports sessions from the bedrock_proxy Anthropic-compatible proxy.
Database location: ~/.config/bedrock_proxy/conversations.db
"""

import json
import sqlite3
from pathlib import Path

from .base import ExportStats, commit_batch

# Bedrock Proxy database location
BEDROCK_PROXY_DB = Path.home() / ".config/bedrock_proxy/conversations.db"


class BedrockProxyExporter:
    """Exporter for Bedrock Proxy conversation sessions.

    The bedrock_proxy database uses an identical schema to agent_session_tools,
    so this exporter performs a direct copy of sessions and messages.
    """

    source_name = "bedrock_proxy"

    def __init__(self, db_path: Path | None = None):
        """Initialize exporter.

        Args:
            db_path: Custom path to bedrock_proxy database (uses default if None)
        """
        self.db_path = db_path or BEDROCK_PROXY_DB

    def is_available(self) -> bool:
        """Check if Bedrock Proxy database is available."""
        return self.db_path.exists()

    def export_all(
        self, conn: sqlite3.Connection, incremental: bool = True, batch_size: int = 50
    ) -> ExportStats:
        """Export all sessions from Bedrock Proxy database.

        Args:
            conn: Target database connection
            incremental: If True, skip sessions already imported
            batch_size: Number of sessions per batch commit

        Returns:
            Export statistics
        """
        if not self.is_available():
            return ExportStats()

        stats = ExportStats()
        session_batch = []
        message_batch = []

        with sqlite3.connect(self.db_path) as source_conn:
            source_conn.row_factory = sqlite3.Row

            # Get all sessions from bedrock_proxy
            sessions = source_conn.execute("""
                SELECT id, source, project_path, git_branch, created_at, updated_at, metadata
                FROM sessions
                ORDER BY created_at
            """).fetchall()

            for session in sessions:
                session_id = session["id"]

                # Check if already imported (incremental mode)
                if incremental:
                    existing = conn.execute(
                        "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
                    ).fetchone()
                    if existing:
                        stats.skipped += 1
                        continue

                # Get messages for this session
                messages = source_conn.execute(
                    """
                    SELECT id, session_id, role, content, model, timestamp, metadata, seq
                    FROM messages
                    WHERE session_id = ?
                    ORDER BY seq, timestamp
                    """,
                    (session_id,),
                ).fetchall()

                if not messages:
                    stats.skipped += 1
                    continue

                # Add session to batch
                session_batch.append(
                    {
                        "id": session_id,
                        "source": self.source_name,  # Override source to track origin
                        "project_path": session["project_path"],
                        "git_branch": session["git_branch"],
                        "created_at": session["created_at"],
                        "updated_at": session["updated_at"],
                        "metadata": session["metadata"],
                        "status": "added",
                    }
                )

                # Add messages to batch
                for msg in messages:
                    message_batch.append(
                        {
                            "id": msg["id"],
                            "session_id": session_id,
                            "role": msg["role"],
                            "content": msg["content"],
                            "model": msg["model"],
                            "timestamp": msg["timestamp"],
                            "metadata": msg["metadata"]
                            if msg["metadata"]
                            else json.dumps({}),
                            "seq": msg["seq"] if msg["seq"] else 0,
                        }
                    )

                # Commit batch if full
                if len(session_batch) >= batch_size:
                    commit_batch(conn, session_batch, message_batch, stats)
                    session_batch = []
                    message_batch = []

        # Commit remaining batch
        if session_batch:
            commit_batch(conn, session_batch, message_batch, stats)

        return stats
