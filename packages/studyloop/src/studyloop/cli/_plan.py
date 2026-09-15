"""Study plan command group.

The agent-facing surface for study plans. Every command has a ``--json``
form because a Socratic mentor agent drives these programmatically, while the
default human output stays readable in a terminal sidebar.

``plan evaluate`` prints the Markdown block by default: that is what an agent
pastes into the conversation at each of the three session checkpoints.

``list``, ``show`` and ``status`` read and write through
:class:`~studyloop.planning.PlanApplication`, so the activation refusal here is
the same refusal the Web API gives — same blockers, same nudges, no write.
``new``, ``interview``, ``evaluate``, ``milestone`` and ``record`` move onto
the seam in Phase 2 and still use the storage modules directly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

import click
from rich.table import Table

from studyloop.cli._shared import console
from studyloop.planning import (
    PLAN_STATUSES,
    InvalidField,
    InvalidMilestone,
    InvalidPlanId,
    PlanApplication,
    PlanConflict,
    PlanError,
    PlanNotFound,
    PlanNotReady,
    ReadinessView,
    StudyPlan,
    TransitionLifecycle,
    create_plan,
    draft_plan,
    evaluate_and_record,
    evaluate_plan,
    interview_spec,
    load_plan,
    plans_dir,
    record_learning,
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

if TYPE_CHECKING:
    from studyloop.planning import PlanDetail


def _fail(message: str) -> NoReturn:
    """Print an error and exit non-zero, never a traceback.

    Typed ``NoReturn`` so callers like :func:`_load` are provably
    non-optional — otherwise every use site has to defend against a ``None``
    that can never actually arrive.
    """
    console.print(f"[red]{message}[/red]")
    raise SystemExit(1)


def _fail_for(exc: PlanError, plan_id: str) -> NoReturn:
    """Map a seam refusal to the CLI's message and exit code (design §2).

    Every domain error has its own line, so an agent reading the output can
    tell a missing plan from a taken id from a bad value without parsing the
    seam's exception text. The final ``_fail`` is the safety net for a
    ``PlanError`` subclass this mapping has not met yet.
    """
    if isinstance(exc, PlanNotFound):
        _fail(f"No study plan with id {plan_id!r}. Try: studyloop plan list")
    if isinstance(exc, PlanNotReady):
        _refuse_activation(exc.readiness)
    if isinstance(exc, PlanConflict):
        _fail(f"A study plan with id {plan_id!r} already exists. Choose another id.")
    if isinstance(exc, InvalidPlanId):
        _fail(f"Invalid plan id {plan_id!r}: {exc}")
    if isinstance(exc, InvalidField):
        _fail(f"Invalid value: {exc}")
    if isinstance(exc, InvalidMilestone):
        _fail(f"No such milestone on {plan_id!r}: {exc}")
    _fail(str(exc))


def _inspect(plan_id: str, *, include_markdown: bool = False) -> PlanDetail:
    try:
        return PlanApplication().inspect(plan_id, include_markdown=include_markdown)
    except PlanError as exc:
        _fail_for(exc, plan_id)


def _load(plan_id: str) -> StudyPlan:
    """Load the mutable model for the commands Phase 2 has not migrated yet."""
    try:
        return load_plan(plan_id)
    except PlanNotFoundError:
        _fail(f"No study plan with id {plan_id!r}. Try: studyloop plan list")
    except InvalidPlanIdError as exc:
        _fail(str(exc))


def _print_readiness(check: ReadinessView) -> None:
    """Show what still blocks activation, then what would merely improve it."""
    if check.blockers:
        console.print("[yellow]Not ready to activate:[/yellow]")
        for item in check.blockers:
            console.print(f"  [red]•[/red] {item}")
    else:
        console.print("[green]Ready to activate.[/green]")
    for item in check.nudges:
        console.print(f"  [dim]• {item}[/dim]")


def _refuse_activation(check: ReadinessView) -> NoReturn:
    """The one way every command says no to activating an incomplete plan."""
    console.print(f"[red]Cannot activate {check.plan_id!r} — the plan is incomplete.[/red]")
    _print_readiness(check)
    raise SystemExit(1)


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
    try:
        plans = PlanApplication().browse(status=status)
    except PlanError as exc:
        _fail_for(exc, status or "")
    if as_json:
        click.echo(json.dumps([p.to_json_dict() for p in plans], indent=2))
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
        table.add_row(
            plan.plan_id,
            plan.title,
            plan.status,
            f"{plan.milestone_done}/{plan.milestone_total} ({plan.progress_pct}%)",
            plan.next_milestone or "—",
        )
    console.print(table)


@plan_group.command("show")
@click.argument("plan_id")
@click.option("--markdown", "as_markdown", is_flag=True, help="Print the raw document.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def plan_show(plan_id: str, as_markdown: bool, as_json: bool) -> None:
    """Show one study plan."""
    detail = _inspect(plan_id, include_markdown=as_markdown)
    if as_markdown:
        click.echo(detail.markdown or "")
        return
    if as_json:
        click.echo(
            json.dumps(
                {
                    "plan": detail.summary.to_json_dict(),
                    "mission": detail.mission.to_json_dict(),
                    "milestones": [
                        {"title": m.title, "done": m.done, "concepts": list(m.concepts)}
                        for m in detail.milestones
                    ],
                    "readiness": detail.readiness.to_json_dict(),
                },
                indent=2,
            )
        )
        return

    plan = detail.summary
    console.print(f"[bold]{plan.title}[/bold]  [dim]({plan.plan_id})[/dim]")
    console.print(f"Status: {plan.status}   Progress: {plan.milestone_done}/{plan.milestone_total}")
    if detail.mission.why:
        console.print(f"\n[bold]Why[/bold]\n  {detail.mission.why}")
    if detail.milestones:
        console.print("\n[bold]Milestones[/bold]")
        for milestone in detail.milestones:
            box = "x" if milestone.done else " "
            concepts = (
                f"  [dim]({', '.join(milestone.concepts)})[/dim]" if milestone.concepts else ""
            )
            console.print(f"  [{box}] {milestone.index}. {milestone.title}{concepts}")
    console.print()
    _print_readiness(detail.readiness)


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

    check = ReadinessView.from_plan(plan)
    if activate:
        if not check.ready:
            _refuse_activation(check)
        plan.status = "active"

    try:
        path = create_plan(plan)
    except PlanExistsError as exc:
        _fail(str(exc))
    except InvalidPlanIdError as exc:
        _fail(str(exc))

    if as_json:
        click.echo(
            json.dumps(
                {"plan": plan.summary(), "readiness": check.to_json_dict(), "path": str(path)},
                indent=2,
            )
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
    criteria, or milestones — an unevaluable plan must not look active. The
    refusal is the seam's, so it is the same one the Web API gives.
    """
    try:
        detail = PlanApplication().apply(TransitionLifecycle(plan_id=plan_id, status=status))
    except PlanError as exc:
        _fail_for(exc, plan_id)  # PlanNotReady → the blockers, exit 1; the rest one line each
    console.print(f"[green]{detail.summary.plan_id}[/green] → {status}")


@plan_group.command("record")
@click.argument("plan_id")
@click.option("--title", required=True, help="What was learned, in one line.")
@click.option("--body", default="", help="The record's body, as Markdown prose.")
@click.option(
    "--body-file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Read the body from a file instead of --body.",
)
@click.option(
    "--status",
    default="active",
    show_default=True,
    help="Record status (e.g. active, superseded).",
)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def plan_record(
    plan_id: str, title: str, body: str, body_file: str | None, status: str, as_json: bool
) -> None:
    """Append a learning record to a plan — the wind-down's 'record first' step.

    Parses the document, appends the record to the model, and re-renders the
    whole file, so the on-disk shape stays the renderer's business (ADR-0010).
    Re-running with the same title and body is a no-op, which makes it safe for
    an agent to retry.
    """
    if body and body_file:
        _fail("Pass --body or --body-file, not both.")
    if body_file:
        body = Path(body_file).read_text(encoding="utf-8")
    plan = _load(plan_id)  # maps not-found/invalid-id to the friendly failure
    try:
        record, created = record_learning(plan.plan_id, title, body=body, status=status)
    except ValueError as exc:
        _fail(str(exc))
    if as_json:
        click.echo(
            json.dumps(
                {
                    "plan_id": plan.plan_id,
                    "number": record.number,
                    "title": record.title,
                    "status": record.status,
                    "created": created,
                },
                indent=2,
            )
        )
        return
    verb = "recorded" if created else "already recorded (no change)"
    console.print(f"[green]LR-{record.number:04d}[/green] — {record.title}: {verb}")


@plan_group.command("reindex")
def plan_reindex() -> None:
    """Rebuild the derived plan index in the sessions DB from the documents."""
    count = reindex_all()
    console.print(f"[green]Reindexed[/green] {count} plan(s).")


@plan_group.command("architect")
@click.option(
    "--agent",
    "-a",
    help="AI agent to launch (auto-detects if omitted).",
)
@click.pass_context
def plan_architect(ctx: click.Context, agent: str | None) -> None:
    """Start a study-plan-architect session.

    Convenience alias for ``studyloop study --mode plan-architect``, pinned to
    the topic "Study plan" so the interview-and-evaluate mentor never needs a
    topic of its own -- it is the same launch machinery every other mode uses,
    never a second launch path.
    """
    from studyloop.cli._study import study

    ctx.invoke(
        study,
        topic="Study plan",
        agent=agent,
        mode="plan-architect",
        timer=None,
        energy=5,
        web=False,
        lan=False,
        password="",
        resume=False,
        end_session=False,
    )


@plan_group.command("path")
def plan_path_cmd() -> None:
    """Print the directory holding plan documents."""
    click.echo(str(plans_dir()))
