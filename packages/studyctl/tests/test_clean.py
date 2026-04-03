"""Tests for studyctl clean — functional core (plan_clean) + CLI shell.

Tests the pure logic directly via plan_clean(). No mocking required.
The imperative shell (_clean.py) is tested via Click's CliRunner
with mocks only at the I/O boundary.
"""

from __future__ import annotations

from pathlib import Path

from studyctl.cli._clean_logic import CleanResult, DirInfo, plan_clean

# Inline fixtures only (no conftest.py — pluggy conflict)


# ─── Functional Core Tests (no mocks) ───────────────────────────


class TestPlanCleanNothingToClean:
    def test_no_artifacts_returns_empty_result(self):
        result = plan_clean(
            tmux_running=True,
            zombie_sessions=[],
            session_dirs=[],
            live_tmux_names=set(),
            state={},
            state_file_exists=False,
        )
        assert not result.has_work
        assert result.sessions_to_kill == []
        assert result.dirs_to_remove == []
        assert result.state_to_clean is False
        assert result.warnings == []


class TestPlanCleanStaleSessions:
    def test_zombie_sessions_marked_for_kill(self):
        result = plan_clean(
            tmux_running=True,
            zombie_sessions=["study-old-abc123", "study-stale-def456"],
            session_dirs=[],
            live_tmux_names={"study-old-abc123", "study-stale-def456"},
            state={},
            state_file_exists=False,
        )
        assert result.sessions_to_kill == ["study-old-abc123", "study-stale-def456"]
        assert result.has_work

    def test_active_sessions_not_marked(self):
        """Sessions that are NOT zombies don't appear in zombie_sessions input."""
        result = plan_clean(
            tmux_running=True,
            zombie_sessions=[],  # shell already filtered — only zombies passed in
            session_dirs=[],
            live_tmux_names={"study-active-xyz"},
            state={},
            state_file_exists=False,
        )
        assert result.sessions_to_kill == []


class TestPlanCleanSessionDirs:
    def test_dirs_with_no_live_session_marked_for_removal(self, tmp_path):
        stale_dir = tmp_path / "study-old-topic-abc123"
        stale_dir.mkdir()

        result = plan_clean(
            tmux_running=True,
            zombie_sessions=[],
            session_dirs=[DirInfo(name="study-old-topic-abc123", path=stale_dir, is_symlink=False)],
            live_tmux_names=set(),  # no live sessions
            state={},
            state_file_exists=False,
        )
        assert result.dirs_to_remove == [stale_dir]

    def test_dirs_with_live_session_kept(self, tmp_path):
        active_dir = tmp_path / "study-active-def456"
        active_dir.mkdir()

        result = plan_clean(
            tmux_running=True,
            zombie_sessions=[],
            session_dirs=[DirInfo(name="study-active-def456", path=active_dir, is_symlink=False)],
            live_tmux_names={"study-active-def456"},
            state={},
            state_file_exists=False,
        )
        assert result.dirs_to_remove == []

    def test_symlinks_skipped_with_warning(self, tmp_path):
        real_dir = tmp_path / "real-project"
        real_dir.mkdir()
        symlink = tmp_path / "study-symlink-abc123"
        symlink.symlink_to(real_dir)

        result = plan_clean(
            tmux_running=True,
            zombie_sessions=[],
            session_dirs=[DirInfo(name="study-symlink-abc123", path=symlink, is_symlink=True)],
            live_tmux_names=set(),
            state={},
            state_file_exists=False,
        )
        assert result.dirs_to_remove == []
        assert any("symlink" in w.lower() for w in result.warnings)


class TestPlanCleanStateFile:
    def test_ended_state_with_no_live_session_marked(self):
        result = plan_clean(
            tmux_running=True,
            zombie_sessions=[],
            session_dirs=[],
            live_tmux_names=set(),
            state={"mode": "ended", "tmux_session": "study-old-abc123"},
            state_file_exists=True,
        )
        assert result.state_to_clean is True

    def test_active_state_not_marked(self):
        result = plan_clean(
            tmux_running=True,
            zombie_sessions=[],
            session_dirs=[],
            live_tmux_names={"study-live-xyz"},
            state={"mode": "study", "tmux_session": "study-live-xyz"},
            state_file_exists=True,
        )
        assert result.state_to_clean is False

    def test_ended_state_with_live_session_not_marked(self):
        """mode=ended but tmux session still exists — don't clean."""
        result = plan_clean(
            tmux_running=True,
            zombie_sessions=[],
            session_dirs=[],
            live_tmux_names={"study-alive-abc"},
            state={"mode": "ended", "tmux_session": "study-alive-abc"},
            state_file_exists=True,
        )
        assert result.state_to_clean is False

    def test_no_state_file_not_marked(self):
        result = plan_clean(
            tmux_running=True,
            zombie_sessions=[],
            session_dirs=[],
            live_tmux_names=set(),
            state={},
            state_file_exists=False,
        )
        assert result.state_to_clean is False

    def test_ended_state_no_tmux_name_still_cleaned(self):
        """mode=ended with empty tmux_session — safe to clean."""
        result = plan_clean(
            tmux_running=True,
            zombie_sessions=[],
            session_dirs=[],
            live_tmux_names=set(),
            state={"mode": "ended", "tmux_session": ""},
            state_file_exists=True,
        )
        assert result.state_to_clean is True


class TestPlanCleanNoTmuxServer:
    def test_no_tmux_skips_all_with_warning(self):
        result = plan_clean(
            tmux_running=False,
            zombie_sessions=[],
            session_dirs=[
                DirInfo(name="study-stale", path=Path("/tmp/study-stale"), is_symlink=False)
            ],
            live_tmux_names=set(),
            state={"mode": "ended"},
            state_file_exists=True,
        )
        assert result.sessions_to_kill == []
        assert result.dirs_to_remove == []
        assert result.state_to_clean is False
        assert any("tmux" in w.lower() for w in result.warnings)


class TestPlanCleanCombined:
    def test_full_cleanup_scenario(self, tmp_path):
        """Multiple artifact types cleaned in one pass."""
        stale_dir = tmp_path / "study-dead-abc123"
        stale_dir.mkdir()

        result = plan_clean(
            tmux_running=True,
            zombie_sessions=["study-zombie-xyz"],
            session_dirs=[DirInfo(name="study-dead-abc123", path=stale_dir, is_symlink=False)],
            live_tmux_names={"study-zombie-xyz"},
            state={"mode": "ended", "tmux_session": "study-gone-999"},
            state_file_exists=True,
        )
        assert result.sessions_to_kill == ["study-zombie-xyz"]
        assert result.dirs_to_remove == [stale_dir]
        assert result.state_to_clean is True
        assert result.has_work


# ─── CleanResult Tests ──────────────────────────────────────────


class TestCleanResult:
    def test_has_work_false_when_empty(self):
        assert not CleanResult().has_work

    def test_has_work_true_with_sessions(self):
        assert CleanResult(sessions_to_kill=["s1"]).has_work

    def test_has_work_true_with_dirs(self):
        assert CleanResult(dirs_to_remove=[Path("/tmp/x")]).has_work

    def test_has_work_true_with_state(self):
        assert CleanResult(state_to_clean=True).has_work
