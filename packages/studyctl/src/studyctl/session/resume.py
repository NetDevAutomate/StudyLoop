"""Session resume — reattach to live tmux or rebuild from history."""

from __future__ import annotations

from typing import TYPE_CHECKING

from studyctl.cli._shared import console

if TYPE_CHECKING:
    import click


def get_previous_session_notes(study_id: str | None) -> str | None:
    """Fetch the notes from a previous study session in the DB."""
    if not study_id:
        return None
    from studyctl.history import get_session_notes

    return get_session_notes(study_id)


def handle_resume(ctx: click.Context) -> None:
    """Resume an existing study session.

    Two resume scenarios:
    1. tmux session still alive -> reattach/switch to it
    2. tmux session dead but session dir exists -> create new tmux session
       with ``-r`` flag to resume the AI conversation from history
    """
    from studyctl.session_state import read_session_state
    from studyctl.tmux import (
        attach,
        is_in_tmux,
        kill_session,
        pane_has_child_process,
        session_exists,
    )

    state = read_session_state()
    session_name = state.get("tmux_session")
    session_dir = state.get("session_dir")
    main_pane = state.get("tmux_main_pane")

    if not session_name:
        console.print("[yellow]No active session to resume.[/yellow]")
        ctx.exit(1)
        return

    # Scenario 1: tmux session is still alive AND agent is running -- reconnect
    if session_exists(session_name):
        # Check if the agent is actually running (not just a dead shell).
        # tmux wraps commands in a shell, so we check for child processes.
        agent_alive = pane_has_child_process(main_pane) if main_pane else False

        if agent_alive:
            topic = state.get("topic", "unknown")
            console.print(f"[green]Resuming:[/green] {topic}")

            if is_in_tmux():
                from studyctl.tmux import switch_client

                switch_client(session_name)
            else:
                attach(session_name)
            return

        # tmux session is zombie (agent exited) -- kill it and rebuild
        console.print("[dim]Cleaning up stale tmux session...[/dim]")
        kill_session(session_name)

    # Scenario 2: tmux session dead but session dir preserved
    # Rebuild the tmux session with -r to resume the AI conversation
    from pathlib import Path

    if session_dir and Path(session_dir).exists():
        topic = state.get("topic", "unknown")
        agent = state.get("agent", "claude")
        mode = state.get("mode", "study")
        if mode == "ended":
            mode = "study"
        energy = state.get("energy", 5)
        timer = state.get("timer_mode", "elapsed")

        # Fetch previous session notes from DB for agent context
        previous_notes = get_previous_session_notes(state.get("study_session_id"))

        console.print(
            f"[green]Resuming conversation:[/green] {topic}\n"
            f"  [dim]Rebuilding tmux session with conversation history[/dim]"
        )
        # State file has mode=ended, is_session_active() returns False -- no need to clear
        # Rebuild tmux in the SAME session directory (preserves conversation history)
        from studyctl.cli._study import _handle_start

        _handle_start(
            ctx,
            topic,
            agent,
            mode,
            timer,
            energy,
            web=False,
            resume_session_name=session_name,
            resume_session_dir=session_dir,
            previous_notes=previous_notes,
        )
        return

    console.print(
        f"[yellow]tmux session '{session_name}' no longer exists.[/yellow]\n"
        "  End it: [bold]studyctl study --end[/bold]"
    )
    ctx.exit(1)
