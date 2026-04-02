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
    *,
    resume_session_name: str | None = None,
    resume_session_dir: str | None = None,
    previous_notes: str | None = None,
) -> None:
    """Start a new study session with tmux environment.

    Args:
        resume_session_name: If resuming, reuse this tmux session name
            (same directory with .claude/ history).
        resume_session_dir: If resuming, reuse this session directory.
        previous_notes: If resuming, notes from the previous session
            to inject into the agent persona.
    """
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

    from pathlib import Path

    if resume_session_name and resume_session_dir:
        # Resuming: reuse existing session name and directory
        # so claude -r finds the same conversation history
        session_name = resume_session_name
        session_dir = Path(resume_session_dir)
        is_resuming = True
    else:
        # New session: generate fresh name and directory
        slug = topic.lower().replace(" ", "-")[:20]
        short_id = study_id[:8] if study_id else "unknown"
        session_name = f"study-{slug}-{short_id}"
        session_dir = SESSION_DIR / "sessions" / session_name
        # Claude Code stores history in ~/.claude/projects/{mangled-path}/,
        # not .claude/ in cwd. Check if a project dir exists for this session.
        claude_project_key = str(session_dir).replace("/", "-").lstrip("-")
        claude_project_dir = Path.home() / ".claude" / "projects" / claude_project_key
        is_resuming = claude_project_dir.exists()

    session_dir.mkdir(parents=True, exist_ok=True)

    import stat
    import sys

    # Write a CLAUDE.md so Claude knows this is a study session directory
    # and doesn't waste time exploring for project context.
    claude_md = session_dir / "CLAUDE.md"
    if not claude_md.exists():
        claude_md.write_text(
            f"# Study Session: {topic}\n\n"
            "This is a studyctl study session directory. "
            "Do not search for code or project files here.\n\n"
            "Use `studyctl topic` to log topics and `studyctl park` to park questions.\n"
        )

    # Create a studyctl wrapper in the session directory that uses the
    # correct Python (the one running this process). Without this, the
    # Homebrew-installed studyctl (old version) shadows the dev version
    # and `studyctl topic` fails with "unknown command".
    wrapper = session_dir / "studyctl"
    wrapper.write_text(f'#!/bin/sh\nexec {sys.executable} -m studyctl.cli "$@"\n')
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # Clean up stale tmux session with same name
    if session_exists(session_name):
        kill_session(session_name)

    # Build commands before creating panes
    persona_file = build_persona_file(mode, topic, energy, previous_notes=previous_notes)

    # Allow integration tests to inject a mock agent command
    import os

    test_agent_cmd = os.environ.get("STUDYCTL_TEST_AGENT_CMD")
    if test_agent_cmd:
        agent_cmd = test_agent_cmd.format(persona_file=persona_file)
    else:
        agent_cmd = get_launch_command(agent, persona_file, resume=is_resuming)

    import sys

    python = sys.executable
    sidebar_cmd = f"{python} -m studyctl.tui.sidebar"

    # Prepend session dir to PATH so the studyctl wrapper is found
    # (the agent spawns bash subprocesses that need to find studyctl).
    path_prefix = f"export PATH={session_dir}:$PATH; "

    # Wrap the agent command so that when the agent exits (user quits
    # Claude, types /exit, or Ctrl+C), the session cleans up automatically.
    wrapped_agent_cmd = (
        f"{path_prefix}"
        f"{agent_cmd}; "
        f'{python} -c "'
        f"from studyctl.cli._study import _cleanup_session; "
        f"_cleanup_session()"
        f'"'
    )

    # Create session in the session directory — agent conversation history
    # (.claude/, .kiro/, etc.) is preserved here across sessions.
    main_pane = create_session(
        session_name,
        command=wrapped_agent_cmd,
        cwd=str(session_dir),
    )

    # Set PATH for all panes in this session so the studyctl wrapper
    # in the session dir is found first (before any globally installed
    # older version). Uses tmux set-environment so ALL panes inherit it.
    from studyctl.tmux import set_environment

    current_path = os.environ.get("PATH", "")
    set_environment(session_name, "PATH", f"{session_dir}:{current_path}")

    # Ensure panes are destroyed when their commands exit. Without this,
    # user/plugin tmux configs may keep dead panes alive (remain-on-exit on),
    # preventing the session from auto-destroying after Q.
    from studyctl.tmux import set_option

    set_option(session_name, "remain-on-exit", "off")
    # When the session is destroyed, detach the client (return to original
    # shell) rather than switching to another tmux session. Critical for
    # non-technical users who don't want to be stranded in tmux.
    set_option(session_name, "detach-on-destroy", "on")

    # Load user's studyctl tmux overlay if they've explicitly created one.
    # We do NOT auto-load a bundled config — it would clobber the user's
    # theme (catppuccin, dracula, etc.), prefix, and keybindings.
    # The bundled data/tmux-studyctl.conf serves as a reference/template.
    import contextlib

    user_conf = SESSION_DIR / "tmux-studyctl.conf"
    if user_conf.exists():
        with contextlib.suppress(Exception):
            load_config(user_conf)

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
            "session_dir": str(session_dir),
            "agent": agent,
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
    """Resume an existing study session.

    Two resume scenarios:
    1. tmux session still alive → reattach/switch to it
    2. tmux session dead but session dir exists → create new tmux session
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

    # Scenario 1: tmux session is still alive AND agent is running — reconnect
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

        # tmux session is zombie (agent exited) — kill it and rebuild
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
        previous_notes = _get_previous_session_notes(state.get("study_session_id"))

        console.print(
            f"[green]Resuming conversation:[/green] {topic}\n"
            f"  [dim]Rebuilding tmux session with conversation history[/dim]"
        )
        # State file has mode=ended, is_session_active() returns False — no need to clear
        # Rebuild tmux in the SAME session directory (preserves conversation history)
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


def _handle_end(_ctx: click.Context) -> None:
    """End the current study session cleanly."""
    from studyctl.history import end_study_session
    from studyctl.session_state import (
        read_session_state,
        write_session_state,
    )

    state = read_session_state()
    study_id = state.get("study_session_id")
    persona_file = state.get("persona_file")

    if not study_id:
        console.print("[yellow]No active session found.[/yellow]")
        return

    topic = state.get("topic", "unknown")

    # Capture session context before ending
    from studyctl.session_state import parse_parking_file, parse_topics_file

    notes = _build_session_notes(parse_topics_file(), parse_parking_file())

    # End the DB session with captured notes
    end_study_session(study_id, notes=notes)

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
    with contextlib.suppress(OSError):
        oneline.unlink()

    console.print(f"[bold]Session ended:[/bold] {topic}")

    # Kill all study tmux sessions (current + any stale ones).
    # No switch_client — we want the tmux client to exit, returning
    # the user to their original shell.
    from studyctl.tmux import kill_all_study_sessions

    kill_all_study_sessions()
    console.print("  tmux session closed.")

    # Clear transient IPC files but KEEP session-state.json (with mode=ended).
    # The state file is needed by --resume to find the session directory
    # and metadata. It's cleared when a new session starts.
    from studyctl.session_state import PARKING_FILE, TOPICS_FILE

    for f in [TOPICS_FILE, PARKING_FILE, oneline]:
        with contextlib.suppress(OSError):
            f.unlink()


def _get_previous_session_notes(study_id: str | None) -> str | None:
    """Fetch the notes from a previous study session in the DB."""
    if not study_id:
        return None
    try:
        import sqlite3

        from studyctl.settings import get_db_path

        conn = sqlite3.connect(str(get_db_path()))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT notes FROM study_sessions WHERE id = ?", (study_id,)).fetchone()
        conn.close()
        return row["notes"] if row and row["notes"] else None
    except Exception:
        return None


def _build_session_notes(
    topics: list,
    parking: list,
) -> str:
    """Build a summary of the session for the DB notes field.

    This is what ``--resume`` uses to give the agent context about
    where the conversation was when the session ended.
    """
    lines: list[str] = []

    wins = [t for t in topics if t.status in ("win", "insight")]
    struggles = [t for t in topics if t.status == "struggling"]
    learning = [t for t in topics if t.status == "learning"]

    if wins:
        lines.append("Wins: " + ", ".join(t.topic for t in wins))
    if learning:
        lines.append("In progress: " + ", ".join(t.topic for t in learning))
    if struggles:
        lines.append("Struggling: " + ", ".join(t.topic for t in struggles))
    if parking:
        lines.append("Parked: " + ", ".join(p.question for p in parking))

    if not lines:
        lines.append("No topics recorded during session.")

    return "\n".join(lines)


def _cleanup_session() -> None:
    """Auto-cleanup when the agent process exits.

    Called by the wrapper shell command in the main tmux pane. This runs
    inside the tmux session, so it can switch the client back before
    killing the session.
    """
    import contextlib
    import os

    from studyctl.history import end_study_session
    from studyctl.session_state import (
        PARKING_FILE,
        SESSION_DIR,
        TOPICS_FILE,
        parse_parking_file,
        parse_topics_file,
        read_session_state,
        write_session_state,
    )

    state = read_session_state()
    study_id = state.get("study_session_id")
    session_name = state.get("tmux_session")
    persona_file = state.get("persona_file")

    if not study_id:
        return

    # Capture session context as notes before ending.
    # This is what --resume uses to give the agent context about
    # where the conversation left off.
    notes = _build_session_notes(
        parse_topics_file(),
        parse_parking_file(),
    )

    # End the DB session with captured notes
    with contextlib.suppress(Exception):
        end_study_session(study_id, notes=notes)

    # Signal dashboard summary view
    with contextlib.suppress(Exception):
        write_session_state({"mode": "ended"})

    # Clean up temp files
    if persona_file:
        with contextlib.suppress(OSError):
            os.unlink(persona_file)
    oneline = SESSION_DIR / "session-oneline.txt"
    with contextlib.suppress(OSError):
        oneline.unlink()

    # Fire-and-forget: kill ALL study tmux sessions. We're running INSIDE
    # the session (agent wrapper pane), so tmux will SIGHUP us. Don't use
    # kill_session() (retry loop) — we won't survive to verify.
    # Killing all study-* sessions ensures no stale sessions accumulate.
    with contextlib.suppress(Exception):
        from studyctl.tmux import kill_all_study_sessions

        kill_all_study_sessions(current_session=session_name)

    # Clear transient IPC files but KEEP session-state.json (mode=ended).
    # Needed by --resume to find the session directory.
    for f in [TOPICS_FILE, PARKING_FILE, oneline]:
        with contextlib.suppress(OSError):
            f.unlink()


def _start_web_background(_session_name: str) -> None:
    """Start the web dashboard as a background process."""
    import shutil
    import subprocess
    import sys

    # Use the studyctl entry point if installed, otherwise python -m
    studyctl_bin = shutil.which("studyctl")
    cmd = (
        [studyctl_bin, "web", "--port", "8567"]
        if studyctl_bin
        else [sys.executable, "-m", "studyctl.cli", "web", "--port", "8567"]
    )
    try:
        proc = subprocess.Popen(
            cmd,
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
