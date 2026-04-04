"""Tests for studyctl CLI commands using Click's CliRunner.

Strategy: Most commands depend on history functions that need a live sessions.db.
We monkeypatch `_connect` to return None, and each history function returns its
empty/default sentinel.  Commands are designed to handle this gracefully with
user-friendly messages.

Note on `review`: With no DB, `spaced_repetition_due` still returns entries for
configured topics (marked "New topic") because `last_studied()` returns None when
no connection exists. The "Nothing due" path only triggers when every topic has been
recently studied. We test both paths explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path
from click.testing import CliRunner

from studyctl.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def _no_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure no real database is ever touched during CLI tests."""
    import studyctl.history._connection as _conn

    monkeypatch.setattr(_conn, "_connect", lambda: None)


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------


class TestVersion:
    def test_version_exits_zero(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0

    def test_version_contains_studyctl(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--version"])
        assert "version" in result.output.lower()


# ---------------------------------------------------------------------------
# topics
# ---------------------------------------------------------------------------


class TestTopics:
    def test_topics_with_monkeypatched_list(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        @dataclass
        class FakeTopic:
            name: str
            display_name: str
            notebook_id: str | None
            obsidian_paths: list[Path] = field(default_factory=list)
            tags: list[str] = field(default_factory=list)

        fake_topics = [
            FakeTopic(name="python", display_name="Python Study", notebook_id=None),
            FakeTopic(name="sql", display_name="SQL Mastery", notebook_id="abc123"),
        ]
        import studyctl.cli._sync as sync_mod

        monkeypatch.setattr(sync_mod, "get_topics", lambda: fake_topics)

        result = runner.invoke(cli, ["topics"])
        assert result.exit_code == 0
        assert "python" in result.output
        assert "Python Study" in result.output
        assert "sql" in result.output
        assert "SQL Mastery" in result.output

    def test_topics_empty_list(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        import studyctl.cli._sync as sync_mod

        monkeypatch.setattr(sync_mod, "get_topics", lambda: [])

        result = runner.invoke(cli, ["topics"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# review (spaced repetition)
# ---------------------------------------------------------------------------


class TestReview:
    def test_review_no_db_shows_new_topics(self, runner: CliRunner) -> None:
        """With no DB, configured topics appear as 'New topic' needing review."""
        result = runner.invoke(cli, ["review"])
        assert result.exit_code == 0
        assert "Spaced Repetition" in result.output
        assert "New topic" in result.output

    def test_review_nothing_due(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        """When spaced_repetition_due returns empty, show the all-clear message."""
        import studyctl.cli._review as review_mod

        monkeypatch.setattr(review_mod, "spaced_repetition_due", lambda _kw: [])

        result = runner.invoke(cli, ["review"])
        assert result.exit_code == 0
        assert "Nothing due for review" in result.output


# ---------------------------------------------------------------------------
# struggles (no DB)
# ---------------------------------------------------------------------------


class TestStruggles:
    def test_struggles_no_db_shows_empty(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["struggles"])
        assert result.exit_code == 0
        assert "No recurring struggle topics" in result.output

    def test_struggles_accepts_days_option(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["struggles", "--days", "7"])
        assert result.exit_code == 0
        assert "No recurring struggle topics" in result.output


# ---------------------------------------------------------------------------
# config init (interactive wizard)
# ---------------------------------------------------------------------------


class TestConfigInit:
    def test_config_init_all_yes(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Config init with all options enabled writes correct YAML."""
        config_file = tmp_path / "config.yaml"
        monkeypatch.setattr("studyctl.shared.CONFIG_PATH", config_file)

        # Simulate: yes bridging, "cooking" domain, yes nlm, yes obsidian, path, no agent install
        user_input = "y\ncooking\ny\ny\n~/MyVault\nn\n"
        result = runner.invoke(cli, ["config", "init"], input=user_input)
        assert result.exit_code == 0
        assert "Configuration saved" in result.output

        import yaml

        config = yaml.safe_load(config_file.read_text())
        assert config["knowledge_domains"]["primary"] == "cooking"
        assert config["notebooklm"]["enabled"] is True
        assert config["obsidian_base"] == "~/MyVault"

    def test_config_init_all_no(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Config init with all options declined."""
        config_file = tmp_path / "config.yaml"
        monkeypatch.setattr("studyctl.shared.CONFIG_PATH", config_file)

        user_input = "n\nn\nn\nn\n"
        result = runner.invoke(cli, ["config", "init"], input=user_input)
        assert result.exit_code == 0
        assert "Configuration saved" in result.output

        import yaml

        config = yaml.safe_load(config_file.read_text())
        assert "knowledge_domains" not in config
        assert config["notebooklm"]["enabled"] is False

    def test_config_init_defaults(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Config init accepting all defaults (just pressing Enter)."""
        config_file = tmp_path / "config.yaml"
        monkeypatch.setattr("studyctl.shared.CONFIG_PATH", config_file)

        # All empty = accept defaults: yes bridging, "networking", no nlm, yes obsidian
        user_input = "\n\n\n\n\n\n"
        result = runner.invoke(cli, ["config", "init"], input=user_input)
        assert result.exit_code == 0
        assert "Configuration saved" in result.output

    def test_config_init_skip_agents(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Config init with --no-install-agents skips agent installation prompt."""
        config_file = tmp_path / "config.yaml"
        monkeypatch.setattr("studyctl.shared.CONFIG_PATH", config_file)

        user_input = "n\nn\nn\n"
        result = runner.invoke(cli, ["config", "init", "--no-install-agents"], input=user_input)
        assert result.exit_code == 0
        assert "Agent Installation" not in result.output

    def test_config_init_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["config", "init", "--help"])
        assert result.exit_code == 0
        assert "Interactive setup" in result.output


# ---------------------------------------------------------------------------
# config show
# ---------------------------------------------------------------------------


class TestConfigShow:
    def test_config_show_no_config(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Config show with no config file shows error message."""
        monkeypatch.setattr("studyctl.settings._CONFIG_PATH", tmp_path / "nonexistent.yaml")
        result = runner.invoke(cli, ["config", "show"])
        assert result.exit_code == 0
        assert "No config file found" in result.output

    def test_config_show_with_config(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Config show with valid config displays settings."""
        import yaml

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "obsidian_base": str(tmp_path),
                    "notebooklm": {"enabled": True},
                    "knowledge_domains": {"primary": "cooking"},
                    "topics": [
                        {
                            "name": "Python",
                            "slug": "python",
                            "obsidian_path": str(tmp_path / "python"),
                            "tags": ["python", "coding"],
                        }
                    ],
                }
            )
        )
        monkeypatch.setattr("studyctl.settings._CONFIG_PATH", config_file)
        # config show imports settings._CONFIG_PATH which is already monkeypatched above

        result = runner.invoke(cli, ["config", "show"])
        assert result.exit_code == 0
        assert "Core Settings" in result.output
        assert "cooking" in result.output

    def test_config_show_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["config", "show", "--help"])
        assert result.exit_code == 0
        assert "Display current configuration" in result.output


# ---------------------------------------------------------------------------
# help text
# ---------------------------------------------------------------------------


class TestHelp:
    def test_root_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "AuDHD study pipeline" in result.output
