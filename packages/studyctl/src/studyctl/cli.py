"""studyctl CLI — sync, plan, and schedule study sessions."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from .config import Topic, get_topics
from .history import spaced_repetition_due, struggle_topics
from .maintenance import dedup_notebook, find_duplicates
from .scheduler import (
    Job,
    install_all,
    install_job,
    list_jobs,
    remove_all,
    remove_job,
)
from .shared import init_config, pull_state, push_state
from .shared import sync_status as shared_sync_status
from .state import SyncState
from .sync import find_changed_sources, find_sources, generate_audio, sync_topic

# Topic keywords for session DB queries
TOPIC_KEYWORDS = {
    "python": [
        "python",
        "pattern",
        "dataclass",
        "protocol",
        "abc",
        "strategy",
        "bridge",
        "decorator",
    ],
    "sql": ["sql", "query", "join", "index", "postgresql", "athena", "redshift", "window function"],
    "data-engineering": [
        "spark",
        "glue",
        "pipeline",
        "etl",
        "airflow",
        "dbt",
        "kafka",
        "partition",
        "dag",
    ],
    "aws-analytics": ["sagemaker", "athena", "redshift", "lake formation", "emr", "glue catalog"],
}

console = Console()


def _get_topic(name: str) -> Topic | None:
    for t in get_topics():
        if t.name == name or name in t.name:
            return t
    return None


@click.group()
@click.version_option()
def cli() -> None:
    """studyctl — AuDHD study pipeline: Obsidian→NotebookLM sync and study management."""


@cli.command()
@click.argument("topic_name", required=False)
@click.option("--all", "sync_all", is_flag=True, help="Sync all topics")
@click.option("--dry-run", is_flag=True, help="Show what would be synced")
def sync(topic_name: str | None, sync_all: bool, dry_run: bool) -> None:
    """Sync Obsidian course notes to NotebookLM notebooks."""
    state = SyncState()
    topics = get_topics() if sync_all else ([_get_topic(topic_name)] if topic_name else [])
    topics = [t for t in topics if t]

    if not topics:
        console.print("[red]Specify a topic name or use --all[/red]")
        console.print("Topics: " + ", ".join(t.name for t in get_topics()))
        raise SystemExit(1)

    for topic in topics:
        result = sync_topic(topic, state, dry_run=dry_run)
        prefix = "[dim]DRY RUN[/dim] " if dry_run else ""
        nb = topic.notebook_id[:8] + "..." if topic.notebook_id else "[yellow]new[/yellow]"
        if result["changed"] == 0:
            console.print(f"{prefix}[dim]{topic.display_name} ({nb}): up to date[/dim]")
        else:
            changed = result["changed"]
            total = result["total"]
            synced = result["synced"]
            failed = result["failed"]
            console.print(
                f"{prefix}[bold]{topic.display_name}[/bold] → {nb}: "
                f"{changed}/{total} to sync, {synced} done, {failed} failed"
            )
            if dry_run and result.get("files"):
                for f in result["files"]:
                    console.print(f"  [dim]  {f}[/dim]")
                if result["changed"] > 10:
                    console.print(f"  [dim]  ... and {result['changed'] - 10} more[/dim]")


@cli.command()
@click.argument("topic_name", required=False)
def status(topic_name: str | None) -> None:
    """Show sync status for topics."""
    state = SyncState()
    topics = [_get_topic(topic_name)] if topic_name else get_topics()
    topics = [t for t in topics if t]

    table = Table(title="Study Pipeline Status")
    table.add_column("Topic", style="bold cyan")
    table.add_column("Notebook", style="dim")
    table.add_column("Sources", justify="right")
    table.add_column("Changed", justify="right")
    table.add_column("Last Sync", style="dim")

    for topic in topics:
        ts = state.get_topic(topic.name)
        total = len(find_sources(topic))
        changed = len(find_changed_sources(topic, state))
        nb = ts.notebook_id[:8] + "..." if ts.notebook_id else "[red]not created[/red]"
        synced_count = len(ts.sources)
        last = ts.last_sync[:10] if ts.last_sync else "never"
        table.add_row(
            topic.display_name,
            nb,
            f"{synced_count}/{total}",
            str(changed) if changed else "[green]0[/green]",
            last,
        )

    console.print(table)


@cli.command()
@click.argument("topic_name")
@click.option("--instructions", "-i", default="", help="Custom instructions for audio generation")
def audio(topic_name: str, instructions: str) -> None:
    """Generate a NotebookLM audio overview for a topic."""
    topic = _get_topic(topic_name)
    if not topic:
        console.print(f"[red]Unknown topic: {topic_name}[/red]")
        raise SystemExit(1)

    state = SyncState()
    ts = state.get_topic(topic.name)
    if not ts.notebook_id:
        console.print("[red]Notebook not created yet. Run 'studyctl sync' first.[/red]")
        raise SystemExit(1)

    console.print(f"Generating audio for [bold]{topic.display_name}[/bold]...")
    task_id = generate_audio(topic, state, instructions)
    if task_id:
        console.print(f"[green]✓[/green] Audio generation started (task: {task_id})")
        console.print(f"  Check status: notebooklm artifact list --notebook {ts.notebook_id}")
    else:
        console.print("[red]Failed to start audio generation[/red]")


@cli.command()
def topics() -> None:
    """List configured study topics."""
    for topic in get_topics():
        console.print(f"[bold cyan]{topic.name}[/bold cyan] — {topic.display_name}")
        for p in topic.obsidian_paths:
            exists = "✓" if p.exists() else "✗"
            console.print(f"  {exists} {p}")


@cli.command()
@click.argument("topic_name", required=False)
@click.option("--all", "dedup_all", is_flag=True, help="Dedup all topic notebooks")
@click.option("--dry-run", is_flag=True, help="Show duplicates without removing")
def dedup(topic_name: str | None, dedup_all: bool, dry_run: bool) -> None:
    """Remove duplicate sources from NotebookLM notebooks."""
    state = SyncState()
    topics = get_topics() if dedup_all else ([_get_topic(topic_name)] if topic_name else [])
    topics = [t for t in topics if t]

    if not topics:
        console.print("[red]Specify a topic or use --all[/red]")
        raise SystemExit(1)

    for topic in topics:
        ts = state.get_topic(topic.name)
        if not ts.notebook_id:
            console.print(f"[dim]{topic.display_name}: no notebook[/dim]")
            continue

        dupes = find_duplicates(ts.notebook_id)
        if not dupes:
            console.print(f"[dim]{topic.display_name}: no duplicates[/dim]")
            continue

        total_dupes = sum(len(v) - 1 for v in dupes.values())
        name = topic.display_name
        console.print(f"[bold]{name}[/bold]: {total_dupes} duplicates across {len(dupes)} titles")
        for title, sources in dupes.items():
            console.print(
                f"  {len(sources)}x {title}"
                + (" [dim](keeping newest)[/dim]" if not dry_run else "")
            )

        if not dry_run:
            result = dedup_notebook(ts.notebook_id)
            console.print(f"  [green]✓[/green] Removed {result['removed']} duplicates")


@cli.group(name="state")
def state_group() -> None:
    """Cross-machine state sync (via Obsidian vault)."""


@state_group.command(name="push")
@click.argument("remote", required=False)
def state_push(remote: str | None) -> None:
    """Push local progress and sync state to remote machine(s)."""
    try:
        pushed = push_state(remote)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        console.print("Run 'studyctl state init' first")
        raise SystemExit(1) from None
    if pushed:
        for f in pushed:
            console.print(f"[green]✓[/green] {f}")
    else:
        console.print("[dim]Everything up to date (or no remotes reachable)[/dim]")


@state_group.command(name="pull")
@click.argument("remote", required=False)
def state_pull(remote: str | None) -> None:
    """Pull progress and sync state from remote machine(s)."""
    try:
        pulled = pull_state(remote)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1) from None
    if pulled:
        for f in pulled:
            console.print(f"[green]✓[/green] {f}")
    else:
        console.print("[dim]Everything up to date (or no remotes reachable)[/dim]")


@state_group.command(name="status")
def state_status_cmd() -> None:
    """Check sync config and remote connectivity."""
    info = shared_sync_status()
    if not info["configured"]:
        console.print("[red]Not configured.[/red] Run: studyctl state init")
        console.print(f"Config: {info['config_path']}")
        return
    console.print(f"Local machine: [bold]{info['local']}[/bold]")
    for name, r in info["remotes"].items():
        status = "[green]reachable[/green]" if r["reachable"] else "[red]unreachable[/red]"
        console.print(f"  {name} ({r['host']}): {status}")


@state_group.command(name="init")
def state_init() -> None:
    """Create default sync config."""
    path = init_config()
    console.print(f"[green]✓[/green] Config at {path}")
    console.print("Edit remotes to match your machines, then run 'studyctl state status'")


# ── schedule ──────────────────────────────────────────────────────────────────


@cli.group(name="schedule")
def schedule_group() -> None:
    """Manage scheduled jobs (launchd on macOS, cron on Linux)."""


@schedule_group.command(name="install")
@click.option("--username", "-u", help="Username for paths (default: current user)")
def schedule_install(username: str | None) -> None:
    """Install all scheduled jobs."""
    installed = install_all(username)
    for name in installed:
        console.print(f"[green]✓[/green] Installed {name}")
    if not installed:
        console.print("[dim]No jobs installed[/dim]")


@schedule_group.command(name="remove")
def schedule_remove() -> None:
    """Remove all scheduled jobs."""
    removed = remove_all()
    for name in removed:
        console.print(f"[green]✓[/green] Removed {name}")


@schedule_group.command(name="list")
def schedule_list() -> None:
    """List active scheduled jobs."""
    jobs = list_jobs()
    if not jobs:
        console.print("[dim]No studyctl jobs scheduled[/dim]")
        console.print("Run: studyctl schedule install")
        return
    for j in jobs:
        console.print(f"  {j['name']}: {j.get('status', j.get('cron', '?'))}")


@schedule_group.command(name="add")
@click.argument("name")
@click.argument("command")
@click.argument("schedule")
@click.option("--username", "-u", help="Username for paths")
def schedule_add(name: str, command: str, schedule: str, username: str | None) -> None:
    """Add a custom scheduled job.

    Example: studyctl schedule add my-backup "~/scripts/backup.sh" "daily 3am"
    """
    job = Job(name=name, command=command, schedule=schedule)
    if install_job(job, username):
        console.print(f"[green]✓[/green] Added {name} ({schedule})")
    else:
        console.print(f"[red]Failed to add {name}[/red]")


@schedule_group.command(name="delete")
@click.argument("name")
def schedule_delete(name: str) -> None:
    """Remove a specific scheduled job."""
    job = Job(name=name, command="", schedule="")
    if remove_job(job):
        console.print(f"[green]✓[/green] Removed {name}")


# ── review (spaced repetition) ────────────────────────────────────────────────


@cli.command("schedule-blocks")
@click.option("--start", "-s", default=None, help="Start time (HH:MM, default: next hour).")
@click.option("--gap", "-g", default=10, help="Minutes between sessions.")
@click.option("--output", "-o", default=None, type=click.Path(), help="Output directory.")
@click.option("--open/--no-open", "open_file", default=True, help="Open .ics file after creation.")
def schedule_blocks(start: str | None, gap: int, output: str | None, open_file: bool) -> None:
    """Create calendar time blocks from spaced repetition schedule."""
    from studyctl.calendar import schedule_reviews, write_ics
    from studyctl.history import spaced_repetition_due

    due = spaced_repetition_due(TOPIC_KEYWORDS)
    if not due:
        console.print("[green]Nothing due for review! \N{PARTY POPPER}[/green]")
        return

    start_time = None
    if start:
        now = datetime.now()
        h, m = start.split(":")
        start_time = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
        if start_time < now:
            start_time += timedelta(days=1)

    events = schedule_reviews(due, start_time=start_time, gap_minutes=gap)
    output_dir = Path(output) if output else None
    path = write_ics(events, output_dir=output_dir)

    console.print(f"\n[bold]\N{CALENDAR} Created {len(events)} study blocks:[/bold]")
    for evt in events:
        t = evt["start"].strftime("%H:%M")
        console.print(f"  {t} — {evt['topic']} ({evt['review_type']}, {evt['duration_min']}min)")
    console.print(f"\n[dim]Saved to: {path}[/dim]")

    if open_file:
        import platform
        import subprocess

        if platform.system() == "Darwin":
            subprocess.run(["open", str(path)], check=False)
        elif platform.system() == "Linux":
            subprocess.run(["xdg-open", str(path)], check=False)


@cli.command()
def review() -> None:
    """Check what's due for spaced repetition review."""
    due = spaced_repetition_due(TOPIC_KEYWORDS)
    if not due:
        console.print("[green]Nothing due for review[/green]")
        return

    table = Table(title="Spaced Repetition — Due for Review")
    table.add_column("Topic", style="bold cyan")
    table.add_column("Last Studied")
    table.add_column("Days Ago", justify="right")
    table.add_column("Review Type", style="yellow")

    for item in due:
        days = str(item["days_ago"]) if item["days_ago"] is not None else "never"
        last = item["last_studied"] or "never"
        table.add_row(item["topic"], last, days, item["review_type"])

    console.print(table)


@cli.command()
@click.option("--days", "-d", default=30, help="Look back N days")
def struggles(days: int) -> None:
    """Find topics you keep asking about (potential struggle areas)."""
    topics = struggle_topics(days=days)
    if not topics:
        console.print("[dim]No recurring struggle topics found[/dim]")
        return

    console.print("[bold]Topics appearing in 3+ sessions (potential struggle areas):[/bold]\n")
    for t in topics:
        bar = "█" * min(t["mentions"], 20)
        console.print(f"  [cyan]{t['topic']:20s}[/cyan] {bar} ({t['mentions']} mentions)")


# ── win tracking ──────────────────────────────────────────────────────────────


@cli.command()
@click.option("--days", "-d", default=30, help="Look back period in days.")
def wins(days: int) -> None:
    """Show your learning wins — concepts you've mastered."""
    from .history import get_progress_summary, get_wins

    summary = get_progress_summary()
    if not summary:
        console.print("[dim]No progress data yet. Use your study mentor to start tracking![/dim]")
        return

    total = summary.get("total", 0)
    mastered = summary.get("mastered", 0)
    confident = summary.get("confident", 0)
    learning = summary.get("learning", 0)
    struggling = summary.get("struggling", 0)

    console.print("\n[bold]📊 Progress Overview[/bold]")
    console.print(
        f"  🏆 Mastered: {mastered}  "
        f"✅ Confident: {confident}  "
        f"📖 Learning: {learning}  "
        f"🔧 Struggling: {struggling}  "
        f"({total} total)"
    )

    recent = get_wins(days=days)
    if recent:
        console.print(f"\n[bold green]🎉 Wins in the last {days} days:[/bold green]")
        for w in recent:
            emoji = "🏆" if w["confidence"] == "mastered" else "✅"
            console.print(
                f"  {emoji} [bold]{w['concept']}[/bold] ({w['topic']}) "
                f"— {w['session_count']} sessions"
            )
    else:
        console.print(f"\n[dim]No new wins in the last {days} days. Keep going! 💪[/dim]")


@cli.command()
@click.argument("concept")
@click.option("--topic", "-t", required=True, help="Study topic.")
@click.option(
    "--confidence",
    "-c",
    type=click.Choice(["struggling", "learning", "confident", "mastered"]),
    required=True,
    help="Current confidence level.",
)
@click.option("--notes", "-n", default=None, help="Optional notes.")
def progress(concept: str, topic: str, confidence: str, notes: str | None) -> None:
    """Record progress on a concept."""
    from .history import record_progress

    if record_progress(topic, concept, confidence, notes=notes):
        emoji = {"struggling": "🔧", "learning": "📖", "confident": "✅", "mastered": "🏆"}
        console.print(
            f"{emoji.get(confidence, '📝')} Recorded: "
            f"[bold]{concept}[/bold] ({topic}) → {confidence}"
        )
    else:
        console.print("[red]Failed to record progress. Check your session database path.[/red]")


# ── auto-resume ───────────────────────────────────────────────────────────────


@cli.command()
def resume() -> None:
    """Show where you left off — last session summary for quick context reload."""
    from .history import check_medication_window, get_last_session_summary, get_study_streaks

    summary = get_last_session_summary()
    if not summary:
        console.print("[dim]No sessions found. Start a study session to begin tracking![/dim]")
        return

    console.print("[bold]Where you left off:[/bold]\n")

    # Last session info
    source = summary["source"].replace("_", " ").title()
    updated = summary.get("updated") or summary["started"]
    if updated:
        updated = updated[:16].replace("T", " ")
    console.print(f"  Last session: [cyan]{source}[/cyan] ({updated})")

    if summary["topics_covered"]:
        topics_str = ", ".join(summary["topics_covered"])
        console.print(f"  Topics: [bold]{topics_str}[/bold]")

    if summary["last_message_preview"]:
        preview = summary["last_message_preview"]
        if len(preview) > 150:
            preview = preview[:150] + "..."
        console.print(f"  Context: [dim]{preview}[/dim]")

    # Concepts in progress
    if summary["concepts_in_progress"]:
        console.print("\n[bold]In progress:[/bold]")
        for c in summary["concepts_in_progress"]:
            emoji = "🔧" if c["confidence"] == "struggling" else "📖"
            console.print(f"  {emoji} {c['concept']} ({c['topic']}) — {c['confidence']}")

    # Streak info
    streak_data = get_study_streaks()
    if streak_data["current_streak"] > 0:
        console.print(
            f"\n  Streak: [bold green]{streak_data['current_streak']} days[/bold green]"
            f" (best: {streak_data['longest_streak']})"
            f" | This week: {streak_data['sessions_this_week']} sessions"
        )

    # Medication window (if configured)
    raw_config = {}
    config_path = Path.home() / ".config" / "studyctl" / "config.yaml"
    if config_path.exists():
        import yaml

        raw_config = yaml.safe_load(config_path.read_text()) or {}
    med_config = raw_config.get("medication")
    if med_config:
        med = check_medication_window(med_config)
        if med:
            phase_emoji = {
                "onset": "💊",
                "peak": "🧠",
                "tapering": "📉",
                "worn_off": "😴",
            }
            emoji = phase_emoji.get(med["phase"], "💊")
            console.print(
                f"\n  {emoji} Meds: [bold]{med['phase']}[/bold] — {med['recommendation']}"
            )


# ── streaks ───────────────────────────────────────────────────────────────────


@cli.command()
def streaks() -> None:
    """Show your study streak and consistency stats."""
    from .history import get_study_streaks

    data = get_study_streaks()
    if not data.get("last_session_date"):
        console.print("[dim]No study sessions found yet.[/dim]")
        return

    console.print("\n[bold]Study Consistency[/bold]\n")

    # Current streak with visual
    current = data["current_streak"]
    longest = data["longest_streak"]
    fire = "🔥" if current >= 3 else ""
    console.print(f"  Current streak: [bold green]{current} days[/bold green] {fire}")
    console.print(f"  Longest streak: [bold]{longest} days[/bold]")
    console.print(f"  Study days (last 90): [bold]{data['total_days']}[/bold]")
    console.print(f"  Sessions this week: [bold]{data['sessions_this_week']}[/bold]")
    console.print(f"  Last session: {data['last_session_date']}")

    # Weekly consistency bar
    consistency = data["total_days"] / 90 * 100
    bar_len = int(consistency / 5)
    bar = "█" * bar_len + "░" * (20 - bar_len)
    console.print(f"\n  Consistency: [{bar}] {consistency:.0f}%")

    if current == 0:
        console.print(
            "\n  [dim]No session today or yesterday. Start one to keep your streak going![/dim]"
        )


# ── progress map ──────────────────────────────────────────────────────────────


@cli.command("progress-map")
def progress_map() -> None:
    """Show a visual progress map of all tracked concepts."""
    from .history import get_progress_for_map

    entries = get_progress_for_map()
    if not entries:
        console.print(
            "[dim]No progress data yet."
            " Use your study mentor and 'studyctl progress' to start tracking![/dim]"
        )
        return

    # Group by topic
    by_topic: dict[str, list[dict]] = {}
    for entry in entries:
        by_topic.setdefault(entry["topic"], []).append(entry)

    # Render confidence levels with visual indicators
    conf_style = {
        "mastered": ("🏆", "bold green"),
        "confident": ("✅", "green"),
        "learning": ("📖", "yellow"),
        "struggling": ("🔧", "red"),
    }

    console.print("\n[bold]Progress Map[/bold]\n")

    for topic, concepts in sorted(by_topic.items()):
        console.print(f"  [bold cyan]{topic}[/bold cyan]")
        for c in concepts:
            emoji, style = conf_style.get(c["confidence"], ("📝", "dim"))
            sessions = c["session_count"]
            console.print(
                f"    {emoji} [{style}]{c['concept']}[/{style}]"
                f" — {c['confidence']} ({sessions} sessions)"
            )
        console.print()

    # Generate Mermaid diagram
    console.print("[bold]Mermaid diagram (paste into any Mermaid renderer):[/bold]\n")
    console.print("```mermaid")
    console.print("graph TD")
    for topic, concepts in sorted(by_topic.items()):
        topic_id = topic.replace(" ", "_").replace("-", "_")
        console.print(f'    {topic_id}["{topic}"]')
        for c in concepts:
            concept_id = f"{topic_id}_{c['concept'].replace(' ', '_').replace('-', '_')}"
            conf = c["confidence"]
            if conf == "mastered":
                style = ":::mastered"
            elif conf == "confident":
                style = ":::confident"
            elif conf == "learning":
                style = ":::learning"
            else:
                style = ":::struggling"
            console.print(f'    {topic_id} --> {concept_id}["{c["concept"]}"]')
            console.print(f"    class {concept_id} {conf}")
    console.print()
    console.print("    classDef mastered fill:#10b981,color:#fff")
    console.print("    classDef confident fill:#3b82f6,color:#fff")
    console.print("    classDef learning fill:#f59e0b,color:#000")
    console.print("    classDef struggling fill:#ef4444,color:#fff")
    console.print("```")


# --- Docs commands ---


def _find_docs_dir() -> Path:
    """Find the docs directory relative to the package."""
    # Walk up from this file to find the repo root (has mkdocs.yml)
    candidate = Path(__file__).resolve().parent
    for _ in range(6):
        if (candidate / "mkdocs.yml").exists():
            return candidate / "docs"
        candidate = candidate.parent
    # Fallback: check common install locations
    for p in [
        Path.home() / "code" / "personal" / "tools" / "socratic-study-mentor" / "docs",
        Path.home() / ".agents" / "shared",
    ]:
        if p.exists():
            return p
    msg = "Could not find docs directory. Run from the repo or set STUDYCTL_DOCS_DIR."
    raise click.ClickException(msg)


def _strip_markdown(text: str) -> str:
    """Strip markdown formatting for TTS-friendly plain text."""
    import re

    # Remove code blocks entirely
    text = re.sub(r"```[\s\S]*?```", "", text)
    # Remove inline code
    text = re.sub(r"`[^`]+`", "", text)
    # Remove markdown headers
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Remove bold/italic markers
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    # Remove links, keep text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Remove admonition markers
    text = re.sub(r"^!!! \w+.*$", "", text, flags=re.MULTILINE)
    # Remove table formatting
    text = re.sub(r"^\|.*\|$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[-|: ]+$", "", text, flags=re.MULTILINE)
    # Collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@cli.group(name="docs")
def docs_group() -> None:
    """Browse and read documentation."""


@docs_group.command(name="serve")
@click.option("--port", "-p", default=8000, help="Port for local server")
def docs_serve(port: int) -> None:
    """Serve documentation site locally and open in browser."""
    import subprocess

    repo_root = _find_docs_dir().parent
    console.print(f"[bold]Serving docs at http://localhost:{port}[/bold]")
    subprocess.run(["mkdocs", "serve", "-a", f"localhost:{port}"], cwd=str(repo_root), check=False)


@docs_group.command(name="open")
def docs_open() -> None:
    """Build and open documentation in browser."""
    import subprocess
    import webbrowser

    repo_root = _find_docs_dir().parent
    site_dir = repo_root / "site"
    console.print("Building docs...")
    subprocess.run(["mkdocs", "build"], cwd=str(repo_root), check=True, capture_output=True)
    index = site_dir / "index.html"
    if index.exists():
        webbrowser.open(f"file://{index}")
        console.print("[green]Opened docs in browser[/green]")
    else:
        console.print("[red]Build failed — site/index.html not found[/red]")


@docs_group.command(name="list")
def docs_list() -> None:
    """List available documentation pages."""
    docs_dir = _find_docs_dir()
    table = Table(title="Documentation Pages")
    table.add_column("Page", style="bold")
    table.add_column("Title")
    for md in sorted(docs_dir.glob("*.md")):
        # Read first heading as title
        title = md.stem.replace("-", " ").title()
        for line in md.read_text().splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        table.add_row(md.stem, title)
    console.print(table)


@docs_group.command(name="read")
@click.argument("page")
def docs_read(page: str) -> None:
    """Read a documentation page aloud using study-speak.

    PAGE is the doc name without .md extension (e.g. 'voice-output', 'audhd-learning-philosophy').
    Use 'studyctl docs list' to see available pages.
    """
    import subprocess

    docs_dir = _find_docs_dir()
    md_file = docs_dir / f"{page}.md"
    if not md_file.exists():
        # Fuzzy match
        matches = [f for f in docs_dir.glob("*.md") if page.lower() in f.stem.lower()]
        if len(matches) == 1:
            md_file = matches[0]
        else:
            console.print(
                f"[red]Page '{page}' not found.[/red] Run [bold]studyctl docs list[/bold]"
            )
            return

    text = _strip_markdown(md_file.read_text())
    if not text:
        console.print("[yellow]Page is empty after stripping markdown.[/yellow]")
        return

    speak_bin = Path.home() / ".local" / "bin" / "study-speak"
    if not speak_bin.exists():
        console.print(
            "[red]study-speak not installed.[/red]"
            " Run: uv tool install './packages/agent-session-tools[tts]'"
        )
        return

    console.print(f"[bold]📖 Reading: {md_file.stem}[/bold]")
    console.print(f"[dim]({len(text.split())} words — press Ctrl+C to stop)[/dim]\n")

    try:
        subprocess.run([str(speak_bin), text], check=True, timeout=300)
        console.print("\n[green]✓ Done reading[/green]")
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped reading[/yellow]")
    except subprocess.TimeoutExpired:
        console.print("\n[yellow]Reading timed out[/yellow]")
