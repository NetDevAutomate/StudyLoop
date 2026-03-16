"""Review commands — spaced repetition, progress, teachback, bridges."""

from __future__ import annotations

from pathlib import Path

import click
from rich.table import Table

from studyctl.cli._shared import TOPIC_KEYWORDS, console
from studyctl.history import (
    get_bridges,
    get_teachback_history,
    record_bridge,
    record_teachback,
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
    """Show your learning wins \u2014 concepts you've mastered."""
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
        console.print("[red]Failed to record progress. Check your session database path.[/red]")


@click.command()
def resume() -> None:
    """Show where you left off \u2014 last session summary for quick context reload."""
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


@click.command("progress-map")
def progress_map() -> None:
    """Show a visual progress map of all tracked concepts."""
    from studyctl.history import get_progress_for_map

    entries = get_progress_for_map()
    if not entries:
        console.print(
            "[dim]No progress data yet."
            " Use your study mentor and 'studyctl progress' to start tracking![/dim]"
        )
        return

    by_topic: dict[str, list[dict]] = {}
    for entry in entries:
        by_topic.setdefault(entry["topic"], []).append(entry)

    conf_style = {
        "mastered": ("\U0001f3c6", "bold green"),
        "confident": ("\u2705", "green"),
        "learning": ("\U0001f4d6", "yellow"),
        "struggling": ("\U0001f527", "red"),
    }

    console.print("\n[bold]Progress Map[/bold]\n")

    for topic, concepts in sorted(by_topic.items()):
        console.print(f"  [bold cyan]{topic}[/bold cyan]")
        for c in concepts:
            emoji, style = conf_style.get(c["confidence"], ("\U0001f4dd", "dim"))
            sessions = c["session_count"]
            console.print(
                f"    {emoji} [{style}]{c['concept']}[/{style}]"
                f" \u2014 {c['confidence']} ({sessions} sessions)"
            )
        console.print()

    console.print("[bold]Mermaid diagram (paste into any Mermaid renderer):[/bold]\n")
    console.print("```mermaid")
    console.print("graph TD")
    for topic, concepts in sorted(by_topic.items()):
        topic_id = topic.replace(" ", "_").replace("-", "_")
        console.print(f'    {topic_id}["{topic}"]')
        for c in concepts:
            concept_id = f"{topic_id}_{c['concept'].replace(' ', '_').replace('-', '_')}"
            conf = c["confidence"]
            console.print(f'    {topic_id} --> {concept_id}["{c["concept"]}"]')
            console.print(f"    class {concept_id} {conf}")
    console.print()
    console.print("    classDef mastered fill:#10b981,color:#fff")
    console.print("    classDef confident fill:#3b82f6,color:#fff")
    console.print("    classDef learning fill:#f59e0b,color:#000")
    console.print("    classDef struggling fill:#ef4444,color:#fff")
    console.print("```")


@click.command()
@click.argument("concept")
@click.option("--topic", "-t", required=True, help="Study topic.")
@click.option(
    "--score",
    "-s",
    required=True,
    help="Comma-separated scores: accuracy,own_words,structure,depth,transfer (each 1-4).",
)
@click.option(
    "--type",
    "review_type",
    type=click.Choice(["micro", "structured", "transfer", "full"]),
    required=True,
    help="Type of teach-back review.",
)
@click.option("--angle", "-a", default=None, help="Question angle used (e.g. bloom_apply).")
@click.option("--notes", "-n", default=None, help="Optional notes.")
def teachback(
    concept: str,
    topic: str,
    score: str,
    review_type: str,
    angle: str | None,
    notes: str | None,
) -> None:
    """Record a teach-back score for a concept.

    Example: studyctl teachback "Spark partitioning" -t spark --score "3,3,4,3,2" --type structured
    """
    parts = score.split(",")
    if len(parts) != 5:
        console.print(
            "[red]Score must be 5 comma-separated values"
            " (accuracy,own_words,structure,depth,transfer)[/red]"
        )
        raise SystemExit(1)

    try:
        scores = tuple(int(p.strip()) for p in parts)
    except ValueError:
        console.print("[red]Each score must be an integer 1-4[/red]")
        raise SystemExit(1) from None

    for s in scores:
        if not 1 <= s <= 4:
            console.print("[red]Each score must be between 1 and 4[/red]")
            raise SystemExit(1)

    if record_teachback(concept, topic, scores, review_type, angle=angle, notes=notes):  # type: ignore[arg-type]
        total = sum(scores)
        if total >= 18:
            label = "Mastery demonstrated"
            style = "bold green"
        elif total >= 14:
            label = "Solid understanding"
            style = "green"
        elif total >= 9:
            label = "Partial understanding"
            style = "yellow"
        else:
            label = "Memorised, not understood"
            style = "red"

        console.print(
            f"[{style}]{label}[/{style}] \u2014 [bold]{concept}[/bold] ({topic}): {total}/20"
        )
        a, o, s, d, t = scores
        console.print(f"  Accuracy: {a}  Own Words: {o}  Structure: {s}  Depth: {d}  Transfer: {t}")
    else:
        console.print("[red]Failed to record teach-back. Check your session database.[/red]")


@click.command("teachback-history")
@click.argument("concept")
@click.option("--topic", "-t", default=None, help="Filter by topic.")
def teachback_history_cmd(concept: str, topic: str | None) -> None:
    """Show teach-back score progression for a concept."""
    history = get_teachback_history(concept, topic)
    if not history:
        console.print(f"[dim]No teach-back history for '{concept}'[/dim]")
        return

    table = Table(title=f"Teach-Back History: {concept}")
    table.add_column("Date", style="dim")
    table.add_column("Type")
    table.add_column("Total", justify="right", style="bold")
    table.add_column("A", justify="center")
    table.add_column("O", justify="center")
    table.add_column("S", justify="center")
    table.add_column("D", justify="center")
    table.add_column("T", justify="center")
    table.add_column("Angle", style="dim")

    for entry in history:
        total = entry["total_score"]
        if total >= 18:
            total_style = "[bold green]"
        elif total >= 14:
            total_style = "[green]"
        elif total >= 9:
            total_style = "[yellow]"
        else:
            total_style = "[red]"
        total_str = f"{total_style}{total}[/]"

        date = entry["created_at"][:10] if entry["created_at"] else "?"
        table.add_row(
            date,
            entry["review_type"],
            total_str,
            str(entry["score_accuracy"] or ""),
            str(entry["score_own_words"] or ""),
            str(entry["score_structure"] or ""),
            str(entry["score_depth"] or ""),
            str(entry["score_transfer"] or ""),
            entry["question_angle"] or "",
        )

    console.print(table)


# --- Knowledge bridges ---


@click.group(name="bridge")
def bridge_group() -> None:
    """Manage knowledge bridges between domains."""


@bridge_group.command(name="add")
@click.argument("source")
@click.argument("target")
@click.option("--source-domain", "-s", required=True, help="Source domain (e.g. networking).")
@click.option("--target-domain", "-t", required=True, help="Target domain (e.g. spark).")
@click.option("--mapping", "-m", default=None, help="Why they map (structural similarity).")
@click.option(
    "--quality",
    "-q",
    type=click.Choice(["proposed", "validated", "effective", "misleading", "rejected"]),
    default="validated",
    help="Bridge quality.",
)
def bridge_add(
    source: str,
    target: str,
    source_domain: str,
    target_domain: str,
    mapping: str | None,
    quality: str,
) -> None:
    """Add a knowledge bridge between two concepts.

    Example: studyctl bridge add "ECMP load balancing" "Spark partition distribution"
             -s networking -t spark -m "distribute work across parallel processors"
    """
    if record_bridge(source, source_domain, target, target_domain, mapping, quality, "student"):
        console.print(
            f"[green]Bridge added:[/green] "
            f"[bold]{source}[/bold] ({source_domain}) "
            f"-> [bold]{target}[/bold] ({target_domain})"
        )
    else:
        console.print("[red]Failed to add bridge. Check your session database.[/red]")


@bridge_group.command(name="list")
@click.option("--source-domain", "-s", default=None, help="Filter by source domain.")
@click.option("--target-domain", "-t", default=None, help="Filter by target domain.")
@click.option("--quality", "-q", default=None, help="Filter by quality.")
def bridge_list(source_domain: str | None, target_domain: str | None, quality: str | None) -> None:
    """List knowledge bridges."""
    bridges = get_bridges(target_domain=target_domain, source_domain=source_domain, quality=quality)
    if not bridges:
        console.print("[dim]No bridges found. Use 'studyctl bridge add' to create some.[/dim]")
        return

    table = Table(title="Knowledge Bridges")
    table.add_column("Source", style="cyan")
    table.add_column("Domain", style="dim")
    table.add_column("Target", style="bold")
    table.add_column("Domain", style="dim")
    table.add_column("Quality")
    table.add_column("Used", justify="right")
    table.add_column("Helpful", justify="right")

    quality_style = {
        "effective": "bold green",
        "validated": "green",
        "proposed": "yellow",
        "misleading": "red",
        "rejected": "dim red",
    }

    for b in bridges:
        q = b["quality"]
        style = quality_style.get(q, "dim")
        table.add_row(
            b["source_concept"],
            b["source_domain"],
            b["target_concept"],
            b["target_domain"],
            f"[{style}]{q}[/{style}]",
            str(b["times_used"]),
            str(b["times_helpful"]),
        )

    console.print(table)
