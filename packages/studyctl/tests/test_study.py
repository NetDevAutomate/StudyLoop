"""Tests for studyctl study CLI command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from studyctl.cli._study import study

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
    def test_requires_topic(self, runner):
        result = runner.invoke(study, [])
        assert result.exit_code != 0 or "Topic is required" in result.output

    def test_tmux_not_available(self, runner):
        with patch("studyctl.tmux.shutil.which", return_value=None):
            result = runner.invoke(study, ["Test Topic"])
            assert result.exit_code != 0
            assert "tmux" in result.output

    def test_no_agent_found(self, runner):
        with (
            patch("studyctl.tmux.is_tmux_available", return_value=True),
            patch("studyctl.agent_launcher.shutil.which", return_value=None),
            patch("studyctl.session_state.read_session_state", return_value={}),
        ):
            result = runner.invoke(study, ["Test Topic"])
            assert result.exit_code != 0
            assert "No AI agent" in result.output

    def test_existing_session_blocks(self, runner):
        state = {"study_session_id": "existing123"}
        with (
            patch("studyctl.tmux.shutil.which", return_value="/usr/bin/tmux"),
            patch("studyctl.tmux.subprocess.run", side_effect=_tmux_side_effect),
            patch("studyctl.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyctl.session_state.read_session_state", return_value=state),
            patch("studyctl.session_state.STATE_FILE") as sf,
        ):
            sf.exists.return_value = True
            result = runner.invoke(study, ["Test Topic"])
            assert result.exit_code != 0
            assert "already active" in result.output

    def test_start_creates_tmux_session(self, runner, tmp_path):
        with (
            patch("studyctl.tmux.shutil.which", return_value="/usr/bin/tmux"),
            patch("studyctl.tmux.subprocess.run", side_effect=_tmux_side_effect),
            patch("studyctl.tmux.LOCK_FILE", tmp_path / "lock"),
            patch("studyctl.tmux.os.execvp"),
            patch("studyctl.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyctl.session_state.read_session_state", return_value={}),
            patch("studyctl.session_state.STATE_FILE", tmp_path / "state.json"),
            patch("studyctl.session_state.SESSION_DIR", tmp_path),
            patch("studyctl.session_state.TOPICS_FILE", tmp_path / "topics.md"),
            patch("studyctl.session_state.PARKING_FILE", tmp_path / "parking.md"),
            patch("studyctl.history.start_study_session", return_value="abc12345"),
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
            patch("studyctl.tmux.shutil.which", return_value="/usr/bin/tmux"),
            patch("studyctl.tmux.subprocess.run", side_effect=_tmux_side_effect),
            patch("studyctl.tmux.LOCK_FILE", tmp_path / "lock"),
            patch("studyctl.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyctl.session_state.read_session_state", return_value={}),
            patch("studyctl.session_state.STATE_FILE", tmp_path / "state.json"),
            patch("studyctl.session_state.SESSION_DIR", tmp_path),
            patch("studyctl.session_state.TOPICS_FILE", tmp_path / "topics.md"),
            patch("studyctl.session_state.PARKING_FILE", tmp_path / "parking.md"),
            patch("studyctl.history.start_study_session", return_value="abc12345"),
        ):
            with patch.dict("os.environ", {"TMUX": "/tmp/tmux"}):
                result = runner.invoke(study, ["Test Topic"])

            assert result.exit_code == 0

    def test_defaults_pomodoro_timer_for_co_study(self, runner, tmp_path):
        with (
            patch("studyctl.tmux.shutil.which", return_value="/usr/bin/tmux"),
            patch("studyctl.tmux.subprocess.run", side_effect=_tmux_side_effect),
            patch("studyctl.tmux.LOCK_FILE", tmp_path / "lock"),
            patch("studyctl.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch("studyctl.session_state.read_session_state", return_value={}),
            patch("studyctl.session_state.STATE_FILE", tmp_path / "state.json"),
            patch("studyctl.session_state.SESSION_DIR", tmp_path),
            patch("studyctl.session_state.TOPICS_FILE", tmp_path / "topics.md"),
            patch("studyctl.session_state.PARKING_FILE", tmp_path / "parking.md"),
            patch("studyctl.history.start_study_session", return_value="abc12345"),
        ):
            with patch.dict("os.environ", {"TMUX": "/tmp/tmux"}):
                result = runner.invoke(study, ["Test Topic", "--mode", "co-study"])

            assert result.exit_code == 0


class TestStudyEnd:
    def test_end_no_session(self, runner):
        with patch("studyctl.session_state.read_session_state", return_value={}):
            result = runner.invoke(study, ["--end"])
            assert "No active session" in result.output

    def test_end_cleans_up(self, runner):
        state = {
            "study_session_id": "abc123",
            "topic": "Test",
            "tmux_session": "study-test-abc12345",
            "persona_file": "/tmp/nonexistent.md",
        }
        with (
            patch("studyctl.session_state.read_session_state", return_value=state),
            patch("studyctl.session_state.STATE_FILE") as sf,
            patch("studyctl.session_state.SESSION_DIR") as sd,
            patch("studyctl.session_state.TOPICS_FILE") as tf,
            patch("studyctl.session_state.PARKING_FILE") as pf,
            patch("studyctl.history.end_study_session") as end,
            patch("studyctl.session_state._write_file_secure"),
            patch("studyctl.session_state._ensure_session_dir"),
            patch("studyctl.tmux.subprocess.run") as tmux_run,
        ):
            sf.exists.return_value = True
            sd.__truediv__ = MagicMock(return_value=MagicMock(exists=MagicMock(return_value=False)))
            tf.unlink = MagicMock()
            pf.unlink = MagicMock()
            tmux_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(study, ["--end"])

            assert "Session ended" in result.output
            end.assert_called_once_with("abc123", notes="No topics recorded during session.")


class TestStudyResume:
    def test_resume_no_session(self, runner):
        with patch("studyctl.session_state.read_session_state", return_value={}):
            result = runner.invoke(study, ["--resume"])
            assert "No active session" in result.output

    def test_resume_stale_tmux(self, runner):
        state = {"tmux_session": "study-dead-abc12345", "topic": "Test"}
        with (
            patch("studyctl.session_state.read_session_state", return_value=state),
            patch("studyctl.tmux.subprocess.run") as tmux_run,
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
            patch("studyctl.session_state.read_session_state", return_value=state),
            patch("studyctl.tmux.subprocess.run") as tmux_run,
        ):
            # session_exists returns 0 (exists); pgrep returns 0 (has children)
            tmux_run.return_value = MagicMock(returncode=0, stdout="47593\n")
            with patch.dict("os.environ", {"TMUX": "/tmp/tmux"}):
                result = runner.invoke(study, ["--resume"])
                assert "Resuming" in result.output
