"""studyctl CLI — sync, plan, and schedule study sessions."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from .config import DEFAULT_TOPICS, Topic
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
    for t in DEFAULT_TOPICS:
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
    topics = DEFAULT_TOPICS if sync_all else ([_get_topic(topic_name)] if topic_name else [])
    topics = [t for t in topics if t]

    if not topics:
        console.print("[red]Specify a topic name or use --all[/red]")
        console.print("Topics: " + ", ".join(t.name for t in DEFAULT_TOPICS))
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
    topics = [_get_topic(topic_name)] if topic_name else DEFAULT_TOPICS
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
    for topic in DEFAULT_TOPICS:
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
    topics = DEFAULT_TOPICS if dedup_all else ([_get_topic(topic_name)] if topic_name else [])
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
