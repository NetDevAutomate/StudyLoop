"""Clean logic — pure functional core, no I/O.

Decides what to clean based on pre-gathered data.
The imperative shell (_clean.py) handles all side effects.

See docs/mentoring/functional-core-imperative-shell.md for the pattern.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class DirInfo:
    """Pre-gathered info about a session directory."""

    name: str
    path: Path
    is_symlink: bool


@dataclass
class CleanResult:
    """What the clean operation decided to do."""

    sessions_to_kill: list[str] = field(default_factory=list)
    dirs_to_remove: list[Path] = field(default_factory=list)
    state_to_clean: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def has_work(self) -> bool:
        """True if there's anything to clean."""
        return bool(self.sessions_to_kill or self.dirs_to_remove or self.state_to_clean)


def plan_clean(
    *,
    tmux_running: bool,
    zombie_sessions: list[str],
    session_dirs: list[DirInfo],
    live_tmux_names: set[str],
    state: dict,
    state_file_exists: bool,
) -> CleanResult:
    """Decide what to clean. Pure logic — no I/O, no side effects.

    Args:
        tmux_running: Whether the tmux server is accessible.
        zombie_sessions: Session names confirmed as zombies (no child, aged >60s).
        session_dirs: Info about each directory in ~/.config/studyctl/sessions/.
        live_tmux_names: Set of tmux session names that currently exist.
        state: Contents of session-state.json (empty dict if missing).
        state_file_exists: Whether session-state.json exists on disk.

    Returns:
        CleanResult describing what should be cleaned.
    """
    sessions_to_kill: list[str] = []
    dirs_to_remove: list[Path] = []
    warnings: list[str] = []
    state_to_clean = False

    if not tmux_running:
        warnings.append("tmux server not running — skipped session checks")
        return CleanResult(warnings=warnings)

    # Step 1: Zombie tmux sessions
    sessions_to_kill = list(zombie_sessions)

    # Step 2: Stale session directories
    for d in session_dirs:
        if d.is_symlink:
            warnings.append(f"Skipped symlink: {d.name}")
            continue
        if d.name not in live_tmux_names:
            dirs_to_remove.append(d.path)

    # Step 3: Stale state file
    if state_file_exists and state.get("mode") == "ended":
        tmux_name = state.get("tmux_session", "")
        if not tmux_name or tmux_name not in live_tmux_names:
            state_to_clean = True

    return CleanResult(
        sessions_to_kill=sessions_to_kill,
        dirs_to_remove=dirs_to_remove,
        state_to_clean=state_to_clean,
        warnings=warnings,
    )
