"""Tests for studyctl.session.orchestrator — ttyd background process."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestStartTtydBackground:
    def test_spawns_ttyd_with_correct_args(self):
        """ttyd is launched with the tmux session name and correct flags."""
        from studyctl.session.orchestrator import start_ttyd_background

        mock_popen = MagicMock()
        mock_popen.return_value.pid = 12345
        mock_state = MagicMock()

        with (
            patch("studyctl.session.orchestrator.subprocess.Popen", mock_popen),
            patch("studyctl.session.orchestrator.shutil.which", return_value="/usr/local/bin/ttyd"),
            patch("studyctl.session_state.write_session_state", mock_state),
        ):
            start_ttyd_background("study-python-abc123", lan=False)

        args = mock_popen.call_args[0][0]
        assert args[0] == "/usr/local/bin/ttyd"
        assert "-W" in args
        assert "-p" in args
        assert "tmux" in args
        assert "study-python-abc123" in args
        # Default: localhost only
        idx = args.index("-i")
        assert args[idx + 1] == "127.0.0.1"
        # PID stored
        mock_state.assert_called_once_with({"ttyd_pid": 12345, "ttyd_port": 7681})

    def test_lan_mode_binds_all_interfaces(self):
        """With lan=True, ttyd binds to 0.0.0.0."""
        from studyctl.session.orchestrator import start_ttyd_background

        mock_popen = MagicMock()
        mock_popen.return_value.pid = 12345

        with (
            patch("studyctl.session.orchestrator.subprocess.Popen", mock_popen),
            patch("studyctl.session.orchestrator.shutil.which", return_value="/usr/local/bin/ttyd"),
            patch("studyctl.session_state.write_session_state"),
        ):
            start_ttyd_background("study-python-abc123", lan=True)

        args = mock_popen.call_args[0][0]
        idx = args.index("-i")
        assert args[idx + 1] == "0.0.0.0"

    def test_skips_when_ttyd_not_installed(self):
        """No error when ttyd is not installed — just skip."""
        from studyctl.session.orchestrator import start_ttyd_background

        with patch("studyctl.session.orchestrator.shutil.which", return_value=None):
            start_ttyd_background("study-test", lan=False)

    def test_uses_configured_port(self):
        """Port from config is used if set."""
        from studyctl.session.orchestrator import start_ttyd_background

        mock_popen = MagicMock()
        mock_popen.return_value.pid = 99

        with (
            patch("studyctl.session.orchestrator.subprocess.Popen", mock_popen),
            patch("studyctl.session.orchestrator.shutil.which", return_value="/usr/bin/ttyd"),
            patch("studyctl.session_state.write_session_state"),
            patch("studyctl.session.orchestrator._get_ttyd_port", return_value=9999),
        ):
            start_ttyd_background("study-test", lan=False)

        args = mock_popen.call_args[0][0]
        idx = args.index("-p")
        assert args[idx + 1] == "9999"
