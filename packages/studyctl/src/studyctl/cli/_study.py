"""Study command -- one command to create the complete study environment.

Thin CLI dispatcher that delegates to session/ package for orchestration,
resume, and cleanup. FCIS helpers (zombie cleanup, backlog, auto-persist)
remain here as thin wrappers over logic/ modules.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import click

from studyctl.cli._shared import console

if TYPE_CHECKING:
    from studyctl.logic.briefing_logic import ContentContext, ReviewContext
    from studyctl.settings import TopicConfig

logger = logging.getLogger(__name__)


def _resolve_topic_config(topic: str) -> TopicConfig | None:
    """Resolve free-text topic to a TopicConfig. Returns None on no match."""
    import contextlib

    with contextlib.suppress(Exception):
        from studyctl.logic.topic_resolver import resolve_topic
        from studyctl.settings import load_settings

        settings = load_settings()
        if not settings.topics:
            return None

        result = resolve_topic(topic, settings.topics)

        if result.resolved:
            return result.resolved

        if result.matches:
            return _interactive_pick(result.matches, topic)

    return None


def _interactive_pick(candidates: list[TopicConfig], query: str) -> TopicConfig | None:
    """Show a numbered list picker for ambiguous topic matches."""

    console.print(f"\n[yellow]'{query}' matches multiple topics:[/yellow]")
    for i, t in enumerate(candidates, 1):
        tags = f" ({', '.join(t.tags)})" if t.tags else ""
        console.print(f"  [bold]{i}[/bold]. {t.name}{tags}")
    console.print("  [bold]0[/bold]. Skip (no briefing)")

    try:
        choice = click.prompt("Select", type=int, default=0)
        if 1 <= choice <= len(candidates):
            return candidates[choice - 1]
    except (click.Abort, EOFError):
        pass
    return None


def _agent_names() -> list[str]:
    """Registered agent names for CLI --agent choices."""
    from studyctl.agent_launcher import AGENTS

    return list(AGENTS.keys())


@click.command()
@click.argument("topic", required=False)
@click.option(
    "--agent",
    "-a",
    type=click.Choice(sorted(_agent_names())),
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
@click.option("--lan", is_flag=True, help="Expose web dashboard + terminal to LAN (implies --web).")
@click.option(
    "--password",
    default="",
    help="Password for HTTP Basic Auth when using --lan (auto-generated if not set).",
)
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
    lan: bool,
    password: str,
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

    if lan:
        web = True

    # Resolve free-text topic to a TopicConfig (for briefing, content, review)
    topic_config = _resolve_topic_config(topic)

    _handle_start(
        ctx,
        topic,
        agent,
        mode,
        timer,
        energy,
        web,
        lan=lan,
        password=password,
        topic_config=topic_config,
    )


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


def _gather_review_context(course_name: str) -> ReviewContext | None:
    """Gather review stats for a course. Returns None on any failure."""
    try:
        from studyctl.logic.briefing_logic import ReviewContext
        from studyctl.services.review import get_due, get_stats

        stats = get_stats(course_name)
        due_cards = get_due(course_name)
        struggling = sum(1 for c in due_cards if not c.last_correct)
        return ReviewContext(
            due_count=len(due_cards),
            struggling_count=struggling,
            mastered_count=stats.get("mastered", 0),
            total_reviews=stats.get("total_reviews", 0),
            flashcard_count=stats.get("flashcard_count", 0),
            quiz_count=stats.get("quiz_count", 0),
        )
    except Exception:
        logger.warning("review context unavailable for %s", course_name)
        return None


def _gather_content_context(content_base, slug: str, obsidian_path) -> ContentContext | None:
    """Gather content inventory for a topic slug. Returns None on any failure."""
    try:
        from pathlib import Path

        from studyctl.logic.briefing_logic import ContentContext

        base = Path(content_base) / slug
        if not base.exists():
            return ContentContext(
                chapter_count=0,
                obsidian_path=str(obsidian_path) if obsidian_path else "",
                content_base=str(content_base),
            )

        chapters_dir = base / "chapters"
        chapter_count = sum(1 for _ in chapters_dir.glob("*.md")) if chapters_dir.exists() else 0

        return ContentContext(
            chapter_count=chapter_count,
            obsidian_path=str(obsidian_path) if obsidian_path else "",
            content_base=str(content_base),
        )
    except Exception:
        logger.warning("content context unavailable for %s", slug)
        return None


def _build_study_briefing(topic_config: TopicConfig | None) -> str | None:
    """Gather review stats + content inventory, format as briefing markdown.

    Returns None if no topic_config (graceful degradation — identical to
    today's behaviour when no TopicConfig is resolved).
    """
    if not topic_config:
        return None

    import contextlib

    with contextlib.suppress(Exception):
        from studyctl.logic.briefing_logic import BriefingData, format_study_briefing
        from studyctl.settings import load_settings

        settings = load_settings()
        warnings: list[str] = []

        review = _gather_review_context(topic_config.slug)
        if review is None:
            warnings.append("Review stats unavailable")

        content = _gather_content_context(
            settings.content.base_path,
            topic_config.slug,
            topic_config.obsidian_path,
        )
        if content is None:
            warnings.append("Content inventory unavailable")

        data = BriefingData(
            topic_name=topic_config.name,
            review=review,
            content=content,
            assembly_warnings=warnings,
        )
        result = format_study_briefing(data)
        return result if result else None

    return None


def _brief_summary(topic_config: TopicConfig | None) -> str:
    """One-line terminal summary for user orientation."""
    if not topic_config:
        return ""
    return f"Topic resolved: {topic_config.name} ({topic_config.slug})"


def _auto_persist_struggled(
    study_session_id: str,
    topic_entries: list,
) -> None:
    """Persist struggled topics from session-topics.md to the backlog.

    Thin CLI wrapper over services.backlog.auto_persist_struggled —
    adds console output.
    """
    try:
        from studyctl.services.backlog import auto_persist_struggled

        persisted = auto_persist_struggled(study_session_id, topic_entries)
        if persisted:
            console.print(
                f"[dim]Saved {persisted} struggled "
                f"topic{'s' if persisted != 1 else ''} to backlog[/dim]"
            )
    except Exception:
        logger.exception("Failed to auto-persist struggled topics to backlog")


def _handle_start(
    ctx: click.Context,
    topic: str,
    agent: str | None,
    mode: str,
    timer: str,
    energy: int,
    web: bool,
    *,
    lan: bool = False,
    password: str = "",
    topic_config: TopicConfig | None = None,
    resume_session_name: str | None = None,
    resume_session_dir: str | None = None,
    previous_notes: str | None = None,
) -> None:
    """Start a new study session with tmux environment."""
    from pathlib import Path

    from studyctl.agent_launcher import (
        AGENTS,
        build_canonical_persona,
        detect_agents,
    )
    from studyctl.history import start_study_session
    from studyctl.session.orchestrator import (
        attach_if_needed,
        build_wrapped_agent_cmd,
        create_tmux_environment,
        setup_session_dir,
        start_ttyd_background,
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
                "  Install one of: Claude Code, Gemini CLI, Kiro CLI, or OpenCode\n"
                "  e.g. [bold]npm install -g @anthropic-ai/claude-code[/bold]"
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

    from studyctl.output import energy_to_label

    energy_label = energy_to_label(energy)

    study_id = start_study_session(
        topic, energy_label, topic_slug=topic_config.slug if topic_config else None
    )
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

    # Build study briefing from topic resolution (review stats, content inventory)
    briefing = _build_study_briefing(topic_config)
    if briefing:
        previous_notes = f"{previous_notes}\n\n{briefing}" if previous_notes else briefing
        # Echo brief summary to terminal for user orientation
        console.print(f"\n[dim]{_brief_summary(topic_config)}[/dim]")

    # Build persona + MCP config via adapter pattern
    adapter = AGENTS[agent]
    canonical = build_canonical_persona(mode, topic, energy, previous_notes=previous_notes)

    # Track persona version for effectiveness analysis
    import hashlib

    persona_hash = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    from studyctl.history.sessions import update_persona_hash

    update_persona_hash(study_id, persona_hash)

    persona_file = adapter.setup(canonical, session_dir)
    if adapter.mcp_setup:
        adapter.mcp_setup(session_dir)

    # Allow integration tests to inject a mock agent command
    import os

    test_agent_cmd = os.environ.get("STUDYCTL_TEST_AGENT_CMD")
    if test_agent_cmd:
        agent_cmd = test_agent_cmd.format(persona_file=persona_file)
    else:
        agent_cmd = adapter.launch_cmd(persona_file, is_resuming)

    wrapped_cmd = build_wrapped_agent_cmd(session_dir, agent_cmd)

    result = create_tmux_environment(
        session_name=session_name,
        session_dir=session_dir,
        wrapped_agent_cmd=wrapped_cmd,
        session_state_dir=SESSION_DIR,
    )

    # Store tmux metadata + topic resolution in session state for resume/end
    state_update = {
        "tmux_session": session_name,
        "tmux_main_pane": result["tmux_main_pane"],
        "tmux_sidebar_pane": result["tmux_sidebar_pane"],
        "persona_file": str(persona_file),
        "session_dir": str(session_dir),
        "agent": agent,
    }
    state_update["persona_hash"] = persona_hash
    if topic_config:
        state_update["topic_slug"] = topic_config.slug
        state_update["topic_config_name"] = topic_config.name
    write_session_state(state_update)

    # Resolve LAN credentials: CLI flag > config > auto-generate
    lan_username = "study"
    lan_password = password
    if lan:
        try:
            from studyctl.settings import load_settings as _ls_inner

            _settings = _ls_inner()
            lan_username = _settings.lan_username or "study"
            if not lan_password:
                lan_password = _settings.lan_password
        except Exception:
            pass
    if lan and not lan_password:
        import secrets

        lan_password = secrets.token_urlsafe(16)

    if lan and lan_password:
        console.print(
            f"\n[bold yellow]LAN credentials:[/bold yellow] "
            f"[green]{lan_username}[/green] / [green]{lan_password}[/green]"
        )
        console.print(
            "[dim]Set lan_username and lan_password in config.yaml to avoid "
            "auto-generated passwords.[/dim]"
        )

    if web:
        start_web_background(session_name, lan=lan, password=lan_password)

    # Start ttyd if installed (allows iPad/LAN terminal access)
    start_ttyd_background(session_name, lan=lan)

    # Persist LAN info to session state so it's visible after os.execvp
    if lan:
        import socket

        try:
            hostname = socket.gethostname()
            lan_ip = socket.gethostbyname(hostname)
        except Exception:
            lan_ip = "<your-ip>"
        from studyctl.session.orchestrator import _get_web_port

        web_port = _get_web_port()
        write_session_state(
            {
                "lan_ip": lan_ip,
                "lan_password": lan_password,
                "lan_url": f"http://{lan_ip}:{web_port}/session",
            }
        )

        # Print LAN info — this shows briefly before tmux takes over,
        # but is also saved in session state (visible via web dashboard
        # and `studyctl study --resume` output).
        console.print("\n[bold]LAN access:[/bold]")
        console.print(f"  Dashboard: http://{lan_ip}:{web_port}/session")
        console.print(f"  Password:  {lan_password}")
        console.print("  Username:  (any value works)")

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
