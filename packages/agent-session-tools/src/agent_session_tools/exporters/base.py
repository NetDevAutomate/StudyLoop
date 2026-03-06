"""Base classes and protocols for session exporters."""

import sqlite3
from dataclasses import dataclass
from threading import Lock
from typing import Protocol


@dataclass
class ExportStats:
    added: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    _lock: Lock = Lock()

    def __iadd__(self, other):
        with self._lock:
            self.added += other.added
            self.updated += other.updated
            self.skipped += other.skipped
            self.errors += other.errors
        return self


class SessionExporter(Protocol):
    """Protocol for session exporters."""

    @property
    def source_name(self) -> str:
        """Unique identifier for this source."""
        ...

    def is_available(self) -> bool:
        """Check if source data is available on system."""
        ...

    def export_all(
        self, conn: sqlite3.Connection, incremental: bool = True, batch_size: int = 50
    ) -> ExportStats:
        """Export all sessions from this source with batching."""
        ...


def commit_batch(
    conn: sqlite3.Connection, sessions: list, messages: list, stats: ExportStats
) -> None:
    """Commit a batch of sessions and messages to the database."""
    if not sessions:
        return

    try:
        conn.executemany(
            """
            INSERT OR REPLACE INTO sessions (
                id, source, project_path, git_branch, created_at, updated_at, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            [
                (
                    s["id"],
                    s["source"],
                    s["project_path"],
                    s.get("git_branch"),
                    s["created_at"],
                    s["updated_at"],
                    s["metadata"],
                )
                for s in sessions
            ],
        )

        conn.executemany(
            """
            INSERT OR REPLACE INTO messages (
                id, session_id, role, content, model, timestamp, metadata, seq
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            [
                (
                    m["id"],
                    m["session_id"],
                    m["role"],
                    m["content"],
                    m["model"],
                    m["timestamp"],
                    m["metadata"],
                    m["seq"],
                )
                for m in messages
            ],
        )

        stats.added += len([s for s in sessions if s.get("status") == "added"])
        stats.updated += len([s for s in sessions if s.get("status") == "updated"])

        conn.commit()
    except Exception as e:
        conn.rollback()
        stats.errors += len(sessions)
        raise e
