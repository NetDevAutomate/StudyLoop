"""Socratic companion prompt command for one note."""

from __future__ import annotations

from pathlib import Path

import click

from studyloop.cli._shared import console
from studyloop.learning.note_companion import (
    CompanionMode,
    build_note_companion_pack,
    pack_to_json,
)
from studyloop.learning.voice import speak_text


@click.command("chat-note")
@click.argument("path", type=click.Path(exists=False, path_type=Path))
@click.option(
    "--mode",
    type=click.Choice(["recall", "diagram", "trace", "teachback", "repair"]),
    default="recall",
    show_default=True,
)
@click.option("--voice", is_flag=True, help="Speak the first companion prompt.")
@click.option("--json", "json_output", is_flag=True, help="Output the context pack as JSON.")
def chat_note(path: Path, mode: CompanionMode, voice: bool, json_output: bool) -> None:
    """Build a Socratic context pack for a note."""
    try:
        pack = build_note_companion_pack(path, mode=mode)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        click.echo(pack_to_json(pack))
    else:
        console.print(f"[bold cyan]{pack.title}[/bold cyan] — {mode} companion\n")
        console.print(pack.prompt)
        console.print(f"\n[bold]Suggested evidence command:[/bold] {pack.suggested_command}")

    if voice:
        text = f"Let's discuss {pack.title}. Start by recalling the smallest concrete idea."
        if not speak_text(text):
            console.print(
                "[yellow]Voice output was unavailable; continuing without speech.[/yellow]"
            )
