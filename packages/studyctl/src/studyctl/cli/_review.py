"""Review commands — spaced repetition, progress, and struggle detection."""

from __future__ import annotations

from pathlib import Path

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


@click.command()
@click.option("--days", "-d", default=30, help="Look back period in days.")
def wins(days: int) -> None:
    """Show your learning wins -- concepts you've mastered."""
    from studyctl.history import get_progress_summary, get_wins

    summary = get_progress_summary()
    if not summary:
        console.print("[dim]No progress data yet. Use your study mentor to start tracking![/dim]")
        return

    total = summary.get("total", 0)
    mastered = summary.get("mastered", 0)
    confident = summary.get("confident", 0)
    learning = summary.get("learning", 0)
    struggling = summary.get("struggling", 0)

    console.print("\n[bold]\U0001f4ca Progress Overview[/bold]")
    console.print(
        f"  \U0001f3c6 Mastered: {mastered}  "
        f"\u2705 Confident: {confident}  "
        f"\U0001f4d6 Learning: {learning}  "
        f"\U0001f527 Struggling: {struggling}  "
        f"({total} total)"
    )

    recent = get_wins(days=days)
    if recent:
        console.print(f"\n[bold green]\U0001f389 Wins in the last {days} days:[/bold green]")
        for w in recent:
            emoji = "\U0001f3c6" if w["confidence"] == "mastered" else "\u2705"
            console.print(
                f"  {emoji} [bold]{w['concept']}[/bold] ({w['topic']}) "
                f"\u2014 {w['session_count']} sessions"
            )
    else:
        console.print(f"\n[dim]No new wins in the last {days} days. Keep going! \U0001f4aa[/dim]")


@click.command()
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
    from studyctl.history import record_progress

    if record_progress(topic, concept, confidence, notes=notes):
        emoji = {
            "struggling": "\U0001f527",
            "learning": "\U0001f4d6",
            "confident": "\u2705",
            "mastered": "\U0001f3c6",
        }
        console.print(
            f"{emoji.get(confidence, '\U0001f4dd')} Recorded: "
            f"[bold]{concept}[/bold] ({topic}) \u2192 {confidence}"
        )
    else:
        console.print("[red]Failed to record progress. Run 'studyctl doctor' to diagnose.[/red]")


@click.command()
def resume() -> None:
    """Show where you left off -- last session summary for quick context reload."""
    from studyctl.history import (
        check_medication_window,
        get_last_session_summary,
        get_study_streaks,
    )

    summary = get_last_session_summary()
    if not summary:
        console.print("[dim]No sessions found. Start a study session to begin tracking![/dim]")
        return

    console.print("[bold]Where you left off:[/bold]\n")

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

    if summary["concepts_in_progress"]:
        console.print("\n[bold]In progress:[/bold]")
        for c in summary["concepts_in_progress"]:
            emoji = "\U0001f527" if c["confidence"] == "struggling" else "\U0001f4d6"
            console.print(f"  {emoji} {c['concept']} ({c['topic']}) \u2014 {c['confidence']}")

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
                "onset": "\U0001f48a",
                "peak": "\U0001f9e0",
                "tapering": "\U0001f4c9",
                "worn_off": "\U0001f634",
            }
            emoji = phase_emoji.get(med["phase"], "\U0001f48a")
            console.print(
                f"\n  {emoji} Meds: [bold]{med['phase']}[/bold] \u2014 {med['recommendation']}"
            )


@click.command()
def streaks() -> None:
    """Show your study streak and consistency stats."""
    from studyctl.history import get_study_streaks

    data = get_study_streaks()
    if not data.get("last_session_date"):
        console.print("[dim]No study sessions found yet.[/dim]")
        return

    console.print("\n[bold]Study Consistency[/bold]\n")

    current = data["current_streak"]
    longest = data["longest_streak"]
    fire = "\U0001f525" if current >= 3 else ""
    console.print(f"  Current streak: [bold green]{current} days[/bold green] {fire}")
    console.print(f"  Longest streak: [bold]{longest} days[/bold]")
    console.print(f"  Study days (last 90): [bold]{data['total_days']}[/bold]")
    console.print(f"  Sessions this week: [bold]{data['sessions_this_week']}[/bold]")
    console.print(f"  Last session: {data['last_session_date']}")

    consistency = data["total_days"] / 90 * 100
    bar_len = int(consistency / 5)
    bar = "\u2588" * bar_len + "\u2591" * (20 - bar_len)
    console.print(f"\n  Consistency: [{bar}] {consistency:.0f}%")

    if current == 0:
        console.print(
            "\n  [dim]No session today or yesterday. Start one to keep your streak going![/dim]"
        )
