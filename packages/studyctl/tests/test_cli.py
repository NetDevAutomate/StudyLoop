"""Tests for studyctl CLI commands using Click's CliRunner.

Strategy: Most commands depend on history functions that need a live sessions.db.
We monkeypatch `studyctl.history._find_db` to return None, which makes `_connect()`
return None, and each history function returns its empty/default sentinel.
Commands are designed to handle this gracefully with user-friendly messages.

Note on `review`: With no DB, `spaced_repetition_due` still returns entries for
configured topics (marked "New topic") because `last_studied()` returns None when
no connection exists. The "Nothing due" path only triggers when every topic has been
recently studied. We test both paths explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path  # noqa: TC003 — used at runtime in Topic fixture

import pytest
from click.testing import CliRunner

from studyctl.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def _no_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure no real database is ever touched during CLI tests."""
    import studyctl.history as hist

    monkeypatch.setattr(hist, "_find_db", lambda: None)


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------


class TestVersion:
    def test_version_exits_zero(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0

    def test_version_contains_studyctl(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--version"])
        assert "studyctl" in result.output.lower() or "1." in result.output


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
        import studyctl.cli as cli_mod

        monkeypatch.setattr(cli_mod, "get_topics", lambda: fake_topics)

        result = runner.invoke(cli, ["topics"])
        assert result.exit_code == 0
        assert "python" in result.output
        assert "Python Study" in result.output
        assert "sql" in result.output
        assert "SQL Mastery" in result.output

    def test_topics_empty_list(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        import studyctl.cli as cli_mod

        monkeypatch.setattr(cli_mod, "get_topics", lambda: [])

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
        import studyctl.cli as cli_mod

        monkeypatch.setattr(cli_mod, "spaced_repetition_due", lambda _kw: [])

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
# wins (no DB)
# ---------------------------------------------------------------------------


class TestWins:
    def test_wins_no_db_shows_empty(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["wins"])
        assert result.exit_code == 0
        assert "No progress data" in result.output


# ---------------------------------------------------------------------------
# resume (no DB)
# ---------------------------------------------------------------------------


class TestResume:
    def test_resume_no_db_shows_no_sessions(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["resume"])
        assert result.exit_code == 0
        assert "No sessions found" in result.output


# ---------------------------------------------------------------------------
# streaks (no DB)
# ---------------------------------------------------------------------------


class TestStreaks:
    def test_streaks_no_db_shows_no_sessions(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["streaks"])
        assert result.exit_code == 0
        assert "No study sessions found" in result.output


# ---------------------------------------------------------------------------
# progress-map (no DB)
# ---------------------------------------------------------------------------


class TestProgressMap:
    def test_progress_map_no_db_shows_empty(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["progress-map"])
        assert result.exit_code == 0
        assert "No progress data" in result.output


# ---------------------------------------------------------------------------
# schedule list (mocked -- no subprocess)
# ---------------------------------------------------------------------------


class TestScheduleList:
    def test_schedule_list_no_jobs(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import studyctl.cli as cli_mod

        monkeypatch.setattr(cli_mod, "list_jobs", lambda: [])

        result = runner.invoke(cli, ["schedule", "list"])
        assert result.exit_code == 0
        assert "No studyctl jobs scheduled" in result.output

    def test_schedule_list_with_jobs(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import studyctl.cli as cli_mod

        monkeypatch.setattr(
            cli_mod,
            "list_jobs",
            lambda: [
                {"name": "session-export", "status": "0"},
                {"name": "studyctl-sync", "cron": "0 7 * * *"},
            ],
        )

        result = runner.invoke(cli, ["schedule", "list"])
        assert result.exit_code == 0
        assert "session-export" in result.output
        assert "studyctl-sync" in result.output


# ---------------------------------------------------------------------------
# help text
# ---------------------------------------------------------------------------


class TestHelp:
    def test_root_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "AuDHD study pipeline" in result.output

    def test_schedule_subgroup_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["schedule", "--help"])
        assert result.exit_code == 0
        assert "Manage scheduled jobs" in result.output

    def test_state_subgroup_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["state", "--help"])
        assert result.exit_code == 0
        assert "Cross-machine state sync" in result.output
