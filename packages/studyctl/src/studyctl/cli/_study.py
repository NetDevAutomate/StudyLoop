"""Study command -- one command to create the complete study environment.

Thin CLI dispatcher that delegates to session/ package for orchestration,
resume, and cleanup. FCIS helpers (zombie cleanup, backlog, auto-persist)
remain here as thin wrappers over logic/ modules.
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
        from studyctl.session.resume import handle_resume

        handle_resume(ctx)
        return

    if not topic:
        console.print("[red]Topic is required. Usage: studyctl study 'topic'[/red]")
        ctx.exit(1)
        return

    # Resolve defaults
    if timer is None:
        timer = "pomodoro" if mode == "co-study" else "elapsed"

    _handle_start(ctx, topic, agent, mode, timer, energy, web)


def _auto_clean_zombies() -> None:
    """Silently kill zombie study sessions before starting a new one.

    Handles tmux-resurrect restoring previously killed sessions.
    Uses the FCIS clean logic -- gather data, decide, execute.
    Runs quietly: no output unless something goes wrong.
    """
    import contextlib
    import shutil

    from studyctl.logic.clean_logic import DirInfo, plan_clean
    from studyctl.session_state import SESSION_DIR, STATE_FILE, read_session_state
    from studyctl.tmux import (
        is_tmux_server_running,
        is_zombie_session,
        kill_session,
        list_study_sessions,
    )

    with contextlib.suppress(Exception):
        tmux_running = is_tmux_server_running()
        if not tmux_running:
            return

        study_sessions = list_study_sessions()
        zombie_sessions = [s for s in study_sessions if is_zombie_session(s)]

        sessions_dir = SESSION_DIR / "sessions"
        session_dirs = (
            [
                DirInfo(name=d.name, path=d, is_symlink=d.is_symlink())
                for d in sorted(sessions_dir.iterdir())
                if d.is_dir() or d.is_symlink()
            ]
            if sessions_dir.exists()
            else []
        )

        plan = plan_clean(
            tmux_running=True,
            zombie_sessions=zombie_sessions,
            session_dirs=session_dirs,
            live_tmux_names=set(study_sessions),
            state=read_session_state(),
            state_file_exists=STATE_FILE.exists(),
        )

        if not plan.has_work:
            return

        for name in plan.sessions_to_kill:
            kill_session(name)
        for path in plan.dirs_to_remove:
            shutil.rmtree(path, ignore_errors=True)
        if plan.state_to_clean:
            STATE_FILE.unlink(missing_ok=True)

        if plan.sessions_to_kill:
            console.print(
                f"[dim]Cleaned {len(plan.sessions_to_kill)} "
                f"stale session{'s' if len(plan.sessions_to_kill) != 1 else ''} "
                f"(tmux-resurrect)[/dim]"
            )


def _build_backlog_notes(topic: str) -> str | None:
    """Gather pending backlog items and build a summary for the agent persona.

    Returns None if no pending items. Uses FCIS pattern -- gather data
    from parking.py, delegate formatting to backlog_logic.
    """
    import contextlib

    with contextlib.suppress(Exception):
        from studyctl.logic.backlog_logic import BacklogItem, build_backlog_summary
        from studyctl.parking import get_parked_topics

        raw = get_parked_topics(status="pending")
        if not raw:
            return None
        items = [
            BacklogItem(
                id=t["id"],
                question=t["question"],
                topic_tag=t.get("topic_tag"),
                tech_area=t.get("tech_area"),
                source=t.get("source", "parked"),
                context=t.get("context"),
                parked_at=t["parked_at"],
                session_topic=None,
            )
            for t in raw
        ]
        return build_backlog_summary(items, topic)
    return None


def _auto_persist_struggled(
    study_session_id: str,
    topic_entries: list,
) -> None:
    """Persist struggled topics from session-topics.md to the backlog.

    Uses FCIS pattern -- plan_auto_persist decides what to persist,
    then we execute by calling park_topic for each action.
    """
    import contextlib

    with contextlib.suppress(Exception):
        from studyctl.logic.backlog_logic import plan_auto_persist
        from studyctl.parking import get_parked_topics, park_topic

        # Gather existing questions for this session to deduplicate
        existing = get_parked_topics(study_session_id=study_session_id)
        existing_questions = {t["question"] for t in existing}

        # Decide
        actions = plan_auto_persist(topic_entries, existing_questions, study_session_id)

        # Execute
        persisted = 0
        for action in actions:
            result = park_topic(
                question=action.question,
                topic_tag=action.topic_tag,
                context=action.context,
                study_session_id=action.study_session_id,
                source=action.source,
            )
            if result:
                persisted += 1

        if persisted:
            console.print(
                f"[dim]Saved {persisted} struggled "
                f"topic{'s' if persisted != 1 else ''} to backlog[/dim]"
            )


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
    """Start a new study session with tmux environment."""
    from pathlib import Path

    from studyctl.agent_launcher import build_persona_file, detect_agents, get_launch_command
    from studyctl.history import start_study_session
    from studyctl.session.orchestrator import (
        attach_if_needed,
        build_wrapped_agent_cmd,
        create_tmux_environment,
        setup_session_dir,
        start_web_background,
    )
    from studyctl.session_state import (
        PARKING_FILE,
        SESSION_DIR,
        TOPICS_FILE,
        _ensure_session_dir,
        is_session_active,
        write_session_state,
    )
    from studyctl.tmux import is_tmux_available, kill_session, session_exists

    # --- Pre-flight checks ---

    if not is_tmux_available():
        console.print(
            "[red]tmux 3.1+ is required but not found.[/red]\n"
            "  Install: [bold]brew install tmux[/bold] (macOS) or "
            "[bold]apt install tmux[/bold] (Linux)"
        )
        ctx.exit(1)
        return

    _auto_clean_zombies()

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

    if is_session_active():
        console.print(
            "[yellow]A session is already active.[/yellow]\n"
            "  Resume: [bold]studyctl study --resume[/bold]\n"
            "  End:    [bold]studyctl study --end[/bold]"
        )
        ctx.exit(1)
        return

    # --- Create DB session ---

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

    # Write session state
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
    TOPICS_FILE.touch(mode=0o600, exist_ok=True)
    PARKING_FILE.touch(mode=0o600, exist_ok=True)

    # --- Resolve session directory ---

    if resume_session_name and resume_session_dir:
        session_name = resume_session_name
        session_dir = Path(resume_session_dir)
        is_resuming = True
    else:
        slug = topic.lower().replace(" ", "-")[:20]
        short_id = study_id[:8] if study_id else "unknown"
        session_name = f"study-{slug}-{short_id}"
        session_dir = SESSION_DIR / "sessions" / session_name
        claude_project_key = str(session_dir).replace("/", "-").lstrip("-")
        claude_project_dir = Path.home() / ".claude" / "projects" / claude_project_key
        is_resuming = claude_project_dir.exists()

    # Clean up stale tmux session with same name
    if session_exists(session_name):
        kill_session(session_name)

    # --- Build commands and orchestrate tmux ---

    setup_session_dir(session_dir, topic)

    backlog_notes = _build_backlog_notes(topic)
    if backlog_notes:
        previous_notes = f"{previous_notes}\n\n{backlog_notes}" if previous_notes else backlog_notes

    persona_file = build_persona_file(mode, topic, energy, previous_notes=previous_notes)

    # Allow integration tests to inject a mock agent command
    import os

    test_agent_cmd = os.environ.get("STUDYCTL_TEST_AGENT_CMD")
    if test_agent_cmd:
        agent_cmd = test_agent_cmd.format(persona_file=persona_file)
    else:
        agent_cmd = get_launch_command(agent, persona_file, resume=is_resuming)

    wrapped_cmd = build_wrapped_agent_cmd(session_dir, agent_cmd)

    result = create_tmux_environment(
        session_name=session_name,
        session_dir=session_dir,
        wrapped_agent_cmd=wrapped_cmd,
        session_state_dir=SESSION_DIR,
    )

    # Store tmux metadata in session state for resume/end
    write_session_state(
        {
            "tmux_session": session_name,
            "tmux_main_pane": result["tmux_main_pane"],
            "tmux_sidebar_pane": result["tmux_sidebar_pane"],
            "persona_file": str(persona_file),
            "session_dir": str(session_dir),
            "agent": agent,
        }
    )

    if web:
        start_web_background(session_name)

    attach_if_needed(session_name, result["already_in_tmux"])


def _handle_end(_ctx: click.Context) -> None:
    """End the current study session cleanly (user-facing)."""
    from studyctl.session.cleanup import end_session_common
    from studyctl.session_state import read_session_state

    state = read_session_state()

    if not state.get("study_session_id"):
        console.print("[yellow]No active session found.[/yellow]")
        return

    topic = end_session_common(state)
    if topic:
        console.print(f"[bold]Session ended:[/bold] {topic}")
        console.print("  tmux session closed.")


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
