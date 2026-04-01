"""Integration tests for studyctl study — real tmux sessions with a mock agent.

These tests create actual tmux sessions, verify pane layout, sidebar
content, IPC file updates, and cleanup behaviour. They use a mock agent
script instead of Claude Code (fast, free, deterministic).

Requires: tmux installed. Skipped if tmux is not available.

Run with: uv run pytest tests/test_study_integration.py -v
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

# Skip entire module if tmux is not installed
pytestmark = pytest.mark.skipif(
    not shutil.which("tmux"),
    reason="tmux not installed",
)

# Test timeout — how long to wait for async operations (seconds)
POLL_TIMEOUT = 10
POLL_INTERVAL = 0.5


def _tmux(*args: str) -> subprocess.CompletedProcess[str]:
    """Run a tmux command."""
    return subprocess.run(
        ["tmux", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _wait_for(predicate, timeout=POLL_TIMEOUT, interval=POLL_INTERVAL, desc="condition"):
    """Poll until predicate returns True or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    msg = f"Timed out waiting for {desc} after {timeout}s"
    raise TimeoutError(msg)


def _capture_pane(pane_id: str) -> str:
    """Capture the visible content of a tmux pane."""
    result = _tmux("capture-pane", "-t", pane_id, "-p")
    return result.stdout


def _session_exists(name: str) -> bool:
    return _tmux("has-session", "-t", name).returncode == 0


@pytest.fixture()
def mock_agent_script(tmp_path):
    """Create a mock agent script that simulates Claude's behaviour."""
    script = tmp_path / "mock-agent.sh"
    # Use the full uv run path so studyctl is found regardless of PATH
    project_dir = Path(__file__).parent.parent.parent.parent
    studyctl_cmd = f"uv run --project {project_dir} studyctl"
    script.write_text(
        textwrap.dedent(f"""\
        #!/bin/bash
        # Mock agent: logs topics, then waits for C-c
        echo "Mock agent started"
        echo "Persona file: $1"

        # Simulate agent logging topics after a brief delay
        sleep 2
        {studyctl_cmd} topic "Closures" --status learning --note "exploring basics"
        sleep 1
        {studyctl_cmd} topic "First-class functions" --status win --note "understood"
        sleep 1
        {studyctl_cmd} park "How do generators relate to closures?"

        echo "Mock agent ready — waiting for exit signal"
        # Wait indefinitely (C-c or kill will terminate)
        trap 'echo "Mock agent exiting"; exit 0' INT TERM
        while true; do sleep 1; done
    """)
    )
    script.chmod(0o755)
    return str(script)


@pytest.fixture()
def clean_session_state():
    """Ensure no stale session state before/after test."""
    _cleanup_ipc()
    yield
    _cleanup_ipc()


def _cleanup_ipc():
    """Remove IPC files and kill any study tmux sessions."""
    config_dir = Path.home() / ".config" / "studyctl"
    for f in [
        "session-state.json",
        "session-topics.md",
        "session-parking.md",
        "session-oneline.txt",
    ]:
        (config_dir / f).unlink(missing_ok=True)
    # Kill any study sessions from tests
    result = _tmux("list-sessions", "-F", "#{session_name}")
    if result.returncode == 0:
        for name in result.stdout.strip().splitlines():
            if name.startswith("study-"):
                _tmux("kill-session", "-t", name)


@pytest.fixture()
def study_session(mock_agent_script, clean_session_state):
    """Start a study session with the mock agent.

    Uses STUDYCTL_TEST_AGENT_CMD env var to override the agent command.
    The study orchestrator checks this before using the agent registry.
    """
    env = {**os.environ}
    env.pop("TMUX", None)  # Pretend we're not in tmux
    env["STUDYCTL_TEST_AGENT_CMD"] = f"bash {mock_agent_script} {{persona_file}}"

    # Start study in background (it will try to tmux attach via execvp,
    # which will fail since we're not in a terminal — but the tmux session
    # and panes will be created before that point)
    subprocess.run(
        ["uv", "run", "studyctl", "study", "Integration Test", "--energy", "5"],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )

    # Wait for state file to appear
    state_file = Path.home() / ".config" / "studyctl" / "session-state.json"
    _wait_for(state_file.exists, desc="session-state.json")

    state = json.loads(state_file.read_text())
    session_name = state.get("tmux_session", "")

    _wait_for(lambda: _session_exists(session_name), desc=f"tmux session {session_name}")

    yield {
        "session_name": session_name,
        "state": state,
        "state_file": state_file,
        "main_pane": state.get("tmux_main_pane"),
        "sidebar_pane": state.get("tmux_sidebar_pane"),
    }

    # Cleanup
    if _session_exists(session_name):
        _tmux("kill-session", "-t", session_name)
    _cleanup_ipc()


class TestTmuxSessionCreation:
    """Test that studyctl study creates the right tmux layout."""

    def test_session_created(self, study_session):
        assert _session_exists(study_session["session_name"])

    def test_two_panes(self, study_session):
        result = _tmux(
            "list-panes",
            "-t",
            study_session["session_name"],
            "-F",
            "#{pane_id}",
        )
        panes = result.stdout.strip().splitlines()
        assert len(panes) == 2, f"Expected 2 panes, got {len(panes)}: {panes}"

    def test_state_file_written(self, study_session):
        state = study_session["state"]
        assert state["topic"] == "Integration Test"
        assert state["energy"] == 5
        assert state["tmux_session"]
        assert state["tmux_main_pane"]
        assert state["tmux_sidebar_pane"]


class TestSidebarUpdates:
    """Test that studyctl topic populates the sidebar."""

    def test_topics_appear_in_ipc_file(self, study_session):
        topics_file = Path.home() / ".config" / "studyctl" / "session-topics.md"

        # Wait for mock agent to call studyctl topic (takes ~4 seconds)
        _wait_for(
            lambda: topics_file.exists() and topics_file.stat().st_size > 0,
            timeout=15,
            desc="topics to appear in IPC file",
        )

        content = topics_file.read_text()
        assert "Closures" in content
        assert "status:learning" in content

    def test_win_logged(self, study_session):
        topics_file = Path.home() / ".config" / "studyctl" / "session-topics.md"

        _wait_for(
            lambda: topics_file.exists() and "First-class functions" in topics_file.read_text(),
            timeout=15,
            desc="win topic in IPC file",
        )

        content = topics_file.read_text()
        assert "status:win" in content

    def test_parking_logged(self, study_session):
        parking_file = Path.home() / ".config" / "studyctl" / "session-parking.md"

        _wait_for(
            lambda: parking_file.exists() and parking_file.stat().st_size > 0,
            timeout=15,
            desc="parked topic in IPC file",
        )

        content = parking_file.read_text()
        assert "generators" in content.lower()

    def test_sidebar_pane_has_content(self, study_session):
        """Check that the sidebar pane shows the Textual app (not a shell prompt)."""
        sidebar = study_session["sidebar_pane"]

        # Wait for sidebar to start rendering
        _wait_for(
            lambda: (
                "pause" in _capture_pane(sidebar).lower()
                or "quit" in _capture_pane(sidebar).lower()
            ),
            timeout=10,
            desc="sidebar Textual app to render",
        )


class TestCleanup:
    """Test session cleanup on agent exit."""

    @pytest.mark.xfail(reason="Wrapper cleanup depends on Python PATH in tmux pane")
    def test_agent_exit_triggers_cleanup(self, study_session):
        main_pane = study_session["main_pane"]
        state_file = study_session["state_file"]

        # Send C-c to agent pane — triggers the wrapper cleanup
        _tmux("send-keys", "-t", main_pane, "C-c")

        # Wait for the state file to be marked as ended or cleared.
        # The tmux session may or may not die (depends on whether
        # switch_client(":{previous}") succeeds — no previous in tests).
        _wait_for(
            lambda: not state_file.exists() or "ended" in state_file.read_text(),
            timeout=15,
            desc="state file cleared or marked ended",
        )
