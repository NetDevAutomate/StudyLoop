"""Tests for the Kiro CLI session exporter.

Validates:
- is_available() reflects DB file existence.
- export_all() imports well-formed conversations into the target DB.
- Malformed JSON in the source DB increments stats.errors.
- Incremental mode skips already-imported sessions.
- Empty history is skipped gracefully.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from agent_session_tools.exporters.kiro import KiroCliExporter
from agent_session_tools.migrations import migrate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def migrated_db(temp_db):
    """Return a temp_db with all migrations applied so exporter columns exist."""
    conn, db_path = temp_db
    migrate(conn)
    return conn, db_path


@pytest.fixture()
def kiro_db(tmp_path) -> Path:
    """Create a fake Kiro CLI SQLite database with the expected schema."""
    db_path = tmp_path / "kiro-data.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE conversations (key TEXT, value TEXT)")
    conn.commit()
    conn.close()
    return db_path


def _insert_conversation(db_path: Path, project_key: str, data: dict) -> None:
    """Helper to insert a row into the fake Kiro DB."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO conversations (key, value) VALUES (?, ?)",
        (project_key, json.dumps(data)),
    )
    conn.commit()
    conn.close()


def _make_conversation(
    conversation_id: str = "conv-001",
    messages: list[dict] | None = None,
) -> dict:
    """Build a minimal well-formed Kiro conversation payload."""
    if messages is None:
        messages = [
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "content": "A programming language."},
        ]
    return {
        "conversation_id": conversation_id,
        "history": messages,
    }


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


class TestKiroIsAvailable:
    def test_available_when_db_exists(self, kiro_db, monkeypatch):
        monkeypatch.setattr("agent_session_tools.exporters.kiro.KIRO_DB", kiro_db)
        exporter = KiroCliExporter()
        assert exporter.is_available() is True

    def test_not_available_when_db_missing(self, tmp_path, monkeypatch):
        missing = tmp_path / "no-such-file.sqlite3"
        monkeypatch.setattr("agent_session_tools.exporters.kiro.KIRO_DB", missing)
        exporter = KiroCliExporter()
        assert exporter.is_available() is False


# ---------------------------------------------------------------------------
# export_all — happy path
# ---------------------------------------------------------------------------


class TestKiroExportAll:
    def test_single_conversation(self, kiro_db, migrated_db, monkeypatch):
        monkeypatch.setattr("agent_session_tools.exporters.kiro.KIRO_DB", kiro_db)
        conn, _ = migrated_db

        _insert_conversation(kiro_db, "/home/user/project-a", _make_conversation())

        exporter = KiroCliExporter()
        stats = exporter.export_all(conn)

        assert stats.added == 1
        assert stats.errors == 0

        # Verify session row
        session = conn.execute(
            "SELECT * FROM sessions WHERE id = 'kiro_conv-001'"
        ).fetchone()
        assert session is not None
        assert session["source"] == "kiro_cli"
        assert session["project_path"] == "/home/user/project-a"

        # Verify messages
        msgs = conn.execute(
            "SELECT role, content, seq FROM messages WHERE session_id = 'kiro_conv-001' ORDER BY seq"
        ).fetchall()
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"
        assert msgs[0]["seq"] == 1
        assert msgs[1]["seq"] == 2

    def test_multiple_conversations(self, kiro_db, migrated_db, monkeypatch):
        monkeypatch.setattr("agent_session_tools.exporters.kiro.KIRO_DB", kiro_db)
        conn, _ = migrated_db

        for i in range(3):
            _insert_conversation(
                kiro_db,
                f"/project-{i}",
                _make_conversation(conversation_id=f"conv-{i}"),
            )

        exporter = KiroCliExporter()
        stats = exporter.export_all(conn)

        assert stats.added == 3
        count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        assert count == 3

    def test_returns_empty_stats_when_unavailable(
        self, tmp_path, migrated_db, monkeypatch
    ):
        monkeypatch.setattr(
            "agent_session_tools.exporters.kiro.KIRO_DB", tmp_path / "nonexistent.db"
        )
        conn, _ = migrated_db
        exporter = KiroCliExporter()
        stats = exporter.export_all(conn)
        assert stats.added == 0
        assert stats.skipped == 0
        assert stats.errors == 0


# ---------------------------------------------------------------------------
# Malformed data handling
# ---------------------------------------------------------------------------


class TestKiroMalformedData:
    def test_invalid_json_increments_errors(self, kiro_db, migrated_db, monkeypatch):
        monkeypatch.setattr("agent_session_tools.exporters.kiro.KIRO_DB", kiro_db)
        conn, _ = migrated_db

        # Insert raw bad JSON (not going through json.dumps)
        src_conn = sqlite3.connect(kiro_db)
        src_conn.execute(
            "INSERT INTO conversations (key, value) VALUES (?, ?)",
            ("/project", "{malformed json!!!"),
        )
        src_conn.commit()
        src_conn.close()

        exporter = KiroCliExporter()
        stats = exporter.export_all(conn)
        assert stats.errors == 1
        assert stats.added == 0

    def test_empty_history_is_skipped(self, kiro_db, migrated_db, monkeypatch):
        monkeypatch.setattr("agent_session_tools.exporters.kiro.KIRO_DB", kiro_db)
        conn, _ = migrated_db

        data = {"conversation_id": "empty-conv", "history": []}
        _insert_conversation(kiro_db, "/empty-project", data)

        exporter = KiroCliExporter()
        stats = exporter.export_all(conn)
        assert stats.skipped == 1
        assert stats.added == 0

    def test_missing_history_key_is_skipped(self, kiro_db, migrated_db, monkeypatch):
        monkeypatch.setattr("agent_session_tools.exporters.kiro.KIRO_DB", kiro_db)
        conn, _ = migrated_db

        data = {"conversation_id": "no-history"}
        _insert_conversation(kiro_db, "/project", data)

        exporter = KiroCliExporter()
        stats = exporter.export_all(conn)
        assert stats.skipped == 1

    def test_non_dict_messages_in_history_are_ignored(
        self, kiro_db, migrated_db, monkeypatch
    ):
        """Non-dict entries in history should be silently skipped."""
        monkeypatch.setattr("agent_session_tools.exporters.kiro.KIRO_DB", kiro_db)
        conn, _ = migrated_db

        data = {
            "conversation_id": "mixed-conv",
            "history": [
                "this is a string, not a dict",
                {"role": "user", "content": "valid message"},
                42,
                None,
            ],
        }
        _insert_conversation(kiro_db, "/project", data)

        exporter = KiroCliExporter()
        stats = exporter.export_all(conn)
        assert stats.added == 1

        msgs = conn.execute(
            "SELECT * FROM messages WHERE session_id = 'kiro_mixed-conv'"
        ).fetchall()
        assert len(msgs) == 1

    def test_messages_with_no_content_are_excluded(
        self, kiro_db, migrated_db, monkeypatch
    ):
        monkeypatch.setattr("agent_session_tools.exporters.kiro.KIRO_DB", kiro_db)
        conn, _ = migrated_db

        data = {
            "conversation_id": "no-content-conv",
            "history": [
                {"role": "user", "content": ""},
                {"role": "user", "content": None},
                {"role": "assistant", "content": "real answer"},
            ],
        }
        _insert_conversation(kiro_db, "/project", data)

        exporter = KiroCliExporter()
        stats = exporter.export_all(conn)
        assert stats.added == 1

        msgs = conn.execute(
            "SELECT * FROM messages WHERE session_id = 'kiro_no-content-conv'"
        ).fetchall()
        # Only "real answer" has truthy content
        assert len(msgs) == 1


# ---------------------------------------------------------------------------
# Incremental mode
# ---------------------------------------------------------------------------


class TestKiroIncremental:
    def test_skips_already_imported_session(self, kiro_db, migrated_db, monkeypatch):
        monkeypatch.setattr("agent_session_tools.exporters.kiro.KIRO_DB", kiro_db)
        conn, _ = migrated_db

        _insert_conversation(kiro_db, "/project", _make_conversation())

        exporter = KiroCliExporter()

        # First import
        stats1 = exporter.export_all(conn)
        assert stats1.added == 1

        # Second import — same session should be skipped
        stats2 = exporter.export_all(conn, incremental=True)
        assert stats2.skipped == 1
        assert stats2.added == 0

    def test_non_incremental_reimports(self, kiro_db, migrated_db, monkeypatch):
        monkeypatch.setattr("agent_session_tools.exporters.kiro.KIRO_DB", kiro_db)
        conn, _ = migrated_db

        _insert_conversation(kiro_db, "/project", _make_conversation())

        exporter = KiroCliExporter()

        stats1 = exporter.export_all(conn)
        assert stats1.added == 1

        # Non-incremental re-import should NOT skip
        stats2 = exporter.export_all(conn, incremental=False)
        assert stats2.added == 1
        assert stats2.skipped == 0


# ---------------------------------------------------------------------------
# Batching
# ---------------------------------------------------------------------------


class TestKiroBatching:
    def test_batch_size_commits_in_chunks(self, kiro_db, migrated_db, monkeypatch):
        """With batch_size=2 and 5 conversations, all 5 should still be imported."""
        monkeypatch.setattr("agent_session_tools.exporters.kiro.KIRO_DB", kiro_db)
        conn, _ = migrated_db

        for i in range(5):
            _insert_conversation(
                kiro_db,
                f"/project-{i}",
                _make_conversation(conversation_id=f"batch-{i}"),
            )

        exporter = KiroCliExporter()
        stats = exporter.export_all(conn, batch_size=2)

        assert stats.added == 5
        count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        assert count == 5


# ---------------------------------------------------------------------------
# source_name
# ---------------------------------------------------------------------------


class TestKiroSourceName:
    def test_source_name_value(self):
        exporter = KiroCliExporter()
        assert exporter.source_name == "kiro_cli"
