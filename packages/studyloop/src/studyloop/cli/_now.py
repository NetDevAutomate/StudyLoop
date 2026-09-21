"""Current-study recommendation command."""

from __future__ import annotations

import json

import click
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from studyloop.cli._shared import console
from studyloop.learning import EnergyLevel, InterleaveMode, Modality, build_now_plan
from studyloop.learning.voice import speak_text


def _active_plans(plan) -> dict:
    """``plan_id → ActivePlanSummary`` for every active plan the engine listed."""
    return {entry.plan_id: entry for entry in getattr(plan, "active_plans", ())}


def _plan_line(rec, plans: dict) -> str:
    """One line naming every plan an action advances, in the engine's order.

    Rendering only: the refs and their order come from the ranker; a
    milestone is named when the ref points at one.
    """
    parts: list[str] = []
    for ref in getattr(rec, "plan_refs", ()):
        entry = plans.get(ref.plan_id)
        label = entry.title if entry is not None else ref.plan_id
        if ref.milestone_index is not None:
            label += f" (milestone {ref.milestone_index + 1}"
            if entry is not None and entry.next_milestone_index == ref.milestone_index:
                label += f": {entry.next_milestone}"
            label += ")"
        parts.append(label)
    return "; ".join(parts)


def _render_plan(plan) -> None:
    # Every learner-authored string — concepts, reasons, plan titles, milestone
    # titles, warnings — is escaped before it meets Rich markup: a plan titled
    # "SQL [/bold] Windows" is text to show, not a closing tag to parse
    # (council review 3, F4: it used to raise MarkupError and exit 1).
    primary = plan.primary
    plans = _active_plans(plan)
    plan_line = _plan_line(primary, plans)
    # A body-double primary (design §5) carries the co-study session door, not a
    # progress write: label it as the door it is.
    door = "Sit with the plan" if primary.source == "body_double" else "Record evidence"
    body = (
        f"[bold]{escape(primary.concept)}[/bold]\n"
        f"Topic: [cyan]{escape(primary.topic)}[/cyan]\n"
        f"Action: [yellow]{escape(primary.action_type)}[/yellow] for about "
        f"{primary.estimated_minutes} min\n"
        f"Why: {escape(primary.reason)}\n"
        f"Source: [dim]{escape(primary.source)}[/dim]\n"
        + (f"Plan: [magenta]{escape(plan_line)}[/magenta]\n" if plan_line else "")
        + f"\n[bold]{door}:[/bold]\n{escape(primary.evidence_command)}"
    )
    console.print(Panel(body, title="Study Now", border_style="cyan"))

    if plan.interleave_ratio:
        ratio = " | ".join(f"{name}: {pct}%" for name, pct in plan.interleave_ratio.items())
        console.print(f"[dim]Adaptive interleave mix: {ratio}[/dim]")

    for deferred in getattr(plan, "energy_deferred", ()):
        console.print(
            f"[yellow]Deferred for energy:[/yellow] {escape(deferred.plan_title)} — "
            f"milestone {deferred.milestone_index + 1} “{escape(deferred.title)}” needs "
            f"energy {deferred.energy_floor}/10; {plan.energy} energy carries "
            f"{deferred.energy_capability}/10. Due recall and gentle review stay available."
        )
    # One line per deferred repair (design §5, amendment 2): its own key, its
    # own sentence — a repair has no milestone number to print.
    for repair in getattr(plan, "energy_deferred_repairs", ()):
        where = f"{escape(repair.plan_title)} — " if repair.plan_title else ""
        console.print(
            f"[yellow]Deferred for energy:[/yellow] {where}repairing "
            f"“{escape(repair.concept)}” ({escape(repair.confidence)}) asks for "
            f"{repair.required_capability}/10; {plan.energy} energy carries "
            f"{repair.energy_capability}/10. Due recall and gentle review stay available."
        )
    for completion in getattr(plan, "completion_actions", ()):
        # "Closing review", not "Plan complete": the status is still active until
        # the learner agrees with the architect (council review 6, F6).
        console.print(f"[green]Closing review:[/green] {escape(completion.action)}")
        # The review's evidence, one dim line per counted item (D-G); the
        # sentence above already carries the proposal and the counts.
        for line in getattr(completion, "evidence", ()):
            console.print(f"  [dim]• {escape(line)}[/dim]")
    for warning in getattr(plan, "warnings", ()):
        console.print(f"[dim]Plan warning: {escape(warning)}[/dim]")

    if plan.alternates:
        table = Table(title="Alternates")
        table.add_column("Concept", style="bold")
        table.add_column("Topic", style="cyan")
        table.add_column("Action")
        table.add_column("Why")
        if plans:
            table.add_column("Plan", style="magenta")
        for item in plan.alternates:
            row = [
                escape(item.concept),
                escape(item.topic),
                escape(item.action_type),
                escape(item.reason),
            ]
            if plans:
                row.append(escape(_plan_line(item, plans)))
            table.add_row(*row)
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
        plan_line = _plan_line(plan.primary, _active_plans(plan))
        spoken = (
            f"Study {plan.primary.concept}. "
            f"Use {plan.primary.action_type} for about {plan.primary.estimated_minutes} minutes. "
            f"{plan.primary.reason}."
            + (f" This advances your plan {plan_line}." if plan_line else "")
        )
        if not speak_text(spoken):
            console.print(
                "[yellow]Voice output was unavailable; continuing without speech.[/yellow]"
            )
