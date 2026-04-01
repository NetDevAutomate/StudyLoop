"""Tests for the Aider session exporter."""

from pathlib import Path

import pytest

from agent_session_tools.exporters.aider import AiderExporter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def aider_tree(tmp_path: Path) -> Path:
    """Create a fake project directory containing an Aider history file.

    Layout::

        tmp_path/
          project-a/
            .aider.chat.history.md   <- valid history
    """
    project = tmp_path / "project-a"
    project.mkdir()

    content = (
        "#### user message\n"
        "Tell me about Python decorators\n"
        "\n"
        "#### assistant response\n"
        "Decorators are higher-order functions that wrap other functions.\n"
    )
    (project / ".aider.chat.history.md").write_text(content)
    return tmp_path


@pytest.fixture()
def aider_tree_multi(tmp_path: Path) -> Path:
    """Create multiple projects under tmp_path, plus an excluded directory."""
    proj_a = tmp_path / "project-a"
    proj_a.mkdir()
    (proj_a / ".aider.chat.history.md").write_text(
        "#### user message\nHello\n#### assistant response\nHi there\n"
    )

    proj_b = tmp_path / "project-b"
    proj_b.mkdir()
    (proj_b / ".aider.chat.history.md").write_text(
        "#### user message\nGoodbye\n#### assistant response\nBye!\n"
    )

    excluded = tmp_path / "node_modules" / "dep"
    excluded.mkdir(parents=True)
    (excluded / ".aider.chat.history.md").write_text(
        "#### user message\nShould be excluded\n"
    )

    return tmp_path


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


class TestIsAvailable:
    def test_returns_true_when_search_path_exists(self, tmp_path: Path):
        exporter = AiderExporter(search_paths=[tmp_path])
        assert exporter.is_available() is True

    def test_returns_false_when_no_search_paths_exist(self, tmp_path: Path):
        missing = tmp_path / "does_not_exist"
        exporter = AiderExporter(search_paths=[missing])
        assert exporter.is_available() is False

    def test_returns_true_if_any_path_exists(self, tmp_path: Path):
        missing = tmp_path / "nope"
        exporter = AiderExporter(search_paths=[missing, tmp_path])
        assert exporter.is_available() is True


# ---------------------------------------------------------------------------
# _parse_aider_markdown
# ---------------------------------------------------------------------------


class TestParseAiderMarkdown:
    def setup_method(self):
        self.exporter = AiderExporter(search_paths=[])

    def test_empty_content_returns_no_messages(self):
        assert self.exporter._parse_aider_markdown("") == []

    def test_content_without_headers_returns_no_messages(self):
        assert self.exporter._parse_aider_markdown("just some text\nno headers") == []

    def test_single_user_message(self):
        content = "#### user message\nWhat is a closure?\n"
        msgs = self.exporter._parse_aider_markdown(content)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert "closure" in msgs[0]["content"]

    def test_user_and_assistant_pair(self):
        content = (
            "#### user message\n"
            "Explain generators\n"
            "\n"
            "#### assistant response\n"
            "Generators yield values lazily.\n"
        )
        msgs = self.exporter._parse_aider_markdown(content)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"

    def test_role_detection_user_keyword(self):
        """Any header containing 'user' maps to role='user'."""
        content = "#### The user says\nHello\n"
        msgs = self.exporter._parse_aider_markdown(content)
        assert msgs[0]["role"] == "user"

    def test_role_detection_non_user_defaults_to_assistant(self):
        """Headers without 'user' map to role='assistant'."""
        content = "#### aider response\nSome code\n"
        msgs = self.exporter._parse_aider_markdown(content)
        assert msgs[0]["role"] == "assistant"

    def test_multiline_content_preserved(self):
        content = "#### user message\nLine one\nLine two\nLine three\n"
        msgs = self.exporter._parse_aider_markdown(content)
        assert "Line one\nLine two\nLine three" == msgs[0]["content"]

    def test_messages_have_required_keys(self):
        content = "#### user message\nTest\n"
        msgs = self.exporter._parse_aider_markdown(content)
        msg = msgs[0]
        assert set(msg.keys()) == {
            "id",
            "role",
            "content",
            "model",
            "timestamp",
            "metadata",
        }
        assert msg["model"] is None
        assert msg["timestamp"] is None
        assert msg["metadata"] == "{}"

    def test_multiple_exchanges(self):
        content = (
            "#### user message\nQ1\n"
            "#### assistant response\nA1\n"
            "#### user message\nQ2\n"
            "#### assistant response\nA2\n"
        )
        msgs = self.exporter._parse_aider_markdown(content)
        assert len(msgs) == 4
        assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]


# ---------------------------------------------------------------------------
# export_all (integration with temp DB)
# ---------------------------------------------------------------------------


class TestExportAll:
    def test_exports_sessions_and_messages(
        self, migrated_db, aider_tree: Path, monkeypatch
    ):
        """History file is exported as one session with two messages."""
        conn, _ = migrated_db
        # Monkeypatch load_config to avoid real config dependency
        monkeypatch.setattr(
            "agent_session_tools.exporters.aider.load_config",
            lambda: {"excluded_dirs": []},
        )

        exporter = AiderExporter(search_paths=[aider_tree])
        stats = exporter.export_all(conn, incremental=False)

        assert stats.added == 1
        assert stats.errors == 0

        sessions = conn.execute("SELECT * FROM sessions").fetchall()
        assert len(sessions) == 1
        assert sessions[0]["source"] == "aider"

        messages = conn.execute("SELECT * FROM messages ORDER BY seq").fetchall()
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

    def test_incremental_skips_unchanged(
        self, migrated_db, aider_tree: Path, monkeypatch
    ):
        """Running export twice in incremental mode skips the second time."""
        conn, _ = migrated_db
        monkeypatch.setattr(
            "agent_session_tools.exporters.aider.load_config",
            lambda: {"excluded_dirs": []},
        )

        exporter = AiderExporter(search_paths=[aider_tree])
        stats_first = exporter.export_all(conn, incremental=True)
        assert stats_first.added == 1

        stats_second = exporter.export_all(conn, incremental=True)
        assert stats_second.skipped == 1
        assert stats_second.added == 0

    def test_empty_directory_produces_zero_stats(
        self, migrated_db, tmp_path: Path, monkeypatch
    ):
        conn, _ = migrated_db
        monkeypatch.setattr(
            "agent_session_tools.exporters.aider.load_config",
            lambda: {"excluded_dirs": []},
        )

        exporter = AiderExporter(search_paths=[tmp_path])
        stats = exporter.export_all(conn, incremental=False)

        assert stats.added == 0
        assert stats.errors == 0

    def test_walk_excludes_directories(
        self, migrated_db, aider_tree_multi: Path, monkeypatch
    ):
        """node_modules directory should be excluded from the walk."""
        conn, _ = migrated_db
        monkeypatch.setattr(
            "agent_session_tools.exporters.aider.load_config",
            lambda: {"excluded_dirs": ["node_modules"]},
        )

        exporter = AiderExporter(search_paths=[aider_tree_multi])
        stats = exporter.export_all(conn, incremental=False)

        # Only project-a and project-b should be exported, not node_modules
        assert stats.added == 2
        sources = conn.execute("SELECT project_path FROM sessions").fetchall()
        project_paths = [row["project_path"] for row in sources]
        assert not any("node_modules" in p for p in project_paths)
