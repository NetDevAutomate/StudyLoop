"""Study command -- one command to create the complete study environment.

Thin CLI dispatcher that delegates to session/ package for orchestration,
resume, and cleanup.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import click

from studyloop.cli._shared import console

if TYPE_CHECKING:
    from studyloop.settings import TopicConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StudySessionSelection:
    """Resolved startup choice from the textual study picker."""

    topic: str
    mode: str
    topic_config: TopicConfig | None = None


def _resolve_topic_config(topic: str) -> TopicConfig | None:
    """Resolve free-text topic to a TopicConfig. Returns None on no match."""
    import contextlib

    with contextlib.suppress(Exception):
        from studyloop.logic.topic_resolver import resolve_topic
        from studyloop.settings import load_settings

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


def _first_existing_study_root() -> Path:
    """Return the preferred configured study root, even if it does not exist yet."""
    from studyloop.settings import load_settings

    settings = load_settings()
    roots = settings.content.study_paths or [Path.home() / "Obsidian" / "Personal" / "Study"]
    for root in roots:
        expanded = root.expanduser()
        if expanded.is_dir():
            return expanded
    return roots[0].expanduser()


def _child_dirs(path: Path) -> list[Path]:
    """Return visible child directories sorted for picker display."""
    if not path.is_dir():
        return []
    return sorted(
        [child for child in path.iterdir() if child.is_dir() and not child.name.startswith(".")],
        key=lambda p: p.name.lower(),
    )


def _prompt_choice(title: str, options: list[str]) -> int | None:
    """Prompt for a numbered choice. Returns zero-based index or None."""
    console.print(f"\n[bold]{title}[/bold]")
    for index, label in enumerate(options, 1):
        console.print(f"  [bold]{index}[/bold]. {label}")
    console.print("  [bold]0[/bold]. Cancel")
    try:
        choice = click.prompt("Select", type=int, default=1)
    except (click.Abort, EOFError):
        return None
    if choice == 0:
        return None
    if 1 <= choice <= len(options):
        return choice - 1
    console.print("[red]Invalid selection.[/red]")
    return None


def _topic_from_path(path: Path, fallback: str) -> str:
    """Build a readable topic label from a selected directory."""
    name = path.name.replace("_", " ").replace("-", " ").strip()
    return name or fallback


def _prompt_study_session() -> StudySessionSelection | None:
    """Textual startup picker for no-argument ``studyloop study``."""
    study_root = _first_existing_study_root()
    selected = _prompt_choice(
        "Start Study Session",
        [
            "Body Double",
            f"Course Material or Topic ({study_root})",
            f"Course Vendor ({study_root / 'Courses'})",
            f"Course ({study_root / 'Courses' / '<vendor>' / '<course>'})",
        ],
    )
    if selected is None:
        return None

    if selected == 0:
        return StudySessionSelection(topic="Body Double", mode="co-study")

    if selected == 1:
        topic_dirs = _child_dirs(study_root)
        if not topic_dirs:
            topic = click.prompt("Topic", default="Study Session")
            return StudySessionSelection(topic=topic, mode="study")
        choice = _prompt_choice("Choose Topic Directory", [path.name for path in topic_dirs])
        if choice is None:
            return None
        path = topic_dirs[choice]
        return StudySessionSelection(topic=_topic_from_path(path, "Study Session"), mode="study")

    courses_root = study_root / "Courses"
    vendors = _child_dirs(courses_root)
    if not vendors:
        console.print(f"[yellow]No course vendors found under {courses_root}[/yellow]")
        return None

    vendor_choice = _prompt_choice("Choose Course Vendor", [path.name for path in vendors])
    if vendor_choice is None:
        return None
    vendor = vendors[vendor_choice]

    if selected == 2:
        return StudySessionSelection(topic=_topic_from_path(vendor, "Course Vendor"), mode="study")

    courses = _child_dirs(vendor)
    if not courses:
        console.print(f"[yellow]No courses found under {vendor}[/yellow]")
        return None
    course_choice = _prompt_choice("Choose Course", [path.name for path in courses])
    if course_choice is None:
        return None
    course = courses[course_choice]
    return StudySessionSelection(topic=_topic_from_path(course, "Course"), mode="study")


def _agent_names() -> list[str]:
    """Registered agent names for CLI --agent choices."""
    from studyloop.agent_launcher import AGENTS

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

        studyloop study "Python Decorators" --energy 7

        studyloop study "Spark Internals" --mode co-study --timer pomodoro

        studyloop study --resume

        studyloop study --end
    """
    if end_session:
        _handle_end(ctx)
        return

    if resume:
        from studyloop.session.resume import handle_resume

        handle_resume(ctx, start_fn=_handle_start)
        return

    topic_config = None
    if not topic:
        selection = _prompt_study_session()
        if selection is None:
            ctx.exit(1)
            return
        topic = selection.topic
        mode = selection.mode
        topic_config = selection.topic_config

    # Resolve defaults
    if timer is None:
        timer = "pomodoro" if mode == "co-study" else "elapsed"

    if lan:
        web = True

    # Resolve free-text topic to a TopicConfig (for briefing, content, review)
    if topic_config is None:
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
    from studyloop.session.start import SessionStartError, start_session

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
    from studyloop.session.cleanup import end_session_common
    from studyloop.session_state import read_session_state

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
    """Run the Textual sidebar app (launched by studyloop study in tmux)."""
    try:
        from studyloop.tui.sidebar import run_sidebar  # type: ignore[import-not-found]
    except ImportError:
        console.print(
            "[red]Textual is required for the sidebar.[/red]\n"
            "  Install: pip install 'studyloop[tui]'"
        )
        raise SystemExit(1) from None

    run_sidebar()
