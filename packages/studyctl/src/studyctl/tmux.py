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


def create_session(name: str, width: int = 200, height: int = 50) -> str:
    """Create a detached tmux session. Returns the initial pane ID.

    Uses a file lock to prevent concurrent creation races (e.g. two
    terminals running ``studyctl study`` simultaneously).
    """
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            result = _tmux(
                "new-session",
                "-d",
                "-s",
                name,
                "-x",
                str(width),
                "-y",
                str(height),
                "-P",
                "-F",
                "#{pane_id}",
                check=True,
            )
            return result.stdout.strip()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def split_pane(
    target: str,
    direction: str = "right",
    size: int = 30,
) -> str:
    """Split a pane. Returns the new pane ID (never positional index).

    Args:
        target: Session name or pane ID to split.
        direction: "right" for horizontal, "below" for vertical.
        size: Column/row count for the new pane.
    """
    flag = "-h" if direction == "right" else "-v"
    result = _tmux(
        "split-window",
        flag,
        "-t",
        target,
        "-l",
        str(size),
        "-P",
        "-F",
        "#{pane_id}",
        check=True,
    )
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


def kill_session(name: str) -> None:
    """Kill a tmux session by name. No-op if it doesn't exist."""
    _tmux("kill-session", "-t", name)


def attach(name: str) -> None:
    """Attach to a tmux session. Replaces the current process.

    Uses ``os.execvp`` so the Python process is replaced — no dangling
    parent process left behind.
    """
    os.execvp("tmux", ["tmux", "attach-session", "-t", name])
