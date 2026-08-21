"""Study plan command group.

The agent-facing surface for study plans. Every command has a ``--json``
form because a Socratic mentor agent drives these programmatically, while the
default human output stays readable in a terminal sidebar.

``plan evaluate`` prints the Markdown block by default: that is what an agent
pastes into the conversation at each of the three session checkpoints.
"""

from __future__ import annotations

import json
from typing import NoReturn

import click
from rich.table import Table

from studyloop.cli._shared import console
from studyloop.planning import (
    PLAN_STATUSES,
    StudyPlan,
    create_plan,
    draft_plan,
    evaluate_and_record,
    evaluate_plan,
    interview_spec,
    list_plans,
    load_plan,
    load_plan_text,
    plans_dir,
    readiness,
    reindex_all,
    save_plan,
    seed_from_history,
    unique_plan_id,
)
from studyloop.planning.store import (
    InvalidPlanIdError,
    PlanExistsError,
    PlanNotFoundError,
)


def _fail(message: str) -> NoReturn:
    """Print an error and exit non-zero, never a traceback.

    Typed ``NoReturn`` so callers like :func:`_load` are provably
    non-optional — otherwise every use site has to defend against a ``None``
    that can never actually arrive.
    """
    console.print(f"[red]{message}[/red]")
    raise SystemExit(1)


def _load(plan_id: str) -> StudyPlan:
    try:
        return load_plan(plan_id)
    except PlanNotFoundError:
        _fail(f"No study plan with id {plan_id!r}. Try: studyloop plan list")
    except InvalidPlanIdError as exc:
        _fail(str(exc))


def _print_readiness(check: dict) -> None:
    """Show what still blocks activation, then what would merely improve it."""
    if check["blockers"]:
        console.print("[yellow]Not ready to activate:[/yellow]")
        for item in check["blockers"]:
            console.print(f"  [red]•[/red] {item}")
    else:
        console.print("[green]Ready to activate.[/green]")
    for item in check["nudges"]:
        console.print(f"  [dim]• {item}[/dim]")


@click.group("plan")
def plan_group() -> None:
    """Create, inspect, and evaluate structured study plans."""


@plan_group.command("list")
@click.option(
    "--status",
    type=click.Choice(PLAN_STATUSES),
    default=None,
    help="Only show plans in this state.",
)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def plan_list(status: str | None, as_json: bool) -> None:
    """List study plans."""
    plans = list_plans(status=status or "")
    if as_json:
        click.echo(json.dumps([p.summary() for p in plans], indent=2))
        return
    if not plans:
        console.print("[dim]No study plans yet. Create one: studyloop plan new --title ...[/dim]")
        return

    table = Table(title="Study Plans")
    table.add_column("ID", style="bold")
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Progress")
    table.add_column("Next", style="dim")
    for plan in plans:
        # Bind once: calling next_milestone() twice both re-walks the milestone
        # list and leaves the Optional unnarrowed for the type checker.
        nxt = plan.next_milestone()
        table.add_row(
            plan.plan_id,
            plan.title,
            plan.status,
            f"{plan.milestone_done}/{plan.milestone_total} ({plan.progress_pct}%)",
            nxt.title if nxt else "—",
        )
    console.print(table)


@plan_group.command("show")
@click.argument("plan_id")
@click.option("--markdown", "as_markdown", is_flag=True, help="Print the raw document.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def plan_show(plan_id: str, as_markdown: bool, as_json: bool) -> None:
    """Show one study plan."""
    plan = _load(plan_id)
    if as_markdown:
        click.echo(load_plan_text(plan.plan_id))
        return
    if as_json:
        click.echo(
            json.dumps(
                {
                    "plan": plan.summary(),
                    "mission": {
                        "why": plan.mission.why,
                        "success": plan.mission.success,
                        "constraints": plan.mission.constraints,
                        "out_of_scope": plan.mission.out_of_scope,
                    },
                    "milestones": [
                        {"title": m.title, "done": m.done, "concepts": m.concepts}
                        for m in plan.milestones
                    ],
                    "readiness": readiness(plan),
                },
                indent=2,
            )
        )
        return

    console.print(f"[bold]{plan.title}[/bold]  [dim]({plan.plan_id})[/dim]")
    console.print(f"Status: {plan.status}   Progress: {plan.milestone_done}/{plan.milestone_total}")
    if plan.mission.why:
        console.print(f"\n[bold]Why[/bold]\n  {plan.mission.why}")
    if plan.milestones:
        console.print("\n[bold]Milestones[/bold]")
        for index, milestone in enumerate(plan.milestones):
            box = "x" if milestone.done else " "
            concepts = (
                f"  [dim]({', '.join(milestone.concepts)})[/dim]" if milestone.concepts else ""
            )
            console.print(f"  [{box}] {index}. {milestone.title}{concepts}")
    console.print()
    _print_readiness(readiness(plan))


@plan_group.command("new")
@click.option("--title", required=True, help="Plan title.")
@click.option("--why", default="", help="The mission: what changes once this is learned.")
@click.option("--topic", "topics", multiple=True, help="Topic (repeatable).")
@click.option("--success", "success", multiple=True, help="Success criterion (repeatable).")
@click.option(
    "--milestone",
    "milestones",
    multiple=True,
    help="Milestone, optionally 'Title (concepts: a, b)' (repeatable).",
)
@click.option("--constraint", "constraints", multiple=True, help="Constraint (repeatable).")
@click.option("--out-of-scope", "out_of_scope", multiple=True, help="Excluded topic (repeatable).")
@click.option("--resource", "resources", multiple=True, help="Source URL or label (repeatable).")
@click.option("--target-date", default="", help="Target date (YYYY-MM-DD).")
@click.option("--energy-floor", type=int, default=3, show_default=True, help="Minimum energy 1-10.")
@click.option("--activate", is_flag=True, help="Activate immediately (refused if incomplete).")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def plan_new(
    title: str,
    why: str,
    topics: tuple[str, ...],
    success: tuple[str, ...],
    milestones: tuple[str, ...],
    constraints: tuple[str, ...],
    out_of_scope: tuple[str, ...],
    resources: tuple[str, ...],
    target_date: str,
    energy_floor: int,
    activate: bool,
    as_json: bool,
) -> None:
    """Create a study plan.

    Omitted answers are left explicitly blank in the document rather than
    invented, and ``readiness`` reports what is still missing.
    """
    plan = draft_plan(
        title,
        {
            "why": why,
            "success": list(success),
            "topics": list(topics),
            "constraints": list(constraints),
            "out_of_scope": list(out_of_scope),
            "milestones": list(milestones),
            "resources": list(resources),
            "target_date": target_date,
            "energy_floor": energy_floor,
        },
        plan_id=unique_plan_id(title),
    )

    check = readiness(plan)
    if activate:
        if not check["ready"]:
            console.print(f"[red]Cannot activate {plan.plan_id!r} — the plan is incomplete.[/red]")
            _print_readiness(check)
            raise SystemExit(1)
        plan.status = "active"

    try:
        path = create_plan(plan)
    except PlanExistsError as exc:
        _fail(str(exc))
    except InvalidPlanIdError as exc:
        _fail(str(exc))

    if as_json:
        click.echo(
            json.dumps({"plan": plan.summary(), "readiness": check, "path": str(path)}, indent=2)
        )
        return
    console.print(f"[green]Created[/green] {plan.plan_id} → {path}")
    _print_readiness(check)


@plan_group.command("interview")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def plan_interview(as_json: bool) -> None:
    """Print the plan-creation interview and evidence-based seed suggestions.

    An agent calls this to learn what to ask, and what the databases already
    suggest the learner should plan for.
    """
    questions = interview_spec()
    seed = seed_from_history()
    if as_json:
        click.echo(json.dumps({"questions": questions, "seed": seed}, indent=2))
        return

    console.print("[bold]Plan interview[/bold] — work through these in order.\n")
    for index, question in enumerate(questions, 1):
        flag = "" if question["required"] else " [dim](optional)[/dim]"
        console.print(f"{index}. {question['prompt']}{flag}")
        console.print(f"   [dim]{question['why']}[/dim]")

    if seed.get("struggling_topics"):
        console.print("\n[bold]Struggling recently[/bold]")
        for item in seed["struggling_topics"]:
            console.print(f"  • {item['topic']}")
    if seed.get("due_concepts"):
        console.print("\n[bold]Due for review[/bold]")
        for item in seed["due_concepts"]:
            console.print(f"  • {item.get('concept') or item.get('topic')}")
    for note in seed.get("notes", []):
        console.print(f"  [dim]{note}[/dim]")


@plan_group.command("evaluate")
@click.argument("plan_id")
@click.option(
    "--phase",
    type=click.Choice(["start", "mid", "end"]),
    default="start",
    show_default=True,
    help="Which session checkpoint this is.",
)
@click.option("--record", is_flag=True, help="Persist the checkpoint and append it to the plan.")
@click.option("--study-id", default="", help="Session id to attribute the checkpoint to.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def plan_evaluate(plan_id: str, phase: str, record: bool, study_id: str, as_json: bool) -> None:
    """Evaluate a plan against your study and session history."""
    plan = _load(plan_id)
    evaluation = (
        evaluate_and_record(plan, phase, study_id=study_id)
        if record
        else evaluate_plan(plan, phase, study_id=study_id)
    )
    if as_json:
        click.echo(json.dumps(evaluation.to_dict(), indent=2, default=str))
        return
    click.echo(evaluation.as_markdown())
    if record:
        console.print("[green]Checkpoint recorded.[/green]")


@plan_group.command("milestone")
@click.argument("plan_id")
@click.argument("index", type=int)
@click.option("--done/--undone", "done", default=None, help="Set explicitly instead of toggling.")
def plan_milestone(plan_id: str, index: int, done: bool | None) -> None:
    """Toggle (or set) a milestone's completion state."""
    plan = _load(plan_id)
    if index < 0 or index >= len(plan.milestones):
        _fail(f"No milestone at index {index} (plan has {len(plan.milestones)}).")
    milestone = plan.milestones[index]
    milestone.done = (not milestone.done) if done is None else done
    save_plan(plan)
    state = "done" if milestone.done else "not done"
    console.print(
        f"[green]{milestone.title}[/green] → {state}  "
        f"({plan.milestone_done}/{plan.milestone_total}, {plan.progress_pct}%)"
    )


@plan_group.command("status")
@click.argument("plan_id")
@click.argument("status", type=click.Choice(PLAN_STATUSES))
def plan_status(plan_id: str, status: str) -> None:
    """Change a plan's lifecycle state.

    Activation is refused while the plan is missing a mission, success
    criteria, or milestones — an unevaluable plan must not look active.
    """
    plan = _load(plan_id)
    if status == "active":
        check = readiness(plan)
        if not check["ready"]:
            console.print(f"[red]Cannot activate {plan.plan_id!r} — the plan is incomplete.[/red]")
            _print_readiness(check)
            raise SystemExit(1)
    plan.status = status
    save_plan(plan)
    console.print(f"[green]{plan.plan_id}[/green] → {status}")


@plan_group.command("reindex")
def plan_reindex() -> None:
    """Rebuild the derived plan index in the sessions DB from the documents."""
    count = reindex_all()
    console.print(f"[green]Reindexed[/green] {count} plan(s).")


@plan_group.command("path")
def plan_path_cmd() -> None:
    """Print the directory holding plan documents."""
    click.echo(str(plans_dir()))
