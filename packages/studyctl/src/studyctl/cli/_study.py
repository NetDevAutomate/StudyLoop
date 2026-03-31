"""Study command — one command to create the complete study environment.

Orchestrates: session DB record, IPC files, tmux session + layout,
agent launch, Textual sidebar, and optional web dashboard.
"""

from __future__ import annotations

from datetime import UTC, datetime

import click

from studyctl.cli._shared import console


@click.command()
@click.argument("topic", required=False)
@click.option(
    "--agent",
    "-a",
    type=click.Choice(["claude"]),
    help="AI agent to launch (auto-detects if omitted).",
)
@click.option(
    "--mode",
    "-m",
    default="study",
    type=click.Choice(["study", "co-study"]),
    help="Session mode.",
)
@click.option(
    "--timer",
    "-T",
    type=click.Choice(["elapsed", "pomodoro"]),
    help="Timer mode (defaults by session mode).",
)
@click.option(
    "--energy",
    "-e",
    type=click.IntRange(1, 10),
    default=5,
    show_default=True,
    help="Energy level (1-10).",
)
@click.option("--web", is_flag=True, help="Also start the web dashboard.")
@click.option("--resume", is_flag=True, help="Resume an existing session.")
@click.option("--end", "end_session", is_flag=True, help="End the current session.")
@click.pass_context
def study(
    ctx: click.Context,
    topic: str | None,
    agent: str | None,
    mode: str,
    timer: str | None,
    energy: int,
    web: bool,
    resume: bool,
    end_session: bool,
) -> None:
    """Start a study session with full tmux environment.

    Examples:

        studyctl study "Python Decorators" --energy 7

        studyctl study "Spark Internals" --mode co-study --timer pomodoro

        studyctl study --resume

        studyctl study --end
    """
    if end_session:
        _handle_end(ctx)
        return

    if resume:
        _handle_resume(ctx)
        return

    if not topic:
        console.print("[red]Topic is required. Usage: studyctl study 'topic'[/red]")
        ctx.exit(1)
        return

    # Resolve defaults
    if timer is None:
        timer = "pomodoro" if mode == "co-study" else "elapsed"

    _handle_start(ctx, topic, agent, mode, timer, energy, web)


def _handle_start(
    ctx: click.Context,
    topic: str,
    agent: str | None,
    mode: str,
    timer: str,
    energy: int,
    web: bool,
) -> None:
    """Start a new study session with tmux environment."""
    from studyctl.agent_launcher import build_persona_file, detect_agents, get_launch_command
    from studyctl.history import start_study_session
    from studyctl.session_state import (
        PARKING_FILE,
        SESSION_DIR,
        TOPICS_FILE,
        _ensure_session_dir,
        is_session_active,
        write_session_state,
    )
    from studyctl.tmux import (
        attach,
        create_session,
        is_in_tmux,
        is_tmux_available,
        kill_session,
        load_config,
        select_pane,
        session_exists,
        split_pane,
        switch_client,
    )

    # --- Pre-flight checks ---

    if not is_tmux_available():
        console.print(
            "[red]tmux 3.1+ is required but not found.[/red]\n"
            "  Install: [bold]brew install tmux[/bold] (macOS) or "
            "[bold]apt install tmux[/bold] (Linux)"
        )
        ctx.exit(1)
        return

    # Resolve agent
    if agent is None:
        available = detect_agents()
        if not available:
            console.print(
                "[red]No AI agent found.[/red]\n"
                "  Install Claude Code: [bold]npm install -g @anthropic-ai/claude-code[/bold]"
            )
            ctx.exit(1)
            return
        agent = available[0]

    # Check for existing session
    if is_session_active():
        console.print(
            "[yellow]A session is already active.[/yellow]\n"
            "  Resume: [bold]studyctl study --resume[/bold]\n"
            "  End:    [bold]studyctl study --end[/bold]"
        )
        ctx.exit(1)
        return

    # --- Create session ---

    # Map energy to label for history.py
    if energy <= 3:
        energy_label = "low"
    elif energy <= 7:
        energy_label = "medium"
    else:
        energy_label = "high"

    study_id = start_study_session(topic, energy_label)
    if not study_id:
        console.print("[red]Failed to start session. Run 'studyctl doctor'.[/red]")
        ctx.exit(1)
        return

    # Write session state with timer fields
    _ensure_session_dir()
    now = datetime.now(UTC).isoformat()
    write_session_state(
        {
            "study_session_id": study_id,
            "topic": topic,
            "energy": energy,
            "energy_label": energy_label,
            "mode": mode,
            "timer_mode": timer,
            "started_at": now,
            "paused_at": None,
            "total_paused_seconds": 0,
        }
    )

    # Create empty IPC files
    TOPICS_FILE.touch(mode=0o600, exist_ok=True)
    PARKING_FILE.touch(mode=0o600, exist_ok=True)

    # --- Build tmux session ---

    # Generate session name: study-{slug}-{short_id}
    slug = topic.lower().replace(" ", "-")[:20]
    short_id = study_id[:8] if study_id else "unknown"
    session_name = f"study-{slug}-{short_id}"

    # Clean up stale session with same name
    if session_exists(session_name):
        kill_session(session_name)

    # Build commands before creating panes
    persona_file = build_persona_file(mode, topic, energy)
    agent_cmd = get_launch_command(agent, persona_file)

    import sys

    sidebar_cmd = f"{sys.executable} -m studyctl.tui.sidebar"

    # Create session with the agent command running directly in the
    # initial pane — no shell prompt, no visible command in scrollback.
    main_pane = create_session(session_name, command=agent_cmd)

    # Load studyctl tmux config overlay (only study-specific settings,
    # respects user's existing theme/prefix/keybindings)
    import contextlib
    from pathlib import Path

    bundled_conf = Path(__file__).parent.parent / "data" / "tmux-studyctl.conf"
    user_conf = SESSION_DIR / "tmux-studyctl.conf"
    tmux_conf = user_conf if user_conf.exists() else bundled_conf
    if tmux_conf.exists():
        with contextlib.suppress(Exception):
            load_config(tmux_conf)

    # --- Switch/attach FIRST so tmux resizes to the actual terminal ---
    # This ensures the split percentage is calculated against the real
    # terminal width, not the detached default (80x24).
    already_in_tmux = is_in_tmux()
    if already_in_tmux:
        switch_client(session_name)

    # Split for sidebar (right pane, 25% width)
    # command= runs directly — no shell prompt or visible command.
    sidebar_pane = split_pane(
        main_pane,
        direction="right",
        size=25,
        percentage=True,
        command=sidebar_cmd,
    )

    # Focus main pane (agent)
    select_pane(main_pane)

    # Store tmux metadata in session state for resume/end
    write_session_state(
        {
            "tmux_session": session_name,
            "tmux_main_pane": main_pane,
            "tmux_sidebar_pane": sidebar_pane,
            "persona_file": str(persona_file),
        }
    )

    # --- Optional web dashboard ---

    if web:
        _start_web_background(session_name)

    # --- Attach if not already in tmux ---
    if not already_in_tmux:
        # Replaces this process via os.execvp — no code runs after this
        attach(session_name)


def _handle_resume(ctx: click.Context) -> None:
    """Resume an existing study session."""
    from studyctl.session_state import read_session_state
    from studyctl.tmux import attach, is_in_tmux, session_exists

    state = read_session_state()
    session_name = state.get("tmux_session")

    if not session_name:
        console.print("[yellow]No active session to resume.[/yellow]")
        ctx.exit(1)
        return

    if not session_exists(session_name):
        console.print(
            f"[yellow]tmux session '{session_name}' no longer exists.[/yellow]\n"
            "  The session may have been killed externally.\n"
            "  End it: [bold]studyctl study --end[/bold]"
        )
        ctx.exit(1)
        return

    topic = state.get("topic", "unknown")
    console.print(f"[green]Resuming:[/green] {topic}")

    if is_in_tmux():
        from studyctl.tmux import switch_client

        switch_client(session_name)
    else:
        attach(session_name)


def _handle_end(_ctx: click.Context) -> None:
    """End the current study session cleanly."""
    from studyctl.history import end_study_session
    from studyctl.session_state import (
        clear_session_files,
        read_session_state,
        write_session_state,
    )
    from studyctl.tmux import kill_session, session_exists

    state = read_session_state()
    study_id = state.get("study_session_id")
    session_name = state.get("tmux_session")
    persona_file = state.get("persona_file")

    if not study_id:
        console.print("[yellow]No active session found.[/yellow]")
        return

    topic = state.get("topic", "unknown")

    # End the DB session
    end_study_session(study_id)

    # Signal dashboard summary view
    write_session_state({"mode": "ended"})

    # Clean up persona file
    import contextlib
    import os

    if persona_file:
        with contextlib.suppress(OSError):
            os.unlink(persona_file)

    # Clean up oneline file
    from studyctl.session_state import SESSION_DIR

    oneline = SESSION_DIR / "session-oneline.txt"
    if oneline.exists():
        with contextlib.suppress(OSError):
            oneline.unlink()

    console.print(f"[bold]Session ended:[/bold] {topic}")

    # Kill tmux session
    if session_name and session_exists(session_name):
        kill_session(session_name)
        console.print(f"  tmux session '{session_name}' closed.")

    # Clear IPC files
    clear_session_files()


def _start_web_background(_session_name: str) -> None:
    """Start the web dashboard as a background process."""
    import subprocess

    try:
        proc = subprocess.Popen(
            ["uv", "run", "studyctl", "web", "--port", "8567"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Store PID for cleanup
        from studyctl.session_state import write_session_state

        write_session_state({"web_pid": proc.pid})
    except Exception:
        console.print("[yellow]Could not start web dashboard.[/yellow]")


# ---------------------------------------------------------------------------
# Sidebar CLI entry point
# ---------------------------------------------------------------------------


@click.command("sidebar")
def sidebar_cmd() -> None:
    """Run the Textual sidebar app (launched by studyctl study in tmux)."""
    try:
        from studyctl.tui.sidebar import run_sidebar  # type: ignore[import-not-found]
    except ImportError:
        console.print(
            "[red]Textual is required for the sidebar.[/red]\n"
            "  Install: [bold]pip install 'studyctl[tui]'[/bold]"
        )
        raise SystemExit(1) from None

    run_sidebar()
