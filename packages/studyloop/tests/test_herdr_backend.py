"""Tests for studyloop.herdr — HerdrBackend multiplexer implementation.

TDD: These tests mock the subprocess boundary (assert exact argv built and
parse representative JSON responses) so they run in CI without a herdr binary.

Tests needing the real binary are marked @pytest.mark.integration and are
deselected by default (see pyproject.toml addopts).
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    """Build a CompletedProcess matching subprocess.run(text=True)."""
    return subprocess.CompletedProcess(
        args=["herdr"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _json_result(data: dict | list) -> subprocess.CompletedProcess[str]:
    """Build a CompletedProcess with JSON stdout."""
    return _make_result(stdout=json.dumps(data))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_subprocess():
    """Mock subprocess.run for herdr tests."""
    with patch("studyloop.herdr.subprocess.run") as mock_run:
        mock_run.return_value = _make_result()
        yield mock_run


@pytest.fixture()
def mock_shutil_which():
    """Mock shutil.which for detection tests."""
    with patch("studyloop.herdr.shutil.which") as mock_which:
        mock_which.return_value = "/usr/local/bin/herdr"
        yield mock_which


@pytest.fixture()
def backend():
    """Create a HerdrBackend instance for testing."""
    from studyloop.herdr import HerdrBackend

    return HerdrBackend()


# ---------------------------------------------------------------------------
# Protocol Conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """HerdrBackend must satisfy the Multiplexer protocol."""

    def test_herdr_backend_is_multiplexer_instance(self):
        from studyloop.herdr import HerdrBackend
        from studyloop.multiplexer import Multiplexer

        backend = HerdrBackend()
        assert isinstance(backend, Multiplexer)

    def test_herdr_backend_has_all_protocol_methods(self):
        """Every Multiplexer protocol method exists on HerdrBackend."""
        from studyloop.herdr import HerdrBackend
        from studyloop.multiplexer import Multiplexer

        expected_methods = {
            name
            for name in dir(Multiplexer)
            if not name.startswith("_") and callable(getattr(Multiplexer, name, None))
        }
        backend = HerdrBackend()
        for method_name in expected_methods:
            assert hasattr(backend, method_name), f"HerdrBackend missing method: {method_name}"
            assert callable(getattr(backend, method_name))


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


class TestDetection:
    """is_available, is_inside_session, is_server_running."""

    def test_is_available_true(self, mock_shutil_which, mock_subprocess, backend):
        mock_shutil_which.return_value = "/usr/local/bin/herdr"
        mock_subprocess.return_value = _make_result(
            stdout="herdr 0.7.4-preview.2026-07-17-813fec141faa"
        )
        assert backend.is_available() is True

    def test_is_available_false_not_on_path(self, mock_shutil_which, backend):
        mock_shutil_which.return_value = None
        assert backend.is_available() is False

    def test_is_available_false_command_fails(self, mock_shutil_which, mock_subprocess, backend):
        mock_shutil_which.return_value = "/usr/local/bin/herdr"
        mock_subprocess.side_effect = FileNotFoundError("No such file")
        assert backend.is_available() is False

    def test_is_inside_session_true(self, backend):
        with patch.dict(os.environ, {"HERDR_ENV": "1"}):
            assert backend.is_inside_session() is True

    def test_is_inside_session_false_no_env(self, backend):
        env = os.environ.copy()
        env.pop("HERDR_ENV", None)
        with patch.dict(os.environ, env, clear=True):
            assert backend.is_inside_session() is False

    def test_is_inside_session_false_wrong_value(self, backend):
        with patch.dict(os.environ, {"HERDR_ENV": "0"}):
            assert backend.is_inside_session() is False

    def test_is_server_running_true(self, mock_subprocess, backend):
        mock_subprocess.return_value = _json_result(
            [{"name": "default", "running": True, "attached": True}]
        )
        assert backend.is_server_running() is True

    def test_is_server_running_false_on_error(self, mock_subprocess, backend):
        mock_subprocess.side_effect = subprocess.CalledProcessError(
            1, ["herdr", "session", "list", "--json"]
        )
        assert backend.is_server_running() is False


# ---------------------------------------------------------------------------
# Session Lifecycle
# ---------------------------------------------------------------------------


class TestSessionLifecycle:
    """create_session, session_exists, kill_session, list/kill_all."""

    def test_create_session_basic(self, mock_subprocess, backend):
        """Verify argv and JSON response parsing for workspace create."""
        mock_subprocess.return_value = _json_result(
            {
                "workspace_id": "w5",
                "tab_id": "w5:t1",
                "pane_id": "w5:p1",
            }
        )
        result = backend.create_session("study-decorators")

        mock_subprocess.assert_called_once()
        args = mock_subprocess.call_args[0][0]
        assert args[0] == "herdr"
        assert args[1] == "workspace"
        assert args[2] == "create"
        assert "--label" in args
        label_idx = args.index("--label")
        assert args[label_idx + 1] == "study-decorators"
        assert "--no-focus" in args
        # Returns pane_id (the initial pane identifier, per Protocol contract)
        assert result == "w5:p1"

    def test_create_session_with_cwd(self, mock_subprocess, backend):
        mock_subprocess.return_value = _json_result(
            {
                "workspace_id": "w6",
                "tab_id": "w6:t1",
                "pane_id": "w6:p1",
            }
        )
        backend.create_session("study-sql", cwd="/home/user/project")

        args = mock_subprocess.call_args[0][0]
        assert "--cwd" in args
        cwd_idx = args.index("--cwd")
        assert args[cwd_idx + 1] == "/home/user/project"

    def test_create_session_with_env(self, mock_subprocess, backend):
        mock_subprocess.return_value = _json_result(
            {
                "workspace_id": "w7",
                "tab_id": "w7:t1",
                "pane_id": "w7:p1",
            }
        )
        backend.create_session(
            "study-env",
            env={"STUDYLOOP_SESSION_ID": "abc123", "TOPIC": "python"},
        )

        args = mock_subprocess.call_args[0][0]
        # --env appears for each key=value pair
        env_indices = [i for i, a in enumerate(args) if a == "--env"]
        assert len(env_indices) == 2
        env_values = [args[i + 1] for i in env_indices]
        assert "STUDYLOOP_SESSION_ID=abc123" in env_values
        assert "TOPIC=python" in env_values

    def test_create_session_with_command(self, mock_subprocess, backend):
        """command= waits for a stable shell, then uses pane run.

        Five consecutive idle process-info samples are the readiness gate:
        one idle sample can sit between zsh prompt hooks, which is how the
        real herdr integration journey intermittently lost the agent command.
        """
        created = _json_result(
            {
                "workspace_id": "w8",
                "tab_id": "w8:t1",
                "pane_id": "w8:p1",
            }
        )
        idle = _json_result(
            {
                "process_info": {
                    "foreground_processes": [{"pid": 42, "name": "zsh"}],
                    "shell_pid": 42,
                }
            }
        )
        mock_subprocess.side_effect = [created, idle, idle, idle, idle, idle, _make_result()]
        backend.create_session("study-cmd", command="kiro-cli chat")

        # create + five idle readiness samples + pane run.
        assert mock_subprocess.call_count == 7
        run_args = mock_subprocess.call_args_list[-1][0][0]
        assert run_args[0] == "herdr"
        assert run_args[1] == "pane"
        assert run_args[2] == "run"
        assert "w8:p1" in run_args
        assert "kiro-cli chat" in run_args

    def test_session_exists_true(self, mock_subprocess, backend):
        """workspace list JSON, filter by label match."""
        mock_subprocess.return_value = _json_result(
            [
                {"workspace_id": "w1", "label": "StudyLoop"},
                {"workspace_id": "w3", "label": "study-decorators"},
            ]
        )
        assert backend.session_exists("study-decorators") is True

    def test_session_exists_false(self, mock_subprocess, backend):
        mock_subprocess.return_value = _json_result(
            [
                {"workspace_id": "w1", "label": "StudyLoop"},
            ]
        )
        assert backend.session_exists("study-python") is False

    def test_session_exists_handles_error(self, mock_subprocess, backend):
        mock_subprocess.side_effect = subprocess.CalledProcessError(
            1, ["herdr", "workspace", "list"]
        )
        assert backend.session_exists("study-anything") is False

    def test_kill_session(self, mock_subprocess, backend):
        """kill_session should find workspace by label then close it."""
        # First call: workspace list (find by label)
        # Second call: workspace close
        mock_subprocess.side_effect = [
            _json_result(
                [
                    {"workspace_id": "w1", "label": "StudyLoop"},
                    {"workspace_id": "w9", "label": "study-sql"},
                ]
            ),
            _json_result({"type": "ok"}),
        ]
        result = backend.kill_session("study-sql")

        assert result is True
        # Second call should be workspace close w9
        close_args = mock_subprocess.call_args_list[1][0][0]
        assert close_args == ["herdr", "workspace", "close", "w9"]

    def test_kill_session_not_found(self, mock_subprocess, backend):
        mock_subprocess.return_value = _json_result(
            [
                {"workspace_id": "w1", "label": "StudyLoop"},
            ]
        )
        result = backend.kill_session("study-nonexistent")
        assert result is False

    def test_list_study_sessions(self, mock_subprocess, backend):
        """Returns labels of workspaces matching 'study-' prefix."""
        mock_subprocess.return_value = _json_result(
            [
                {"workspace_id": "w1", "label": "StudyLoop"},
                {"workspace_id": "w2", "label": "Study"},
                {"workspace_id": "w3", "label": "study-decorators"},
                {"workspace_id": "w4", "label": "study-sql-joins"},
            ]
        )
        result = backend.list_study_sessions()
        assert result == ["study-decorators", "study-sql-joins"]

    def test_kill_all_study_sessions(self, mock_subprocess, backend):
        """Closes all study-* workspaces, current_session last."""
        mock_subprocess.side_effect = [
            # workspace list
            _json_result(
                [
                    {"workspace_id": "w1", "label": "StudyLoop"},
                    {"workspace_id": "w3", "label": "study-decorators"},
                    {"workspace_id": "w4", "label": "study-sql"},
                    {"workspace_id": "w5", "label": "study-spark"},
                ]
            ),
            # close w3 (other)
            _json_result({"type": "ok"}),
            # close w5 (other)
            _json_result({"type": "ok"}),
            # close w4 (current — killed last)
            _json_result({"type": "ok"}),
        ]
        backend.kill_all_study_sessions(current_session="study-sql")

        # Should close w3, w5 (others first), then w4 (current last). Not w1 (StudyLoop).
        assert mock_subprocess.call_count == 4
        close_calls = mock_subprocess.call_args_list[1:]
        close_ids = [call[0][0][-1] for call in close_calls]
        assert close_ids == ["w3", "w5", "w4"]  # others first, current last


# ---------------------------------------------------------------------------
# Pane Management
# ---------------------------------------------------------------------------


class TestPaneManagement:
    """split_pane, send_keys, select_pane."""

    def test_split_pane_right(self, mock_subprocess, backend):
        mock_subprocess.return_value = _json_result(
            {
                "pane_id": "w5:p2",
                "workspace_id": "w5",
                "tab_id": "w5:t1",
            }
        )
        result = backend.split_pane("w5:p1", direction="right", size=30, percentage=True)

        args = mock_subprocess.call_args[0][0]
        assert args[0:3] == ["herdr", "pane", "split"]
        assert "w5:p1" in args
        assert "--direction" in args
        dir_idx = args.index("--direction")
        assert args[dir_idx + 1] == "right"
        assert "--ratio" in args
        ratio_idx = args.index("--ratio")
        assert args[ratio_idx + 1] == "0.3"
        assert "--no-focus" in args
        assert result == "w5:p2"

    def test_split_pane_down(self, mock_subprocess, backend):
        mock_subprocess.return_value = _json_result(
            {
                "pane_id": "w5:p3",
                "workspace_id": "w5",
                "tab_id": "w5:t1",
            }
        )
        result = backend.split_pane("w5:p1", direction="down", size=50, percentage=True)

        args = mock_subprocess.call_args[0][0]
        assert "--direction" in args
        dir_idx = args.index("--direction")
        assert args[dir_idx + 1] == "down"
        assert "--ratio" in args
        ratio_idx = args.index("--ratio")
        assert args[ratio_idx + 1] == "0.5"
        assert result == "w5:p3"

    def test_split_pane_with_command(self, mock_subprocess, backend):
        """command= triggers a pane run after the split."""
        mock_subprocess.side_effect = [
            # split response
            _json_result({"pane_id": "w5:p4", "workspace_id": "w5", "tab_id": "w5:t1"}),
            # pane run response
            _make_result(),
        ]
        result = backend.split_pane("w5:p1", command="studyloop-sidebar")

        assert mock_subprocess.call_count == 2
        run_args = mock_subprocess.call_args_list[1][0][0]
        assert run_args[0:3] == ["herdr", "pane", "run"]
        assert "w5:p4" in run_args
        assert "studyloop-sidebar" in run_args
        assert result == "w5:p4"

    def test_split_pane_with_env(self, mock_subprocess, backend):
        mock_subprocess.return_value = _json_result(
            {
                "pane_id": "w5:p5",
                "workspace_id": "w5",
                "tab_id": "w5:t1",
            }
        )
        backend.split_pane("w5:p1", env={"FOO": "bar", "BAZ": "qux"})

        args = mock_subprocess.call_args[0][0]
        env_indices = [i for i, a in enumerate(args) if a == "--env"]
        assert len(env_indices) == 2
        env_values = [args[i + 1] for i in env_indices]
        assert "FOO=bar" in env_values
        assert "BAZ=qux" in env_values

    def test_send_keys_with_enter(self, mock_subprocess, backend):
        """send_keys with enter=True uses pane run (text + enter)."""
        backend.send_keys("w5:p1", "echo hello", enter=True)

        args = mock_subprocess.call_args[0][0]
        assert args[0:3] == ["herdr", "pane", "run"]
        assert "w5:p1" in args
        assert "echo hello" in args

    def test_send_keys_without_enter(self, mock_subprocess, backend):
        """send_keys with enter=False uses pane send-text only."""
        backend.send_keys("w5:p1", "partial text", enter=False)

        args = mock_subprocess.call_args[0][0]
        assert args[0:3] == ["herdr", "pane", "send-text"]
        assert "w5:p1" in args
        assert "partial text" in args

    def test_send_keys_special_keys(self, mock_subprocess, backend):
        """Special keys like C-c use pane send-keys."""
        backend.send_keys("w5:p1", "C-c", enter=False)

        args = mock_subprocess.call_args[0][0]
        assert args[0:3] == ["herdr", "pane", "send-keys"]
        assert "w5:p1" in args
        assert "C-c" in args

    def test_select_pane(self, mock_subprocess, backend):
        """select_pane is a no-op for herdr (splits use --no-focus)."""
        backend.select_pane("w5:p2")

        # No subprocess call should be made — it's a no-op
        mock_subprocess.assert_not_called()


# ---------------------------------------------------------------------------
# Session Configuration
# ---------------------------------------------------------------------------


class TestSessionConfiguration:
    """configure_session_defaults for herdr."""

    def test_configure_session_defaults(self, mock_subprocess, backend):
        """herdr has no runtime options; this is a best-effort metadata report."""
        backend.configure_session_defaults("study-decorators")

        # For herdr, configure_session_defaults is mostly a no-op or
        # sets workspace metadata. Verify it doesn't raise.
        # Implementation may call pane report-metadata or rename.
        # The key constraint: it must not raise.


# ---------------------------------------------------------------------------
# Client / Attach
# ---------------------------------------------------------------------------


class TestClientAttach:
    """switch_client and attach."""

    def test_switch_client(self, mock_subprocess, backend):
        """switch_client focuses the workspace (already inside herdr)."""
        # First: workspace list to find workspace_id from label
        mock_subprocess.side_effect = [
            _json_result(
                [
                    {"workspace_id": "w3", "label": "study-decorators"},
                ]
            ),
            _make_result(),
        ]
        backend.switch_client("study-decorators")

        # Should call workspace focus with the workspace_id
        focus_args = mock_subprocess.call_args_list[1][0][0]
        assert focus_args[0] == "herdr"
        assert "workspace" in focus_args
        assert "focus" in focus_args
        assert "w3" in focus_args

    def test_attach_calls_execvp(self, mock_subprocess, backend):
        """attach replaces the current process via os.execvp."""
        with patch("studyloop.herdr.os.execvp") as mock_execvp:
            backend.attach("study-decorators")
            mock_execvp.assert_called_once()
            call_args = mock_execvp.call_args[0]
            assert call_args[0] == "herdr"
            assert "herdr" in call_args[1]


# ---------------------------------------------------------------------------
# Process Introspection
# ---------------------------------------------------------------------------


class TestProcessIntrospection:
    """pane_has_child_process, is_zombie_session."""

    def test_pane_has_child_process_true(self, mock_subprocess, backend):
        """foreground_processes with entries → True."""
        mock_subprocess.return_value = _json_result(
            {
                "pid": 12345,
                "foreground_processes": [
                    {"pid": 12346, "argv": ["kiro-cli", "chat"], "cwd": "/tmp"}
                ],
                "cwd": "/Users/test",
            }
        )
        assert backend.pane_has_child_process("w5:p1") is True

        args = mock_subprocess.call_args[0][0]
        assert args[0:3] == ["herdr", "pane", "process-info"]
        assert "w5:p1" in args

    def test_pane_has_child_process_false(self, mock_subprocess, backend):
        """Empty foreground_processes → False."""
        mock_subprocess.return_value = _json_result(
            {
                "pid": 12345,
                "foreground_processes": [],
                "cwd": "/Users/test",
            }
        )
        assert backend.pane_has_child_process("w5:p1") is False

    def test_pane_shell_itself_is_not_a_child_process(self, mock_subprocess, backend):
        """herdr reports the pane shell as foreground; match tmux child semantics."""
        mock_subprocess.return_value = _json_result(
            {
                "process_info": {
                    "shell_pid": 42,
                    "foreground_processes": [{"pid": 42, "name": "zsh", "argv": ["-zsh"]}],
                }
            }
        )
        assert backend.pane_has_child_process("w5:p1") is False

    def test_workspace_panes_fall_back_to_pane_list_for_herdr_08(self, mock_subprocess, backend):
        """0.8.x workspace list has pane_count but no embedded pane IDs."""
        mock_subprocess.side_effect = [
            _json_result(
                {
                    "workspaces": [
                        {
                            "workspace_id": "w5",
                            "label": "study-python",
                            "pane_count": 2,
                        }
                    ]
                }
            ),
            _json_result(
                {
                    "panes": [
                        {"workspace_id": "w5", "pane_id": "w5:p1"},
                        {"workspace_id": "w5", "pane_id": "w5:p2"},
                        {"workspace_id": "other", "pane_id": "other:p1"},
                    ]
                }
            ),
        ]
        assert backend._get_workspace_panes("study-python") == ["w5:p1", "w5:p2"]
        pane_list_args = mock_subprocess.call_args_list[1][0][0]
        assert pane_list_args[1:3] == ["pane", "list"]

    def test_pane_has_child_process_error(self, mock_subprocess, backend):
        """Process-info failure → False (pane may be gone)."""
        mock_subprocess.side_effect = subprocess.CalledProcessError(
            1, ["herdr", "pane", "process-info"]
        )
        assert backend.pane_has_child_process("w5:p1") is False

    def test_is_zombie_session_true(self, mock_subprocess, backend):
        """Session with no children and old enough age → zombie."""
        # workspace list → find workspace
        # pane process-info → no foreground_processes
        mock_subprocess.side_effect = [
            # workspace list to find workspace + initial pane
            _json_result(
                [
                    {"workspace_id": "w9", "label": "study-old-topic", "panes": ["w9:p1"]},
                ]
            ),
            # pane process-info for the pane → no children
            _json_result(
                {
                    "pid": 99999,
                    "foreground_processes": [],
                    "cwd": "/tmp",
                }
            ),
        ]
        # Mock session_state to return an old started_at
        import time

        old_time = time.time() - 120  # 2 minutes ago
        with patch("studyloop.herdr._get_session_start_time", return_value=old_time):
            assert backend.is_zombie_session("study-old-topic", min_age_seconds=60.0) is True

    def test_is_zombie_session_false_has_children(self, mock_subprocess, backend):
        """Session with active children → not zombie."""
        mock_subprocess.side_effect = [
            _json_result(
                [
                    {"workspace_id": "w9", "label": "study-active", "panes": ["w9:p1"]},
                ]
            ),
            _json_result(
                {
                    "pid": 99999,
                    "foreground_processes": [{"pid": 99998, "argv": ["claude"], "cwd": "/tmp"}],
                    "cwd": "/tmp",
                }
            ),
        ]
        assert backend.is_zombie_session("study-active") is False

    def test_is_zombie_session_false_too_young(self, mock_subprocess, backend):
        """Session that's too new → not zombie (still starting)."""
        mock_subprocess.side_effect = [
            _json_result(
                [
                    {"workspace_id": "w9", "label": "study-new", "panes": ["w9:p1"]},
                ]
            ),
            _json_result(
                {
                    "pid": 99999,
                    "foreground_processes": [],
                    "cwd": "/tmp",
                }
            ),
        ]
        import time

        recent_time = time.time() - 10  # 10 seconds ago, below 60s threshold
        with patch("studyloop.herdr._get_session_start_time", return_value=recent_time):
            assert backend.is_zombie_session("study-new", min_age_seconds=60.0) is False

    def test_is_zombie_session_not_found(self, mock_subprocess, backend):
        """Session not found in workspace list → False."""
        mock_subprocess.return_value = _json_result([])
        assert backend.is_zombie_session("study-gone") is False


# ---------------------------------------------------------------------------
# Test Harness Support
# ---------------------------------------------------------------------------


class TestHarnessSupport:
    """capture_pane and wait_for_content."""

    def test_capture_pane(self, mock_subprocess, backend):
        mock_subprocess.return_value = _make_result(stdout="$ echo hello\nhello\n$ ")
        result = backend.capture_pane("w5:p1", lines=30)

        args = mock_subprocess.call_args[0][0]
        assert args[0:3] == ["herdr", "pane", "read"]
        assert "w5:p1" in args
        assert "--source" in args
        source_idx = args.index("--source")
        assert args[source_idx + 1] == "recent-unwrapped"
        assert "--lines" in args
        lines_idx = args.index("--lines")
        assert args[lines_idx + 1] == "30"
        assert result == "$ echo hello\nhello\n$ "

    def test_wait_for_content_success(self, mock_subprocess, backend):
        """Uses herdr wait output with --match and --timeout."""
        mock_subprocess.return_value = _json_result(
            {
                "output_matched": True,
                "read": {"text": "$ echo hello\nhello\n$ "},
            }
        )
        result = backend.wait_for_content("w5:p1", "hello", timeout_ms=5000)

        args = mock_subprocess.call_args[0][0]
        assert args[0:3] == ["herdr", "wait", "output"]
        assert "w5:p1" in args
        assert "--match" in args
        match_idx = args.index("--match")
        assert args[match_idx + 1] == "hello"
        assert "--timeout" in args
        timeout_idx = args.index("--timeout")
        assert args[timeout_idx + 1] == "5000"
        assert "hello" in result

    def test_wait_for_content_timeout(self, mock_subprocess, backend):
        """Timeout raises MultiplexerError."""
        from studyloop.multiplexer import MultiplexerError

        mock_subprocess.side_effect = subprocess.CalledProcessError(
            1,
            ["herdr", "wait", "output"],
            stderr="timed out waiting for match",
        )
        with pytest.raises(MultiplexerError, match=r"[Tt]imed out|wait"):
            backend.wait_for_content("w5:p1", "never-appears", timeout_ms=1000)

    def test_wait_for_content_regex(self, mock_subprocess, backend):
        """Pattern is passed with --regex flag."""
        mock_subprocess.return_value = _json_result(
            {
                "output_matched": True,
                "read": {"text": "line 1\nMATCHED_42\nline 3"},
            }
        )
        backend.wait_for_content("w5:p1", r"MATCHED_\d+", timeout_ms=3000)

        args = mock_subprocess.call_args[0][0]
        assert "--regex" in args


# ---------------------------------------------------------------------------
# Error Handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Explicit, typed failures for missing binary, server down, bad JSON."""

    def test_subprocess_called_process_error_raises_multiplexer_error(
        self, mock_subprocess, backend
    ):
        from studyloop.multiplexer import MultiplexerError

        mock_subprocess.side_effect = subprocess.CalledProcessError(
            1,
            ["herdr", "workspace", "create"],
            stderr="server not running",
        )
        with pytest.raises(MultiplexerError, match=r"server|herdr"):
            backend.create_session("study-fail")

    def test_subprocess_timeout_raises_multiplexer_error(self, mock_subprocess, backend):
        from studyloop.multiplexer import MultiplexerError

        mock_subprocess.side_effect = subprocess.TimeoutExpired(
            cmd=["herdr", "workspace", "create"], timeout=30
        )
        with pytest.raises(MultiplexerError, match=r"[Tt]imeout|timed out"):
            backend.create_session("study-timeout")

    def test_invalid_json_raises_multiplexer_error(self, mock_subprocess, backend):
        from studyloop.multiplexer import MultiplexerError

        mock_subprocess.return_value = _make_result(stdout="not json at all {{{")
        with pytest.raises(MultiplexerError, match=r"[Jj]SON|parse|response"):
            backend.create_session("study-badjson")

    def test_missing_key_in_json_raises_multiplexer_error(self, mock_subprocess, backend):
        from studyloop.multiplexer import MultiplexerError

        # workspace create response missing workspace_id
        mock_subprocess.return_value = _json_result({"tab_id": "w1:t1", "pane_id": "w1:p1"})
        with pytest.raises(MultiplexerError, match=r"workspace_id|missing|key"):
            backend.create_session("study-missingkey")

    def test_file_not_found_error_raises_multiplexer_error(self, mock_subprocess, backend):
        """Binary removed between is_available and actual call."""
        from studyloop.multiplexer import MultiplexerError

        mock_subprocess.side_effect = FileNotFoundError("herdr: No such file")
        with pytest.raises(MultiplexerError, match=r"herdr|not found|binary"):
            backend.create_session("study-gone")


# ---------------------------------------------------------------------------
# Integration tests (require real herdr binary)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestHerdrIntegration:
    """Real herdr binary tests. Skipped if herdr not available.

    SAFETY: Creates only throwaway workspaces and cleans them up.
    Never touches workspaces labelled 'StudyLoop' or 'Study'.
    """

    @pytest.fixture(autouse=True)
    def require_herdr(self):
        """Skip entire class if herdr is not on PATH."""
        import shutil

        if not shutil.which("herdr"):
            pytest.skip("herdr binary not available")

    @pytest.fixture()
    def real_backend(self):
        from studyloop.herdr import HerdrBackend

        return HerdrBackend()

    @pytest.fixture()
    def cleanup_workspace(self, real_backend):
        """Yield a list; append workspace IDs during test, cleanup after."""
        workspace_ids: list[str] = []
        yield workspace_ids
        for ws_id in workspace_ids:
            with contextlib.suppress(Exception):
                # Use raw subprocess to ensure cleanup even if backend is broken
                subprocess.run(
                    ["herdr", "workspace", "close", ws_id],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

    def test_create_and_close_workspace(self, real_backend, cleanup_workspace):
        """Create a workspace, verify it exists, close it."""
        ws_id = real_backend.create_session("study-test-probe-t2")
        cleanup_workspace.append(ws_id)

        assert real_backend.session_exists("study-test-probe-t2")
        assert real_backend.kill_session("study-test-probe-t2") is True
        cleanup_workspace.clear()  # Already cleaned
        assert not real_backend.session_exists("study-test-probe-t2")

    def test_split_and_read_pane(self, real_backend, cleanup_workspace):
        """Split a pane, send text, read it back."""
        ws_id = real_backend.create_session("study-test-split-t2")
        cleanup_workspace.append(ws_id)

        # Get the initial pane_id from workspace create
        # (workspace_id returned, initial pane is ws_id + pane suffix)
        # We need to list panes — use session_exists to verify first
        assert real_backend.session_exists("study-test-split-t2")

        # The workspace_id IS the session handle. For split, we need pane_id.
        # workspace create returns workspace_id; initial pane format is opaque.
        # Use capture_pane on the workspace-level to read.
