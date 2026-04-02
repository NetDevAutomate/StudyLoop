"""StudySession — high-level test harness for study command lifecycle.

Wraps TmuxHarness with study-specific operations and assertions.
Designed as a context manager for automatic cleanup.

Usage::

    with StudySession(tmp_path) as session:
        session.start("Python Decorators", energy=7)
        session.assert_agent_running()
        session.assert_sidebar_running()
        session.end_via_Q()
        session.assert_session_ended()
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .agents import long_running_agent
from .tmux import TmuxHarness

# IPC file locations (mirrors studyctl.session_state)
CONFIG_DIR = Path.home() / ".config" / "studyctl"
STATE_FILE = CONFIG_DIR / "session-state.json"
TOPICS_FILE = CONFIG_DIR / "session-topics.md"
PARKING_FILE = CONFIG_DIR / "session-parking.md"
ONELINE_FILE = CONFIG_DIR / "session-oneline.txt"


class StudySession:
    """High-level test harness for studyctl study sessions.

    Manages the full lifecycle: start → interact → assert → end → cleanup.
    """

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.tmux = TmuxHarness()
        self._session_name: str | None = None
        self._main_pane: str | None = None
        self._sidebar_pane: str | None = None
        self._started = False

    def __enter__(self) -> StudySession:
        return self

    def __exit__(self, *exc) -> None:
        self.cleanup()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def session_name(self) -> str | None:
        """tmux session name (populated after start)."""
        return self._session_name

    @property
    def main_pane(self) -> str | None:
        """Main (agent) pane ID."""
        return self._main_pane

    @property
    def sidebar_pane(self) -> str | None:
        """Sidebar pane ID."""
        return self._sidebar_pane

    @property
    def state(self) -> dict:
        """Read the current session state from the IPC file."""
        try:
            return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
        except (json.JSONDecodeError, OSError):
            return {}

    # ------------------------------------------------------------------
    # Lifecycle operations
    # ------------------------------------------------------------------

    def start(
        self,
        topic: str,
        *,
        energy: int = 5,
        agent_cmd: str | None = None,
    ) -> None:
        """Start a study session and wait for it to be fully ready.

        Args:
            topic: Study topic.
            energy: Energy level 1-10.
            agent_cmd: Override agent command. Defaults to long_running_agent.
        """
        if agent_cmd is None:
            agent_cmd = long_running_agent(self.tmp_path)

        # Clean any prior state
        self._clean_ipc_files()

        # Build and run the studyctl study command
        env = os.environ.copy()
        env["STUDYCTL_TEST_AGENT_CMD"] = agent_cmd
        # Remove TMUX env var so studyctl uses attach (not switch-client)
        env.pop("TMUX", None)
        env.pop("TMUX_PANE", None)

        subprocess.run(
            [
                sys.executable,
                "-m",
                "studyctl.cli",
                "study",
                topic,
                "--energy",
                str(energy),
                "--agent",
                "claude",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

        # studyctl study with attach replaces the process via execvp,
        # but in tests it won't actually attach (no terminal).
        # The session should still be created in detached mode.

        # Wait for the state file to appear with a study_session_id
        self.tmux.wait_for(
            lambda: self.state.get("study_session_id") is not None,
            timeout=10,
            msg="session state file not written",
        )

        state = self.state
        self._session_name = state.get("tmux_session")
        self._main_pane = state.get("tmux_main_pane")
        self._sidebar_pane = state.get("tmux_sidebar_pane")

        if self._session_name:
            self.tmux.track_session(self._session_name)

        # Wait for the tmux session to be ready with both panes
        self.tmux.wait_for(
            lambda: self._session_name is not None and self.tmux.session_exists(self._session_name),
            timeout=10,
            msg="tmux session not created",
        )

        # Wait for both panes to exist
        self.tmux.wait_for(
            lambda: len(self.tmux.list_panes(self._session_name)) >= 2,
            timeout=10,
            msg="expected 2 panes (agent + sidebar)",
        )

        # Refresh pane IDs from state (they may have been written after split)
        state = self.state
        self._main_pane = state.get("tmux_main_pane")
        self._sidebar_pane = state.get("tmux_sidebar_pane")
        self._started = True

    def resume(self) -> None:
        """Run --resume and wait for the session to be ready."""
        env = os.environ.copy()
        # Use long_running_agent for rebuilt sessions
        env["STUDYCTL_TEST_AGENT_CMD"] = long_running_agent(self.tmp_path)
        env.pop("TMUX", None)
        env.pop("TMUX_PANE", None)

        subprocess.run(
            [sys.executable, "-m", "studyctl.cli", "study", "--resume"],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

        # Wait for session to be ready
        self.tmux.wait_for(
            lambda: self.state.get("mode") not in (None, "ended"),
            timeout=10,
            msg="session not resumed (mode still ended or missing)",
        )

        state = self.state
        self._session_name = state.get("tmux_session")
        self._main_pane = state.get("tmux_main_pane")
        self._sidebar_pane = state.get("tmux_sidebar_pane")

        if self._session_name:
            self.tmux.track_session(self._session_name)

    def end_via_q(self, *, timeout: float = 15) -> None:
        """Press Q in the sidebar pane and wait for the session to end."""
        assert self._sidebar_pane, "No sidebar pane — was start() called?"
        self.tmux.send_keys(self._sidebar_pane, "Q")

        # Wait for the tmux session to be destroyed
        self.tmux.wait_for(
            lambda: (
                self._session_name is not None and not self.tmux.session_exists(self._session_name)
            ),
            timeout=timeout,
            msg="tmux session not killed after Q",
        )
        self._started = False

    def end_via_cli(self) -> None:
        """Run studyctl study --end."""
        env = os.environ.copy()
        env.pop("TMUX", None)

        subprocess.run(
            [sys.executable, "-m", "studyctl.cli", "study", "--end"],
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )
        self._started = False

    def kill_agent(self) -> None:
        """Kill the agent process (simulate crash). Leaves tmux session alive."""
        assert self._main_pane, "No main pane — was start() called?"
        # Get the pane PID and kill its children (the agent)
        result = self.tmux._tmux("display-message", "-t", self._main_pane, "-p", "#{pane_pid}")
        if result.returncode == 0:
            pid = result.stdout.strip()
            # Kill children of the pane shell (the agent process)
            subprocess.run(["pkill", "-P", pid], capture_output=True)

    # ------------------------------------------------------------------
    # Assertions
    # ------------------------------------------------------------------

    def assert_agent_running(self, *, timeout: float = 10) -> None:
        """Assert the agent pane has a running child process."""
        assert self._main_pane, "No main pane — was start() called?"
        self.tmux.wait_for(
            lambda: self.tmux.pane_has_children(self._main_pane),
            timeout=timeout,
            msg="agent pane has no child processes (agent not running)",
        )

    def assert_sidebar_running(self, *, timeout: float = 10) -> None:
        """Assert the sidebar pane process is alive.

        The Textual sidebar runs as a direct Python process (no children),
        so we check that the pane's process hasn't exited.
        """
        assert self._sidebar_pane, "No sidebar pane — was start() called?"
        self.tmux.wait_for(
            lambda: self.tmux.pane_process_alive(self._sidebar_pane),
            timeout=timeout,
            msg="sidebar pane process is dead",
        )

    def assert_pane_contains(
        self,
        pane: str,
        pattern: str,
        *,
        timeout: float = 15,
    ) -> str:
        """Assert a pane's content matches a regex pattern. Returns content."""
        pane_id = self._resolve_pane(pane)
        return self.tmux.wait_for_pane_content(pane_id, pattern, timeout=timeout)

    def assert_session_ended(self) -> None:
        """Assert the session state is ended and tmux session is gone."""
        state = self.state
        assert state.get("mode") == "ended", (
            f"Expected mode='ended', got mode={state.get('mode')!r}"
        )
        if self._session_name:
            assert not self.tmux.session_exists(self._session_name), (
                f"tmux session {self._session_name!r} still exists"
            )

    def assert_state_has(self, **expected: object) -> None:
        """Assert specific keys/values exist in the session state."""
        state = self.state
        for key, value in expected.items():
            assert key in state, f"Key {key!r} not in session state"
            if value is not None:
                assert state[key] == value, f"state[{key!r}] = {state[key]!r}, expected {value!r}"

    def assert_pane_count(self, expected: int) -> None:
        """Assert the number of panes in the tmux session."""
        assert self._session_name, "No session — was start() called?"
        panes = self.tmux.list_panes(self._session_name)
        assert len(panes) == expected, f"Expected {expected} panes, got {len(panes)}: {panes}"

    def assert_no_study_sessions(self) -> None:
        """Assert no tmux sessions with 'study-' prefix exist."""
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return  # No tmux server = no sessions = pass
        study_sessions = [n for n in result.stdout.strip().splitlines() if n.startswith("study-")]
        assert not study_sessions, f"Stale study sessions remain: {study_sessions}"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_pane(self, pane: str) -> str:
        """Resolve 'main' / 'sidebar' to actual pane IDs."""
        if pane == "main":
            assert self._main_pane, "No main pane"
            return self._main_pane
        if pane == "sidebar":
            assert self._sidebar_pane, "No sidebar pane"
            return self._sidebar_pane
        return pane  # assume raw pane ID

    def _clean_ipc_files(self) -> None:
        """Remove stale IPC files from a previous test."""
        for f in (STATE_FILE, TOPICS_FILE, PARKING_FILE, ONELINE_FILE):
            if f.exists():
                f.unlink()

    def cleanup(self) -> None:
        """Kill any managed tmux sessions and clean IPC files."""
        self.tmux.cleanup()
        self._clean_ipc_files()
        self._started = False
