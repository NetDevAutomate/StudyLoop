"""Study command -- one command to create the complete study environment.

Thin CLI dispatcher that delegates to session/ package for orchestration,
resume, and cleanup.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import click

from studyctl.cli._shared import console

if TYPE_CHECKING:
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

        handle_resume(ctx, start_fn=_handle_start)
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
    """Thin CLI wrapper: delegates to session.start.start_session.

    Translates SessionStartError into console output + ctx.exit(1).
    """
    from studyctl.session.start import SessionStartError, start_session

    try:
        start_session(
            topic,
            agent,
            mode,
            timer,
            energy,
            web,
            lan=lan,
            password=password,
            topic_config=topic_config,
            resume_session_name=resume_session_name,
            resume_session_dir=resume_session_dir,
            previous_notes=previous_notes,
        )
    except SessionStartError as exc:
        console.print(exc.message)
        ctx.exit(1)


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
