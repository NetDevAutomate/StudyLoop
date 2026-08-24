"""Study plan command group.

The agent-facing read/proposal surface has ``--json`` forms, while the
authority-bearing proposal decision is intentionally interactive-only. Default
human output stays readable in a terminal sidebar.

``plan evaluate`` prints the Markdown block by default: that is what an agent
pastes into the conversation at each of the three session checkpoints.
"""

from __future__ import annotations

import json
import sys
import uuid
from typing import NoReturn

import click
from rich.table import Table

from studyloop.cli._shared import console
from studyloop.planning import (
    PLAN_STATUSES,
    ActorContext,
    DecideProposal,
    LifecycleError,
    PlanningCommand,
    PlanningRef,
    PlanningRepositoryError,
    PlanningRequest,
    ProposalRef,
    RecordCheckpoint,
    RecordMilestoneOutcome,
    StudyPlan,
    SubmitProposalDraft,
    TransitionPlanStatus,
    draft_plan,
    evaluate_plan,
    interview_spec,
    list_plans,
    load_plan,
    load_plan_text,
    plans_dir,
    readiness,
    reindex_all,
    seed_from_history,
    unique_plan_id,
)
from studyloop.planning.compat import (
    PreferredPlanIdGenerator,
    proposal_draft_from_plan,
    require_outcome,
    require_proposal,
    require_view,
)
from studyloop.planning.index import record_checkpoint
from studyloop.planning.runtime import planning_lifecycle
from studyloop.planning.store import (
    InvalidPlanIdError,
    PlanNotFoundError,
)

_CLI_MODEL = ActorContext("model", "compatibility-translator", "cli")
_CLI_RECORDER = ActorContext("recorder", "studyloop", "cli")
_ATTESTATION_CONFIRMATION = "I confirm this records my own completed practice"


def _fail(message: str) -> NoReturn:
    """Print an error and exit non-zero, never a traceback.

    Typed ``NoReturn`` so callers like :func:`_load` are provably
    non-optional — otherwise every use site has to defend against a ``None``
    that can never actually arrive.
    """
    console.print(f"[red]{message}[/red]")
    raise SystemExit(1)


def _interactive_terminal() -> bool:
    """Return true only when learner input and output are attached to a TTY."""
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def _confirmed_cli_learner(effect: str, details: str) -> ActorContext:
    """Create learner authority only after an exact interactive confirmation."""
    if not _interactive_terminal():
        _fail("Learner plan mutations require a genuine interactive terminal.")
    console.print(f"[bold]{effect}[/bold]\n{details}")
    if not click.confirm("Confirm this exact learner-authority change?", default=False):
        _fail("No learner plan mutation was recorded.")
    return ActorContext("learner", "local-interactive-learner", "cli-tty")


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
@click.option(
    "--confirm",
    is_flag=True,
    help="Deprecated: approval requires a separate digest-bound 'plan decide' command.",
)
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
    confirm: bool,
    as_json: bool,
) -> None:
    """Deprecated compatibility adapter for creating a draft study plan.

    Omitted answers are left explicitly blank in the document rather than
    invented, and ``readiness`` reports what is still missing.
    """
    if activate:
        _fail(
            "--activate is not available on deprecated plan new; "
            "create a confirmed draft, then activate it explicitly"
        )
    if confirm:
        _fail(
            "--confirm cannot approve a proposal created by this same command. "
            "Run plan new without it, review the displayed proposal, then use plan decide "
            "with that exact proposal ID and digest."
        )
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

    try:
        service = planning_lifecycle(ids=PreferredPlanIdGenerator(plan.plan_id))
        key = uuid.uuid4().hex
        brief = service.prepare(
            PlanningRequest(
                "create",
                json.dumps(
                    {
                        "title": title,
                        "why": why,
                        "topics": list(topics),
                        "success": list(success),
                        "milestones": list(milestones),
                        "constraints": list(constraints),
                        "out_of_scope": list(out_of_scope),
                        "resources": list(resources),
                        "target_date": target_date,
                        "energy_floor": energy_floor,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                f"cli-new:{key}",
            ),
            _CLI_MODEL,
        )
        review = require_proposal(
            service.handle(
                PlanningCommand(
                    _CLI_MODEL,
                    SubmitProposalDraft(
                        brief.run_id,
                        f"cli-proposal:{key}",
                        brief.brief_context_digest,
                        proposal_draft_from_plan(plan),
                    ),
                ),
            )
        )
    except (InvalidPlanIdError, LifecycleError, PlanningRepositoryError) as exc:
        _fail(str(exc))

    if as_json:
        click.echo(
            json.dumps(
                {
                    "confirmed": False,
                    "proposal_id": review.proposal_id,
                    "proposal_digest": review.proposal_digest,
                    "plan": review.plan_preview.summary(),
                },
                indent=2,
            )
        )
        raise click.exceptions.Exit(1)
    console.print(review.markdown_preview)
    console.print(f"Proposal ID: {review.proposal_id}")
    console.print(f"Proposal digest: {review.proposal_digest}")
    _fail(
        "No plan was created. After reviewing this proposal, use plan decide from an "
        "interactive terminal and enter an explicit decision when prompted."
    )


@plan_group.command("decide")
@click.argument("proposal_id")
@click.argument("proposal_digest")
def plan_decide(proposal_id: str, proposal_digest: str) -> None:
    """Apply a separately reviewed proposal by exact ID and digest."""
    if not _interactive_terminal():
        _fail("Plan decisions require a genuine interactive terminal; agent/JSON use is refused.")
    try:
        service = planning_lifecycle()
        review = require_proposal(service.inspect(ProposalRef(proposal_id)))
        console.print(review.markdown_preview)
        console.print(f"Proposal ID: {review.proposal_id}")
        console.print(f"Proposal digest: {review.proposal_digest}")
        typed_decision = click.prompt("Learner decision", type=click.Choice(["approve", "reject"]))
        if not click.confirm(
            f"Confirm {typed_decision} for exactly {proposal_id} / {proposal_digest}?",
            default=False,
        ):
            _fail("No learner decision was recorded.")
        learner = ActorContext("learner", "local-interactive-learner", "cli-tty")
        outcome = require_outcome(
            service.handle(
                PlanningCommand(
                    learner,
                    DecideProposal(
                        proposal_id,
                        proposal_digest,
                        typed_decision,
                        f"cli-decision:{uuid.uuid4().hex}",
                    ),
                )
            )
        )
        view = (
            require_view(service.inspect(PlanningRef(outcome.plan_id)))
            if outcome.status == "applied"
            else None
        )
    except (InvalidPlanIdError, LifecycleError, PlanningRepositoryError) as exc:
        _fail(str(exc))
    if outcome.status == "applied" and view is not None:
        console.print(f"[green]Applied reviewed proposal[/green] {proposal_id}")
        _print_readiness(readiness(view.plan))
    else:
        console.print(f"[yellow]Rejected proposal[/yellow] {proposal_id}")


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
    evaluation = evaluate_plan(plan, phase, study_id=study_id)
    if record:
        command_key = f"cli-checkpoint:{uuid.uuid4().hex}"
        try:
            service = planning_lifecycle(evidence=plan.evidence)
            service.handle(
                PlanningCommand(
                    _CLI_RECORDER,
                    RecordCheckpoint(
                        plan.plan_id,
                        evaluation.to_checkpoint(),
                        command_key,
                    ),
                )
            )
            try:
                if not record_checkpoint(
                    evaluation, study_id=study_id, idempotency_key=command_key
                ):
                    evaluation.warnings.append("checkpoint not saved to the database")
            except Exception:
                evaluation.warnings.append("checkpoint not saved to the database")
        except (LifecycleError, PlanningRepositoryError) as exc:
            _fail(str(exc))
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
@click.option("--evidence-id", "evidence_ids", multiple=True, help="Trusted evidence id.")
@click.option("--attest-reason", default="", help="Milestone-specific learner reason.")
@click.option("--confirmation", default="", help="Exact learner attestation confirmation.")
def plan_milestone(
    plan_id: str,
    index: int,
    done: bool | None,
    evidence_ids: tuple[str, ...],
    attest_reason: str,
    confirmation: str,
) -> None:
    """Record an explicit evidence-backed milestone outcome."""
    plan = _load(plan_id)
    if index < 0 or index >= len(plan.milestones):
        _fail(f"No milestone at index {index} (plan has {len(plan.milestones)}).")
    if done is None:
        _fail("Choose --done or --undone explicitly; milestone toggles are forbidden.")
    milestone = plan.milestones[index]
    if done and not attest_reason:
        _fail(
            "CLI learner completion requires a milestone-specific learner attestation; "
            "trusted verification is recorded only by the internal recorder."
        )
    if done and attest_reason and confirmation != _ATTESTATION_CONFIRMATION:
        _fail(f"Learner attestation requires exactly: {_ATTESTATION_CONFIRMATION}")
    if not done:
        outcome_kind = "incomplete"
    elif attest_reason:
        outcome_kind = "learner_attested"
    else:  # pragma: no cover - guarded above
        _fail("--done requires a learner attestation")
    learner = _confirmed_cli_learner(
        "Record milestone outcome",
        (
            f"Plan: {plan.plan_id}\nMilestone: {milestone.title}\n"
            f"Outcome: {outcome_kind}\nEvidence: {', '.join(evidence_ids) or 'none'}\n"
            f"Reason: {attest_reason or 'none'}"
        ),
    )
    try:
        service = planning_lifecycle(evidence=plan.evidence)
        outcome = require_outcome(
            service.handle(
                PlanningCommand(
                    learner,
                    RecordMilestoneOutcome(
                        plan.plan_id,
                        milestone.milestone_id,
                        outcome_kind,
                        evidence_ids,
                        f"cli-milestone:{uuid.uuid4().hex}",
                        reason=attest_reason,
                        confirmation=confirmation,
                    ),
                ),
            )
        )
        updated = require_view(service.inspect(PlanningRef(plan.plan_id))).plan
    except (LifecycleError, PlanningRepositoryError) as exc:
        _fail(str(exc))
    state = "verified done" if outcome.status == "verified_complete" else outcome.status
    console.print(
        f"[green]{milestone.title}[/green] → {state}  "
        f"({updated.milestone_done}/{updated.milestone_total}, {updated.progress_pct}%)"
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
    learner = _confirmed_cli_learner(
        "Change plan lifecycle status",
        f"Plan: {plan.plan_id}\nCurrent: {plan.status}\nRequested: {status}",
    )
    try:
        outcome = require_outcome(
            planning_lifecycle(evidence=plan.evidence).handle(
                PlanningCommand(
                    learner,
                    TransitionPlanStatus(
                        plan.plan_id,
                        status,
                        f"cli-status:{uuid.uuid4().hex}",
                    ),
                ),
            )
        )
    except (LifecycleError, PlanningRepositoryError) as exc:
        _fail(str(exc))
    console.print(f"[green]{plan.plan_id}[/green] → {status} ({outcome.status})")


@plan_group.command("reindex")
def plan_reindex() -> None:
    """Rebuild the derived plan index in the sessions DB from the documents."""
    count = reindex_all()
    console.print(f"[green]Reindexed[/green] {count} plan(s).")


@plan_group.command("path")
def plan_path_cmd() -> None:
    """Print the directory holding plan documents."""
    click.echo(str(plans_dir()))
