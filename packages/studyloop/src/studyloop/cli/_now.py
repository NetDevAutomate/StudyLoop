"""Current-study recommendation command."""

from __future__ import annotations

import json

import click
from rich.panel import Panel
from rich.table import Table

from studyloop.cli._shared import console
from studyloop.learning import EnergyLevel, InterleaveMode, Modality, build_now_plan
from studyloop.learning.voice import speak_text


def _render_plan(plan) -> None:
    primary = plan.primary
    body = (
        f"[bold]{primary.concept}[/bold]\n"
        f"Topic: [cyan]{primary.topic}[/cyan]\n"
        f"Action: [yellow]{primary.action_type}[/yellow] for about "
        f"{primary.estimated_minutes} min\n"
        f"Why: {primary.reason}\n"
        f"Source: [dim]{primary.source}[/dim]\n\n"
        f"[bold]Record evidence:[/bold]\n{primary.evidence_command}"
    )
    console.print(Panel(body, title="Study Now", border_style="cyan"))

    if plan.interleave_ratio:
        ratio = " | ".join(f"{name}: {pct}%" for name, pct in plan.interleave_ratio.items())
        console.print(f"[dim]Adaptive interleave mix: {ratio}[/dim]")

    if plan.alternates:
        table = Table(title="Alternates")
        table.add_column("Concept", style="bold")
        table.add_column("Topic", style="cyan")
        table.add_column("Action")
        table.add_column("Why")
        for item in plan.alternates:
            table.add_row(item.concept, item.topic, item.action_type, item.reason)
        console.print(table)


@click.command("now")
@click.option(
    "--energy",
    type=click.Choice(["low", "medium", "high"]),
    default="medium",
    show_default=True,
)
@click.option("--time", "time_minutes", type=int, default=25, show_default=True)
@click.option(
    "--modality",
    type=click.Choice(["recall", "conversation", "hands-on", "visual", "audio"]),
    default="recall",
    show_default=True,
)
@click.option(
    "--interleave",
    type=click.Choice(["off", "adaptive"]),
    default="off",
    show_default=True,
)
@click.option("--json", "json_output", is_flag=True, help="Output recommendation as JSON.")
@click.option("--speak", is_flag=True, help="Speak the primary recommendation via study-speak.")
def now(
    energy: EnergyLevel,
    time_minutes: int,
    modality: Modality,
    interleave: InterleaveMode,
    json_output: bool,
    speak: bool,
) -> None:
    """Recommend the best study action for right now."""
    plan = build_now_plan(
        energy=energy,
        time_minutes=time_minutes,
        modality=modality,
        interleave=interleave,
    )
    if json_output:
        click.echo(json.dumps(plan.to_json_dict(), indent=2))
    else:
        _render_plan(plan)

    if speak:
        spoken = (
            f"Study {plan.primary.concept}. "
            f"Use {plan.primary.action_type} for about {plan.primary.estimated_minutes} minutes. "
            f"{plan.primary.reason}."
        )
        if not speak_text(spoken):
            console.print(
                "[yellow]Voice output was unavailable; continuing without speech.[/yellow]"
            )
