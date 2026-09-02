"""Tests for studyloop clean — functional core (plan_clean) + CLI shell.

Tests the pure logic directly via plan_clean(). No mocking required.
The imperative shell (_clean.py) is tested via Click's CliRunner
with mocks only at the I/O boundary.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from studyloop.logic.clean_logic import CleanResult, DirInfo, plan_clean

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


# ─── Imperative Shell Tests (CliRunner + mocks at the I/O boundary) ─────
#
# R-02: kill_all_study_sessions() used to be reachable from the per-session
# end path (session/cleanup.py). That call site is gone now -- the ending
# session's own multiplexer name is killed instead. `studyloop clean --all`
# is the one place left that still reaches for the blunt "kill everything"
# sweep, as a deliberate, explicit operation the review's fix recommended
# keeping ("keep a separate, explicit 'clean everything' operation for
# `studyloop clean`"). Default `clean` (no --all) is unchanged: zombie-only,
# via individual kill_session() calls.


class TestCleanAllFlag:
    def _mock_mux(self, *, all_sessions: list[str], zombies: set[str]):
        from unittest.mock import MagicMock

        mux = MagicMock()
        mux.is_server_running.return_value = True
        mux.list_study_sessions.return_value = list(all_sessions)
        mux.is_zombie_session.side_effect = lambda name: name in zombies
        mux.kill_session.return_value = True
        return mux

    def _invoke(self, mux, tmp_path, args: list[str]):
        from click.testing import CliRunner

        from studyloop import session_state as ss
        from studyloop.cli._clean import clean

        with (
            patch("studyloop.multiplexer.get_backend", return_value=mux),
            patch.object(ss, "SESSION_DIR", tmp_path),
            patch.object(ss, "STATE_FILE", tmp_path / "session-state.json"),
        ):
            return CliRunner().invoke(clean, args)

    def test_default_dry_run_lists_only_zombies(self, tmp_path):
        """Regression: --all absent must not change default behaviour."""
        mux = self._mock_mux(
            all_sessions=["study-live-1", "study-zombie-2"], zombies={"study-zombie-2"}
        )

        result = self._invoke(mux, tmp_path, ["--dry-run"])

        assert result.exit_code == 0, result.output
        assert "study-zombie-2" in result.output
        assert "study-live-1" not in result.output
        mux.kill_all_study_sessions.assert_not_called()

    def test_dry_run_all_lists_every_study_session(self, tmp_path):
        mux = self._mock_mux(
            all_sessions=["study-live-1", "study-zombie-2"], zombies={"study-zombie-2"}
        )

        result = self._invoke(mux, tmp_path, ["--dry-run", "--all"])

        assert result.exit_code == 0, result.output
        assert "study-live-1" in result.output
        assert "study-zombie-2" in result.output
        mux.kill_all_study_sessions.assert_not_called()  # dry-run never acts

    def test_all_calls_kill_all_study_sessions_not_individual_kills(self, tmp_path):
        mux = self._mock_mux(
            all_sessions=["study-live-1", "study-zombie-2"], zombies={"study-zombie-2"}
        )

        result = self._invoke(mux, tmp_path, ["--all"])

        assert result.exit_code == 0, result.output
        mux.kill_all_study_sessions.assert_called_once_with(current_session=None)
        mux.kill_session.assert_not_called()

    def test_without_all_only_zombies_are_individually_killed(self, tmp_path):
        mux = self._mock_mux(
            all_sessions=["study-live-1", "study-zombie-2"], zombies={"study-zombie-2"}
        )

        result = self._invoke(mux, tmp_path, [])

        assert result.exit_code == 0, result.output
        mux.kill_all_study_sessions.assert_not_called()
        mux.kill_session.assert_called_once_with("study-zombie-2")
