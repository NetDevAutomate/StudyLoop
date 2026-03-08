"""Tests for the Gemini CLI session exporter."""

import json
from pathlib import Path

import pytest

import agent_session_tools.exporters.gemini as gemini_mod
from agent_session_tools.exporters.gemini import GeminiCliExporter
from agent_session_tools.migrations import migrate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_session_file(chats_dir: Path, session_id: str, messages: list[dict]) -> Path:
    """Write a minimal Gemini CLI session JSON file to *chats_dir*."""
    data = {
        "sessionId": session_id,
        "projectHash": "abc123",
        "startTime": "2025-06-01T10:00:00",
        "lastUpdated": "2025-06-01T11:00:00",
        "messages": messages,
    }
    path = chats_dir / f"session-{session_id}.json"
    path.write_text(json.dumps(data))
    return path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def migrated_db(temp_db):
    """Return (conn, db_path) with migrations applied."""
    conn, db_path = temp_db
    migrate(conn)
    return conn, db_path


@pytest.fixture()
def gemini_dir(tmp_path: Path, monkeypatch) -> Path:
    """Create a fake Gemini CLI directory tree and point the module constant at it.

    Layout::

        tmp_path/
          gemini_tmp/
            some_project/
              chats/
                session-sess001.json
    """
    gemini_tmp = tmp_path / "gemini_tmp"
    chats = gemini_tmp / "some_project" / "chats"
    chats.mkdir(parents=True)

    messages = [
        {
            "id": "msg-1",
            "type": "user",
            "content": "Explain async/await",
            "timestamp": 1717236000000,  # 2024-06-01 ~10:00 UTC
            "model": None,
            "tokens": {"input": 10, "output": 0},
            "thoughts": None,
        },
        {
            "id": "msg-2",
            "type": "gemini",
            "content": "Async/await is a concurrency pattern.",
            "timestamp": 1717236060000,
            "model": "gemini-2.5-pro",
            "tokens": {"input": 10, "output": 50},
            "thoughts": "thinking...",
        },
    ]
    _write_session_file(chats, "sess001", messages)

    # Monkeypatch the module-level constant so the exporter finds our fake tree
    monkeypatch.setattr(gemini_mod, "GEMINI_DIR", gemini_tmp)
    return gemini_tmp


@pytest.fixture()
def gemini_dir_empty(tmp_path: Path, monkeypatch) -> Path:
    """Point GEMINI_DIR at a directory that exists but contains no session files."""
    empty = tmp_path / "gemini_empty"
    empty.mkdir()
    monkeypatch.setattr(gemini_mod, "GEMINI_DIR", empty)
    return empty


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


class TestIsAvailable:
    def test_true_when_directory_exists(self, gemini_dir):
        exporter = GeminiCliExporter()
        assert exporter.is_available() is True

    def test_false_when_directory_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gemini_mod, "GEMINI_DIR", tmp_path / "no_such_dir")
        exporter = GeminiCliExporter()
        assert exporter.is_available() is False


# ---------------------------------------------------------------------------
# _parse_session_file
# ---------------------------------------------------------------------------


class TestParseSessionFile:
    def test_parses_valid_session(self, gemini_dir):
        exporter = GeminiCliExporter()
        session_file = list(gemini_dir.rglob("session-*.json"))[0]
        result = exporter._parse_session_file(session_file)

        assert result is not None
        session_id, project_hash, messages, created_at, updated_at = result
        assert session_id == "gemini_sess001"
        assert project_hash == "abc123"
        assert len(messages) == 2

    def test_gemini_role_replaced_with_assistant(self, gemini_dir):
        exporter = GeminiCliExporter()
        session_file = list(gemini_dir.rglob("session-*.json"))[0]
        _, _, messages, _, _ = exporter._parse_session_file(session_file)
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"  # "gemini" -> "assistant"

    def test_timestamp_converted_from_ms(self, gemini_dir):
        exporter = GeminiCliExporter()
        session_file = list(gemini_dir.rglob("session-*.json"))[0]
        _, _, messages, _, _ = exporter._parse_session_file(session_file)
        # Timestamp should be ISO-format, not None
        assert messages[0]["timestamp"] is not None
        assert "T" in messages[0]["timestamp"]

    def test_returns_none_for_invalid_json(self, tmp_path):
        bad_file = tmp_path / "session-bad.json"
        bad_file.write_text("not json at all {{{")
        exporter = GeminiCliExporter()
        assert exporter._parse_session_file(bad_file) is None

    def test_list_content_joined(self, tmp_path, monkeypatch):
        """When content is a list of parts, they should be joined with newlines."""
        chats = tmp_path / "proj" / "chats"
        chats.mkdir(parents=True)
        monkeypatch.setattr(gemini_mod, "GEMINI_DIR", tmp_path)

        data = {
            "sessionId": "list-content-test",
            "projectHash": "proj",
            "startTime": "2025-01-01T00:00:00",
            "lastUpdated": "2025-01-01T01:00:00",
            "messages": [
                {
                    "id": "m1",
                    "type": "user",
                    "content": ["part one", "part two"],
                    "timestamp": None,
                }
            ],
        }
        (chats / "session-list-content-test.json").write_text(json.dumps(data))

        exporter = GeminiCliExporter()
        _, _, messages, _, _ = exporter._parse_session_file(
            chats / "session-list-content-test.json"
        )
        assert messages[0]["content"] == "part one\npart two"

    def test_metadata_contains_tokens_and_thoughts(self, gemini_dir):
        exporter = GeminiCliExporter()
        session_file = list(gemini_dir.rglob("session-*.json"))[0]
        _, _, messages, _, _ = exporter._parse_session_file(session_file)

        meta = json.loads(messages[1]["metadata"])
        assert "tokens" in meta
        assert "thoughts" in meta
        assert meta["thoughts"] == "thinking..."


# ---------------------------------------------------------------------------
# export_all (integration)
# ---------------------------------------------------------------------------


class TestExportAll:
    def test_exports_session_and_messages(self, migrated_db, gemini_dir):
        conn, _ = migrated_db
        exporter = GeminiCliExporter()
        stats = exporter.export_all(conn, incremental=False)

        assert stats.added == 1
        assert stats.errors == 0

        sessions = conn.execute("SELECT * FROM sessions").fetchall()
        assert len(sessions) == 1
        assert sessions[0]["source"] == "gemini_cli"

        messages = conn.execute("SELECT * FROM messages ORDER BY seq").fetchall()
        assert len(messages) == 2

    def test_incremental_skips_existing_session(self, migrated_db, gemini_dir):
        conn, _ = migrated_db
        exporter = GeminiCliExporter()

        stats_first = exporter.export_all(conn, incremental=True)
        assert stats_first.added == 1

        stats_second = exporter.export_all(conn, incremental=True)
        assert stats_second.skipped == 1
        assert stats_second.added == 0

    def test_unavailable_returns_zero_stats(self, migrated_db, tmp_path, monkeypatch):
        conn, _ = migrated_db
        monkeypatch.setattr(gemini_mod, "GEMINI_DIR", tmp_path / "nonexistent")
        exporter = GeminiCliExporter()
        stats = exporter.export_all(conn, incremental=False)

        assert stats.added == 0
        assert stats.skipped == 0
        assert stats.errors == 0

    def test_empty_messages_session_skipped(self, migrated_db, tmp_path, monkeypatch):
        """A session file with zero messages should be skipped, not error."""
        gemini_tmp = tmp_path / "gemini_empty_msg"
        chats = gemini_tmp / "proj" / "chats"
        chats.mkdir(parents=True)
        monkeypatch.setattr(gemini_mod, "GEMINI_DIR", gemini_tmp)

        _write_session_file(chats, "empty-sess", messages=[])

        conn, _ = migrated_db
        exporter = GeminiCliExporter()
        stats = exporter.export_all(conn, incremental=False)

        assert stats.added == 0
        assert stats.skipped == 1
