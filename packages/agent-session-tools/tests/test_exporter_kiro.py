"""Tests for the Kiro CLI session exporter.

Validates:
- is_available() reflects DB file existence.
- export_all() imports well-formed conversations from both v1 and v2 tables.
- Malformed JSON in the source DB increments stats.errors.
- Incremental mode skips already-imported sessions.
- Updated sessions are re-imported when updated_at changes.
- Empty history is skipped gracefully.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from agent_session_tools.exporters.kiro import KiroCliExporter, _extract_text


# ---------------------------------------------------------------------------
# Helpers — Kiro message format builders
# ---------------------------------------------------------------------------


def _make_user_msg(prompt: str) -> dict:
    """Build a Kiro-format user message with a prompt."""
    return {
        "user": {
            "additional_context": "",
            "env_context": {"env_state": {"operating_system": "macos"}},
            "content": {"Prompt": {"prompt": prompt}},
        },
    }


def _make_assistant_msg(text: str) -> dict:
    """Build a Kiro-format assistant message with text in ToolUse.content."""
    return {
        "assistant": {
            "ToolUse": {
                "message_id": "msg-001",
                "content": text,
            },
            "content": {},
        },
    }


def _make_tool_result_msg() -> dict:
    """Build a Kiro-format tool-result user message (no extractable text)."""
    return {
        "user": {
            "content": {"ToolUseResults": [{"result": "ok"}]},
        },
    }


def _make_entry(
    user_prompt: str | None = None,
    assistant_text: str | None = None,
    timestamp_ms: int | None = None,
) -> dict:
    """Build a complete Kiro history entry with optional user + assistant."""
    entry: dict = {}
    if user_prompt is not None:
        entry.update(_make_user_msg(user_prompt))
    if assistant_text is not None:
        entry.update(_make_assistant_msg(assistant_text))
    if timestamp_ms is not None:
        entry["request_metadata"] = {
            "request_id": "req-1",
            "message_id": "msg-1",
            "request_start_timestamp_ms": timestamp_ms,
        }
    return entry


def _make_conversation(
    conversation_id: str = "conv-001",
    history: list[dict] | None = None,
) -> dict:
    """Build a minimal well-formed Kiro conversation payload."""
    if history is None:
        history = [
            _make_entry(
                user_prompt="What is Python?", assistant_text="A programming language."
            ),
        ]
    return {
        "conversation_id": conversation_id,
        "history": history,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def kiro_db(tmp_path) -> Path:
    """Create a fake Kiro CLI SQLite database with the v2 schema."""
    db_path = tmp_path / "kiro-data.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE conversations_v2 ("
        "key TEXT NOT NULL, "
        "conversation_id TEXT NOT NULL, "
        "value TEXT NOT NULL, "
        "created_at INTEGER NOT NULL, "
        "updated_at INTEGER NOT NULL, "
        "PRIMARY KEY (key, conversation_id))"
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture()
def kiro_db_v1(tmp_path) -> Path:
    """Create a fake Kiro CLI SQLite database with the v1 schema only."""
    db_path = tmp_path / "kiro-data-v1.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE conversations (key TEXT, value TEXT)")
    conn.commit()
    conn.close()
    return db_path


def _insert_v2(
    db_path: Path,
    project_key: str,
    data: dict,
    conversation_id: str | None = None,
    created_at: int = 1766936938000,
    updated_at: int = 1766936938000,
) -> None:
    """Insert a row into the conversations_v2 table."""
    conv_id = conversation_id or data.get("conversation_id", "conv-001")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO conversations_v2 (key, conversation_id, value, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (project_key, conv_id, json.dumps(data), created_at, updated_at),
    )
    conn.commit()
    conn.close()


def _insert_v1(db_path: Path, project_key: str, data: dict) -> None:
    """Insert a row into the conversations (v1) table."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO conversations (key, value) VALUES (?, ?)",
        (project_key, json.dumps(data)),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# _extract_text unit tests
# ---------------------------------------------------------------------------


class TestExtractText:
    def test_user_prompt(self):
        entry = _make_entry(user_prompt="Hello world")
        results = _extract_text(entry)
        assert len(results) == 1
        assert results[0][0] == "user"
        assert results[0][1] == "Hello world"

    def test_assistant_tooluse_content(self):
        entry = _make_entry(assistant_text="Here is the answer")
        results = _extract_text(entry)
        assert len(results) == 1
        assert results[0][0] == "assistant"
        assert results[0][1] == "Here is the answer"

    def test_both_user_and_assistant(self):
        entry = _make_entry(user_prompt="Q?", assistant_text="A.")
        results = _extract_text(entry)
        assert len(results) == 2
        roles = [r for r, _, _ in results]
        assert roles == ["user", "assistant"]

    def test_tool_result_yields_nothing(self):
        entry = _make_tool_result_msg()
        results = _extract_text(entry)
        assert results == []

    def test_timestamp_backfilled(self):
        entry = _make_entry(user_prompt="Hi", timestamp_ms=1766936938000)
        results = _extract_text(entry)
        assert len(results) == 1
        assert results[0][2] is not None
        assert "2025" in results[0][2] or "2026" in results[0][2]

    def test_empty_entry(self):
        assert _extract_text({}) == []


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
# export_all — v2 happy path
# ---------------------------------------------------------------------------


class TestKiroExportAllV2:
    def test_single_conversation(self, kiro_db, migrated_db, monkeypatch):
        monkeypatch.setattr("agent_session_tools.exporters.kiro.KIRO_DB", kiro_db)
        conn, _ = migrated_db

        _insert_v2(kiro_db, "/home/user/project-a", _make_conversation())

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
        assert session["created_at"] is not None

        # Verify messages
        msgs = conn.execute(
            "SELECT role, content, seq FROM messages WHERE session_id = 'kiro_conv-001' ORDER BY seq"
        ).fetchall()
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "What is Python?"
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["content"] == "A programming language."
        assert msgs[0]["seq"] == 1
        assert msgs[1]["seq"] == 2

    def test_multiple_conversations(self, kiro_db, migrated_db, monkeypatch):
        monkeypatch.setattr("agent_session_tools.exporters.kiro.KIRO_DB", kiro_db)
        conn, _ = migrated_db

        for i in range(3):
            _insert_v2(
                kiro_db,
                f"/project-{i}",
                _make_conversation(conversation_id=f"conv-{i}"),
                conversation_id=f"conv-{i}",
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

    def test_tool_result_messages_excluded(self, kiro_db, migrated_db, monkeypatch):
        """ToolUseResults entries should not produce messages."""
        monkeypatch.setattr("agent_session_tools.exporters.kiro.KIRO_DB", kiro_db)
        conn, _ = migrated_db

        history = [
            _make_entry(user_prompt="Do something"),
            _make_tool_result_msg(),  # no extractable text
            _make_entry(assistant_text="Done."),
        ]
        _insert_v2(kiro_db, "/project", _make_conversation(history=history))

        exporter = KiroCliExporter()
        stats = exporter.export_all(conn)
        assert stats.added == 1

        msgs = conn.execute(
            "SELECT role FROM messages WHERE session_id = 'kiro_conv-001' ORDER BY seq"
        ).fetchall()
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"


# ---------------------------------------------------------------------------
# export_all — v1 fallback
# ---------------------------------------------------------------------------


class TestKiroExportAllV1:
    def test_v1_table_works(self, kiro_db_v1, migrated_db, monkeypatch):
        """The exporter should fall back to the v1 conversations table."""
        monkeypatch.setattr("agent_session_tools.exporters.kiro.KIRO_DB", kiro_db_v1)
        conn, _ = migrated_db

        _insert_v1(
            kiro_db_v1, "/old-project", _make_conversation(conversation_id="v1-conv")
        )

        exporter = KiroCliExporter()
        stats = exporter.export_all(conn)

        assert stats.added == 1
        session = conn.execute(
            "SELECT * FROM sessions WHERE id = 'kiro_v1-conv'"
        ).fetchone()
        assert session is not None
        assert session["source"] == "kiro_cli"


# ---------------------------------------------------------------------------
# Malformed data handling
# ---------------------------------------------------------------------------


class TestKiroMalformedData:
    def test_invalid_json_increments_errors(self, kiro_db, migrated_db, monkeypatch):
        monkeypatch.setattr("agent_session_tools.exporters.kiro.KIRO_DB", kiro_db)
        conn, _ = migrated_db

        # Insert raw bad JSON directly
        src_conn = sqlite3.connect(kiro_db)
        src_conn.execute(
            "INSERT INTO conversations_v2 (key, conversation_id, value, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("/project", "bad-conv", "{malformed json!!!", 1000, 1000),
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
        _insert_v2(kiro_db, "/empty-project", data, conversation_id="empty-conv")

        exporter = KiroCliExporter()
        stats = exporter.export_all(conn)
        assert stats.skipped == 1
        assert stats.added == 0

    def test_missing_history_key_is_skipped(self, kiro_db, migrated_db, monkeypatch):
        monkeypatch.setattr("agent_session_tools.exporters.kiro.KIRO_DB", kiro_db)
        conn, _ = migrated_db

        data = {"conversation_id": "no-history"}
        _insert_v2(kiro_db, "/project", data, conversation_id="no-history")

        exporter = KiroCliExporter()
        stats = exporter.export_all(conn)
        assert stats.skipped == 1

    def test_non_dict_messages_in_history_are_ignored(
        self, kiro_db, migrated_db, monkeypatch
    ):
        """Non-dict entries in history should be silently skipped."""
        monkeypatch.setattr("agent_session_tools.exporters.kiro.KIRO_DB", kiro_db)
        conn, _ = migrated_db

        history = [
            "this is a string, not a dict",
            _make_entry(user_prompt="valid message"),
            42,
            None,
        ]
        data = _make_conversation(conversation_id="mixed-conv", history=history)
        _insert_v2(kiro_db, "/project", data, conversation_id="mixed-conv")

        exporter = KiroCliExporter()
        stats = exporter.export_all(conn)
        assert stats.added == 1

        msgs = conn.execute(
            "SELECT * FROM messages WHERE session_id = 'kiro_mixed-conv'"
        ).fetchall()
        assert len(msgs) == 1

    def test_history_with_only_tool_results_is_skipped(
        self, kiro_db, migrated_db, monkeypatch
    ):
        """If all history entries are tool results with no text, skip the session."""
        monkeypatch.setattr("agent_session_tools.exporters.kiro.KIRO_DB", kiro_db)
        conn, _ = migrated_db

        history = [_make_tool_result_msg(), _make_tool_result_msg()]
        data = _make_conversation(conversation_id="tools-only", history=history)
        _insert_v2(kiro_db, "/project", data, conversation_id="tools-only")

        exporter = KiroCliExporter()
        stats = exporter.export_all(conn)
        # No extractable text → no messages → session not added
        assert stats.added == 0


# ---------------------------------------------------------------------------
# Incremental mode
# ---------------------------------------------------------------------------


class TestKiroIncremental:
    def test_skips_already_imported_session(self, kiro_db, migrated_db, monkeypatch):
        monkeypatch.setattr("agent_session_tools.exporters.kiro.KIRO_DB", kiro_db)
        conn, _ = migrated_db

        _insert_v2(kiro_db, "/project", _make_conversation())

        exporter = KiroCliExporter()

        # First import
        stats1 = exporter.export_all(conn)
        assert stats1.added == 1

        # Second import — same session should be skipped
        stats2 = exporter.export_all(conn, incremental=True)
        assert stats2.skipped == 1
        assert stats2.added == 0

    def test_updated_session_reimported(self, kiro_db, migrated_db, monkeypatch):
        """When updated_at changes, the session should be re-imported as 'updated'."""
        monkeypatch.setattr("agent_session_tools.exporters.kiro.KIRO_DB", kiro_db)
        conn, _ = migrated_db

        _insert_v2(
            kiro_db,
            "/project",
            _make_conversation(),
            updated_at=1000000,
        )

        exporter = KiroCliExporter()
        stats1 = exporter.export_all(conn)
        assert stats1.added == 1

        # Update the row in Kiro DB with a new updated_at
        src_conn = sqlite3.connect(kiro_db)
        src_conn.execute(
            "UPDATE conversations_v2 SET updated_at = ? WHERE conversation_id = ?",
            (2000000, "conv-001"),
        )
        src_conn.commit()
        src_conn.close()

        stats2 = exporter.export_all(conn, incremental=True)
        assert stats2.updated == 1
        assert stats2.skipped == 0

    def test_non_incremental_reimports(self, kiro_db, migrated_db, monkeypatch):
        monkeypatch.setattr("agent_session_tools.exporters.kiro.KIRO_DB", kiro_db)
        conn, _ = migrated_db

        _insert_v2(kiro_db, "/project", _make_conversation())

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
            _insert_v2(
                kiro_db,
                f"/project-{i}",
                _make_conversation(conversation_id=f"batch-{i}"),
                conversation_id=f"batch-{i}",
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
