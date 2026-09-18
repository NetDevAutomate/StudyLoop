"""Study plan command group.

The agent-facing surface for study plans. Every command has a ``--json``
form because a Socratic mentor agent drives these programmatically, while the
default human output stays readable in a terminal sidebar.

``plan evaluate`` prints the Markdown block by default: that is what an agent
pastes into the conversation at each of the three session checkpoints.

Every command reads and writes through
:class:`~studyloop.planning.PlanApplication` — ``browse`` / ``inspect`` /
``prepare_planning`` to read, ``apply`` with an intent to write, ``assess`` to
evaluate — so the activation refusal here is the same refusal the Web API
gives (same blockers, same nudges, no write), a milestone set is idempotent,
and a recorded checkpoint reports both of its sinks. This module maps domain
errors to exit codes and messages (design §2) and formats output; it holds no
plan rule of its own and imports no storage module (D-6).
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
    AssessPlan,
    CompletionReview,
    CreatePlan,
    InvalidField,
    InvalidMilestone,
    InvalidPlanId,
    LearningRecordSpec,
    PlanApplication,
    PlanConflict,
    PlanError,
    PlanNotFound,
    PlanNotReady,
    ReadinessView,
    RevisePlan,
    SetMilestone,
    TransitionLifecycle,
    plans_dir,
)

if TYPE_CHECKING:
    from studyloop.planning import AssessmentResult, PlanDetail, PlanDetailIntent, PlanSummary


def _fail(message: str) -> NoReturn:
    """Print an error and exit non-zero, never a traceback.

    Typed ``NoReturn`` so callers like :func:`_inspect` are provably
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
        _refuse_activation(exc.readiness, already_active=exc.already_active)
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


def _apply(intent: PlanDetailIntent) -> PlanDetail:
    """Apply one intent, mapping any refusal to the one-line failure."""
    try:
        return PlanApplication().apply(intent)
    except PlanError as exc:
        _fail_for(exc, intent.plan_id or "")


def _assess(intent: AssessPlan) -> AssessmentResult:
    try:
        return PlanApplication().assess(intent)
    except PlanError as exc:
        _fail_for(exc, intent.plan_id)


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


def _refuse_activation(check: ReadinessView, *, already_active: bool = False) -> NoReturn:
    """The one way every command says no to activating an incomplete plan.

    When the plan is *already* active (a hand-edited or pre-gate document),
    "activate" is the wrong verb for what the learner tried to do — record,
    tick a milestone, log a checkpoint — so the refusal also says what to do
    next: pause the plan or repair the blockers (council review 2).
    """
    console.print(f"[red]Cannot activate {check.plan_id!r} — the plan is incomplete.[/red]")
    _print_readiness(check)
    if already_active:
        console.print(
            f"[yellow]This plan is already active but incomplete, so it cannot be written to "
            f"as it stands. Repair it with the architect (studyloop plan repair {check.plan_id}) "
            f"or pause it (studyloop plan status {check.plan_id} paused), then retry.[/yellow]"
        )
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
@click.option(
    "--husks",
    "husks_only",
    is_flag=True,
    help="Only active plans that are not ready (they refuse every write until repaired or paused).",
)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def plan_list(status: str | None, husks_only: bool, as_json: bool) -> None:
    """List study plans.

    An active plan that is not ready — a "husk" — is marked ``!`` after its
    status: the readiness gate refuses every write to it until it is repaired
    (``studyloop plan repair <id>``) or paused. Every ``--json`` row carries
    ``ready`` so an agent needs no second call to tell.
    """
    try:
        if husks_only:
            plans = tuple(h.summary for h in PlanApplication().husks())
            if status and status != "active":
                plans = ()  # a husk is active by definition; any other status matches none
        else:
            plans = PlanApplication().browse(status=status)
    except PlanError as exc:
        _fail_for(exc, status or "")
    if as_json:
        click.echo(json.dumps([p.to_json_dict() for p in plans], indent=2))
        return
    if not plans:
        if husks_only:
            console.print("[dim]No active plan is blocked. Every active plan is ready.[/dim]")
        else:
            console.print(
                "[dim]No study plans yet. Create one: studyloop plan new --title ...[/dim]"
            )
        return

    table = Table(title="Study Plans")
    table.add_column("ID", style="bold")
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Progress")
    table.add_column("Next", style="dim")
    for plan in plans:
        is_husk = plan.status == "active" and not plan.ready
        table.add_row(
            plan.plan_id,
            plan.title,
            f"{plan.status} [red]![/red]" if is_husk else plan.status,
            f"{plan.milestone_done}/{plan.milestone_total} ({plan.progress_pct}%)",
            plan.next_milestone or "—",
        )
    console.print(table)
    if any(p.status == "active" and not p.ready for p in plans):
        console.print(
            "[yellow]! = active but not ready: refuses every write until repaired "
            "(studyloop plan repair <id>) or paused.[/yellow]"
        )


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
    invented, and ``readiness`` reports what is still missing. ``--activate``
    is the same ``CreatePlan`` with ``status="active"``: the seam judges the
    resulting document and refuses — writing nothing — when it is incomplete,
    exactly as ``plan status <id> active`` and the Web API do.
    """
    detail = _apply(
        CreatePlan(
            title=title,
            answers={
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
            status="active" if activate else "draft",
        )
    )
    # Plans live as ``<id>.md`` in the plans directory (``studyloop plan
    # path``); the path is shown as a convenience for the learner, not read.
    path = plans_dir() / f"{detail.summary.plan_id}.md"

    if as_json:
        click.echo(
            json.dumps(
                {
                    "plan": detail.summary.to_json_dict(),
                    "readiness": detail.readiness.to_json_dict(),
                    "path": str(path),
                },
                indent=2,
            )
        )
        return
    console.print(f"[green]Created[/green] {detail.summary.plan_id} → {path}")
    _print_readiness(detail.readiness)


@plan_group.command("interview")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def plan_interview(as_json: bool) -> None:
    """Print the plan-creation interview and evidence-based seed suggestions.

    An agent calls this to learn what to ask, and what the databases already
    suggest the learner should plan for.
    """
    brief = PlanApplication().prepare_planning()
    seed = brief.to_json_dict()["seed"]
    if as_json:
        questions = brief.to_json_dict()["questions"]
        click.echo(json.dumps({"questions": questions, "seed": seed}, indent=2))
        return

    console.print("[bold]Plan interview[/bold] — work through these in order.\n")
    for index, question in enumerate(brief.interview, 1):
        flag = "" if question.required else " [dim](optional)[/dim]"
        console.print(f"{index}. {question.prompt}{flag}")
        console.print(f"   [dim]{question.why}[/dim]")

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
    """Evaluate a plan against your study and session history.

    With ``--record`` the checkpoint goes to the durable log and to the plan
    document; each write is reported on its own, so a failed database write
    is named rather than hidden behind "recorded" — and a checkpoint that
    landed nowhere is "not recorded", never "partially" (review 2, F9).
    """
    result = _assess(AssessPlan(plan_id=plan_id, phase=phase, study_id=study_id, record=record))
    if as_json:
        click.echo(json.dumps(result.evaluation.to_json_dict(), indent=2, default=str))
        return
    click.echo(result.evaluation.markdown)
    if not record:
        return
    if result.recording_complete:
        console.print("[green]Checkpoint recorded.[/green]")
    else:
        headline = "partially recorded" if result.any_sink_saved else "not recorded"
        console.print(
            f"[yellow]Checkpoint {headline} — "
            f"database: {result.db_write}, document: {result.document_write}[/yellow]"
        )


@plan_group.command("milestone")
@click.argument("plan_id")
@click.argument("index", type=int)
@click.option("--done/--undone", "done", default=None, help="Set explicitly instead of toggling.")
def plan_milestone(plan_id: str, index: int, done: bool | None) -> None:
    """Toggle (or set) a milestone's completion state.

    Either way the write is one idempotent ``SetMilestone``: with a flag the
    state is set as asked (running it twice is safe); without one the current
    state is read and its opposite is set. An index the plan does not have —
    past the end or negative — is refused by the seam.
    """
    if done is None:
        current = _inspect(plan_id)
        done = not any(m.index == index and m.done for m in current.milestones)
    detail = _apply(SetMilestone(plan_id=plan_id, index=index, done=done))
    milestone = detail.milestones[index]
    state = "done" if milestone.done else "not done"
    console.print(
        f"[green]{milestone.title}[/green] → {state}  "
        f"({detail.summary.milestone_done}/{detail.summary.milestone_total}, "
        f"{detail.summary.progress_pct}%)"
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
    detail = _apply(TransitionLifecycle(plan_id=plan_id, status=status))
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

    One ``RevisePlan`` carrying the record: the seam parses the document,
    appends through the store's single learning-record rule, and re-renders
    the whole file, so the on-disk shape stays the renderer's business
    (ADR-0010). Re-running with the same title and body adds nothing, which
    makes it safe for an agent to retry; ``created`` says which happened —
    and it is the mutation's own outcome, not a read taken before it, so a
    record another writer filed in between is reported honestly (review 2).
    """
    if body and body_file:
        _fail("Pass --body or --body-file, not both.")
    if body_file:
        body = Path(body_file).read_text(encoding="utf-8")
    spec = LearningRecordSpec(title=title, body=body, status=status)
    detail = _apply(RevisePlan(plan_id=plan_id, learning_record=spec))
    outcome = detail.learning_record_outcome
    if outcome is None:  # pragma: no cover - a revision carrying a record always reports one
        _fail(f"Learning record {spec.title!r} was not persisted on {plan_id!r}.")
    record, created = outcome.record, outcome.created
    if as_json:
        click.echo(
            json.dumps(
                {
                    "plan_id": detail.summary.plan_id,
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
    count = PlanApplication().reindex()
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


#: The sentence that frames a repair brief in place of the planning one.
REPAIR_BRIEF_INTRO = (
    "This is a PLAN REPAIR session: the plan below is active but incomplete — "
    "ask the learner only for what is missing, then repair it."
)


def _render_plan_as_it_stands(s: PlanSummary) -> str:
    """The ``### The plan as it stands`` section both launch briefs carry."""
    topics = ", ".join(s.topics) if s.topics else "(none)"
    return (
        "### The plan as it stands\n\n"
        f"- Title: {s.title}\n"
        f"- Id: {s.plan_id}\n"
        f"- Status: {s.status}\n"
        f"- Topics: {topics}\n"
        f"- Milestones: {s.milestone_done}/{s.milestone_total} done\n"
        f"- Created: {s.created}\n"
    )


def _render_repair_brief(detail: PlanDetail) -> str:
    """The brief ``plan repair`` hands the architect: blockers first, then the plan as it stands.

    The first section lists exactly ``readiness.blockers`` as ``- `` lines and
    nothing else, so the agent (and the test) can read "what is missing" off
    the top without parsing prose. The provenance sentence is the same one
    ``doctor`` prints — one definition, two surfaces.
    """
    from studyloop.planning import husk_provenance

    s = detail.summary
    blockers = "\n".join(f"- {item}" for item in detail.readiness.blockers)
    return (
        "### Repair: what this plan is missing\n\n"
        f"{blockers}\n\n"
        f"{_render_plan_as_it_stands(s)}\n"
        f"{husk_provenance(s.created)}\n"
    )


@plan_group.command("repair")
@click.argument("plan_id")
@click.option(
    "--agent",
    "-a",
    help="AI agent to launch (auto-detects if omitted).",
)
@click.pass_context
def plan_repair(ctx: click.Context, plan_id: str, agent: str | None) -> None:
    """Repair an active plan the readiness gate refuses to write to, with the architect.

    An active plan that is not ready (a "husk": no mission, no success
    criteria or no milestones) refuses every write until it is repaired or
    paused. This launches the study-plan-architect — the same ``studyloop
    study --mode plan-architect`` chain as ``plan architect``, never a second
    path — with a brief that lists exactly what is missing and the plan as it
    stands. The command itself writes nothing: the document changes only when
    the architect and the learner repair it through the seam.

    A ready plan has nothing to repair (exit 0). A plan that is not active is
    not blocked by anything — finish it with ``studyloop plan architect``.
    """
    detail = _inspect(plan_id)
    s = detail.summary
    if detail.readiness.ready:
        console.print(f"[green]Nothing to repair on {s.plan_id!r} — the plan is ready.[/green]")
        return
    if s.status != "active":
        console.print(
            f"[dim]{s.plan_id!r} is {s.status}, so nothing blocks it — a plan is only refused "
            "writes while it is active and incomplete. Finish it with "
            "`studyloop plan architect`.[/dim]"
        )
        _print_readiness(detail.readiness)
        return

    from studyloop.cli._study import study

    console.print(
        f"[yellow]{s.plan_id!r} ({s.title}) is active but not ready. "
        "Launching the architect to repair it.[/yellow]"
    )
    ctx.invoke(
        study,
        topic=s.title,
        agent=agent,
        mode="plan-architect",
        timer=None,
        energy=5,
        web=False,
        lan=False,
        password="",
        resume=False,
        end_session=False,
        brief=_render_repair_brief(detail),
        brief_intro=REPAIR_BRIEF_INTRO,
    )


#: The sentence that frames a closing-review brief in place of the planning one.
CLOSE_BRIEF_INTRO = (
    "This is a CLOSING REVIEW session: every milestone of the plan below is checked off — "
    "read the evidence back to the learner, propose extending or closing, ask what they are "
    "not comfortable with, and change the plan's status only when the learner agrees."
)


def _render_closing_brief(detail: PlanDetail, review: CompletionReview) -> str:
    """The brief ``plan close`` hands the architect: the closing review first, then the plan.

    The first section's first four ``- `` lines are the three counts and the
    proposal, followed by one evidence line per counted item — readable off
    the top without parsing prose, as the repair brief's blockers are. The
    review is the same :class:`~studyloop.planning.CompletionReview` the
    ``now`` engine puts on its completion action: one definition, two surfaces.
    A partial read (a reader unavailable, council review 6 F1) is that
    definition's business too: the proposal line reads ``unassessed — the
    review is partial`` and the review's evidence names each reader that was
    not read, so the agent knows the counts are what was read so far.
    """
    proposal = review.proposal or "unassessed — the review is partial"
    lines = [
        f"Due reviews on plan concepts: {review.due_reviews}",
        f"Struggles on plan concepts: {review.struggles}",
        f"Unverified milestones: {review.unverified_milestones}",
        f"Proposal: {proposal}",
        *review.evidence,
    ]
    return (
        "### Closing review\n\n"
        + "\n".join(f"- {line}" for line in lines)
        + "\n\n"
        + _render_plan_as_it_stands(detail.summary)
    )


@plan_group.command("close")
@click.argument("plan_id")
@click.option(
    "--agent",
    "-a",
    help="AI agent to launch (auto-detects if omitted).",
)
@click.pass_context
def plan_close(ctx: click.Context, plan_id: str, agent: str | None) -> None:
    """Review a fully-checked plan with the architect and decide: extend it or close it.

    A plan whose every milestone is checked is finished work, not yet a
    finished plan. This runs the end assessment as a preview — due reviews,
    struggles and milestones marked done without evidence, counted on the
    plan's own concepts — and launches the study-plan-architect (the same
    ``studyloop study --mode plan-architect`` chain as ``plan architect`` and
    ``plan repair``, never a second path) with those counts, the proposal they
    imply and the evidence as the first section of its brief. The command
    itself writes nothing: no checkpoint is recorded, and the status changes
    only when the learner agrees in that session (``set_study_plan_status``).

    A plan with open milestones has nothing to close yet (exit 1, naming how
    many are open); a plan that is already ``complete`` is left alone.
    """
    detail = _inspect(plan_id)
    s = detail.summary
    if s.status == "complete":
        console.print(f"[dim]{s.plan_id!r} is already complete.[/dim]")
        return
    if s.milestone_total == 0:
        _fail(
            f"{s.plan_id!r} has no milestones, so there is nothing to close — finish it with "
            "studyloop plan architect."
        )
    open_count = s.milestone_total - s.milestone_done
    if open_count:
        _fail(
            f"{s.plan_id!r} still has {open_count} open milestone(s) — nothing to close yet. "
            f"Tick each as the learner demonstrates it: "
            f"studyloop plan milestone {s.plan_id} INDEX --done"
        )

    result = _assess(AssessPlan(plan_id=s.plan_id, phase="end", record=False))
    review = CompletionReview.from_evaluation(result.evaluation)

    from studyloop.cli._study import study

    if review.partial:
        console.print(
            f"[yellow]{s.plan_id!r} ({s.title}) has every milestone checked, but the closing "
            "review is partial — a reader was unavailable, so it does not propose. Launching "
            "the architect to walk what was read with you.[/yellow]"
        )
    else:
        console.print(
            f"[green]{s.plan_id!r} ({s.title}) has every milestone checked; the closing review "
            f"proposes: {review.proposal}. Launching the architect to decide with you.[/green]"
        )
    ctx.invoke(
        study,
        topic=s.title,
        agent=agent,
        mode="plan-architect",
        timer=None,
        energy=5,
        web=False,
        lan=False,
        password="",
        resume=False,
        end_session=False,
        brief=_render_closing_brief(detail, review),
        brief_intro=CLOSE_BRIEF_INTRO,
    )


@plan_group.command("path")
def plan_path_cmd() -> None:
    """Print the directory holding plan documents."""
    click.echo(str(plans_dir()))
