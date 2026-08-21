"""Backend-agnostic terminal multiplexer protocol for study sessions.

Defines the ``Multiplexer`` Protocol, ``TmuxBackend`` (wrapping tmux.py),
``MultiplexerError``, and the ``get_backend()`` factory.

Call sites import from here — never from tmux.py directly (except for
backwards-compatible module-level functions retained in tmux.py).
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import time
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class MultiplexerError(Exception):
    """Raised when a multiplexer operation fails."""


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Multiplexer(Protocol):
    """Backend-agnostic terminal multiplexer for study sessions.

    18 public methods covering detection, session lifecycle, pane management,
    configuration, client attach, process introspection, and test harness support.
    """

    # --- Detection ---
    def is_available(self) -> bool: ...
    def is_inside_session(self) -> bool: ...
    def is_server_running(self) -> bool: ...

    # --- Session lifecycle ---
    def session_exists(self, name: str) -> bool: ...
    def create_session(
        self,
        name: str,
        *,
        command: str | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str: ...
    def kill_session(self, name: str) -> bool: ...
    def list_study_sessions(self) -> list[str]: ...
    def kill_all_study_sessions(self, current_session: str | None = None) -> None: ...

    # --- Pane management ---
    def split_pane(
        self,
        target: str,
        *,
        direction: str = "right",
        size: int = 30,
        percentage: bool = False,
        command: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str: ...
    def send_keys(self, target: str, keys: str, *, enter: bool = True) -> None: ...
    def select_pane(self, target: str) -> None: ...

    # --- Session configuration (backend-specific semantics) ---
    def configure_session_defaults(self, session: str) -> None: ...

    # --- Client/attach ---
    def switch_client(self, name: str) -> None: ...
    def attach(self, name: str) -> None: ...

    # --- Process introspection ---
    def pane_has_child_process(self, pane_id: str) -> bool: ...
    def is_zombie_session(self, name: str, min_age_seconds: float = 60.0) -> bool: ...

    # --- Test harness support ---
    def capture_pane(self, pane_id: str, lines: int = 50) -> str: ...
    def wait_for_content(
        self, pane_id: str, pattern: str, timeout_ms: int = 10000
    ) -> str: ...


# ---------------------------------------------------------------------------
# TmuxBackend
# ---------------------------------------------------------------------------


class TmuxBackend:
    """Wraps existing tmux.py module-level functions into the Multiplexer protocol.

    Each method delegates to the corresponding function in tmux.py, keeping
    backwards compatibility intact. The module-level functions in tmux.py
    remain for any code that imports them directly.
    """

    def is_available(self) -> bool:
        from studyloop.tmux import is_tmux_available

        return is_tmux_available()

    def is_inside_session(self) -> bool:
        from studyloop.tmux import is_in_tmux

        return is_in_tmux()

    def is_server_running(self) -> bool:
        from studyloop.tmux import is_tmux_server_running

        return is_tmux_server_running()

    def session_exists(self, name: str) -> bool:
        from studyloop.tmux import session_exists

        return session_exists(name)

    def create_session(
        self,
        name: str,
        *,
        command: str | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        """Create a detached session. env= is applied via set_environment after creation."""
        from studyloop.tmux import create_session, set_environment

        pane_id = create_session(name, command=command, cwd=cwd)
        if env:
            for key, value in env.items():
                set_environment(name, key, value)
        return pane_id

    def kill_session(self, name: str) -> bool:
        from studyloop.tmux import kill_session

        return kill_session(name)

    def list_study_sessions(self) -> list[str]:
        from studyloop.tmux import list_study_sessions

        return list_study_sessions()

    def kill_all_study_sessions(self, current_session: str | None = None) -> None:
        from studyloop.tmux import kill_all_study_sessions

        kill_all_study_sessions(current_session)

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
        """Split a pane. env= is not supported by tmux split-window (ignored)."""
        from studyloop.tmux import split_pane

        return split_pane(target, direction, size, percentage=percentage, command=command)

    def send_keys(self, target: str, keys: str, *, enter: bool = True) -> None:
        from studyloop.tmux import send_keys

        send_keys(target, keys, enter=enter)

    def select_pane(self, target: str) -> None:
        from studyloop.tmux import select_pane

        select_pane(target)

    def configure_session_defaults(self, session: str) -> None:
        """Apply tmux-specific session options.

        Encapsulates the three set_option calls + optional user config load
        that were previously inlined in orchestrator.py.
        """
        import contextlib

        from studyloop.session_state import SESSION_DIR
        from studyloop.tmux import load_config, set_option

        set_option(session, "remain-on-exit", "off")
        set_option(session, "detach-on-destroy", "on")
        set_option(session, "window-size", "largest")

        # Load user's studyloop tmux overlay if present
        user_conf = SESSION_DIR / "tmux-studyloop.conf"
        if user_conf.exists():
            with contextlib.suppress(Exception):
                load_config(user_conf)

    def switch_client(self, name: str) -> None:
        from studyloop.tmux import switch_client

        switch_client(name)

    def attach(self, name: str) -> None:
        from studyloop.tmux import attach

        attach(name)

    def pane_has_child_process(self, pane_id: str) -> bool:
        from studyloop.tmux import pane_has_child_process

        return pane_has_child_process(pane_id)

    def is_zombie_session(self, name: str, min_age_seconds: float = 60.0) -> bool:
        from studyloop.tmux import is_zombie_session

        return is_zombie_session(name, min_age_seconds)

    def capture_pane(self, pane_id: str, lines: int = 50) -> str:
        """Capture pane content via tmux capture-pane."""
        from studyloop.tmux import _tmux

        result = _tmux("capture-pane", "-t", pane_id, "-p", "-S", f"-{lines}")
        return result.stdout if result.returncode == 0 else ""

    def wait_for_content(
        self, pane_id: str, pattern: str, timeout_ms: int = 10000
    ) -> str:
        """Poll capture_pane until pattern matches or timeout.

        tmux has no native wait — this implements polling with re.search.
        """
        deadline = time.time() + (timeout_ms / 1000.0)
        compiled = re.compile(pattern)
        while time.time() < deadline:
            content = self.capture_pane(pane_id)
            match = compiled.search(content)
            if match:
                return match.group(0)
            time.sleep(0.1)
        raise MultiplexerError(
            f"Timed out waiting for pattern {pattern!r} in pane {pane_id}"
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_backend() -> Multiplexer:
    """Select multiplexer backend via env → default (tmux) cascade.

    Selection logic:
    - STUDYLOOP_MULTIPLEXER=herdr + herdr available → HerdrBackend
    - STUDYLOOP_MULTIPLEXER=herdr + herdr NOT available → raise MultiplexerError
    - STUDYLOOP_MULTIPLEXER=tmux → TmuxBackend always
    - No env var → TmuxBackend (default until herdr journey suite is green)

    Invalid env values raise MultiplexerError.
    """
    choice = os.environ.get("STUDYLOOP_MULTIPLEXER", "").lower().strip()

    if choice == "tmux" or not choice:
        return TmuxBackend()

    if choice == "herdr":
        if not shutil.which("herdr"):
            raise MultiplexerError(
                "STUDYLOOP_MULTIPLEXER=herdr but herdr binary not found on PATH. "
                "Install herdr or set STUDYLOOP_MULTIPLEXER=tmux."
            )
        # Lazy import — herdr.py may not exist yet (T2 builds it)
        try:
            from studyloop.herdr import HerdrBackend

            return HerdrBackend()
        except ImportError:
            raise MultiplexerError(
                "STUDYLOOP_MULTIPLEXER=herdr but HerdrBackend is not yet implemented. "
                "This is expected until Track T2 lands."
            ) from None

    raise MultiplexerError(
        f"STUDYLOOP_MULTIPLEXER={choice!r} is not a valid backend. "
        f"Supported values: 'tmux', 'herdr'."
    )
