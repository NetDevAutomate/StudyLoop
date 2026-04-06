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


# ---------------------------------------------------------------------------
# bridge subcommands (lives in _review.py)
# ---------------------------------------------------------------------------


class TestBridgeAdd:
    def test_bridge_add_success(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        """bridge add records a bridge and confirms success."""
        import studyctl.cli._review as review_mod

        monkeypatch.setattr(review_mod, "record_bridge", lambda *a, **kw: True)

        result = runner.invoke(
            cli,
            [
                "bridge",
                "add",
                "ECMP",
                "--source-domain",
                "networking",
                "Spark partitions",
                "--target-domain",
                "python",
                "--mapping",
                "Both distribute load across nodes",
            ],
        )
        assert result.exit_code == 0
        assert "Bridge added" in result.output
        assert "ECMP" in result.output
        assert "Spark partitions" in result.output

    def test_bridge_add_failure(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        """bridge add shows error when record_bridge returns False."""
        import studyctl.cli._review as review_mod

        monkeypatch.setattr(review_mod, "record_bridge", lambda *a, **kw: False)

        result = runner.invoke(
            cli,
            [
                "bridge",
                "add",
                "BGP",
                "--source-domain",
                "networking",
                "asyncio",
                "--target-domain",
                "python",
                "--mapping",
                "Both handle concurrent events",
            ],
        )
        assert result.exit_code == 0
        assert "Failed to add bridge" in result.output

    def test_bridge_add_with_quality_flag(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """bridge add accepts --quality option."""
        import studyctl.cli._review as review_mod

        calls = []
        monkeypatch.setattr(
            review_mod,
            "record_bridge",
            lambda *a, **kw: calls.append((a, kw)) or True,
        )

        result = runner.invoke(
            cli,
            [
                "bridge",
                "add",
                "OSPF",
                "--source-domain",
                "networking",
                "graph algorithms",
                "--target-domain",
                "python",
                "--mapping",
                "Both use Dijkstra",
                "--quality",
                "strong",
            ],
        )
        assert result.exit_code == 0
        assert "Bridge added" in result.output

    def test_bridge_add_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["bridge", "add", "--help"])
        assert result.exit_code == 0
        assert "knowledge bridge" in result.output.lower()


class TestBridgeList:
    def test_bridge_list_empty(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        """bridge list with no bridges shows empty message."""
        import studyctl.cli._review as review_mod

        monkeypatch.setattr(review_mod, "get_bridges", lambda **kw: [])

        result = runner.invoke(cli, ["bridge", "list"])
        assert result.exit_code == 0
        assert "No bridges found" in result.output

    def test_bridge_list_with_bridges(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """bridge list renders a table when bridges exist."""
        import studyctl.cli._review as review_mod

        fake_bridges = [
            {
                "source_concept": "ECMP",
                "source_domain": "networking",
                "target_concept": "Spark partitions",
                "target_domain": "python",
                "mapping": "Both distribute load",
                "quality": "strong",
            }
        ]
        monkeypatch.setattr(review_mod, "get_bridges", lambda **kw: fake_bridges)

        result = runner.invoke(cli, ["bridge", "list"])
        assert result.exit_code == 0
        assert "ECMP" in result.output
        assert "networking" in result.output

    def test_bridge_list_filter_by_source_domain(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """bridge list passes source_domain filter to get_bridges."""
        import studyctl.cli._review as review_mod

        received_kwargs: dict = {}

        def fake_get_bridges(**kw):
            received_kwargs.update(kw)
            return []

        monkeypatch.setattr(review_mod, "get_bridges", fake_get_bridges)

        result = runner.invoke(cli, ["bridge", "list", "--source-domain", "networking"])
        assert result.exit_code == 0
        assert received_kwargs.get("source_domain") == "networking"

    def test_bridge_list_filter_by_target_domain(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """bridge list passes target_domain filter to get_bridges."""
        import studyctl.cli._review as review_mod

        received_kwargs: dict = {}

        def fake_get_bridges(**kw):
            received_kwargs.update(kw)
            return []

        monkeypatch.setattr(review_mod, "get_bridges", fake_get_bridges)

        result = runner.invoke(cli, ["bridge", "list", "--target-domain", "python"])
        assert result.exit_code == 0
        assert received_kwargs.get("target_domain") == "python"

    def test_bridge_list_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["bridge", "list", "--help"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# wins / progress / streaks / resume (review commands)
# ---------------------------------------------------------------------------


class TestWins:
    def test_wins_no_progress_data(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """wins shows empty state message when no progress data exists."""

        monkeypatch.setattr(
            "studyctl.history.get_progress_summary",
            lambda: {},
        )
        result = runner.invoke(cli, ["wins"])
        assert result.exit_code == 0
        assert "No progress data" in result.output

    def test_wins_with_data_no_recent_wins(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """wins shows progress overview but empty recent wins."""
        monkeypatch.setattr(
            "studyctl.history.get_progress_summary",
            lambda: {
                "total": 10,
                "mastered": 2,
                "confident": 3,
                "learning": 4,
                "struggling": 1,
            },
        )
        monkeypatch.setattr("studyctl.history.get_wins", lambda days: [])

        result = runner.invoke(cli, ["wins"])
        assert result.exit_code == 0
        assert "Progress Overview" in result.output
        assert "No new wins" in result.output

    def test_wins_with_recent_wins(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """wins displays recent mastered concepts."""
        monkeypatch.setattr(
            "studyctl.history.get_progress_summary",
            lambda: {
                "total": 5,
                "mastered": 1,
                "confident": 1,
                "learning": 2,
                "struggling": 1,
            },
        )
        monkeypatch.setattr(
            "studyctl.history.get_wins",
            lambda days: [
                {
                    "concept": "Decorators",
                    "topic": "python",
                    "confidence": "mastered",
                    "session_count": 3,
                }
            ],
        )
        result = runner.invoke(cli, ["wins"])
        assert result.exit_code == 0
        assert "Decorators" in result.output


class TestProgress:
    def test_progress_records_successfully(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """progress command records confidence and prints confirmation."""
        monkeypatch.setattr("studyctl.history.record_progress", lambda *a, **kw: True)

        result = runner.invoke(
            cli,
            [
                "progress",
                "list comprehensions",
                "--topic",
                "python",
                "--confidence",
                "confident",
            ],
        )
        assert result.exit_code == 0
        assert "Recorded" in result.output
        assert "list comprehensions" in result.output

    def test_progress_failure(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        """progress shows error when record_progress returns False."""
        monkeypatch.setattr("studyctl.history.record_progress", lambda *a, **kw: False)

        result = runner.invoke(
            cli,
            [
                "progress",
                "generators",
                "--topic",
                "python",
                "--confidence",
                "learning",
            ],
        )
        assert result.exit_code == 0
        assert "Failed to record" in result.output

    def test_progress_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["progress", "--help"])
        assert result.exit_code == 0
        assert "Record progress" in result.output


class TestStreaks:
    def test_streaks_no_sessions(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        """streaks shows empty state when no sessions exist."""
        monkeypatch.setattr(
            "studyctl.history.get_study_streaks",
            lambda: {"last_session_date": None, "current_streak": 0},
        )
        result = runner.invoke(cli, ["streaks"])
        assert result.exit_code == 0
        assert "No study sessions found" in result.output

    def test_streaks_with_data(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        """streaks shows streak stats when sessions exist."""
        monkeypatch.setattr(
            "studyctl.history.get_study_streaks",
            lambda: {
                "last_session_date": "2026-04-05",
                "current_streak": 3,
                "longest_streak": 7,
                "total_days": 15,
                "sessions_this_week": 4,
            },
        )
        monkeypatch.setattr("studyctl.history.get_energy_session_data", lambda days: [])
        result = runner.invoke(cli, ["streaks"])
        assert result.exit_code == 0
        assert "3 days" in result.output
        assert "Consistency" in result.output


class TestResume:
    def test_resume_no_sessions(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        """resume shows empty state when no sessions exist."""
        monkeypatch.setattr("studyctl.history.get_last_session_summary", lambda: None)
        result = runner.invoke(cli, ["resume"])
        assert result.exit_code == 0
        assert "No sessions found" in result.output

    def test_resume_with_session(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        """resume displays last session summary."""
        monkeypatch.setattr(
            "studyctl.history.get_last_session_summary",
            lambda: {
                "source": "claude_code",
                "started": "2026-04-05T10:00:00",
                "updated": "2026-04-05T11:30:00",
                "topics_covered": ["python", "networking"],
                "last_message_preview": "We covered list comprehensions and OSPF.",
                "concepts_in_progress": [],
            },
        )
        monkeypatch.setattr(
            "studyctl.history.get_study_streaks",
            lambda: {"current_streak": 0, "longest_streak": 5},
        )
        result = runner.invoke(cli, ["resume"])
        assert result.exit_code == 0
        assert "Where you left off" in result.output
        assert "Claude Code" in result.output
