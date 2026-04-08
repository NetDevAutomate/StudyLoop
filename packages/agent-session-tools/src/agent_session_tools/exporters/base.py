"""Base classes and protocols for session exporters."""

import sqlite3
from dataclasses import dataclass
from typing import Protocol


@dataclass
class ExportStats:
    added: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0

    def __iadd__(self, other: "ExportStats") -> "ExportStats":
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
    """Commit a batch of sessions and messages to the database.

    Sessions and messages are lists of dicts with named keys matching the DB columns.
    Missing optional fields default to NULL via dict.get().
    """
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
                    s.get("created_at"),
                    s.get("updated_at"),
                    s.get("metadata"),
                )
                for s in sessions
            ],
        )

        if messages:
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
                        m.get("model"),
                        m.get("timestamp"),
                        m.get("metadata"),
                        m.get("seq"),
                    )
                    for m in messages
                ],
            )

        # Update stats from session status flags
        for s in sessions:
            status = s.get("status", "added")
            if status == "added":
                stats.added += 1
            elif status == "updated":
                stats.updated += 1
            elif status == "skipped":
                stats.skipped += 1

        conn.commit()
    except Exception:
        conn.rollback()
        stats.errors += len(sessions)
        raise
