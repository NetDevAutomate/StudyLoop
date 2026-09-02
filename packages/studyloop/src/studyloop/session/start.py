"""Session start orchestration — tmux environment setup, DB record, agent launch.

This module owns the logic of *starting* a study session. It is framework-agnostic:
no Click imports, no CLI concerns. Callers (CLI, web API, tests) catch
``SessionStartError`` and translate it to their own error representation.

The CLI wrapper in ``cli/_study.py`` is the primary caller; it calls ``ctx.exit(1)``
when this module raises ``SessionStartError``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from studyloop.output import console
from studyloop.web.runtime_feedback import (
    LanCredentialFeedback,
    build_web_access_info,
    format_lan_credential_lines,
)

if TYPE_CHECKING:
    from studyloop.logic.briefing_logic import ContentContext, ReviewContext
    from studyloop.settings import TopicConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------


class SessionStartError(Exception):
    """Raised when session startup cannot proceed.

    Callers should print ``self.message`` to the user and exit with code 1.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _rollback_failed_startup(
    *,
    study_id: str | None,
    session_name: str | None,
    session_dir,
    remove_session_dir: bool,
    reason: str,
) -> None:
    """Best-effort cleanup when startup fails after partial initialization."""
    import shutil
    from pathlib import Path

    from studyloop.history import abort_study_session
    from studyloop.multiplexer import get_backend
    from studyloop.session_state import SESSION_DIR, clear_session_files

    if study_id:
        abort_study_session(study_id, f"Startup failed: {reason}")

    if session_name:
        mux = get_backend()
        if mux.session_exists(session_name):
            try:
                mux.kill_session(session_name)
            except Exception:
                logger.warning("failed to kill partially started session %s", session_name)

    try:
        clear_session_files()
    except Exception:
        logger.warning("failed to clear session IPC files after startup failure", exc_info=True)

    oneline = SESSION_DIR / "session-oneline.txt"
    try:
        oneline.unlink(missing_ok=True)
    except OSError:
        logger.warning("failed to remove session-oneline.txt after startup failure", exc_info=True)

    if remove_session_dir and session_dir:
        try:
            shutil.rmtree(Path(session_dir), ignore_errors=True)
        except Exception:
            logger.warning("failed to remove session dir after startup failure", exc_info=True)


# ---------------------------------------------------------------------------
# Briefing / backlog helpers
# ---------------------------------------------------------------------------


def _build_backlog_notes(topic: str) -> str | None:
    """Gather pending backlog items and build a summary for the agent persona.

    Returns None if no pending items. Uses FCIS pattern — gather data
    from parking.py, delegate formatting to backlog_logic.
    """
    import contextlib

    with contextlib.suppress(Exception):
        from studyloop.logic.backlog_logic import BacklogItem, build_backlog_summary
        from studyloop.parking import get_parked_topics

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
        from studyloop.logic.briefing_logic import ReviewContext
        from studyloop.services.review import get_due, get_stats

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

        from studyloop.logic.briefing_logic import ContentContext

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


def build_study_briefing(topic_config: TopicConfig | None) -> str | None:
    """Gather review stats + content inventory, format as briefing markdown.

    Returns None if no topic_config (graceful degradation — identical to
    today's behaviour when no TopicConfig is resolved).
    """
    if not topic_config:
        return None

    import contextlib

    with contextlib.suppress(Exception):
        from studyloop.logic.briefing_logic import BriefingData, format_study_briefing
        from studyloop.settings import load_settings

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


def brief_summary(topic_config: TopicConfig | None) -> str:
    """One-line terminal summary for user orientation."""
    if not topic_config:
        return ""
    return f"Topic resolved: {topic_config.name} ({topic_config.slug})"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def start_session(
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
    """Start a new study session with tmux environment.

    Raises:
        SessionStartError: When startup cannot proceed (tmux missing, no agent,
            session already active, DB failure). The caller should print
            ``error.message`` and exit with code 1.
    """
    from pathlib import Path

    from studyloop.agent_launcher import (
        AGENTS,
        build_canonical_persona,
        detect_agents,
    )
    from studyloop.history import start_study_session
    from studyloop.multiplexer import get_backend
    from studyloop.session.orchestrator import (
        attach_if_needed,
        build_wrapped_agent_cmd,
        create_tmux_environment,
        setup_session_dir,
        start_web_background,
    )
    from studyloop.session_state import (
        PARKING_FILE,
        SESSION_DIR,
        TOPICS_FILE,
        _ensure_session_dir,
        claim_blocks_cli_start,
        read_session_state,
        write_session_state,
    )

    mux = get_backend()

    # --- Pre-flight checks ---

    if not mux.is_available():
        raise SessionStartError(
            "[red]Terminal multiplexer is required but not available.[/red]\n"
            "  Install: [bold]brew install tmux[/bold] (macOS) or "
            "[bold]apt install tmux[/bold] (Linux)"
        )

    try:
        import textual  # noqa: F401
    except ImportError as exc:
        raise SessionStartError(
            "[red]The study sidebar requires Textual, but it is not installed.[/red]\n"
            "  Reinstall or add the TUI extra: pip install 'studyloop[tui]'"
        ) from exc

    from studyloop.session.cleanup import auto_clean_zombies

    auto_clean_zombies()

    if agent is None:
        available = detect_agents()
        if not available:
            raise SessionStartError(
                "[red]No AI agent found.[/red]\n"
                "  Install one of: Kiro CLI, Codex, Claude Code, OpenCode, or pi\n"
                "  e.g. [bold]npm install -g @anthropic-ai/claude-code[/bold]"
            )
        agent = available[0]

    # R-01b: a claim EXISTING no longer blocks unconditionally — only a
    # claim whose recorded owner is provably still alive does. A stale
    # claim (owner dead) is reclaimed instead of refused forever, exactly
    # as the web start path already does (docs/architecture/
    # session-authority.md clause 2). is_session_active() is unchanged and
    # still answers "does a claim exist", but no longer gates the start.
    claim = read_session_state()
    if claim_blocks_cli_start(claim):
        raise SessionStartError(
            "[yellow]A session is already active.[/yellow]\n"
            "  Resume: [bold]studyloop study --resume[/bold]\n"
            "  End:    [bold]studyloop study --end[/bold]"
        )
    if claim.get("study_session_id") and claim.get("mode") != "ended":
        logger.warning(
            "Reclaiming stale session claim id=%s transport=%s — its owner is no longer alive",
            claim.get("study_session_id"),
            claim.get("transport", "cli"),
        )

    # --- Create DB session ---

    from studyloop.output import energy_to_label

    energy_label = energy_to_label(energy)

    study_id = start_study_session(
        topic, energy_label, topic_slug=topic_config.slug if topic_config else None
    )
    if not study_id:
        raise SessionStartError(
            "[red]Failed to create session in DB.[/red]\n"
            "  Likely cause: agent-session-tools not installed or sessions DB has no schema.\n"
            "  Fix: [bold]uv pip install agent-session-tools[/bold], then retry.\n"
            "  Run [bold]studyloop doctor[/bold] for full diagnostics."
        )

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

    remove_session_dir_on_failure = False
    if resume_session_name and resume_session_dir:
        session_name = resume_session_name
        session_dir = Path(resume_session_dir)
        is_resuming = True
    else:
        # slug_session_dir strips path traversal from the user-controlled topic
        # (this dir is later rmtree'd on failure, so an unsanitised "../.." is a
        # real escape vector — shared with the web session-start paths).
        from studyloop.web.services.session_start import slug_session_dir

        slug = slug_session_dir(topic)
        short_id = study_id[:8] if study_id else "unknown"
        session_name = f"study-{slug}-{short_id}"
        session_dir = SESSION_DIR / "sessions" / session_name
        remove_session_dir_on_failure = True
        claude_project_key = str(session_dir).replace("/", "-").lstrip("-")
        claude_project_dir = Path.home() / ".claude" / "projects" / claude_project_key
        is_resuming = claude_project_dir.exists()

    # Clean up stale session with same name
    if mux.session_exists(session_name):
        mux.kill_session(session_name)

    # --- Build commands and orchestrate tmux ---

    try:
        setup_session_dir(session_dir, topic)

        backlog_notes = _build_backlog_notes(topic)
        if backlog_notes:
            previous_notes = (
                f"{previous_notes}\n\n{backlog_notes}" if previous_notes else backlog_notes
            )

        # Build study briefing from topic resolution (review stats, content inventory)
        briefing = build_study_briefing(topic_config)
        if briefing:
            previous_notes = f"{previous_notes}\n\n{briefing}" if previous_notes else briefing
            # Echo brief summary to terminal for user orientation
            console.print(f"\n[dim]{brief_summary(topic_config)}[/dim]")

        # Build persona + MCP config via adapter pattern
        adapter = AGENTS[agent]
        canonical = build_canonical_persona(mode, topic, energy, previous_notes=previous_notes)

        # Track persona version for effectiveness analysis
        import hashlib

        persona_hash = hashlib.sha256(canonical.encode()).hexdigest()[:16]
        from studyloop.history.sessions import update_persona_hash

        try:
            update_persona_hash(study_id, persona_hash)
        except Exception:
            logger.warning("failed to persist persona hash for %s", study_id, exc_info=True)

        persona_file = adapter.setup(canonical, session_dir)
        if adapter.mcp_setup:
            adapter.mcp_setup(session_dir)

        # Allow integration tests to inject a test-only agent command.
        # Import-time snapshot (R-09c), not os.environ directly -- see
        # studyloop.test_hatch_env: a dotenv loader that runs later in the
        # process cannot re-inject this key if nothing ever re-reads
        # os.environ for it.
        from studyloop import test_hatch_env

        test_agent_cmd = test_hatch_env("STUDYLOOP_TEST_AGENT_CMD")
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

        # Store session metadata in session state for resume/end
        state_update = {
            "tmux_session": session_name,  # legacy key
            "tmux_main_pane": result["tmux_main_pane"],  # legacy key
            "tmux_sidebar_pane": result["tmux_sidebar_pane"],  # legacy key
            "mux_session": session_name,
            "mux_main_pane": result["mux_main_pane"],
            "mux_sidebar_pane": result["mux_sidebar_pane"],
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
        lan_password_generated = False
        if lan:
            try:
                from studyloop.settings import load_settings as _ls_inner

                _settings = _ls_inner()
                lan_username = _settings.lan_username or "study"
                if not lan_password:
                    lan_password = _settings.lan_password
            except Exception:
                pass
        if lan and not lan_password:
            import secrets

            lan_password = secrets.token_urlsafe(16)
            lan_password_generated = True

        if lan and lan_password:
            console.print()
            for line in format_lan_credential_lines(
                LanCredentialFeedback(
                    username=lan_username,
                    password=lan_password,
                    password_generated=lan_password_generated,
                )
            ):
                console.print(line)

        if web:
            start_web_background(session_name, lan=lan, password=lan_password)

        # Persist LAN info to session state so it's visible after os.execvp
        if lan:
            import socket

            try:
                hostname = socket.gethostname()
                lan_ip = socket.gethostbyname(hostname)
            except Exception:
                lan_ip = "<your-ip>"
            from studyloop.session.orchestrator import _get_web_port

            web_port = _get_web_port()
            access_info = build_web_access_info(
                bind_host="0.0.0.0",
                port=web_port,
                lan_enabled=True,
                lan_hosts=(lan_ip,),
                path="/session",
            )
            lan_url = access_info.lan_urls[0] if access_info.lan_urls else access_info.local_url
            write_session_state(
                {
                    "lan_ip": lan_ip,
                    "lan_password": lan_password,
                    "lan_url": lan_url,
                }
            )

            # Print LAN info — this shows briefly before tmux takes over,
            # but is also saved in session state (visible via web dashboard
            # and `studyloop study --resume` output).
            console.print("\n[bold]LAN access:[/bold]")
            console.print(f"  Dashboard: {lan_url}")
            console.print(f"  Username:  {lan_username}")
            if lan_password_generated:
                console.print(f"  Password:  {lan_password}")
            elif lan_password:
                console.print("  Password:  configured; not shown")

        attach_if_needed(session_name, result["already_in_tmux"])
    except Exception as exc:
        _rollback_failed_startup(
            study_id=study_id,
            session_name=session_name,
            session_dir=session_dir,
            remove_session_dir=remove_session_dir_on_failure,
            reason=str(exc),
        )
        raise SessionStartError(
            f"[red]Failed to start study session.[/red]\n  Cause: {exc}"
        ) from exc
