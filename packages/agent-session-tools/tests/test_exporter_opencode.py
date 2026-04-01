"""Tests for the OpenCode CLI session exporter."""

import json
from pathlib import Path

import pytest

import agent_session_tools.exporters.opencode as opencode_mod
from agent_session_tools.exporters.opencode import OpenCodeExporter, _ms_to_iso


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def opencode_tree(tmp_path: Path, monkeypatch) -> Path:
    """Create a fake OpenCode storage layout and point the module constant at it.

    Layout::

        tmp_path/
          storage/
            session/proj1/sess-001.json
            message/sess-001/msg-001.json
            part/msg-001/part-001.json
    """
    storage = tmp_path / "storage"

    # Session file
    session_dir = storage / "session" / "proj1"
    session_dir.mkdir(parents=True)
    session_data = {
        "id": "sess-001",
        "title": "Test Session",
        "version": "0.1",
        "directory": "/home/user/project",
        "time": {
            "created": 1717236000000,  # ~2024-06-01 10:00 UTC
            "updated": 1717239600000,  # ~2024-06-01 11:00 UTC
        },
    }
    (session_dir / "sess-001.json").write_text(json.dumps(session_data))

    # Message file
    msg_dir = storage / "message" / "sess-001"
    msg_dir.mkdir(parents=True)
    msg_data = {
        "id": "msg-001",
        "role": "user",
        "modelID": "claude-sonnet-4-20250514",
        "providerID": "anthropic",
        "time": {"created": 1717236000000},
        "tokens": {"input": 100, "output": 200},
        "cost": 0.005,
    }
    (msg_dir / "msg-001.json").write_text(json.dumps(msg_data))

    # Part file (text content)
    part_dir = storage / "part" / "msg-001"
    part_dir.mkdir(parents=True)
    part_data = {"type": "text", "text": "Explain decorators please."}
    (part_dir / "part-001.json").write_text(json.dumps(part_data))

    monkeypatch.setattr(opencode_mod, "OPENCODE_DIR", storage)
    return storage


@pytest.fixture()
def opencode_tree_no_messages(tmp_path: Path, monkeypatch) -> Path:
    """OpenCode storage with a session but no message directory."""
    storage = tmp_path / "storage"
    session_dir = storage / "session" / "proj1"
    session_dir.mkdir(parents=True)
    session_data = {
        "id": "orphan-session",
        "title": "No Messages",
        "version": "0.1",
        "directory": "/tmp/orphan",
        "time": {"created": 1717236000000, "updated": 1717236000000},
    }
    (session_dir / "orphan-session.json").write_text(json.dumps(session_data))

    monkeypatch.setattr(opencode_mod, "OPENCODE_DIR", storage)
    return storage


# ---------------------------------------------------------------------------
# _ms_to_iso  (pure function, no fixtures needed)
# ---------------------------------------------------------------------------


class TestMsToIso:
    def test_none_returns_none(self):
        assert _ms_to_iso(None) is None

    def test_zero_returns_epoch(self):
        result = _ms_to_iso(0)
        assert result is not None
        # Unix epoch: 1970-01-01T00:00:00 (in local timezone)
        assert "1970-01-01" in result or "1969-12-31" in result  # TZ-dependent

    def test_valid_ms_returns_iso_string(self):
        # 1717236000000 ms = 2024-06-01 10:00:00 UTC
        result = _ms_to_iso(1717236000000)
        assert result is not None
        assert "2024-06-01" in result
        assert "T" in result  # ISO format separator

    def test_negative_ms_returns_before_epoch(self):
        # -1000 ms = just before epoch
        result = _ms_to_iso(-1000)
        assert result is not None
        assert "1969" in result or "1970" in result


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


class TestIsAvailable:
    def test_true_when_session_dir_exists(self, opencode_tree):
        exporter = OpenCodeExporter()
        assert exporter.is_available() is True

    def test_false_when_storage_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(opencode_mod, "OPENCODE_DIR", tmp_path / "nonexistent")
        exporter = OpenCodeExporter()
        assert exporter.is_available() is False

    def test_false_when_storage_exists_but_no_session_dir(self, tmp_path, monkeypatch):
        storage = tmp_path / "storage"
        storage.mkdir()
        monkeypatch.setattr(opencode_mod, "OPENCODE_DIR", storage)
        exporter = OpenCodeExporter()
        assert exporter.is_available() is False


# ---------------------------------------------------------------------------
# _collect_messages
# ---------------------------------------------------------------------------


class TestCollectMessages:
    def test_collects_message_with_text_part(self, opencode_tree):
        exporter = OpenCodeExporter()
        messages = exporter._collect_messages("sess-001")

        assert len(messages) == 1
        msg = messages[0]
        assert msg["id"] == "msg-001"
        assert msg["role"] == "user"
        assert "decorators" in msg["content"].lower()
        assert msg["model"] == "claude-sonnet-4-20250514"
        assert msg["seq"] == 1

    def test_returns_empty_when_message_dir_missing(self, opencode_tree):
        exporter = OpenCodeExporter()
        messages = exporter._collect_messages("nonexistent-session")
        assert messages == []

    def test_metadata_contains_token_and_cost_info(self, opencode_tree):
        exporter = OpenCodeExporter()
        messages = exporter._collect_messages("sess-001")
        meta = json.loads(messages[0]["metadata"])
        assert meta["tokens_in"] == 100
        assert meta["tokens_out"] == 200
        assert meta["cost"] == 0.005
        assert meta["provider"] == "anthropic"


# ---------------------------------------------------------------------------
# _get_text_content
# ---------------------------------------------------------------------------


class TestGetTextContent:
    def test_concatenates_text_parts(self, opencode_tree):
        """Single text part should return its content."""
        exporter = OpenCodeExporter()
        content = exporter._get_text_content("msg-001")
        assert content == "Explain decorators please."

    def test_skips_non_text_parts(self, opencode_tree):
        """Tool-type parts should not appear in the text content."""
        part_dir = opencode_tree / "part" / "msg-001"
        tool_part = {"type": "tool", "text": "should_be_ignored"}
        (part_dir / "part-002.json").write_text(json.dumps(tool_part))

        exporter = OpenCodeExporter()
        content = exporter._get_text_content("msg-001")
        assert "should_be_ignored" not in content

    def test_returns_empty_string_when_no_parts(self, opencode_tree):
        exporter = OpenCodeExporter()
        content = exporter._get_text_content("nonexistent-msg")
        assert content == ""


# ---------------------------------------------------------------------------
# export_all (integration)
# ---------------------------------------------------------------------------


class TestExportAll:
    def test_exports_session_and_messages(self, migrated_db, opencode_tree):
        conn, _ = migrated_db
        exporter = OpenCodeExporter()
        stats = exporter.export_all(conn, incremental=False)

        assert stats.added == 1
        assert stats.errors == 0

        sessions = conn.execute("SELECT * FROM sessions").fetchall()
        assert len(sessions) == 1
        assert sessions[0]["source"] == "opencode"
        assert sessions[0]["project_path"] == "/home/user/project"

        meta = json.loads(sessions[0]["metadata"])
        assert meta["title"] == "Test Session"
        assert meta["version"] == "0.1"

        messages = conn.execute("SELECT * FROM messages").fetchall()
        assert len(messages) == 1

    def test_incremental_skips_existing(self, migrated_db, opencode_tree):
        conn, _ = migrated_db
        exporter = OpenCodeExporter()

        stats_first = exporter.export_all(conn, incremental=True)
        assert stats_first.added == 1

        stats_second = exporter.export_all(conn, incremental=True)
        assert stats_second.skipped == 1
        assert stats_second.added == 0

    def test_unavailable_returns_zero_stats(self, migrated_db, tmp_path, monkeypatch):
        conn, _ = migrated_db
        monkeypatch.setattr(opencode_mod, "OPENCODE_DIR", tmp_path / "nope")
        exporter = OpenCodeExporter()
        stats = exporter.export_all(conn, incremental=False)
        assert stats == opencode_mod.ExportStats()

    def test_session_without_messages_skipped(
        self, migrated_db, opencode_tree_no_messages
    ):
        conn, _ = migrated_db
        exporter = OpenCodeExporter()
        stats = exporter.export_all(conn, incremental=False)
        assert stats.skipped == 1
        assert stats.added == 0
