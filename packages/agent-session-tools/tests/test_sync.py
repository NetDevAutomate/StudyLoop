"""Tests for sync module — unit tests for functions that don't need SSH."""

import sqlite3
from pathlib import Path

import pytest
import typer

from agent_session_tools.sync import (
    _dump_delta_sql,
    _resolve_remote,
    _stream_sql_to_target,
)

# --- _resolve_remote ---


class TestResolveRemote:
    def test_standard_format(self):
        host, path = _resolve_remote("user@192.168.1.1:/home/user/.config/sessions.db")
        assert host == "user@192.168.1.1"
        assert path == "/home/user/.config/sessions.db"

    def test_hostname_only(self):
        host, path = _resolve_remote("myhost:/tmp/db.sqlite")
        assert host == "myhost"
        assert path == "/tmp/db.sqlite"

    def test_no_colon_and_not_endpoint_raises(self):
        with pytest.raises(typer.BadParameter):
            _resolve_remote("not-an-endpoint-or-remote")

    def test_colon_in_path(self):
        """Colon only splits on first occurrence."""
        host, path = _resolve_remote("user@host:/path/with:colon/db.sqlite")
        assert host == "user@host"
        assert path == "/path/with:colon/db.sqlite"


# --- _dump_delta_sql ---


class TestDumpDeltaSql:
    def test_dumps_specified_sessions(self, populated_db):
        _, db_path = populated_db
        sql = _dump_delta_sql(db_path, {"test-session-001"})
        assert "INSERT OR REPLACE INTO" in sql
        assert "test-session-001" in sql
        assert "test-msg-001" in sql

    def test_empty_set_returns_empty(self, populated_db):
        _, db_path = populated_db
        sql = _dump_delta_sql(db_path, set())
        assert sql == ""

    def test_only_specified_sessions(self, temp_db):
        conn, db_path = temp_db
        for sid in ["keep", "skip-1", "skip-2"]:
            conn.execute(
                "INSERT INTO sessions (id, source, created_at) VALUES (?, 'test', '2024-01-01')",
                (sid,),
            )
            conn.execute(
                "INSERT INTO messages (id, session_id, role, content, timestamp) "
                "VALUES (?, ?, 'user', 'hello', '2024-01-01')",
                (f"msg-{sid}", sid),
            )
        conn.commit()

        sql = _dump_delta_sql(db_path, {"keep"})
        assert "keep" in sql
        assert "skip-1" not in sql
        assert "skip-2" not in sql

    def test_no_plain_insert_into(self, populated_db):
        """All INSERT statements must be INSERT OR REPLACE."""
        _, db_path = populated_db
        sql = _dump_delta_sql(db_path, {"test-session-001"})
        for line in sql.splitlines():
            if line.startswith("INSERT"):
                assert line.startswith("INSERT OR REPLACE INTO"), (
                    f"Unprotected insert: {line}"
                )


# --- _stream_sql_to_target (local path only) ---


class TestStreamSqlToTarget:
    def test_imports_into_local_db(self, temp_db):
        _, db_path = temp_db
        sql = (
            "INSERT OR IGNORE INTO sessions (id, source, created_at) "
            "VALUES ('streamed-1', 'test', '2024-01-01');\n"
            "INSERT OR IGNORE INTO messages (id, session_id, role, content, timestamp) "
            "VALUES ('msg-s1', 'streamed-1', 'user', 'hello', '2024-01-01');\n"
        )
        assert _stream_sql_to_target(sql, db_path) is True

        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        conn.close()
        assert count == 1

    def test_empty_sql_is_noop(self, temp_db):
        _, db_path = temp_db
        assert _stream_sql_to_target("", db_path) is True
        assert _stream_sql_to_target("   ", db_path) is True

    def test_duplicate_insert_ignored(self, populated_db):
        """INSERT OR IGNORE should not fail on existing rows."""
        _, db_path = populated_db
        sql = (
            "INSERT OR IGNORE INTO sessions (id, source, created_at) "
            "VALUES ('test-session-001', 'claude_code', '2024-01-01');\n"
        )
        assert _stream_sql_to_target(sql, db_path) is True


# --- Round-trip: dump from one DB, import into another ---


class TestRoundTrip:
    def test_dump_and_import(self, populated_db, temp_db):
        """Dump from source DB, import into empty target DB."""
        _, source_path = populated_db
        _, target_path = temp_db

        sql = _dump_delta_sql(source_path, {"test-session-001"})
        assert _stream_sql_to_target(sql, target_path) is True

        conn = sqlite3.connect(target_path)
        sessions = conn.execute("SELECT id FROM sessions").fetchall()
        messages = conn.execute("SELECT id FROM messages").fetchall()
        conn.close()

        assert len(sessions) == 1
        assert sessions[0][0] == "test-session-001"
        assert len(messages) == 1
        assert messages[0][0] == "test-msg-001"

    def test_delta_round_trip(self, temp_db):
        """Only specified sessions transfer; existing data gets replaced."""
        conn_source, source_path = temp_db

        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            target_path = Path(f.name)

        target_conn = sqlite3.connect(target_path)
        schema_path = (
            Path(__file__).parent.parent / "src" / "agent_session_tools" / "schema.sql"
        )
        target_conn.executescript(schema_path.read_text())

        # Source has sessions A, B, C
        for sid in ["A", "B", "C"]:
            conn_source.execute(
                "INSERT INTO sessions (id, source, created_at, updated_at) "
                "VALUES (?, 'test', '2024-01-01', '2024-01-02')",
                (sid,),
            )
            conn_source.execute(
                "INSERT INTO messages (id, session_id, role, content, timestamp) "
                "VALUES (?, ?, 'user', 'msg', '2024-01-01')",
                (f"msg-{sid}", sid),
            )
        conn_source.commit()

        # Target already has session A with older timestamp
        target_conn.execute(
            "INSERT INTO sessions (id, source, created_at, updated_at) "
            "VALUES ('A', 'test', '2024-01-01', '2024-01-01')"
        )
        target_conn.execute(
            "INSERT INTO messages (id, session_id, role, content, timestamp) "
            "VALUES ('msg-A', 'A', 'user', 'old msg', '2024-01-01')"
        )
        target_conn.commit()
        target_conn.close()

        # Dump B and C (new) and import
        sql = _dump_delta_sql(source_path, {"B", "C"})
        assert _stream_sql_to_target(sql, target_path) is True

        target_conn = sqlite3.connect(target_path)
        ids = {r[0] for r in target_conn.execute("SELECT id FROM sessions").fetchall()}
        msg_count = target_conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        target_conn.close()
        target_path.unlink()

        assert ids == {"A", "B", "C"}
        assert msg_count == 3
