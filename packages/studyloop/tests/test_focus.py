"""Tests for studyloop focus — the max-3-topic attention filter."""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import UTC, datetime, timedelta

import pytest
import yaml
from click.testing import CliRunner

import studyloop.focus as focus_module
from studyloop.cli import cli
from studyloop.focus import (
    FocusState,
    clear_focus,
    get_focus,
    matches_focus,
    set_focus,
    suggest_focus,
)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Point STUDYLOOP_CONFIG at a temp file with a minimal config."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("obsidian_base: ~/Obsidian\n")
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))
    return config_path


class TestFocusState:
    def test_unset_by_default(self, isolated_config):
        state = get_focus()
        assert not state.is_set
        assert state.topics == []

    def test_set_and_get_roundtrip(self, isolated_config):
        set_focus(["python", "sql"])
        state = get_focus()
        assert state.topics == ["python", "sql"]
        assert state.is_set
        assert not state.is_stale

    def test_set_preserves_other_config(self, isolated_config):
        set_focus(["python"])
        raw = yaml.safe_load(isolated_config.read_text())
        assert raw["obsidian_base"] == "~/Obsidian"
        assert raw["focus"]["topics"] == ["python"]

    def test_max_three_topics_enforced(self, isolated_config):
        with pytest.raises(ValueError, match="Maximum 3"):
            set_focus(["a", "b", "c", "d"])

    def test_empty_rejected(self, isolated_config):
        with pytest.raises(ValueError):
            set_focus(["", "  "])

    def test_duplicates_collapsed(self, isolated_config):
        set_focus(["Python", "python", "sql"])
        assert get_focus().topics == ["Python", "sql"]

    def test_clear(self, isolated_config):
        set_focus(["python"])
        clear_focus()
        assert not get_focus().is_set

    def test_stale_detection(self):
        assert FocusState(topics=["x"], updated="2020-01-01").is_stale
        assert not FocusState(topics=[], updated=None).is_stale
        assert FocusState(topics=["x"], updated=None).is_stale


class TestMatchesFocus:
    def test_exact_and_substring(self):
        focus = ["python", "sql window functions"]
        assert matches_focus("Python", focus)
        assert matches_focus("python decorators", focus)  # focus topic within candidate
        assert matches_focus("sql", focus)  # 'sql' substring of focus topic
        assert matches_focus("SQL Window Functions", focus)
        assert not matches_focus("terraform", focus)
        assert not matches_focus("", focus)


class TestFocusCli:
    def test_show_empty(self, runner, isolated_config):
        result = runner.invoke(cli, ["focus"])
        assert result.exit_code == 0
        assert "No focus topics set" in result.output

    def test_set_and_show(self, runner, isolated_config):
        result = runner.invoke(cli, ["focus", "set", "python", "sql"])
        assert result.exit_code == 0
        assert "Focus updated" in result.output

        result = runner.invoke(cli, ["focus"])
        assert "python" in result.output
        assert "sql" in result.output

    def test_set_rejects_four(self, runner, isolated_config):
        result = runner.invoke(cli, ["focus", "set", "a", "b", "c", "d"])
        assert result.exit_code == 1
        assert "Maximum 3" in result.output

    def test_clear(self, runner, isolated_config):
        runner.invoke(cli, ["focus", "set", "python"])
        result = runner.invoke(cli, ["focus", "clear"])
        assert result.exit_code == 0
        result = runner.invoke(cli, ["focus"])
        assert "No focus topics set" in result.output

    def test_suggest_runs_without_data(self, runner, isolated_config):
        result = runner.invoke(cli, ["focus", "suggest"])
        assert result.exit_code == 0


class TestPruneCli:
    def test_prune_refuses_without_full_db(self, runner, isolated_config, tmp_path):
        """Without database.full_db_path configured, prune must refuse."""
        pytest.importorskip("agent_session_tools")
        # Config has no database section -> tiering disabled; hot DB must
        # exist so the failure is the *invariant*, not a missing file.
        db = tmp_path / "sessions.db"
        sqlite3.connect(db).close()
        isolated_config.write_text(f"obsidian_base: ~/Obsidian\ndatabase:\n  path: {db}\n")
        result = runner.invoke(cli, ["prune", "--apply"])
        assert result.exit_code == 1
        assert "full_db_path" in result.output


# ---------------------------------------------------------------------------
# suggest_focus — R-20: the cutoff must be real UTC, not naive local time,
# compared against study_sessions.started_at (written via SQLite's own
# datetime('now'), UTC, "YYYY-MM-DD HH:MM:SS").
# ---------------------------------------------------------------------------


@pytest.fixture
def _fake_sessions_db(tmp_path, monkeypatch):
    """A minimal study_sessions table, wired in place of the real DB lookup."""
    db_path = tmp_path / "fake-sessions.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE study_sessions (session_id TEXT, topic TEXT, started_at TEXT)")
    # study_progress is queried unconditionally too; an empty table is fine.
    conn.execute("CREATE TABLE study_progress (topic TEXT, confidence TEXT)")
    conn.commit()

    monkeypatch.setattr(focus_module, "_connect_sessions_db", lambda: conn)
    yield conn
    conn.close()


@pytest.fixture
def _restore_tz():
    """Change the process TZ for the duration of a test, then restore it.

    `datetime.now()` (no tz argument) reads the OS's local-time setting,
    which on POSIX only takes effect after `time.tzset()`. This is exactly
    the mechanism R-20's bug depends on: a naive cutoff computed under a
    non-UTC TZ silently shifts by the zone's offset.
    """
    original = os.environ.get("TZ")

    def _set(tz: str) -> None:
        os.environ["TZ"] = tz
        time.tzset()

    yield _set

    if original is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = original
    time.tzset()


class TestSuggestFocusUtcCutoff:
    """R-20 / D2: the cutoff must be derived from real UTC, not local time."""

    @pytest.mark.parametrize("tz", ["Pacific/Auckland", "America/Los_Angeles"])
    def test_minute_inside_cutoff_kept_minute_outside_dropped(
        self, tz, _fake_sessions_db, _restore_tz
    ):
        conn = _fake_sessions_db
        days = 1
        cutoff_instant = datetime.now(UTC) - timedelta(days=days)
        inside = (cutoff_instant + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        outside = (cutoff_instant - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")

        conn.execute(
            "INSERT INTO study_sessions (session_id, topic, started_at) "
            "VALUES ('s-in', 'kept-topic', ?)",
            (inside,),
        )
        conn.execute(
            "INSERT INTO study_sessions (session_id, topic, started_at) "
            "VALUES ('s-out', 'dropped-topic', ?)",
            (outside,),
        )
        conn.commit()

        _restore_tz(tz)
        topics = dict(suggest_focus(days=days, limit=10))

        assert "kept-topic" in topics, (
            f"a session 1 minute inside the UTC cutoff must survive under TZ={tz}"
        )
        assert "dropped-topic" not in topics, (
            f"a session 1 minute outside the UTC cutoff must be dropped under TZ={tz}"
        )
