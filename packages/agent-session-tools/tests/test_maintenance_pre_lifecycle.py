"""Pre-lifecycle (`user_version < 41`) `session-maint delete` contracts.

Plan 4, lane L. The lifecycle path (schema 41+) deletes through
`purge_session`; a database no exporter has migrated since then takes the
branch in `maintenance._delete_old` that deletes children-first with foreign
keys on. These tests pin what that branch must do on the oldest shapes.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_session_tools.maintenance import _delete_old
from agent_session_tools.tiering import fts_integrity


def _old_iso(days_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


def _schema4_db(tmp_path: Path) -> Path:
    """A database at schema v4: an FTS index over messages, but none of the
    `messages_fts_*` triggers migration v5 installs, so a row deleted from
    `messages` keeps its index row unless the deleter removes it."""
    db_path = tmp_path / "sessions.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            project_path TEXT,
            created_at TEXT,
            updated_at TEXT,
            content_hash TEXT,
            import_fingerprint TEXT
        );
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            timestamp TEXT,
            content_hash TEXT,
            seq INTEGER,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );
        CREATE VIRTUAL TABLE messages_fts USING fts5(
            content, session_id UNINDEXED, role UNINDEXED
        );
        PRAGMA user_version = 4;
    """)
    conn.commit()
    conn.close()
    return db_path


def _add_session(db_path: Path, session_id: str, days_ago: int, *texts: str) -> None:
    """One session and its messages, indexed by hand (there is no trigger)."""
    when = _old_iso(days_ago)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO sessions (id, source, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, "claude_code", when, when),
    )
    for n, text in enumerate(texts, start=1):
        cursor = conn.execute(
            "INSERT INTO messages (id, session_id, role, content, timestamp)"
            " VALUES (?, ?, 'user', ?, ?)",
            (f"{session_id}-m{n}", session_id, text, when),
        )
        conn.execute(
            "INSERT INTO messages_fts (rowid, content, session_id, role)"
            " VALUES (?, ?, ?, 'user')",
            (cursor.lastrowid, text, session_id),
        )
    conn.commit()
    conn.close()


def _fts_hits(db_path: Path, term: str) -> list[str]:
    conn = sqlite3.connect(db_path)
    try:
        return [
            r[0]
            for r in conn.execute(
                "SELECT session_id FROM messages_fts WHERE messages_fts MATCH ?",
                (term,),
            )
        ]
    finally:
        conn.close()


def _rows(db_path: Path, sql: str) -> list[tuple]:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


class TestPreV5DeleteCleansTheFtsIndex:
    """D#7: on a schema older than v5 there is no `messages_fts_delete`
    trigger, so the deleted messages' index rows stayed behind -- a search
    still found the deleted session, and `fts-check` reported drift."""

    def test_deleted_messages_leave_no_index_rows(self, tmp_path):
        db_path = _schema4_db(tmp_path)
        _add_session(db_path, "old-1", 100, "the gone zebra", "another gone zebra")
        _add_session(db_path, "new-1", 1, "a kept giraffe")
        assert _fts_hits(db_path, "zebra") == ["old-1", "old-1"]

        assert _delete_old(db_path, days=30, confirm=True, backup=False) == 0

        assert _rows(db_path, "SELECT id FROM sessions") == [("new-1",)]
        assert _rows(db_path, "SELECT COUNT(*) FROM messages") == [(1,)]
        assert _fts_hits(db_path, "zebra") == []
        assert _fts_hits(db_path, "giraffe") == ["new-1"]
        conn = sqlite3.connect(db_path)
        try:
            assert fts_integrity(conn).healthy
        finally:
            conn.close()

    def test_a_kept_session_keeps_its_index_rows(self, tmp_path):
        """The cleanup runs inside the session's savepoint: a session the
        schema will not let go keeps its messages and their index rows."""
        db_path = _schema4_db(tmp_path)
        _add_session(db_path, "held", 100, "a held zebra")
        _add_session(db_path, "plain", 100, "a plain zebra")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE local_ref (session_id TEXT REFERENCES sessions(id) NOT NULL)"
        )
        conn.execute("INSERT INTO local_ref VALUES ('held')")
        conn.commit()
        conn.close()

        assert _delete_old(db_path, days=30, confirm=True, backup=False) == 0

        assert _rows(db_path, "SELECT id FROM sessions") == [("held",)]
        assert _fts_hits(db_path, "zebra") == ["held"]
        conn = sqlite3.connect(db_path)
        try:
            assert fts_integrity(conn).healthy
        finally:
            conn.close()
