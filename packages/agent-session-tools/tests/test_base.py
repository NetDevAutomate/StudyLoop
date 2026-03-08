"""Tests for agent_session_tools.exporters.base — ExportStats dataclass and commit_batch."""

import sqlite3

import pytest

from agent_session_tools.exporters.base import ExportStats, commit_batch


# ---------------------------------------------------------------------------
# ExportStats
# ---------------------------------------------------------------------------


class TestExportStats:
    def test_defaults_are_zero(self):
        stats = ExportStats()
        assert stats.added == 0
        assert stats.updated == 0
        assert stats.skipped == 0
        assert stats.errors == 0

    def test_custom_values(self):
        stats = ExportStats(added=1, updated=2, skipped=3, errors=4)
        assert stats.added == 1
        assert stats.updated == 2
        assert stats.skipped == 3
        assert stats.errors == 4

    def test_iadd_accumulates(self):
        a = ExportStats(added=1, updated=2, skipped=3, errors=4)
        b = ExportStats(added=10, updated=20, skipped=30, errors=40)
        a += b
        assert a.added == 11
        assert a.updated == 22
        assert a.skipped == 33
        assert a.errors == 44

    def test_iadd_returns_self(self):
        a = ExportStats()
        b = ExportStats(added=1)
        result = a.__iadd__(b)
        assert result is a

    def test_iadd_does_not_mutate_rhs(self):
        a = ExportStats(added=5)
        b = ExportStats(added=3)
        a += b
        assert b.added == 3

    def test_iadd_with_zeros(self):
        a = ExportStats(added=5, updated=3)
        b = ExportStats()
        a += b
        assert a.added == 5
        assert a.updated == 3

    def test_multiple_iadd(self):
        total = ExportStats()
        for i in range(5):
            total += ExportStats(added=1, errors=i)
        assert total.added == 5
        assert total.errors == 0 + 1 + 2 + 3 + 4  # 10


# ---------------------------------------------------------------------------
# commit_batch — helpers
# ---------------------------------------------------------------------------


def _add_seq_column(conn: sqlite3.Connection) -> None:
    """Add the seq column that the migration normally provides."""
    cols = [row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()]
    if "seq" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN seq INTEGER")


def _make_session(
    sid: str = "s1",
    *,
    source: str = "test",
    project_path: str = "/p",
    status: str = "added",
) -> dict:
    return {
        "id": sid,
        "source": source,
        "project_path": project_path,
        "git_branch": "main",
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T01:00:00",
        "metadata": None,
        "status": status,
    }


def _make_message(
    mid: str = "m1",
    session_id: str = "s1",
    *,
    role: str = "user",
    content: str = "hello",
) -> dict:
    return {
        "id": mid,
        "session_id": session_id,
        "role": role,
        "content": content,
        "model": None,
        "timestamp": "2024-01-01T00:00:00",
        "metadata": None,
        "seq": 1,
    }


# ---------------------------------------------------------------------------
# commit_batch — tests
# ---------------------------------------------------------------------------


class TestCommitBatch:
    @pytest.fixture(autouse=True)
    def _setup_db(self, temp_db):
        """Unpack temp_db and add the seq column for every test."""
        self.conn, self.db_path = temp_db
        _add_seq_column(self.conn)

    # -- Happy path --

    def test_inserts_session_and_message(self):
        stats = ExportStats()
        commit_batch(self.conn, [_make_session()], [_make_message()], stats)

        row = self.conn.execute("SELECT * FROM sessions WHERE id = 's1'").fetchone()
        assert row is not None
        assert row["source"] == "test"

        msg = self.conn.execute("SELECT * FROM messages WHERE id = 'm1'").fetchone()
        assert msg is not None
        assert msg["content"] == "hello"

    def test_stats_incremented_for_added(self):
        stats = ExportStats()
        commit_batch(self.conn, [_make_session(status="added")], [], stats)
        assert stats.added == 1

    def test_stats_incremented_for_updated(self):
        stats = ExportStats()
        commit_batch(self.conn, [_make_session(status="updated")], [], stats)
        assert stats.updated == 1

    def test_stats_incremented_for_skipped(self):
        stats = ExportStats()
        commit_batch(self.conn, [_make_session(status="skipped")], [], stats)
        assert stats.skipped == 1

    def test_default_status_is_added(self):
        session = _make_session()
        del session["status"]  # no explicit status
        stats = ExportStats()
        commit_batch(self.conn, [session], [], stats)
        assert stats.added == 1

    # -- Multiple items --

    def test_batch_of_multiple_sessions(self):
        sessions = [_make_session(f"s{i}") for i in range(5)]
        messages = [_make_message(f"m{i}", f"s{i}") for i in range(5)]
        stats = ExportStats()
        commit_batch(self.conn, sessions, messages, stats)

        count = self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        assert count == 5
        assert stats.added == 5

    def test_mixed_statuses_in_batch(self):
        sessions = [
            _make_session("s1", status="added"),
            _make_session("s2", status="updated"),
            _make_session("s3", status="skipped"),
            _make_session("s4", status="added"),
        ]
        stats = ExportStats()
        commit_batch(self.conn, sessions, [], stats)
        assert stats.added == 2
        assert stats.updated == 1
        assert stats.skipped == 1

    # -- Edge cases --

    def test_empty_sessions_is_noop(self):
        stats = ExportStats()
        commit_batch(self.conn, [], [], stats)
        assert stats.added == 0
        count = self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        assert count == 0

    def test_sessions_without_messages(self):
        stats = ExportStats()
        commit_batch(self.conn, [_make_session()], [], stats)
        assert stats.added == 1
        count = self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        assert count == 0

    def test_insert_or_replace_updates_existing(self):
        stats = ExportStats()
        commit_batch(
            self.conn,
            [_make_session("s1", project_path="/v1", status="added")],
            [],
            stats,
        )
        commit_batch(
            self.conn,
            [_make_session("s1", project_path="/v2", status="updated")],
            [],
            stats,
        )

        row = self.conn.execute(
            "SELECT project_path FROM sessions WHERE id = 's1'"
        ).fetchone()
        assert row["project_path"] == "/v2"
        assert stats.added == 1
        assert stats.updated == 1

    def test_optional_fields_default_to_none(self):
        session = {
            "id": "minimal",
            "source": "test",
            "project_path": "/p",
            "status": "added",
        }
        stats = ExportStats()
        commit_batch(self.conn, [session], [], stats)

        row = self.conn.execute(
            "SELECT * FROM sessions WHERE id = 'minimal'"
        ).fetchone()
        assert row["git_branch"] is None
        assert row["created_at"] is None
        assert row["metadata"] is None

    def test_optional_message_fields_default_to_none(self):
        msg = {
            "id": "msg_min",
            "session_id": "s1",
            "role": "user",
            "content": "hi",
        }
        stats = ExportStats()
        commit_batch(self.conn, [_make_session()], [msg], stats)

        row = self.conn.execute(
            "SELECT * FROM messages WHERE id = 'msg_min'"
        ).fetchone()
        assert row["model"] is None
        assert row["timestamp"] is None
        assert row["seq"] is None

    # -- Error handling --

    def test_rollback_on_error_and_stats_updated(self):
        """If a batch fails, the transaction is rolled back and errors counted."""
        stats = ExportStats()
        # Insert a valid session first
        commit_batch(self.conn, [_make_session("good")], [], stats)
        assert stats.added == 1

        # Now cause an error: message references non-existent column won't work,
        # but a simpler approach is a bad message dict missing required keys.
        bad_messages = [{"bad_key": "no id field"}]
        with pytest.raises(KeyError):
            commit_batch(
                self.conn,
                [_make_session("s_err", status="added")],
                bad_messages,
                stats,
            )
        # The error path sets errors += len(sessions)
        assert stats.errors == 1
        # The failed session should have been rolled back
        row = self.conn.execute("SELECT * FROM sessions WHERE id = 's_err'").fetchone()
        assert row is None

    def test_data_committed_persistently(self):
        """Verify commit_batch actually calls conn.commit() (data survives reconnect)."""
        stats = ExportStats()
        commit_batch(self.conn, [_make_session()], [_make_message()], stats)

        # Open a fresh connection to the same DB
        conn2 = sqlite3.connect(self.db_path)
        conn2.row_factory = sqlite3.Row
        row = conn2.execute("SELECT * FROM sessions WHERE id = 's1'").fetchone()
        assert row is not None
        conn2.close()
