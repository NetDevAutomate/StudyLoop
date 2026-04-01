"""Tests for the RepoPrompt session exporter."""

import json
from pathlib import Path

import pytest

from agent_session_tools.exporters.repoprompt import (
    RepoPromptExporter,
    cf_timestamp_to_iso,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def repoprompt_dir(tmp_path: Path) -> Path:
    """Create a fake RepoPrompt Application Support tree.

    Layout::

        tmp_path/
          Workspaces/
            Workspace-MyProject-<uuid>/
              Chats/
                ChatSession-001.json
          windowSessions.json
    """
    workspace_uuid = "12345678-1234-1234-1234-123456789abc"
    workspace_name = f"Workspace-MyProject-{workspace_uuid}"
    workspace_dir = tmp_path / "Workspaces" / workspace_name
    chats_dir = workspace_dir / "Chats"
    chats_dir.mkdir(parents=True)

    # Create windowSessions.json
    window_sessions = {
        "windows": [
            {
                "workspaceID": workspace_uuid,
                "workspaceName": "my-cool-project",
            }
        ]
    }
    (tmp_path / "windowSessions.json").write_text(json.dumps(window_sessions))

    # Core Foundation timestamp for 2025-01-15 12:00:00 UTC
    # CF epoch = 2001-01-01 00:00:00 UTC, so offset = 978307200
    # 2025-01-15 12:00:00 UTC = 1736942400 unix  =>  CF = 1736942400 - 978307200 = 758635200
    cf_ts_1 = 758635200.0
    cf_ts_2 = 758635260.0  # 60 seconds later

    chat_data = {
        "id": "chat-session-001",
        "shortID": "CS001",
        "name": "Test Chat",
        "workspaceID": workspace_uuid,
        "preferredAIModel": "claude-sonnet-4-20250514",
        "selectedFilePaths": ["/src/main.py"],
        "savedAt": cf_ts_2,
        "messages": [
            {
                "id": "msg-u1",
                "isUser": True,
                "rawText": "How do I use pytest fixtures?",
                "timestamp": cf_ts_1,
                "modelName": None,
                "sequenceIndex": 0,
                "promptTokens": 15,
                "completionTokens": 0,
                "cost": 0.0,
            },
            {
                "id": "msg-a1",
                "isUser": False,
                "rawText": "Fixtures provide reusable test setup.",
                "timestamp": cf_ts_2,
                "modelName": "claude-sonnet-4-20250514",
                "sequenceIndex": 1,
                "promptTokens": 15,
                "completionTokens": 30,
                "cost": 0.002,
            },
        ],
    }
    (chats_dir / "ChatSession-001.json").write_text(json.dumps(chat_data))

    return tmp_path


# ---------------------------------------------------------------------------
# cf_timestamp_to_iso (pure function)
# ---------------------------------------------------------------------------


class TestCfTimestampToIso:
    def test_none_returns_none(self):
        assert cf_timestamp_to_iso(None) is None

    def test_zero_returns_cf_epoch(self):
        """CF timestamp 0 corresponds to 2001-01-01T00:00:00+00:00."""
        result = cf_timestamp_to_iso(0)
        assert result is not None
        assert "2001-01-01" in result
        assert "00:00:00" in result

    def test_known_timestamp(self):
        """Verify a hand-computed CF timestamp converts correctly."""
        # CF = 758635200.0 => unix = 758635200 + 978307200 = 1736942400
        # 1736942400 = 2025-01-15 12:00:00 UTC
        result = cf_timestamp_to_iso(758635200.0)
        assert result is not None
        assert "2025-01-15" in result
        assert "12:00:00" in result

    def test_returns_utc_timezone(self):
        """Returned ISO string should include timezone info."""
        result = cf_timestamp_to_iso(0)
        assert result is not None
        # Should have UTC offset indicator
        assert "+00:00" in result or "Z" in result

    def test_negative_cf_timestamp(self):
        """Negative CF timestamp means before 2001-01-01."""
        result = cf_timestamp_to_iso(-86400.0)  # 1 day before CF epoch
        assert result is not None
        assert "2000-12-31" in result

    def test_overflow_returns_none(self):
        """Extremely large values should return None, not crash."""
        result = cf_timestamp_to_iso(1e20)
        assert result is None


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


class TestIsAvailable:
    def test_true_when_workspaces_dir_exists(self, repoprompt_dir):
        exporter = RepoPromptExporter(app_support_dir=repoprompt_dir)
        assert exporter.is_available() is True

    def test_false_when_dir_missing(self, tmp_path):
        exporter = RepoPromptExporter(app_support_dir=tmp_path / "nonexistent")
        assert exporter.is_available() is False

    def test_false_when_no_workspaces_subdir(self, tmp_path):
        """The app_support_dir exists but has no Workspaces/ subdirectory."""
        (tmp_path / "some_other_dir").mkdir()
        exporter = RepoPromptExporter(app_support_dir=tmp_path)
        assert exporter.is_available() is False


# ---------------------------------------------------------------------------
# _load_workspace_mapping
# ---------------------------------------------------------------------------


class TestLoadWorkspaceMapping:
    def test_loads_mapping_from_window_sessions(self, repoprompt_dir):
        exporter = RepoPromptExporter(app_support_dir=repoprompt_dir)
        mapping = exporter._load_workspace_mapping()
        assert "12345678-1234-1234-1234-123456789abc" in mapping
        assert mapping["12345678-1234-1234-1234-123456789abc"] == "my-cool-project"

    def test_caches_mapping(self, repoprompt_dir):
        exporter = RepoPromptExporter(app_support_dir=repoprompt_dir)
        mapping1 = exporter._load_workspace_mapping()
        mapping2 = exporter._load_workspace_mapping()
        assert mapping1 is mapping2  # Same dict object (cached)

    def test_returns_empty_when_file_missing(self, tmp_path):
        exporter = RepoPromptExporter(app_support_dir=tmp_path)
        mapping = exporter._load_workspace_mapping()
        assert mapping == {}


# ---------------------------------------------------------------------------
# _extract_workspace_name
# ---------------------------------------------------------------------------


class TestExtractWorkspaceName:
    def test_extracts_from_mapping(self, repoprompt_dir):
        exporter = RepoPromptExporter(app_support_dir=repoprompt_dir)
        ws_path = (
            repoprompt_dir
            / "Workspaces"
            / "Workspace-MyProject-12345678-1234-1234-1234-123456789abc"
        )
        name = exporter._extract_workspace_name(ws_path)
        assert name == "my-cool-project"

    def test_fallback_parses_directory_name(self, tmp_path):
        """Without a windowSessions.json, parse from directory name."""
        exporter = RepoPromptExporter(app_support_dir=tmp_path)
        ws_path = (
            tmp_path / "Workspace-SomeProject-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        )
        name = exporter._extract_workspace_name(ws_path)
        assert name == "SomeProject"


# ---------------------------------------------------------------------------
# export_all (integration)
# ---------------------------------------------------------------------------


class TestExportAll:
    def test_exports_session_and_messages(self, migrated_db, repoprompt_dir):
        conn, _ = migrated_db
        exporter = RepoPromptExporter(app_support_dir=repoprompt_dir)
        stats = exporter.export_all(conn, incremental=False)

        assert stats.added == 1
        assert stats.errors == 0

        sessions = conn.execute("SELECT * FROM sessions").fetchall()
        assert len(sessions) == 1
        assert sessions[0]["source"] == "repoprompt"
        assert sessions[0]["project_path"] == "my-cool-project"

        messages = conn.execute("SELECT * FROM messages ORDER BY seq").fetchall()
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        assert "fixtures" in messages[0]["content"].lower()

    def test_incremental_skips_unchanged_fingerprint(self, migrated_db, repoprompt_dir):
        """Second export with unchanged file should skip (same fingerprint)."""
        conn, _ = migrated_db
        exporter = RepoPromptExporter(app_support_dir=repoprompt_dir)

        stats_first = exporter.export_all(conn, incremental=True)
        assert stats_first.added == 1

        stats_second = exporter.export_all(conn, incremental=True)
        # Fingerprint match -> _process_chat_file returns (None, []) -> not counted
        # This means neither added nor skipped via ExportStats, it just returns None
        assert stats_second.added == 0

    def test_unavailable_returns_zero_stats(self, migrated_db, tmp_path):
        conn, _ = migrated_db
        exporter = RepoPromptExporter(app_support_dir=tmp_path / "missing")
        stats = exporter.export_all(conn, incremental=False)
        assert stats.added == 0
        assert stats.skipped == 0

    def test_session_metadata_contains_fingerprint(self, migrated_db, repoprompt_dir):
        conn, _ = migrated_db
        exporter = RepoPromptExporter(app_support_dir=repoprompt_dir)
        exporter.export_all(conn, incremental=False)

        row = conn.execute("SELECT metadata FROM sessions").fetchone()
        meta = json.loads(row["metadata"])
        assert "fingerprint" in meta
        assert meta["name"] == "Test Chat"
        assert meta["shortID"] == "CS001"
        assert meta["preferredAIModel"] == "claude-sonnet-4-20250514"

    def test_message_metadata_contains_cost(self, migrated_db, repoprompt_dir):
        conn, _ = migrated_db
        exporter = RepoPromptExporter(app_support_dir=repoprompt_dir)
        exporter.export_all(conn, incremental=False)

        assistant_msg = conn.execute(
            "SELECT metadata FROM messages WHERE role = 'assistant'"
        ).fetchone()
        meta = json.loads(assistant_msg["metadata"])
        assert meta["cost"] == 0.002
        assert meta["completionTokens"] == 30
