"""tmux session manager — thin wrapper around tmux CLI commands.

Creates and manages study session layouts. All pane targeting uses
``-P -F #{pane_id}`` (never positional indexes which shift on create/destroy).
Config overlay via ``source-file`` (``-f`` is server-level, ignored on running servers).
"""

from __future__ import annotations

import fcntl
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

LOCK_FILE = Path("~/.config/studyctl/studyctl-tmux.lock").expanduser()
MIN_TMUX_VERSION = (3, 1)  # display-popup + pane-border-lines


def _tmux(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a tmux command. All tmux calls go through this."""
    return subprocess.run(
        ["tmux", *args],
        capture_output=True,
        text=True,
        check=check,
    )


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def is_tmux_available() -> bool:
    """Check if tmux is installed and meets minimum version."""
    if not shutil.which("tmux"):
        return False
    result = _tmux("-V")
    if result.returncode != 0:
        return False
    # Parse "tmux 3.4" or "tmux 3.5a"
    match = re.search(r"(\d+)\.(\d+)", result.stdout)
    if not match:
        return False
    major, minor = int(match.group(1)), int(match.group(2))
    return (major, minor) >= MIN_TMUX_VERSION


def get_tmux_version() -> str | None:
    """Return the tmux version string, or None if not installed."""
    result = _tmux("-V")
    return result.stdout.strip() if result.returncode == 0 else None


def is_in_tmux() -> bool:
    """Check if the current process is running inside a tmux session."""
    return "TMUX" in os.environ


def session_exists(name: str) -> bool:
    """Check if a tmux session with the given name exists."""
    result = _tmux("has-session", "-t", name)
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


def create_session(
    name: str,
    command: str | None = None,
    cwd: str | None = None,
) -> str:
    """Create a detached tmux session. Returns the initial pane ID.

    Args:
        name: Session name.
        command: Optional command to run in the initial pane. Runs
            directly (no shell prompt or visible command in scrollback).
        cwd: Working directory for the session. If set, the initial
            pane starts in this directory.

    Does NOT specify ``-x``/``-y`` — the session inherits dimensions
    from the attaching client, so split percentages work correctly
    relative to the actual terminal size.

    Uses a file lock to prevent concurrent creation races.
    """
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            args = ["new-session", "-d", "-s", name]
            if cwd:
                args.extend(["-c", cwd])
            args.extend(["-P", "-F", "#{pane_id}"])
            if command:
                args.append(command)
            result = _tmux(*args, check=True)
            return result.stdout.strip()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def split_pane(
    target: str,
    direction: str = "right",
    size: int = 30,
    *,
    percentage: bool = False,
    command: str | None = None,
) -> str:
    """Split a pane. Returns the new pane ID (never positional index).

    Args:
        target: Session name or pane ID to split.
        direction: "right" for horizontal, "below" for vertical.
        size: Column/row count, or percentage if ``percentage=True``.
        percentage: If True, ``size`` is treated as a percentage (e.g. 25 = 25%).
        command: Optional command to run in the new pane. Runs directly
            (no shell prompt or visible command in scrollback).
    """
    flag = "-h" if direction == "right" else "-v"
    size_str = f"{size}%" if percentage else str(size)
    args = [
        "split-window",
        flag,
        "-t",
        target,
        "-l",
        size_str,
        "-P",
        "-F",
        "#{pane_id}",
    ]
    if command:
        args.append(command)
    result = _tmux(*args, check=True)
    return result.stdout.strip()


def send_keys(target: str, keys: str, *, enter: bool = True) -> None:
    """Send keystrokes to a tmux pane.

    Args:
        target: Pane ID (e.g. "%0") or session:pane specifier.
        keys: Text to send.
        enter: Whether to append Enter after the keys.
    """
    args = ["send-keys", "-t", target, keys]
    if enter:
        args.append("Enter")
    _tmux(*args, check=True)


def load_config(config_path: Path) -> None:
    """Load a tmux config file via ``source-file``.

    This works on running servers (unlike ``-f`` which is server-level
    and ignored if a server is already running).
    """
    _tmux("source-file", str(config_path), check=True)


def set_option(target: str, option: str, value: str) -> None:
    """Set a tmux session option."""
    _tmux("set-option", "-t", target, option, value, check=True)


def set_environment(target: str, name: str, value: str) -> None:
    """Set an environment variable for a tmux session.

    New panes in this session will inherit the variable.
    """
    _tmux("set-environment", "-t", target, name, value, check=True)


def select_pane(target: str) -> None:
    """Focus a specific pane."""
    _tmux("select-pane", "-t", target, check=True)


def display_popup(
    target: str,
    command: str,
    title: str = "",
    width: str = "60%",
    height: str = "40%",
) -> None:
    """Open a tmux popup overlay."""
    args = ["display-popup", "-E", "-t", target, "-w", width, "-h", height]
    if title:
        args.extend(["-T", title])
    args.append(command)
    _tmux(*args, check=True)


def pane_has_child_process(pane_id: str) -> bool:
    """Check if the pane's process has child processes (agent is running).

    tmux wraps commands in a shell, so ``pane_current_command`` always
    reports the wrapper shell (``zsh``/``bash``). Instead, check if the
    pane's PID has children — if it does, the agent is still running.
    """
    result = _tmux("display-message", "-t", pane_id, "-p", "#{pane_pid}")
    if result.returncode != 0:
        return False
    pane_pid = result.stdout.strip()
    if not pane_pid:
        return False
    # Check for child processes of the pane's shell
    check = subprocess.run(
        ["pgrep", "-P", pane_pid],
        capture_output=True,
        text=True,
    )
    return check.returncode == 0


def kill_session(name: str) -> None:
    """Kill a tmux session by name. Waits until the session is gone."""
    import time

    _tmux("kill-session", "-t", name)
    # tmux kill is async — wait for it to take effect
    for _ in range(10):
        if not session_exists(name):
            return
        time.sleep(0.1)
    # Last resort: try again
    _tmux("kill-session", "-t", name)
    time.sleep(0.2)


def kill_all_study_sessions(current_session: str | None = None) -> None:
    """Kill all tmux sessions with 'study-' prefix.

    Ensures no stale sessions accumulate. Called during cleanup
    so non-technical users aren't stranded in tmux.

    Kills the current session LAST — if we're running inside it,
    killing it first would SIGHUP us before we can clean up the rest.
    """
    result = _tmux("list-sessions", "-F", "#{session_name}")
    if result.returncode != 0:
        return
    sessions = [n for n in result.stdout.strip().splitlines() if n.startswith("study-")]

    # Kill other sessions first, current session last
    others = [n for n in sessions if n != current_session]
    for name in others:
        _tmux("kill-session", "-t", name)
    # Now kill the one we're in (if any) — this SIGHUP's us
    if current_session and current_session in sessions:
        _tmux("kill-session", "-t", current_session)


def switch_client(name: str) -> None:
    """Switch the current tmux client to a different session.

    Use this when already inside tmux (``is_in_tmux() is True``).
    """
    _tmux("switch-client", "-t", name, check=True)


def attach(name: str) -> None:
    """Attach to a tmux session. Replaces the current process.

    Uses ``os.execvp`` so the Python process is replaced — no dangling
    parent process left behind.
    """
    os.execvp("tmux", ["tmux", "attach-session", "-t", name])
