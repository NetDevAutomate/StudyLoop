"""Daily recap command group."""

from __future__ import annotations

import json

import click
from rich.panel import Panel

from studyloop.cli._shared import console
from studyloop.learning.recap import build_daily_recap
from studyloop.learning.voice import speak_text


@click.group("recap")
def recap_group() -> None:
    """Short learning recaps."""


@recap_group.command("today")
@click.option("--speak", is_flag=True, help="Speak the recap through study-speak.")
@click.option("--json", "json_output", is_flag=True, help="Output recap as JSON.")
def recap_today(speak: bool, json_output: bool) -> None:
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
