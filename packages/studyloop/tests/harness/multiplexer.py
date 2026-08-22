"""MultiplexerHarness — backend-agnostic test harness for multiplexer journeys.

Wraps the Multiplexer Protocol methods with test-friendly helpers: polling,
managed session tracking, automatic cleanup, and assertion methods.

Parameterised tests create either a tmux-backed or herdr-backed harness
and run the SAME journey against both, proving feature parity.

Usage::

    @pytest.fixture(params=["tmux", "herdr"])
    def mux(request, tmp_path):
        with MultiplexerHarness.from_backend_name(request.param) as h:
            yield h

    def test_session_starts(mux, tmp_path):
        mux.create_session("test-session", cwd=str(tmp_path))
        assert mux.session_exists("test-session")
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pexpect

if TYPE_CHECKING:
    from studyloop.multiplexer import Multiplexer

# IPC file locations (mirrors studyloop.session_state)
CONFIG_DIR = Path.home() / ".config" / "studyloop"
STATE_FILE = CONFIG_DIR / "session-state.json"
TOPICS_FILE = CONFIG_DIR / "session-topics.md"
PARKING_FILE = CONFIG_DIR / "session-parking.md"
ONELINE_FILE = CONFIG_DIR / "session-oneline.txt"


class MultiplexerHarness:
    """Backend-agnostic test harness for multiplexer integration journeys.

    Wraps a Multiplexer Protocol instance with cleanup tracking, polling
    helpers, and study-session lifecycle methods.
    """

    def __init__(self, backend: Multiplexer) -> None:
        self.backend = backend
        self._managed_sessions: list[str] = []
        self._backend_name: str = type(backend).__name__
        self._pty_child: pexpect.spawn | None = None

    @classmethod
    def from_backend_name(cls, name: str) -> MultiplexerHarness:
        """Create a harness from a backend name ('tmux' or 'herdr').

        Raises RuntimeError if the backend is not available.
        """
        from studyloop.multiplexer import TmuxBackend

        if name == "tmux":
            backend = TmuxBackend()
            if not backend.is_available():
                raise RuntimeError("tmux is not available")
            return cls(backend)
        elif name == "herdr":
            from studyloop.herdr import HerdrBackend

            backend = HerdrBackend()
            if not backend.is_available():
                raise RuntimeError("herdr is not available")
            return cls(backend)
        else:
            raise ValueError(f"Unknown backend: {name!r}")

    def __enter__(self) -> MultiplexerHarness:
        return self

    def __exit__(self, *exc: object) -> None:
        self.cleanup_all()

    # ------------------------------------------------------------------
    # Backend info
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Human-readable backend name ('TmuxBackend' or 'HerdrBackend')."""
        return self._backend_name

    @property
    def is_tmux(self) -> bool:
        from studyloop.multiplexer import TmuxBackend

        return isinstance(self.backend, TmuxBackend)

    @property
    def is_herdr(self) -> bool:
        from studyloop.herdr import HerdrBackend

        return isinstance(self.backend, HerdrBackend)

    # ------------------------------------------------------------------
    # Session lifecycle (with tracking)
    # ------------------------------------------------------------------

    def create_session(
        self,
        name: str,
        *,
        command: str | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        """Create a session and track it for cleanup. Returns the pane_id."""
        pane_id = self.backend.create_session(name, command=command, cwd=cwd, env=env)
        self._managed_sessions.append(name)
        return pane_id

    def split_pane(
        self,
        target: str,
        *,
        direction: str = "right",
        size: int = 30,
        percentage: bool = False,
        command: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        """Split a pane. Returns the new pane_id."""
        return self.backend.split_pane(
            target,
            direction=direction,
            size=size,
            percentage=percentage,
            command=command,
            env=env,
        )

    def session_exists(self, name: str) -> bool:
        return self.backend.session_exists(name)

    def kill_session(self, name: str) -> bool:
        result = self.backend.kill_session(name)
        if name in self._managed_sessions:
            self._managed_sessions.remove(name)
        return result

    def send_keys(self, target: str, keys: str, *, enter: bool = True) -> None:
        self.backend.send_keys(target, keys, enter=enter)

    def select_pane(self, target: str) -> None:
        self.backend.select_pane(target)

    def capture_pane(self, pane_id: str, lines: int = 50) -> str:
        return self.backend.capture_pane(pane_id, lines=lines)

    def pane_has_children(self, pane_id: str) -> bool:
        return self.backend.pane_has_child_process(pane_id)

    def configure_session_defaults(self, session: str) -> None:
        self.backend.configure_session_defaults(session)

    def list_study_sessions(self) -> list[str]:
        return self.backend.list_study_sessions()

    def kill_all_study_sessions(self, current: str | None = None) -> None:
        self.backend.kill_all_study_sessions(current)
        # Remove from tracked
        self._managed_sessions = [s for s in self._managed_sessions if s == current]

    # ------------------------------------------------------------------
    # Polling helpers
    # ------------------------------------------------------------------

    @staticmethod
    def wait_for(
        predicate: callable,
        *,
        timeout: float = 15,
        interval: float = 0.5,
        msg: str = "",
    ) -> None:
        """Poll until predicate returns True or timeout expires."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(interval)
        raise TimeoutError(f"Timed out after {timeout}s: {msg or 'condition not met'}")

    def wait_for_pane_content(
        self,
        pane_id: str,
        pattern: str,
        *,
        timeout: float = 15,
    ) -> str:
        """Poll pane content until regex pattern matches. Returns content."""
        compiled = re.compile(pattern)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            content = self.capture_pane(pane_id)
            if compiled.search(content):
                return content
            time.sleep(0.5)
        raise TimeoutError(f"Pattern {pattern!r} not found in pane {pane_id} after {timeout}s")

    def wait_for_session(self, name: str, *, timeout: float = 15) -> None:
        """Wait until a session exists."""
        self.wait_for(
            lambda: self.session_exists(name),
            timeout=timeout,
            msg=f"session {name!r} never appeared",
        )

    def wait_for_session_gone(self, name: str, *, timeout: float = 15) -> None:
        """Wait until a session no longer exists."""
        self.wait_for(
            lambda: not self.session_exists(name),
            timeout=timeout,
            msg=f"session {name!r} still exists",
        )

    # ------------------------------------------------------------------
    # Study-session lifecycle (high-level, via CLI subprocess)
    # ------------------------------------------------------------------

    def start_study_session(
        self,
        topic: str,
        *,
        energy: int = 5,
        agent_cmd: str | None = None,
        backend_env: str | None = None,
    ) -> dict:
        """Start a study session via CLI and wait for state file.

        For herdr, delegates to start_study_session_pty (needs a real terminal).
        For tmux, uses subprocess.run (tmux attach fails gracefully).

        Returns the session state dict (parsed from session-state.json).
        """
        if agent_cmd is None:
            raise ValueError("agent_cmd required (pass long_running_agent(tmp_path))")

        # herdr needs a real PTY (os.execvp launches the TUI)
        if self.is_herdr:
            return self.start_study_session_pty(topic, energy=energy, agent_cmd=agent_cmd)

        self._clean_ipc_files()

        env = os.environ.copy()
        env["STUDYLOOP_TEST_AGENT_CMD"] = agent_cmd
        # Remove multiplexer env vars so we go through real attach flow
        env.pop("TMUX", None)
        env.pop("TMUX_PANE", None)
        env.pop("HERDR_ENV", None)

        # Set the multiplexer backend
        if backend_env:
            env["STUDYLOOP_MULTIPLEXER"] = backend_env
        elif self.is_herdr:
            env["STUDYLOOP_MULTIPLEXER"] = "herdr"
        else:
            env["STUDYLOOP_MULTIPLEXER"] = "tmux"

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "studyloop.cli",
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

        # Wait for state file
        self.wait_for(
            lambda: STATE_FILE.exists() and self._read_state().get("study_session_id"),
            timeout=15,
            msg=f"session state not written (exit={result.returncode}, "
            f"stderr={result.stderr[-200:]!r})",
        )

        state = self._read_state()
        session_name = state.get("mux_session") or state.get("tmux_session")
        if session_name:
            self._managed_sessions.append(session_name)
        return state

    def end_study_via_cli(self, *, backend_env: str | None = None) -> None:
        """Run `studyloop study --end` from a separate process.

        For herdr: kills the PTY child (herdr TUI) first so the workspace
        isn't held open by a connected client.
        """
        # Kill the PTY child before ending — herdr's TUI holds the workspace open
        self.kill_pty_child()

        env = os.environ.copy()
        env.pop("TMUX", None)
        env.pop("HERDR_ENV", None)

        if backend_env:
            env["STUDYLOOP_MULTIPLEXER"] = backend_env
        elif self.is_herdr:
            env["STUDYLOOP_MULTIPLEXER"] = "herdr"
        else:
            env["STUDYLOOP_MULTIPLEXER"] = "tmux"

        subprocess.run(
            [sys.executable, "-m", "studyloop.cli", "study", "--end"],
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )

    # ------------------------------------------------------------------
    # PTY-based study session lifecycle (herdr TUI needs a real terminal)
    # ------------------------------------------------------------------

    def start_study_session_pty(
        self,
        topic: str,
        *,
        energy: int = 5,
        agent_cmd: str | None = None,
    ) -> dict:
        """Start a study session via pexpect PTY for backends that need a terminal.

        herdr's attach flow uses os.execvp("herdr", ["herdr"]) which requires
        a real TTY. pexpect allocates a PTY so herdr's TUI can launch.

        The flow:
        1. pexpect spawns `python -m studyloop.cli study <topic>`
        2. The CLI creates the workspace, panes, writes state file
        3. os.execvp replaces the subprocess with herdr TUI (runs in the PTY)
        4. We wait for the state file, then return — herdr TUI is alive in _pty_child

        Returns the session state dict.
        """
        if agent_cmd is None:
            raise ValueError("agent_cmd required (pass long_running_agent(tmp_path))")

        self._clean_ipc_files()

        # Ensure no stale study workspaces from prior tests
        try:
            stale = self.backend.list_study_sessions()
            for name in stale:
                self.backend.kill_session(name)
            if stale:
                time.sleep(0.5)  # Let herdr process the closes
        except Exception:
            pass

        env: dict[str, str] = dict(os.environ)
        env["STUDYLOOP_TEST_AGENT_CMD"] = agent_cmd
        env["STUDYLOOP_MULTIPLEXER"] = "herdr"
        # Strip multiplexer env vars so the CLI goes through the real attach path
        env.pop("TMUX", None)
        env.pop("TMUX_PANE", None)
        env.pop("HERDR_ENV", None)

        cmd = f"{sys.executable} -m studyloop.cli study '{topic}' --energy {energy} --agent claude"

        self._pty_child = pexpect.spawn(
            cmd,
            env=cast("os._Environ[str]", env),
            timeout=30,
            encoding="utf-8",
        )

        # Wait for the state file to be FULLY written (study_session_id AND pane info).
        # The CLI writes state in two phases:
        #   1. study_session_id, topic, energy, etc.
        #   2. mux_session, mux_main_pane, mux_sidebar_pane (after workspace creation)
        # We need phase 2 to be complete.
        def _state_fully_written() -> bool:
            if not STATE_FILE.exists():
                return False
            s = self._read_state()
            return bool(s.get("study_session_id") and s.get("mux_main_pane"))

        try:
            self.wait_for(_state_fully_written, timeout=20, msg="")
        except TimeoutError:
            # Capture PTY output for diagnostics
            import contextlib

            child_output = ""
            if self._pty_child:
                with contextlib.suppress(Exception):
                    self._pty_child.expect(pexpect.TIMEOUT, timeout=0.1)
                before = self._pty_child.before if isinstance(self._pty_child.before, str) else ""
                child_output = before
            partial_state = self._read_state() if STATE_FILE.exists() else {}
            raise TimeoutError(
                f"session state not fully written via PTY spawn. "
                f"Partial state keys: {list(partial_state.keys())}. "
                f"PTY output tail: {child_output[-300:]!r}. "
                f"Child alive: {self._pty_child.isalive() if self._pty_child else 'N/A'}"
            ) from None

        state = self._read_state()
        session_name = state.get("mux_session") or state.get("tmux_session")
        if session_name:
            self._managed_sessions.append(session_name)
        return state

    def kill_pty_child(self) -> None:
        """Kill the pexpect PTY child (herdr TUI) if alive."""
        child = getattr(self, "_pty_child", None)
        if child is not None and child.isalive():
            child.close(force=True)
        self._pty_child = None

    # ------------------------------------------------------------------
    # State file helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_state() -> dict:
        """Read session-state.json."""
        try:
            if STATE_FILE.exists():
                return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
        return {}

    @staticmethod
    def _clean_ipc_files() -> None:
        """Remove IPC files from prior test."""
        for f in (STATE_FILE, TOPICS_FILE, PARKING_FILE, ONELINE_FILE):
            f.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup_all(self) -> None:
        """Kill all tracked sessions, PTY children, and clean IPC files.

        Also kills ANY stale study-* sessions to prevent test contamination.
        """
        # Kill PTY child first (herdr TUI) so it doesn't interfere with workspace cleanup
        self.kill_pty_child()
        for name in list(self._managed_sessions):
            try:
                if self.backend.session_exists(name):
                    self.backend.kill_session(name)
            except Exception:
                pass
        self._managed_sessions.clear()

        # Safety net: kill ALL study-* sessions (catches leaks from failed tests)
        import contextlib

        with contextlib.suppress(Exception):
            remaining = self.backend.list_study_sessions()
            for name in remaining:
                with contextlib.suppress(Exception):
                    self.backend.kill_session(name)

        self._clean_ipc_files()

    # ------------------------------------------------------------------
    # Assertions
    # ------------------------------------------------------------------

    def assert_session_exists(self, name: str) -> None:
        assert self.session_exists(name), f"Expected session {name!r} to exist"

    def assert_session_gone(self, name: str) -> None:
        assert not self.session_exists(name), f"Expected session {name!r} to NOT exist"

    def assert_no_study_sessions(self) -> None:
        """Assert zero study-* sessions remain."""
        sessions = self.list_study_sessions()
        assert not sessions, f"Stale study sessions remain: {sessions}"

    def assert_pane_has_children(self, pane_id: str) -> None:
        self.wait_for(
            lambda: self.pane_has_children(pane_id),
            timeout=10,
            msg=f"pane {pane_id} has no children (agent not running)",
        )
