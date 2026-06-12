"""Daily recap command group."""

from __future__ import annotations

import json
from pathlib import Path

import click
from rich.panel import Panel

from studyloop.cli._shared import console
from studyloop.learning.recap import build_daily_recap
from studyloop.learning.voice import speak_text, synthesize_text_to_file


@click.group("recap")
def recap_group() -> None:
    """Short learning recaps."""


@recap_group.command("today")
@click.option("--speak", is_flag=True, help="Speak the recap through study-speak.")
@click.option(
    "--audio-file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Save the recap as a local audio file via OpenVox or macOS say.",
)
@click.option("--json", "json_output", is_flag=True, help="Output recap as JSON.")
def recap_today(speak: bool, audio_file: Path | None, json_output: bool) -> None:
    """Show one win, repair target, due item, and next action."""
    recap = build_daily_recap()
    if json_output:
        click.echo(json.dumps(recap.to_json_dict(), indent=2))
    else:
        console.print(
            Panel(
                "\n".join(
                    [
                        f"[bold green]Win:[/bold green] {recap.win}",
                        f"[bold yellow]Repair:[/bold yellow] {recap.repair_target}",
                        f"[bold cyan]Due:[/bold cyan] {recap.due_item}",
                        f"[bold]Next:[/bold] {recap.next_action}",
                    ]
                ),
                title="Today",
                border_style="cyan",
            )
        )
    if speak and not speak_text(recap.speakable_text()):
        console.print("[yellow]Voice output was unavailable; continuing without speech.[/yellow]")
    if audio_file:
        if synthesize_text_to_file(recap.speakable_text(), audio_file):
            console.print(f"[green]Audio recap saved:[/green] {audio_file}")
        else:
            console.print("[yellow]Audio export was unavailable; no file was written.[/yellow]")
