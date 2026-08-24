"""Tests for studyloop.session.orchestrator — ttyd background process."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


class TestStartWebBackground:
    def test_hands_only_verifier_to_web_server_and_closes_parent_fd_before_browser(self):
        from studyloop.learner_credentials import hash_password
        from studyloop.session.orchestrator import start_web_background

        learner_secret = "human-only-pipe-value"  # pragma: allowlist secret
        verifier = hash_password(learner_secret)
        captured: dict[str, object] = {}

        def fake_popen(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            fds = kwargs.get("pass_fds", ())
            captured["fds"] = fds
            if fds:
                child_fd = os.dup(fds[0])
                try:
                    captured["payload"] = os.read(child_fd, 4096)
                finally:
                    os.close(child_fd)
            return SimpleNamespace(pid=12345)

        def assert_parent_fd_closed_before_browser(_url: str) -> None:
            with pytest.raises(OSError):
                os.fstat(captured["fds"][0])

        with (
            patch("studyloop.session.orchestrator.subprocess.Popen", side_effect=fake_popen),
            patch("studyloop.session.orchestrator.shutil.which", return_value="/usr/bin/studyloop"),
            patch("studyloop.session.orchestrator._kill_port_occupant"),
            patch(
                "studyloop.session.orchestrator._open_browser",
                side_effect=assert_parent_fd_closed_before_browser,
            ),
            patch("studyloop.session_state.write_session_state") as write_state,
        ):
            start_web_background(
                "study-python-abc123",
                lan=True,
                username="learner",
                password_verifier=verifier,
            )

        command = captured["command"]
        kwargs = captured["kwargs"]
        assert learner_secret not in " ".join(command)
        assert "--password" not in command
        assert learner_secret not in json.dumps(kwargs.get("env", {}))
        assert json.loads(captured["payload"]) == {
            "username": "learner",
            "password_verifier": verifier,
        }
        assert learner_secret not in captured["payload"].decode()
        inherited_fd = captured["fds"][0]
        with pytest.raises(OSError):
            os.fstat(inherited_fd)
        write_state.assert_called_once_with({"web_pid": 12345, "web_port": 8567})

    def test_failed_web_spawn_closes_parent_credential_fd(self):
        from studyloop.learner_credentials import hash_password
        from studyloop.session.orchestrator import start_web_background

        captured_fd: list[int] = []

        def fail_popen(_command, **kwargs):
            captured_fd.extend(kwargs.get("pass_fds", ()))
            raise OSError("spawn failed")

        with (
            patch("studyloop.session.orchestrator.subprocess.Popen", side_effect=fail_popen),
            patch("studyloop.session.orchestrator.shutil.which", return_value="/usr/bin/studyloop"),
            patch("studyloop.session.orchestrator._kill_port_occupant"),
        ):
            start_web_background(
                "study-python-abc123",
                lan=True,
                username="learner",
                password_verifier=hash_password("failure-path-password"),
            )

        assert captured_fd
        with pytest.raises(OSError):
            os.fstat(captured_fd[0])


class TestStartTtydBackground:
    def test_spawns_ttyd_with_correct_args(self):
        """ttyd is launched with the tmux session name and correct flags."""
        from studyloop.session.orchestrator import start_ttyd_background

        mock_popen = MagicMock()
        mock_popen.return_value.pid = 12345
        mock_state = MagicMock()

        with (
            patch("studyloop.session.orchestrator.subprocess.Popen", mock_popen),
            patch(
                "studyloop.session.orchestrator.shutil.which", return_value="/usr/local/bin/ttyd"
            ),
            patch("studyloop.session_state.write_session_state", mock_state),
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

    def test_lan_mode_keeps_ttyd_on_loopback_without_password_argv(self):
        """LAN terminal access is authenticated by the StudyLoop proxy."""
        from studyloop.session.orchestrator import start_ttyd_background

        mock_popen = MagicMock()
        mock_popen.return_value.pid = 12345

        with (
            patch("studyloop.session.orchestrator.subprocess.Popen", mock_popen),
            patch(
                "studyloop.session.orchestrator.shutil.which", return_value="/usr/local/bin/ttyd"
            ),
            patch("studyloop.session_state.write_session_state"),
        ):
            start_ttyd_background("study-python-abc123", lan=True)

        args = mock_popen.call_args[0][0]
        idx = args.index("-i")
        assert args[idx + 1] == "127.0.0.1"
        assert "-c" not in args

    def test_skips_when_ttyd_not_installed(self):
        """No error when ttyd is not installed — just skip."""
        from studyloop.session.orchestrator import start_ttyd_background

        with patch("studyloop.session.orchestrator.shutil.which", return_value=None):
            start_ttyd_background("study-test", lan=False)

    def test_uses_configured_port(self):
        """Port from config is used if set."""
        from studyloop.session.orchestrator import start_ttyd_background

        mock_popen = MagicMock()
        mock_popen.return_value.pid = 99

        with (
            patch("studyloop.session.orchestrator.subprocess.Popen", mock_popen),
            patch("studyloop.session.orchestrator.shutil.which", return_value="/usr/bin/ttyd"),
            patch("studyloop.session_state.write_session_state"),
            patch("studyloop.session.orchestrator._get_ttyd_port", return_value=9999),
        ):
            start_ttyd_background("study-test", lan=False)

        args = mock_popen.call_args[0][0]
        idx = args.index("-p")
        assert args[idx + 1] == "9999"
