"""Session commands — start/end study sessions, park tangential topics."""

from __future__ import annotations

import click

from studyctl.cli._shared import console


@click.group("session")
def session_group() -> None:
    """Manage live study sessions."""


@session_group.command("start")
@click.option("--topic", "-t", required=True, help="Study topic for this session.")
@click.option(
    "--energy",
    "-e",
    type=click.IntRange(1, 10),
    default=5,
    show_default=True,
    help="Energy level (1-10).",
)
def session_start(topic: str, energy: int) -> None:
    """Start a new study session. Creates DB record + state file."""
    from studyctl.history import start_study_session
    from studyctl.session_state import (
        PARKING_FILE,
        TOPICS_FILE,
        _ensure_session_dir,
        write_session_state,
    )

    _ensure_session_dir()

    # Map integer energy to label for history.py
    if energy <= 3:
        energy_label = "low"
    elif energy <= 7:
        energy_label = "medium"
    else:
        energy_label = "high"

    study_id = start_study_session(topic, energy_label)
    if not study_id:
        console.print("[red]Failed to start session. Run 'studyctl doctor' to diagnose.[/red]")
        raise SystemExit(1)

    # Write session state for dashboard viewports
    write_session_state(
        {
            "study_session_id": study_id,
            "topic": topic,
            "energy": energy,
            "energy_label": energy_label,
            "mode": "study",
        }
    )

    # Create empty IPC files for the dashboard (0600 permissions).
    # Explicit chmod ensures perms are tightened even if files pre-exist.
    for ipc_file in (TOPICS_FILE, PARKING_FILE):
        ipc_file.touch(exist_ok=True)
        ipc_file.chmod(0o600)

    console.print(f"[bold green]Session started:[/bold green] {topic} (energy: {energy}/10)")
    console.print(f"  Session ID: [dim]{study_id}[/dim]")
    console.print("\n  [dim]The study dashboard will update as your AI mentor teaches.[/dim]")
    console.print("  [dim]Open 'studyctl web' in a browser for the visual dashboard.[/dim]")


@session_group.command("end")
@click.option("--notes", "-n", default="", help="Session notes.")
def session_end(notes: str) -> None:
    """End the current study session. Exports data + cleanup."""
    from studyctl.history import end_study_session
    from studyctl.parking import park_topic
    from studyctl.session_state import (
        clear_session_files,
        parse_parking_file,
        parse_topics_file,
        read_session_state,
        write_session_state,
    )

    state = read_session_state()
    study_id = state.get("study_session_id")
    if not study_id:
        console.print("[yellow]No active session found.[/yellow]")
        return

    topic = state.get("topic", "unknown")

    # Parse topics for summary
    topics = parse_topics_file()
    wins = [t for t in topics if t.status in ("win", "insight")]
    struggles = [t for t in topics if t.status == "struggling"]

    # Ensure any parking file entries are in the DB
    parking_entries = parse_parking_file()
    for entry in parking_entries:
        park_topic(
            question=entry.question,
            topic_tag=entry.topic_tag or topic,
            study_session_id=study_id,
            created_by="agent",
        )

    # End the DB session
    end_study_session(study_id, notes=notes or None)

    # Signal dashboard to show summary view
    write_session_state({"mode": "ended"})

    # Print summary
    console.print(f"\n[bold]Session Complete[/bold] \u2014 {topic}\n")

    if wins:
        console.print("[bold green]\u2713 WINS[/bold green]")
        for t in wins:
            console.print(f"  \u2713 {t.topic} \u2014 {t.note}")

    if struggles:
        console.print("\n[bold yellow]\u25b2 FOR NEXT SESSION[/bold yellow]")
        for t in struggles:
            console.print(f"  \u25b2 {t.topic} \u2014 {t.note}")

    if parking_entries:
        console.print(
            f"\n[dim]\u25cb {len(parking_entries)} topic(s) parked for future sessions[/dim]"
        )

    console.print(
        "\n[dim]Stand up. Walk to the kitchen. Put the kettle on.\n"
        "Avoid your phone for 10-15 min \u2014 your brain will replay this at 20x speed.[/dim]"
    )

    # Clean up IPC files but keep state file for dashboard summary view.
    # State file will be cleared on next session start.
    clear_session_files(keep_state=True)


@session_group.command("status")
def session_status() -> None:
    """Show current session state (timer, topics, parking lot)."""
    from studyctl.session_state import (
        parse_parking_file,
        parse_topics_file,
        read_session_state,
    )

    state = read_session_state()
    if not state.get("study_session_id"):
        console.print(
            "[dim]No active session. Start one with 'studyctl session start -t <topic>'[/dim]"
        )
        return

    topic = state.get("topic", "unknown")
    energy = state.get("energy", "?")
    mode = state.get("mode", "study")
    console.print(f"[bold]Active session:[/bold] {topic} (energy: {energy}/10, mode: {mode})\n")

    topics = parse_topics_file()
    if topics:
        console.print("[bold]Topics covered:[/bold]")
        status_style = {
            "win": ("[green]\u2713[/green]", "green"),
            "insight": ("[green]\u2605[/green]", "green"),
            "learning": ("[blue]\u25c6[/blue]", "blue"),
            "struggling": ("[yellow]\u25b2[/yellow]", "yellow"),
            "parked": ("[dim]\u25cb[/dim]", "dim"),
        }
        for t in topics:
            icon, style = status_style.get(t.status, ("\u25c6", "blue"))
            console.print(f"  {icon} [{style}]{t.topic}[/{style}] \u2014 {t.note}")

    parking = parse_parking_file()
    if parking:
        console.print(f"\n[bold]Parking lot ({len(parking)}):[/bold]")
        for p in parking:
            console.print(f"  \u25cb {p.question}")

    wins_count = sum(1 for t in topics if t.status in ("win", "insight"))
    struggle_count = sum(1 for t in topics if t.status == "struggling")
    console.print(
        f"\n  \u2713 Wins: {wins_count}  |  \u25cb Parked: {len(parking)}"
        f"  |  \u25b2 Review: {struggle_count}"
    )


@click.command("topic")
@click.argument("name")
@click.option(
    "--status",
    "-s",
    default="learning",
    type=click.Choice(["learning", "struggling", "insight", "win", "parked"]),
    help="Topic status.",
)
@click.option("--note", "-n", default="", help="Brief note about progress.")
def topic_cmd(name: str, status: str, note: str) -> None:
    """Log a topic to the session activity feed.

    Used by AI agents to update the sidebar and web dashboard in real time.

    Examples:

        studyctl topic "Closures" --status learning --note "grasping the basics"

        studyctl topic "Decorators" --status win --note "can write property decorator"
    """
    from datetime import datetime

    from studyctl.session_state import append_topic, read_session_state

    state = read_session_state()
    if not state.get("study_session_id"):
        console.print("[yellow]No active session. Start one with 'studyctl study'.[/yellow]")
        return

    time_str = datetime.now().strftime("%H:%M")
    append_topic(time_str, name, status, note)

    shapes = {
        "win": "\u2713",
        "insight": "\u2605",
        "learning": "\u25c6",
        "struggling": "\u25b2",
        "parked": "\u25cb",
    }
    shape = shapes.get(status, "\u25c6")
    console.print(f"[dim]{shape} {name}[/dim]")


@click.command("park")
@click.argument("question")
@click.option("--topic", "-t", default=None, help="Topic tag for the parked item.")
@click.option("--context", "-c", default=None, help="What was being discussed.")
def park(question: str, topic: str | None, context: str | None) -> None:
    """Park a tangential topic for a future session."""
    from studyctl.parking import park_topic
    from studyctl.session_state import append_parking, read_session_state

    state = read_session_state()
    study_session_id = state.get("study_session_id")

    # Write to DB immediately (crash resilience)
    row_id = park_topic(
        question=question,
        topic_tag=topic,
        context=context,
        study_session_id=study_session_id,
        created_by="cli",
    )

    if row_id:
        # Also append to the IPC file for dashboard display
        if study_session_id:
            append_parking(question)
        console.print(f"[dim]\u25cb Parked:[/dim] {question}")
    else:
        console.print("[red]Failed to park topic. Run 'studyctl doctor' to diagnose.[/red]")
