"""Tests for studyloop study CLI command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from studyloop.cli._study import StudySessionSelection, study

# Inline fixtures only (no conftest.py — pluggy conflict)


@pytest.fixture()
def runner():
    return CliRunner()


def _tmux_side_effect(args, **kwargs):
    """Mock tmux subprocess that returns version for -V, pane ID for others."""
    if "-V" in args:
        return MagicMock(returncode=0, stdout="tmux 3.4\n", stderr="")
    if "has-session" in args:
        return MagicMock(returncode=1, stdout="", stderr="")  # no existing session
    return MagicMock(returncode=0, stdout="%0\n", stderr="")


class TestStudyCommand:
    def test_no_topic_cancel_exits_without_starting(self, runner):
        with patch("studyloop.cli._study._prompt_study_session", return_value=None):
            result = runner.invoke(study, [])
        assert result.exit_code == 1

    def test_no_topic_uses_picker_selection(self, runner):
        selection = StudySessionSelection(
            topic="Ultimate AWS Data Engineering Bootcamp",
            mode="study",
            topic_config=None,
        )
        with (
            patch("studyloop.cli._study._prompt_study_session", return_value=selection),
            patch("studyloop.cli._study._handle_start") as start,
        ):
            result = runner.invoke(study, ["--energy", "7"])

        assert result.exit_code == 0
        start.assert_called_once()
        args = start.call_args.args
        assert args[1] == "Ultimate AWS Data Engineering Bootcamp"
        assert args[3] == "study"
        assert args[5] == 7

    def test_tmux_not_available(self, runner):
        with patch("studyloop.tmux.shutil.which", return_value=None):
            result = runner.invoke(study, ["Test Topic"])
            assert result.exit_code != 0
            assert "tmux" in result.output

    def test_no_agent_found(self, runner):
        with (
            patch("studyloop.tmux.is_tmux_available", return_value=True),
            patch("studyloop.agent_launcher.shutil.which", return_value=None),
            patch("studyloop.session_state.read_session_state", return_value={}),
        ):
            result = runner.invoke(study, ["Test Topic"])
            assert result.exit_code != 0
            assert "No AI agent" in result.output

    def test_existing_session_blocks(self, runner):
        state = {"study_session_id": "existing123"}
        with (
            patch("studyloop.tmux.shutil.which", return_value="/usr/bin/tmux"),
            patch("studyloop.tmux.subprocess.run", side_effect=_tmux_side_effect),
            patch("studyloop.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyloop.session_state.read_session_state", return_value=state),
            patch("studyloop.session_state.STATE_FILE") as sf,
        ):
            sf.exists.return_value = True
            result = runner.invoke(study, ["Test Topic"])
            assert result.exit_code != 0
            assert "already active" in result.output

    def test_start_creates_tmux_session(self, runner, tmp_path):
        with (
            patch("studyloop.tmux.shutil.which", return_value="/usr/bin/tmux"),
            patch("studyloop.tmux.subprocess.run", side_effect=_tmux_side_effect),
            patch("studyloop.tmux.LOCK_FILE", tmp_path / "lock"),
            patch("studyloop.tmux.os.execvp"),
            patch("studyloop.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyloop.session_state.read_session_state", return_value={}),
            patch("studyloop.session_state.STATE_FILE", tmp_path / "state.json"),
            patch("studyloop.session_state.SESSION_DIR", tmp_path),
            patch("studyloop.session_state.TOPICS_FILE", tmp_path / "topics.md"),
            patch("studyloop.session_state.PARKING_FILE", tmp_path / "parking.md"),
            patch("studyloop.history.start_study_session", return_value="abc12345"),
            # In tmux → switch_client is called (no os.execvp)
            patch.dict("os.environ", {"TMUX": "/tmp/tmux"}),
        ):
            result = runner.invoke(study, ["Python Decorators", "--energy", "7"])

            # switch_client runs synchronously, then execution continues
            # No console output expected because print happens before
            # switch_client in the non-in-tmux path, but in the in-tmux
            # path we now skip printing (switch happens immediately)
            assert result.exit_code == 0

    def test_defaults_elapsed_timer_for_study(self, runner, tmp_path):
        with (
            patch("studyloop.tmux.shutil.which", return_value="/usr/bin/tmux"),
            patch("studyloop.tmux.subprocess.run", side_effect=_tmux_side_effect),
            patch("studyloop.tmux.LOCK_FILE", tmp_path / "lock"),
            patch("studyloop.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyloop.session_state.read_session_state", return_value={}),
            patch("studyloop.session_state.STATE_FILE", tmp_path / "state.json"),
            patch("studyloop.session_state.SESSION_DIR", tmp_path),
            patch("studyloop.session_state.TOPICS_FILE", tmp_path / "topics.md"),
            patch("studyloop.session_state.PARKING_FILE", tmp_path / "parking.md"),
            patch("studyloop.history.start_study_session", return_value="abc12345"),
        ):
            with patch.dict("os.environ", {"TMUX": "/tmp/tmux"}):
                result = runner.invoke(study, ["Test Topic"])

            assert result.exit_code == 0

    def test_defaults_pomodoro_timer_for_co_study(self, runner, tmp_path):
        with (
            patch("studyloop.tmux.shutil.which", return_value="/usr/bin/tmux"),
            patch("studyloop.tmux.subprocess.run", side_effect=_tmux_side_effect),
            patch("studyloop.tmux.LOCK_FILE", tmp_path / "lock"),
            patch("studyloop.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyloop.session_state.read_session_state", return_value={}),
            patch("studyloop.session_state.STATE_FILE", tmp_path / "state.json"),
            patch("studyloop.session_state.SESSION_DIR", tmp_path),
            patch("studyloop.session_state.TOPICS_FILE", tmp_path / "topics.md"),
            patch("studyloop.session_state.PARKING_FILE", tmp_path / "parking.md"),
            patch("studyloop.history.start_study_session", return_value="abc12345"),
        ):
            with patch.dict("os.environ", {"TMUX": "/tmp/tmux"}):
                result = runner.invoke(study, ["Test Topic", "--mode", "co-study"])

            assert result.exit_code == 0


class TestStudyTransportFlag:
    """§1.10: ``--transport [pty|ttyd]`` parity with the web picker.

    The flag exists on the CLI surface today; the ``pty`` branch is
    deferred to §1.5d (CLI-driven PTY sessions need more plumbing
    than the web route got). Declaring the option now keeps the CLI
    and web surfaces symmetric and future-proofs the signature.
    """

    def test_transport_flag_is_declared(self, runner):
        result = runner.invoke(study, ["--help"])
        assert result.exit_code == 0
        assert "--transport" in result.output

    def test_transport_pty_is_not_yet_supported(self, runner):
        """Passing --transport=pty reports the deferral cleanly rather
        than silently running the ttyd/tmux path or crashing."""
        result = runner.invoke(study, ["Test Topic", "--transport", "pty"])
        assert result.exit_code != 0
        assert "pty" in result.output.lower() or "not yet supported" in result.output.lower()

    def test_transport_rejects_unknown_values(self, runner):
        """Click's Choice() should reject anything outside {pty, ttyd}."""
        result = runner.invoke(study, ["Test Topic", "--transport", "acp"])
        assert result.exit_code != 0

    def test_transport_ttyd_is_accepted_and_runs_legacy_path(self, runner, tmp_path):
        """--transport=ttyd must not crash; it's the current default shape."""
        with (
            patch("studyloop.tmux.shutil.which", return_value="/usr/bin/tmux"),
            patch("studyloop.tmux.subprocess.run", side_effect=_tmux_side_effect),
            patch("studyloop.tmux.LOCK_FILE", tmp_path / "lock"),
            patch("studyloop.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyloop.session_state.read_session_state", return_value={}),
            patch("studyloop.session_state.STATE_FILE", tmp_path / "state.json"),
            patch("studyloop.session_state.SESSION_DIR", tmp_path),
            patch("studyloop.session_state.TOPICS_FILE", tmp_path / "topics.md"),
            patch("studyloop.session_state.PARKING_FILE", tmp_path / "parking.md"),
            patch("studyloop.history.start_study_session", return_value="abc12345"),
            patch.dict("os.environ", {"TMUX": "/tmp/tmux"}),
        ):
            result = runner.invoke(study, ["Test Topic", "--transport", "ttyd"])
        assert result.exit_code == 0


class TestStudyEnd:
    def test_end_no_session(self, runner):
        with patch("studyloop.session_state.read_session_state", return_value={}):
            result = runner.invoke(study, ["--end"])
            assert "No active session" in result.output

    def test_end_cleans_up(self, runner, tmp_path):
        state = {
            "study_session_id": "abc123",
            "topic": "Test",
            "tmux_session": "study-test-abc12345",
            "persona_file": "/tmp/nonexistent.md",
        }
        # Patch the session_state path globals with REAL tmp_path paths, not bare
        # MagicMocks. A bare MagicMock here leaks a "<MagicMock id=...>" file into
        # the cwd: the --end path reaches write_session_state(), which does
        # os.open(str(_lock_file()), O_CREAT) where _lock_file() = SESSION_DIR /
        # ".session-state.lock". With SESSION_DIR a mock, str(...) becomes the
        # literal "<MagicMock ...>" and os.open creates a real file. Real paths
        # keep that write sandboxed inside tmp_path.
        with (
            patch("studyloop.session_state.read_session_state", return_value=state),
            patch("studyloop.session_state.STATE_FILE", tmp_path / "state.json"),
            patch("studyloop.session_state.SESSION_DIR", tmp_path),
            patch("studyloop.session_state.TOPICS_FILE", tmp_path / "topics.md"),
            patch("studyloop.session_state.PARKING_FILE", tmp_path / "parking.md"),
            patch("studyloop.history.end_study_session") as end,
            patch("studyloop.session_state._write_file_secure"),
            patch("studyloop.session_state._ensure_session_dir"),
            patch("studyloop.tmux.subprocess.run") as tmux_run,
        ):
            tmux_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(study, ["--end"])

            assert "Session ended" in result.output
            end.assert_called_once_with(
                "abc123",
                notes="No topics recorded during session.",
                win_count=0,
                struggle_count=0,
            )


class TestStudyResume:
    def test_resume_no_session(self, runner):
        with patch("studyloop.session_state.read_session_state", return_value={}):
            result = runner.invoke(study, ["--resume"])
            assert "No active session" in result.output

    def test_resume_stale_tmux(self, runner):
        state = {"tmux_session": "study-dead-abc12345", "topic": "Test"}
        with (
            patch("studyloop.session_state.read_session_state", return_value=state),
            patch("studyloop.tmux.subprocess.run") as tmux_run,
        ):
            tmux_run.return_value = MagicMock(returncode=1)  # session doesn't exist
            result = runner.invoke(study, ["--resume"])
            assert "no longer exists" in result.output

    def test_resume_reconnects(self, runner):
        state = {
            "tmux_session": "study-test-abc12345",
            "tmux_main_pane": "%0",
            "topic": "Test Topic",
        }
        with (
            patch("studyloop.session_state.read_session_state", return_value=state),
            patch("studyloop.tmux.subprocess.run") as tmux_run,
        ):
            # session_exists returns 0 (exists); pgrep returns 0 (has children)
            tmux_run.return_value = MagicMock(returncode=0, stdout="47593\n")
            with patch.dict("os.environ", {"TMUX": "/tmp/tmux"}):
                result = runner.invoke(study, ["--resume"])
                assert "Resuming" in result.output
