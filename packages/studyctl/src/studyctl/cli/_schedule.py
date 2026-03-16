"""Schedule commands — job management and calendar blocks."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import click

from studyctl.cli._shared import TOPIC_KEYWORDS, console
from studyctl.scheduler import (
    Job,
    install_all,
    install_job,
    list_jobs,
    remove_all,
    remove_job,
)


@click.group(name="schedule")
def schedule_group() -> None:
    """Manage scheduled jobs (launchd on macOS, cron on Linux)."""


@schedule_group.command(name="install")
@click.option("--username", "-u", help="Username for paths (default: current user)")
def schedule_install(username: str | None) -> None:
    """Install all scheduled jobs."""
    installed = install_all(username)
    for name in installed:
        console.print(f"[green]\u2713[/green] Installed {name}")
    if not installed:
        console.print("[dim]No jobs installed[/dim]")


@schedule_group.command(name="remove")
def schedule_remove() -> None:
    """Remove all scheduled jobs."""
    removed = remove_all()
    for name in removed:
        console.print(f"[green]\u2713[/green] Removed {name}")


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
        console.print(f"[green]\u2713[/green] Added {name} ({schedule})")
    else:
        console.print(f"[red]Failed to add {name}[/red]")


@schedule_group.command(name="delete")
@click.argument("name")
def schedule_delete(name: str) -> None:
    """Remove a specific scheduled job."""
    job = Job(name=name, command="", schedule="")
    if remove_job(job):
        console.print(f"[green]\u2713[/green] Removed {name}")


@click.command("schedule-blocks")
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
        console.print(
            f"  {t} \u2014 {evt['topic']} ({evt['review_type']}, {evt['duration_min']}min)"
        )
    console.print(f"\n[dim]Saved to: {path}[/dim]")

    if open_file:
        import platform
        import subprocess

        if platform.system() == "Darwin":
            subprocess.run(["open", str(path)], check=False)
        elif platform.system() == "Linux":
            subprocess.run(["xdg-open", str(path)], check=False)
