"""Tests for studyctl.tmux — tmux CLI wrapper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# Inline fixtures only (no conftest.py — pluggy conflict)


@pytest.fixture()
def mock_subprocess():
    """Mock subprocess.run for tmux tests."""
    with patch("studyctl.tmux.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        yield mock_run


@pytest.fixture()
def mock_shutil_which():
    """Mock shutil.which for detection tests."""
    with patch("studyctl.tmux.shutil.which") as mock_which:
        yield mock_which


class TestDetection:
    def test_tmux_available_when_installed(self, mock_shutil_which, mock_subprocess):
        from studyctl.tmux import is_tmux_available

        mock_shutil_which.return_value = "/usr/bin/tmux"
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="tmux 3.4\n")

        assert is_tmux_available() is True

    def test_tmux_not_available_when_missing(self, mock_shutil_which):
        from studyctl.tmux import is_tmux_available

        mock_shutil_which.return_value = None

        assert is_tmux_available() is False

    def test_tmux_not_available_old_version(self, mock_shutil_which, mock_subprocess):
        from studyctl.tmux import is_tmux_available

        mock_shutil_which.return_value = "/usr/bin/tmux"
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="tmux 2.9\n")

        assert is_tmux_available() is False

    def test_tmux_version_with_letter_suffix(self, mock_shutil_which, mock_subprocess):
        from studyctl.tmux import is_tmux_available

        mock_shutil_which.return_value = "/usr/bin/tmux"
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="tmux 3.5a\n")

        assert is_tmux_available() is True

    def test_is_in_tmux_true(self):
        from studyctl.tmux import is_in_tmux

        with patch.dict("os.environ", {"TMUX": "/tmp/tmux-501/default,1234,0"}):
            assert is_in_tmux() is True

    def test_is_in_tmux_false(self):
        from studyctl.tmux import is_in_tmux

        with patch.dict("os.environ", {}, clear=True):
            assert is_in_tmux() is False

    def test_session_exists_true(self, mock_subprocess):
        from studyctl.tmux import session_exists

        mock_subprocess.return_value = MagicMock(returncode=0)

        assert session_exists("study-decorators-abc12345") is True
        mock_subprocess.assert_called_once_with(
            ["tmux", "has-session", "-t", "study-decorators-abc12345"],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_session_exists_false(self, mock_subprocess):
        from studyctl.tmux import session_exists

        mock_subprocess.return_value = MagicMock(returncode=1)

        assert session_exists("nonexistent") is False


class TestSessionManagement:
    def test_create_session_returns_pane_id(self, mock_subprocess, tmp_path):
        from studyctl.tmux import create_session

        mock_subprocess.return_value = MagicMock(returncode=0, stdout="%0\n", stderr="")

        with patch("studyctl.tmux.LOCK_FILE", tmp_path / "lock"):
            pane_id = create_session("test-session")

        assert pane_id == "%0"
        call_args = mock_subprocess.call_args[0][0]
        assert "new-session" in call_args
        assert "-P" in call_args
        assert "-F" in call_args
        assert "#{pane_id}" in call_args

    def test_split_pane_returns_new_pane_id(self, mock_subprocess):
        from studyctl.tmux import split_pane

        mock_subprocess.return_value = MagicMock(returncode=0, stdout="%1\n", stderr="")

        pane_id = split_pane("test-session", direction="right", size=35)

        assert pane_id == "%1"
        call_args = mock_subprocess.call_args[0][0]
        assert "-h" in call_args  # horizontal split for "right"
        assert "-P" in call_args
        assert "#{pane_id}" in call_args

    def test_split_pane_vertical(self, mock_subprocess):
        from studyctl.tmux import split_pane

        mock_subprocess.return_value = MagicMock(returncode=0, stdout="%2\n", stderr="")

        split_pane("test-session", direction="below", size=10)

        call_args = mock_subprocess.call_args[0][0]
        assert "-v" in call_args  # vertical split for "below"

    def test_send_keys_with_enter(self, mock_subprocess):
        from studyctl.tmux import send_keys

        send_keys("%0", "claude --help")

        call_args = mock_subprocess.call_args[0][0]
        assert call_args == ["tmux", "send-keys", "-t", "%0", "claude --help", "Enter"]

    def test_send_keys_without_enter(self, mock_subprocess):
        from studyctl.tmux import send_keys

        send_keys("%0", "C-c", enter=False)

        call_args = mock_subprocess.call_args[0][0]
        assert "Enter" not in call_args

    def test_load_config(self, mock_subprocess, tmp_path):
        from studyctl.tmux import load_config

        conf = tmp_path / "tmux.conf"
        load_config(conf)

        call_args = mock_subprocess.call_args[0][0]
        assert call_args == ["tmux", "source-file", str(conf)]

    def test_kill_session(self, mock_subprocess):
        from studyctl.tmux import kill_session

        # Default mock returns rc=0, so session_exists returns True (session
        # still alive after kill). kill_session retries then returns False.
        # Override to simulate session gone after first kill:
        mock_subprocess.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),  # kill-session
            MagicMock(returncode=1, stdout="", stderr=""),  # has-session (gone)
        ]

        result = kill_session("test-session")

        first_call = mock_subprocess.call_args_list[0][0][0]
        assert first_call == ["tmux", "kill-session", "-t", "test-session"]
        assert result is True

    def test_get_tmux_version(self, mock_subprocess):
        from studyctl.tmux import get_tmux_version

        mock_subprocess.return_value = MagicMock(returncode=0, stdout="tmux 3.4\n")

        assert get_tmux_version() == "tmux 3.4"

    def test_get_tmux_version_not_installed(self, mock_subprocess):
        from studyctl.tmux import get_tmux_version

        mock_subprocess.return_value = MagicMock(returncode=1, stdout="")

        assert get_tmux_version() is None


class TestAttachSafetyGuard:
    """Verify attach() falls back to switch_client when already inside tmux."""

    def test_attach_uses_execvp_outside_tmux(self):
        from studyctl.tmux import attach

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("studyctl.tmux.os.execvp") as mock_exec,
        ):
            attach("study-python-abc123")

        mock_exec.assert_called_once_with(
            "tmux", ["tmux", "attach-session", "-t", "study-python-abc123"]
        )

    def test_attach_falls_back_to_switch_client_inside_tmux(self, mock_subprocess):
        from studyctl.tmux import attach

        with patch.dict("os.environ", {"TMUX": "/tmp/tmux-501/default,1234,0"}):
            attach("study-python-abc123")

        # Should have called switch-client, NOT os.execvp
        mock_subprocess.assert_called_once_with(
            ["tmux", "switch-client", "-t", "study-python-abc123"],
            capture_output=True,
            text=True,
            check=True,
        )

    def test_attach_logs_warning_inside_tmux(self, mock_subprocess):
        from studyctl.tmux import attach

        with (
            patch.dict("os.environ", {"TMUX": "/tmp/tmux-501/default,1234,0"}),
            patch("studyctl.tmux.logger") as mock_logger,
        ):
            attach("study-test")

        mock_logger.warning.assert_called_once()
        assert "nested" in mock_logger.warning.call_args[0][0].lower()
