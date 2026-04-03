"""Sync commands — Obsidian to NotebookLM sync, audio generation."""

from __future__ import annotations

import click
from rich.table import Table

from studyctl.cli._shared import console, get_topic
from studyctl.maintenance import dedup_notebook, find_duplicates
from studyctl.state import SyncState
from studyctl.sync import find_changed_sources, find_sources, generate_audio, sync_topic
from studyctl.topics import get_topics


@click.command()
@click.argument("topic_name", required=False)
@click.option("--all", "sync_all", is_flag=True, help="Sync all topics")
@click.option("--dry-run", is_flag=True, help="Show what would be synced")
def sync(topic_name: str | None, sync_all: bool, dry_run: bool) -> None:
    """Sync Obsidian course notes to NotebookLM notebooks."""
    state = SyncState()
    topics = get_topics() if sync_all else ([get_topic(topic_name)] if topic_name else [])
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


@click.command()
@click.argument("topic_name", required=False)
def status(topic_name: str | None) -> None:
    """Show sync status for topics."""
    state = SyncState()
    topics = [get_topic(topic_name)] if topic_name else get_topics()
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


@click.command()
@click.argument("topic_name")
@click.option("--instructions", "-i", default="", help="Custom instructions for audio generation")
def audio(topic_name: str, instructions: str) -> None:
    """Generate a NotebookLM audio overview for a topic."""
    topic = get_topic(topic_name)
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
        console.print(f"[green]\u2713[/green] Audio generation started (task: {task_id})")
        console.print(f"  Check status: notebooklm artifact list --notebook {ts.notebook_id}")
    else:
        console.print("[red]Failed to start audio generation[/red]")


@click.command()
def topics() -> None:
    """List configured study topics."""
    for topic in get_topics():
        console.print(f"[bold cyan]{topic.name}[/bold cyan] \u2014 {topic.display_name}")
        for p in topic.obsidian_paths:
            exists = "\u2713" if p.exists() else "\u2717"
            console.print(f"  {exists} {p}")


@click.command()
@click.argument("topic_name", required=False)
@click.option("--all", "dedup_all", is_flag=True, help="Dedup all topic notebooks")
@click.option("--dry-run", is_flag=True, help="Show duplicates without removing")
def dedup(topic_name: str | None, dedup_all: bool, dry_run: bool) -> None:
    """Remove duplicate sources from NotebookLM notebooks."""
    state = SyncState()
    topics = get_topics() if dedup_all else ([get_topic(topic_name)] if topic_name else [])
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
            console.print(f"  [green]\u2713[/green] Removed {result['removed']} duplicates")
