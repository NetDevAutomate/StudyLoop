"""Topics command — imperative shell for study backlog management.

Thin adapter: gathers data from parking.py, delegates formatting to
backlog_logic, then presents via Rich console.

See docs/architecture/study-backlog-phase1.md for the full design.
"""

from __future__ import annotations

import click


@click.group("topics")
def topics_group() -> None:
    """Manage your study backlog — outstanding topics across sessions."""


@topics_group.command("list")
@click.option("--tech", "-t", default=None, help="Filter by technology area.")
@click.option(
    "--source",
    "-s",
    default=None,
    type=click.Choice(["parked", "struggled", "manual"]),
    help="Filter by source.",
)
@click.option("--all", "show_all", is_flag=True, help="Include resolved/dismissed topics.")
def topics_list(tech: str | None, source: str | None, show_all: bool) -> None:
    """List pending study backlog topics.

    Examples:

        studyctl topics list

        studyctl topics list --tech Python

        studyctl topics list --source struggled
    """
    from rich.table import Table

    from studyctl.backlog_logic import BacklogItem, format_backlog_list
    from studyctl.cli._shared import console
    from studyctl.parking import get_parked_topics

    # GATHER
    status = None if show_all else "pending"
    raw_topics = get_parked_topics(status=status or "pending", source=source, tech_area=tech)
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
        for t in raw_topics
    ]

    # DECIDE
    result = format_backlog_list(items, tech_filter=tech, source_filter=source)

    # PRESENT
    if result.total == 0:
        label = "pending " if not show_all else ""
        console.print(f"[dim]No {label}topics in your study backlog.[/dim]")
        return

    table = Table(title=f"Study Backlog — {result.total} topics")
    table.add_column("ID", justify="right", style="dim", width=5)
    table.add_column("Topic", style="cyan")
    table.add_column("Tech", style="green")
    table.add_column("Source", style="yellow")
    table.add_column("When", style="dim")

    for item in result.items:
        tech_col = item.tech_area or ""
        source_col = item.source
        when = _relative_time(item.parked_at)
        table.add_row(str(item.id), item.question, tech_col, source_col, when)

    console.print(table)

    if result.by_source:
        parts = [f"{v} {k}" for k, v in sorted(result.by_source.items())]
        console.print(f"[dim]Sources: {', '.join(parts)}[/dim]")


@topics_group.command("add")
@click.argument("topic")
@click.option("--tech", "-t", default=None, help="Technology area (e.g. Python, SQL).")
@click.option("--note", "-n", default=None, help="Additional context or notes.")
def topics_add(topic: str, tech: str | None, note: str | None) -> None:
    """Manually add a topic to your study backlog.

    Examples:

        studyctl topics add "Python decorators" --tech Python

        studyctl topics add "Window functions" --tech SQL --note "Need for analytics work"
    """
    from studyctl.cli._shared import console
    from studyctl.parking import park_topic

    row_id = park_topic(
        question=topic,
        topic_tag=tech,
        context=note,
        study_session_id=None,
        created_by="cli",
        source="manual",
        tech_area=tech,
    )

    if row_id:
        tech_label = f" [{tech}]" if tech else ""
        console.print(f"[bold green]Added[/bold green] topic #{row_id}: {topic}{tech_label}")
    else:
        console.print("[red]Failed to add topic[/red] — check logs for details.")


@topics_group.command("resolve")
@click.argument("topic_id", type=int)
def topics_resolve(topic_id: int) -> None:
    """Mark a backlog topic as resolved/covered.

    Examples:

        studyctl topics resolve 42
    """
    from studyctl.cli._shared import console
    from studyctl.parking import resolve_parked_topic

    success = resolve_parked_topic(topic_id)
    if success:
        console.print(f"[bold green]Resolved[/bold green] topic #{topic_id}")
    else:
        console.print(f"[yellow]Topic #{topic_id} not found or already resolved.[/yellow]")


@topics_group.command("suggest")
@click.option("--limit", "-l", default=10, show_default=True, help="Max suggestions to show.")
@click.option("--topic", "-t", default=None, help="Current study topic for relevance sorting.")
def topics_suggest(limit: int, topic: str | None) -> None:
    """Suggest what to study next, ranked by importance and frequency.

    Uses algorithmic scoring: agent-assessed importance (60%) combined
    with how frequently a topic has been parked/struggled (40%).

    Examples:

        studyctl backlog suggest

        studyctl backlog suggest --limit 5

        studyctl backlog suggest --topic "Python Patterns"
    """
    from rich.table import Table

    from studyctl.backlog_logic import BacklogItem, ScoringInput, score_backlog_items
    from studyctl.cli._shared import console
    from studyctl.parking import get_parked_topics, get_topic_frequencies

    # GATHER
    raw_topics = get_parked_topics(status="pending")
    if not raw_topics:
        console.print("[dim]No pending topics to suggest.[/dim]")
        return

    frequencies = get_topic_frequencies(status="pending")

    scoring_inputs = [
        ScoringInput(
            item=BacklogItem(
                id=t["id"],
                question=t["question"],
                topic_tag=t.get("topic_tag"),
                tech_area=t.get("tech_area"),
                source=t.get("source", "parked"),
                context=t.get("context"),
                parked_at=t["parked_at"],
                session_topic=None,
            ),
            frequency=frequencies.get(t["question"], 1),
            priority=t.get("priority"),
        )
        for t in raw_topics
    ]

    # DECIDE
    suggestions = score_backlog_items(scoring_inputs)[:limit]

    # PRESENT
    table = Table(title=f"Study Suggestions — Top {len(suggestions)}")
    table.add_column("#", justify="right", style="dim", width=3)
    table.add_column("Topic", style="cyan")
    table.add_column("Tech", style="green")
    table.add_column("Score", justify="right", style="bold yellow")
    table.add_column("Why", style="dim")

    for rank, s in enumerate(suggestions, 1):
        tech_col = s.item.tech_area or ""
        score_col = f"{s.score:.2f}"
        table.add_row(str(rank), s.item.question, tech_col, score_col, s.reasoning)

    console.print(table)

    if topic:
        # Highlight items relevant to the current topic
        relevant = [
            s for s in suggestions if s.item.tech_area and s.item.tech_area.lower() in topic.lower()
        ]
        if relevant:
            console.print(
                f"\n[dim]{len(relevant)} of these relate to your current topic ({topic})[/dim]"
            )


def _relative_time(iso_datetime: str) -> str:
    """Convert ISO datetime string to a relative time like '2d', '5h'."""
    from datetime import UTC, datetime

    try:
        parked = datetime.fromisoformat(iso_datetime)
        if parked.tzinfo is None:
            parked = parked.replace(tzinfo=UTC)
        delta = datetime.now(UTC) - parked
        days = delta.days
        if days > 0:
            return f"{days}d"
        hours = delta.seconds // 3600
        if hours > 0:
            return f"{hours}h"
        minutes = delta.seconds // 60
        return f"{minutes}m" if minutes > 0 else "now"
    except (ValueError, TypeError):
        return "?"
