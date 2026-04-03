"""Clean command — imperative shell for session cleanup.

Thin adapter: gathers real-world state, delegates decisions to
_clean_logic.plan_clean(), then executes and presents the result.

See docs/mentoring/functional-core-imperative-shell.md for the pattern.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from rich.console import Console

    from studyctl.cli._clean_logic import CleanResult


@click.command()
@click.option("--dry-run", is_flag=True, help="Show what would be cleaned without acting.")
def clean(dry_run: bool) -> None:
    """Remove orphaned study sessions, directories, and state files.

    Cleans up artifacts left behind by crashed or stale study sessions:
    zombie tmux sessions, leftover session directories, and stale state files.

    Examples:

        studyctl clean --dry-run

        studyctl clean
    """
    import fcntl
    import shutil

    from studyctl.cli._clean_logic import CleanResult, DirInfo, plan_clean
    from studyctl.cli._shared import console
    from studyctl.session_state import SESSION_DIR, STATE_FILE, read_session_state
    from studyctl.tmux import (
        LOCK_FILE,
        is_tmux_server_running,
        is_zombie_session,
        kill_session,
        list_study_sessions,
    )

    # ── GATHER — collect real-world state ────────────────────────
    tmux_running = is_tmux_server_running()
    study_sessions = list_study_sessions() if tmux_running else []
    zombie_sessions = [s for s in study_sessions if is_zombie_session(s)]
    live_tmux_names = set(study_sessions)

    sessions_dir = SESSION_DIR / "sessions"
    session_dirs: list[DirInfo] = []
    if sessions_dir.exists() and tmux_running:
        session_dirs = [
            DirInfo(name=d.name, path=d, is_symlink=d.is_symlink())
            for d in sorted(sessions_dir.iterdir())
            if d.is_dir() or d.is_symlink()
        ]

    state = read_session_state()

    # ── DECIDE — pure logic, no side effects ─────────────────────
    plan = plan_clean(
        tmux_running=tmux_running,
        zombie_sessions=zombie_sessions,
        session_dirs=session_dirs,
        live_tmux_names=live_tmux_names,
        state=state,
        state_file_exists=STATE_FILE.exists(),
    )

    # ── EXECUTE — follow the plan ────────────────────────────────
    execution_warnings: list[str] = []
    if not dry_run:
        for name in plan.sessions_to_kill:
            success = kill_session(name)
            if not success:
                execution_warnings.append(f"Failed to confirm kill: {name}")

        for path in plan.dirs_to_remove:
            try:
                shutil.rmtree(path)
            except OSError as e:
                execution_warnings.append(f"Partial delete {path.name}: {e}")

        if plan.state_to_clean:
            LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(LOCK_FILE, "w") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    # Re-read under lock to prevent TOCTOU with --resume
                    fresh_state = read_session_state()
                    if fresh_state.get("mode") == "ended":
                        STATE_FILE.unlink(missing_ok=True)
                    else:
                        # State changed under us — someone resumed
                        plan = CleanResult(
                            sessions_to_kill=plan.sessions_to_kill,
                            dirs_to_remove=plan.dirs_to_remove,
                            state_to_clean=False,
                            warnings=plan.warnings,
                        )
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)

    all_warnings = plan.warnings + execution_warnings

    # ── PRESENT — format output ──────────────────────────────────
    _print_summary(console, plan, all_warnings, dry_run)


def _print_summary(
    console: Console,
    plan: CleanResult,
    warnings: list[str],
    dry_run: bool,
) -> None:
    """Format and print the clean result."""
    label = "[dim](dry-run)[/dim] " if dry_run else ""

    if not plan.has_work and not warnings:
        msg = "no orphaned artifacts found."
        console.print(f"{label}[bold green]Nothing to clean[/bold green] — {msg}")
        return

    verb_session = "would kill" if dry_run else "killed"
    verb_dir = "would remove" if dry_run else "removed"
    verb_state = "would reset" if dry_run else "reset"
    action = "Would clean" if dry_run else "Cleaned"

    if plan.sessions_to_kill:
        console.print(f"\n{label}[bold]tmux sessions[/bold]")
        for name in plan.sessions_to_kill:
            console.print(f"  [red]{verb_session}[/red] {name}")

    if plan.dirs_to_remove:
        console.print(f"\n{label}[bold]Session directories[/bold]")
        for path in plan.dirs_to_remove:
            console.print(f"  [red]{verb_dir}[/red] {path.name}")

    if plan.state_to_clean:
        console.print(f"\n{label}[bold]State file[/bold]")
        console.print(f"  [red]{verb_state}[/red] session-state.json")

    if warnings:
        console.print(f"\n{label}[bold yellow]Warnings[/bold yellow]")
        for w in warnings:
            console.print(f"  [yellow]{w}[/yellow]")

    n_sessions = len(plan.sessions_to_kill)
    n_dirs = len(plan.dirs_to_remove)
    n_state = "1 state file" if plan.state_to_clean else "0 state files"
    summary = f"{n_sessions} sessions, {n_dirs} dirs, {n_state}"
    console.print(f"\n{label}[bold green]{action}:[/bold green] {summary}")
