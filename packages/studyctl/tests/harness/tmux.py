"""TmuxHarness — core tmux control with reliable polling.

All tmux interaction for tests goes through this class.
No fixed sleeps — everything uses wait_for() polling.
"""

from __future__ import annotations

import re
import subprocess
import time


class TmuxHarness:
    """Low-level tmux control for integration tests."""

    def __init__(self) -> None:
        self._managed_sessions: list[str] = []

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    @staticmethod
    def wait_for(
        predicate: callable,
        *,
        timeout: float = 15,
        interval: float = 0.5,
        msg: str = "",
    ) -> None:
        """Poll until predicate returns True or timeout expires.

        Raises TimeoutError with a descriptive message on failure.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(interval)
        raise TimeoutError(f"Timed out after {timeout}s: {msg or 'condition not met'}")

    @staticmethod
    def wait_for_value(
        func: callable,
        *,
        timeout: float = 15,
        interval: float = 0.5,
        msg: str = "",
    ):
        """Poll until func returns a truthy value. Returns that value."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = func()
            if result:
                return result
            time.sleep(interval)
        raise TimeoutError(f"Timed out after {timeout}s: {msg or 'no truthy value returned'}")

    # ------------------------------------------------------------------
    # tmux commands
    # ------------------------------------------------------------------

    @staticmethod
    def _tmux(*args: str) -> subprocess.CompletedProcess[str]:
        """Run a tmux command."""
        return subprocess.run(
            ["tmux", *args],
            capture_output=True,
            text=True,
        )

    def session_exists(self, name: str) -> bool:
        """Check if a tmux session exists."""
        result = self._tmux("has-session", "-t", name)
        return result.returncode == 0

    def kill_session(self, name: str) -> None:
        """Kill a tmux session and wait until it's gone."""
        self._tmux("kill-session", "-t", name)
        for _ in range(20):
            if not self.session_exists(name):
                return
            time.sleep(0.1)
        # Last resort
        self._tmux("kill-session", "-t", name)
        time.sleep(0.3)

    def list_panes(self, session: str) -> list[dict[str, str]]:
        """List panes in a session with their IDs and commands."""
        result = self._tmux(
            "list-panes",
            "-t",
            session,
            "-F",
            "#{pane_id}|#{pane_current_command}|#{pane_pid}",
        )
        if result.returncode != 0:
            return []
        panes = []
        for line in result.stdout.strip().splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                panes.append(
                    {
                        "pane_id": parts[0],
                        "command": parts[1],
                        "pid": parts[2],
                    }
                )
        return panes

    def capture_pane(self, pane_id: str, lines: int = 50) -> str:
        """Capture visible content from a tmux pane."""
        result = self._tmux("capture-pane", "-t", pane_id, "-p", "-S", f"-{lines}")
        return result.stdout if result.returncode == 0 else ""

    def wait_for_pane_content(
        self,
        pane_id: str,
        pattern: str,
        *,
        timeout: float = 15,
        lines: int = 50,
    ) -> str:
        """Poll pane content until pattern is found. Returns the matching content."""
        compiled = re.compile(pattern)

        def _check() -> str | None:
            content = self.capture_pane(pane_id, lines=lines)
            if compiled.search(content):
                return content
            return None

        return self.wait_for_value(
            _check,
            timeout=timeout,
            msg=f"pattern {pattern!r} not found in pane {pane_id}",
        )

    def pane_has_children(self, pane_id: str) -> bool:
        """Check if a pane's process has child processes (agent is running)."""
        result = self._tmux("display-message", "-t", pane_id, "-p", "#{pane_pid}")
        if result.returncode != 0:
            return False
        pid = result.stdout.strip()
        if not pid:
            return False
        check = subprocess.run(
            ["pgrep", "-P", pid],
            capture_output=True,
            text=True,
        )
        return check.returncode == 0

    def pane_process_alive(self, pane_id: str) -> bool:
        """Check if the pane's process is still running (not exited to shell).

        Unlike pane_has_children, this checks the process itself is alive.
        Useful for processes like the Textual sidebar that don't spawn children.
        """
        result = self._tmux("display-message", "-t", pane_id, "-p", "#{pane_dead}")
        if result.returncode != 0:
            return False
        # #{pane_dead} is "1" if the pane's process has exited, "" otherwise
        return result.stdout.strip() != "1"

    def send_keys(self, pane_id: str, keys: str, *, enter: bool = False) -> None:
        """Send keys to a tmux pane."""
        args = ["send-keys", "-t", pane_id, keys]
        if enter:
            args.append("Enter")
        self._tmux(*args)

    def kill_all_study_sessions(self) -> None:
        """Kill all tmux sessions with study- prefix."""
        result = self._tmux("list-sessions", "-F", "#{session_name}")
        if result.returncode != 0:
            return
        for name in result.stdout.strip().splitlines():
            if name.startswith("study-"):
                self.kill_session(name)

    def track_session(self, name: str) -> None:
        """Register a session for automatic cleanup."""
        self._managed_sessions.append(name)

    def cleanup(self) -> None:
        """Kill all tracked sessions."""
        for name in self._managed_sessions:
            if self.session_exists(name):
                self.kill_session(name)
        self._managed_sessions.clear()
