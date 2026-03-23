"""Review commands — spaced repetition and struggle detection."""

from __future__ import annotations

import click
from rich.table import Table

from studyctl.cli._shared import TOPIC_KEYWORDS, console
from studyctl.history import (
    spaced_repetition_due,
    struggle_topics,
)


@click.command()
def review() -> None:
    """Check what's due for spaced repetition review."""
    due = spaced_repetition_due(TOPIC_KEYWORDS)
    if not due:
        console.print("[green]Nothing due for review[/green]")
        return

    table = Table(title="Spaced Repetition \u2014 Due for Review")
    table.add_column("Topic", style="bold cyan")
    table.add_column("Last Studied")
    table.add_column("Days Ago", justify="right")
    table.add_column("Review Type", style="yellow")

    for item in due:
        days = str(item["days_ago"]) if item["days_ago"] is not None else "never"
        last = item["last_studied"] or "never"
        table.add_row(item["topic"], last, days, item["review_type"])

    console.print(table)


@click.command()
@click.option("--days", "-d", default=30, help="Look back N days")
def struggles(days: int) -> None:
    """Find topics you keep asking about (potential struggle areas)."""
    topics = struggle_topics(days=days)
    if not topics:
        console.print("[dim]No recurring struggle topics found[/dim]")
        return

    console.print("[bold]Topics appearing in 3+ sessions (potential struggle areas):[/bold]\n")
    for t in topics:
        bar = "\u2588" * min(t["mentions"], 20)
        console.print(f"  [cyan]{t['topic']:20s}[/cyan] {bar} ({t['mentions']} mentions)")
