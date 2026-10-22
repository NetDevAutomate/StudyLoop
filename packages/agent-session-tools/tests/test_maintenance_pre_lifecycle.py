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

from typer.testing import CliRunner

from agent_session_tools.maintenance import _delete_old, app
from agent_session_tools.tiering import fts_integrity

runner = CliRunner()


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

        assert (
            _delete_old(
                db_path, days=30, confirm=True, backup=False, allow_unmigrated=True
            )
            == 0
        )

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

        assert (
            _delete_old(
                db_path, days=30, confirm=True, backup=False, allow_unmigrated=True
            )
            == 0
        )

        assert _rows(db_path, "SELECT id FROM sessions") == [("held",)]
        assert _fts_hits(db_path, "zebra") == ["held"]
        conn = sqlite3.connect(db_path)
        try:
            assert fts_integrity(conn).healthy
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Plan 4 item 7 (coordinator decision on FOUND-NOT-FIXED §Owner decisions):
# a pre-41 schema records no tombstone, so a session deleted there is
# re-imported by the next export from its native transcript (F-AST-04). The
# honest contract is to refuse by default and name the migration; the old
# behaviour stays reachable, with a warning, behind --allow-unmigrated.
# ---------------------------------------------------------------------------


def _current_db(tmp_path: Path) -> Path:
    from agent_session_tools.export_sessions import init_db

    db_path = tmp_path / "current.db"
    init_db(str(db_path)).close()
    return db_path


class TestPre41DeleteRefusesByDefault:
    def test_refuses_changes_nothing_and_names_the_migration(self, tmp_path, capsys):
        db_path = _schema4_db(tmp_path)
        _add_session(db_path, "old-1", 100, "hello")

        assert _delete_old(db_path, days=30, confirm=True, backup=False) == 1

        assert _rows(db_path, "SELECT id FROM sessions") == [("old-1",)]
        assert _rows(db_path, "SELECT COUNT(*) FROM messages") == [(1,)]
        out = capsys.readouterr().out
        assert "schema version 4" in out
        assert "41" in out
        assert "tombstone" in out
        assert "Nothing was changed" in out
        assert f"session-maint embed-check --db {db_path}" in out
        assert "--allow-unmigrated" in out

    def test_refuses_the_preview_too(self, tmp_path, capsys):
        """The refusal is about the schema, not the action: no --confirm, same answer."""
        db_path = _schema4_db(tmp_path)
        _add_session(db_path, "old-1", 100, "hello")

        assert _delete_old(db_path, days=30, confirm=False, backup=False) == 1

        out = capsys.readouterr().out
        assert "schema version 4" in out
        assert "Operation cancelled" not in out

    def test_allow_unmigrated_restores_the_old_behaviour_with_a_warning(
        self, tmp_path, capsys
    ):
        db_path = _schema4_db(tmp_path)
        _add_session(db_path, "old-1", 100, "hello")
        _add_session(db_path, "new-1", 1, "hi")

        assert (
            _delete_old(
                db_path, days=30, confirm=True, backup=False, allow_unmigrated=True
            )
            == 0
        )

        assert _rows(db_path, "SELECT id FROM sessions") == [("new-1",)]
        out = capsys.readouterr().out
        assert "⚠️  --allow-unmigrated" in out
        assert "no tombstone" in out
        assert "re-import" in out
        assert "Deleted 1 sessions (1 messages)" in out

    def test_allow_unmigrated_does_not_unlock_forget_learner_records(
        self, tmp_path, capsys
    ):
        """purge_session needs schema 41+ whatever else is passed (ADR-0017)."""
        db_path = _schema4_db(tmp_path)
        _add_session(db_path, "old-1", 100, "hello")

        assert (
            _delete_old(
                db_path,
                days=30,
                confirm=True,
                backup=False,
                forget_learner_records=True,
                allow_unmigrated=True,
            )
            == 1
        )

        assert _rows(db_path, "SELECT id FROM sessions") == [("old-1",)]
        assert "--forget-learner-records needs the current schema" in (
            capsys.readouterr().out
        )

    def test_a_current_schema_is_not_warned_about(self, tmp_path, capsys):
        db_path = _current_db(tmp_path)
        when = _old_iso(100)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO sessions (id, source, created_at, updated_at)"
            " VALUES ('old-1', 'claude_code', ?, ?)",
            (when, when),
        )
        conn.commit()
        conn.close()

        assert (
            _delete_old(
                db_path, days=30, confirm=True, backup=False, allow_unmigrated=True
            )
            == 0
        )

        assert _rows(db_path, "SELECT id FROM sessions") == []
        assert _rows(db_path, "SELECT COUNT(*) FROM context_tombstones") == [(1,)]
        assert "--allow-unmigrated" not in capsys.readouterr().out


class TestPre41Cli:
    def _args(self, db_path: Path, *extra: str) -> list[str]:
        return ["delete", "--days", "30", "--db", str(db_path), "--no-backup", *extra]

    def test_help_names_the_flag(self):
        result = runner.invoke(app, ["delete", "--help"], terminal_width=200)
        assert result.exit_code == 0
        text = " ".join(result.output.split())
        assert "--allow-unmigrated" in text
        assert "tombstone" in text

    def test_refused_without_the_flag(self, tmp_path):
        db_path = _schema4_db(tmp_path)
        _add_session(db_path, "old-1", 100, "hello")

        result = runner.invoke(app, self._args(db_path, "--confirm"))

        assert result.exit_code == 1, result.output
        assert "schema version 4" in result.output
        assert _rows(db_path, "SELECT id FROM sessions") == [("old-1",)]

    def test_deletes_with_the_flag(self, tmp_path):
        db_path = _schema4_db(tmp_path)
        _add_session(db_path, "old-1", 100, "hello")

        result = runner.invoke(
            app, self._args(db_path, "--confirm", "--allow-unmigrated")
        )

        assert result.exit_code == 0, result.output
        assert "⚠️  --allow-unmigrated" in result.output
        assert _rows(db_path, "SELECT id FROM sessions") == []
