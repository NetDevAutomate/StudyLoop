"""Capacity and Rule-of-Three contracts, including locked decisions."""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

import pytest
from planning_lifecycle_support import (
    LEARNER,
    MODEL,
    RECORDER,
    FixedClock,
    PrefixIds,
    canonical_plan,
    lifecycle,
    paths,
    store_plan,
)

from studyloop.planning import (
    Checkpoint,
    DecideProposal,
    Goal,
    GoalLimitError,
    GoalProposal,
    ImportPlanDraft,
    MilestoneProposal,
    Mission,
    PlanningCommand,
    PlanningLifecycle,
    PlanningRef,
    PlanningRequest,
    PlanProposalDraft,
    RecordCheckpoint,
    SubmitProposalDraft,
    TransitionPlanStatus,
)
from studyloop.planning.repository import PlanningRepository


class _PausingRepository(PlanningRepository):
    """Synchronize workers after lifecycle lookup but before repository commit."""

    def __init__(self, root: Path, barrier, pause_key: str) -> None:
        super().__init__(paths(root), index_refresher=None)
        self._barrier = barrier
        self._pause_key = pause_key

    def commit(self, intent, *, guard=None):
        if intent.idempotency_key == self._pause_key:
            self._barrier.wait(timeout=10)
        return super().commit(intent, guard=guard)


def _race_service(root: str, barrier, pause_key: str, clock_value: str) -> PlanningLifecycle:
    return PlanningLifecycle(
        _PausingRepository(Path(root), barrier, pause_key),
        clock=FixedClock(clock_value),
        ids=PrefixIds(),
    )


def _put_result(results, operation: str, call) -> None:
    try:
        result = call()
    except Exception as error:  # explicit cross-process result envelope
        results.put((operation, "error", type(error).__name__, str(error)))
    else:
        results.put((operation, "ok", result))


def _prepare_retry_worker(root: str, barrier, results, clock_value: str) -> None:
    service = _race_service(root, barrier, "prepare:race-prepare", clock_value)

    def call():
        brief = service.prepare(PlanningRequest("create", "Same exact dump", "race-prepare"), MODEL)
        return (
            brief.run_id,
            brief.request_digest,
            brief.brief_context_digest,
            brief.created_at,
        )

    _put_result(results, "prepare", call)


def _submit_retry_worker(
    root: str,
    barrier,
    results,
    clock_value: str,
    run_id: str,
    brief_digest: str,
) -> None:
    service = _race_service(root, barrier, "proposal:race-submit", clock_value)

    def call():
        review = service.handle(
            PlanningCommand(
                MODEL,
                SubmitProposalDraft(
                    run_id,
                    "race-submit",
                    brief_digest,
                    _active_draft("race-submit-goal"),
                ),
            )
        )
        return (
            review.proposal_id,
            review.plan_preview.plan_id,
            review.proposal_digest,
            review.alias_mapping,
            review.created_at,
        )

    _put_result(results, "submit", call)


def _approval_retry_worker(
    root: str,
    barrier,
    results,
    clock_value: str,
    proposal_id: str,
    proposal_digest: str,
) -> None:
    service = _race_service(root, barrier, "decision:race-approval", clock_value)

    def call():
        outcome = service.handle(
            PlanningCommand(
                LEARNER,
                DecideProposal(
                    proposal_id,
                    proposal_digest,
                    "approve",
                    "race-approval",
                ),
            )
        )
        return (
            outcome.status,
            outcome.plan_id,
            outcome.proposal_id,
            outcome.document_digest,
            outcome.structure_digest,
            outcome.document_revision,
            outcome.structure_revision,
        )

    _put_result(results, "approval", call)


def _import_retry_worker(root: str, barrier, results, clock_value: str) -> None:
    service = _race_service(root, barrier, "import:race-import", clock_value)

    def call():
        outcome = service.handle(
            PlanningCommand(
                LEARNER,
                ImportPlanDraft("# Imported retry\n\nSame content.", "race-import"),
            )
        )
        return (
            outcome.status,
            outcome.plan_id,
            outcome.document_digest,
            outcome.structure_digest,
            outcome.document_revision,
            outcome.structure_revision,
        )

    _put_result(results, "import", call)


def _checkpoint_retry_worker(root: str, barrier, results, clock_value: str) -> None:
    service = _race_service(root, barrier, "checkpoint_recorded:race-checkpoint", clock_value)

    def call():
        outcome = service.handle(
            PlanningCommand(
                RECORDER,
                RecordCheckpoint(
                    "checkpoint-target",
                    Checkpoint("mid", "on-track", "2026-08-23T15:00:00+00:00", "Same"),
                    "race-checkpoint",
                ),
            )
        )
        return (
            outcome.status,
            outcome.plan_id,
            outcome.document_digest,
            outcome.structure_digest,
            outcome.document_revision,
            outcome.structure_revision,
        )

    _put_result(results, "checkpoint", call)


def _run_identical_workers(tmp_path: Path, target, *args) -> list[tuple]:
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    workers = [
        context.Process(
            target=target,
            args=(
                str(tmp_path),
                barrier,
                results,
                f"2026-08-23T1{index}:00:00+00:00",
                *args,
            ),
        )
        for index in (6, 7)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=15)
        assert worker.exitcode == 0
    return [results.get(timeout=2), results.get(timeout=2)]


def _committed_lifecycle_count(root: Path, event_type: str) -> int:
    events = [
        json.loads(line) for line in (root / "planning-journal.jsonl").read_text().splitlines()
    ]
    return sum(
        event["event"] == "committed"
        and event.get("payload", {}).get("lifecycle", {}).get("type") == event_type
        for event in events
    )


def _activate_worker(root: str, plan_id: str, barrier, results) -> None:
    service = lifecycle(Path(root))
    barrier.wait()
    try:
        outcome = service.handle(
            PlanningCommand(
                LEARNER,
                TransitionPlanStatus(plan_id, "active", f"activate-{plan_id}"),
            )
        )
    except Exception as error:  # explicit cross-process result envelope
        results.put(("error", type(error).__name__, str(error)))
    else:
        results.put(("ok", outcome.plan_id, outcome.status))


def _active_draft(goal_alias: str, *, override: bool = False) -> PlanProposalDraft:
    return PlanProposalDraft(
        title=f"Plan {goal_alias}",
        mission=Mission(why="Keep the scope bounded", success=["Demonstrate one thing"]),
        goals=(GoalProposal(goal_alias, goal_alias, "Needed", "Aligned"),),
        milestones=(MilestoneProposal(f"m-{goal_alias}", goal_alias, "Do the work"),),
        next_action="Do the work",
        requested_status="active",
        goal_limit_override_requested=override,
        goal_limit_override_reason="These four form one coupled certification" if override else "",
    )


def _submit(service, key: str, goal_alias: str, *, override: bool = False):
    brief = service.prepare(PlanningRequest("create", goal_alias, f"run-{key}"), MODEL)
    return service.handle(
        PlanningCommand(
            MODEL,
            SubmitProposalDraft(
                brief.run_id,
                f"proposal-{key}",
                brief.brief_context_digest,
                _active_draft(goal_alias, override=override),
            ),
        )
    )


def test_concurrent_identical_prepare_replays_one_captured_run(tmp_path: Path) -> None:
    observed = _run_identical_workers(tmp_path, _prepare_retry_worker)

    assert {item[1] for item in observed} == {"ok"}
    assert observed[0][2] == observed[1][2]
    assert _committed_lifecycle_count(tmp_path, "run_captured") == 1
    run_id = observed[0][2][0]
    private_runs = [path.name for path in (tmp_path / "private-runs").iterdir()]
    assert private_runs == [run_id]


def test_concurrent_identical_submission_replays_one_proposal(tmp_path: Path) -> None:
    service = lifecycle(tmp_path)
    brief = service.prepare(PlanningRequest("create", "Same proposal", "submit-race-run"), MODEL)

    observed = _run_identical_workers(
        tmp_path,
        _submit_retry_worker,
        brief.run_id,
        brief.brief_context_digest,
    )

    assert {item[1] for item in observed} == {"ok"}
    assert observed[0][2] == observed[1][2]
    assert _committed_lifecycle_count(tmp_path, "proposal_issued") == 1
    artifacts = list((tmp_path / "private-runs" / brief.run_id).glob("*.json"))
    assert [path.name for path in artifacts] == [f"{observed[0][2][0]}.json"]


def test_concurrent_identical_approval_replays_one_canonical_decision(
    tmp_path: Path,
) -> None:
    review = _submit(lifecycle(tmp_path), "approval-race-seed", "approval-goal")

    observed = _run_identical_workers(
        tmp_path,
        _approval_retry_worker,
        review.proposal_id,
        review.proposal_digest,
    )

    assert {item[1] for item in observed} == {"ok"}
    assert observed[0][2] == observed[1][2]
    assert _committed_lifecycle_count(tmp_path, "proposal_decided") == 1
    view = lifecycle(tmp_path).inspect(PlanningRef(observed[0][2][1]))
    assert view.plan.document_revision == 1
    assert len(view.plan.decisions) == 1


def test_concurrent_identical_import_replays_one_canonical_plan(tmp_path: Path) -> None:
    observed = _run_identical_workers(tmp_path, _import_retry_worker)

    assert {item[1] for item in observed} == {"ok"}
    assert observed[0][2] == observed[1][2]
    assert _committed_lifecycle_count(tmp_path, "plan_imported") == 1
    assert len(list((tmp_path / "plans").glob("*.md"))) == 1


def test_concurrent_identical_checkpoint_replays_one_canonical_append(
    tmp_path: Path,
) -> None:
    store_plan(tmp_path, canonical_plan("checkpoint-target"))

    observed = _run_identical_workers(tmp_path, _checkpoint_retry_worker)

    assert {item[1] for item in observed} == {"ok"}
    assert observed[0][2] == observed[1][2]
    assert _committed_lifecycle_count(tmp_path, "checkpoint_recorded") == 1
    view = lifecycle(tmp_path).inspect(PlanningRef("checkpoint-target"))
    assert view.plan.document_revision == 2
    assert len(view.plan.checkpoints) == 1


def test_rule_of_three_counts_stable_ids_across_active_plans_only(tmp_path: Path) -> None:
    existing = canonical_plan("one", status="active", goal_ids=("g-1", "g-2"))
    existing.goals.append(Goal("ignored", "Paused goal", "Later", "Not active", status="paused"))
    store_plan(tmp_path, existing)
    service = lifecycle(tmp_path)
    review = _submit(service, "third", "g-3")
    outcome = service.handle(
        PlanningCommand(
            LEARNER,
            DecideProposal(review.proposal_id, review.proposal_digest, "approve", "approve-third"),
        )
    )
    assert outcome.status == "applied"

    fourth = _submit(service, "fourth", "g-4")
    with pytest.raises(GoalLimitError, match="3 active goals"):
        service.handle(
            PlanningCommand(
                LEARNER,
                DecideProposal(
                    fourth.proposal_id,
                    fourth.proposal_digest,
                    "approve",
                    "deny-fourth",
                ),
            )
        )


def test_override_requires_learner_reason_and_is_bound_to_exact_goal_set(tmp_path: Path) -> None:
    store_plan(
        tmp_path,
        canonical_plan("existing", status="active", goal_ids=("g-1", "g-2", "g-3")),
    )
    service = lifecycle(tmp_path)
    review = _submit(service, "override", "g-4", override=True)

    with pytest.raises(GoalLimitError, match="learner reason"):
        service.handle(
            PlanningCommand(
                LEARNER,
                DecideProposal(review.proposal_id, review.proposal_digest, "approve", "no-reason"),
            )
        )

    applied = service.handle(
        PlanningCommand(
            LEARNER,
            DecideProposal(
                review.proposal_id,
                review.proposal_digest,
                "approve",
                "with-reason",
                reason="All four are required for the same certification exercise",
            ),
        )
    )
    assert applied.goal_limit_override_digest
    decision_reason = service.inspect(PlanningRef(applied.plan_id)).plan.decisions[-1].reason
    assert "Rule of Three" in decision_reason

    assert service.is_goal_override_valid(applied.goal_limit_override_digest)
    service.handle(
        PlanningCommand(
            LEARNER,
            TransitionPlanStatus(applied.plan_id, "paused", "pause-override"),
        )
    )
    assert not service.is_goal_override_valid(applied.goal_limit_override_digest)


def test_repository_guard_runs_after_idempotent_replay_and_under_current_snapshot(
    tmp_path: Path,
) -> None:
    service = lifecycle(tmp_path)
    review = _submit(service, "guard", "g-1")
    command = PlanningCommand(
        LEARNER,
        DecideProposal(review.proposal_id, review.proposal_digest, "approve", "decision"),
    )
    first = service.handle(command)
    replay = lifecycle(tmp_path).handle(command)
    assert replay == first


def test_concurrent_cross_plan_activation_cannot_exceed_three_active_goals(
    tmp_path: Path,
) -> None:
    store_plan(tmp_path, canonical_plan("base", status="active", goal_ids=("g-1", "g-2")))
    store_plan(tmp_path, canonical_plan("draft-a", status="draft", goal_ids=("g-3",)))
    store_plan(tmp_path, canonical_plan("draft-b", status="draft", goal_ids=("g-4",)))
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    workers = [
        context.Process(target=_activate_worker, args=(str(tmp_path), plan_id, barrier, results))
        for plan_id in ("draft-a", "draft-b")
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=15)
        assert worker.exitcode == 0

    observed = [results.get(timeout=2), results.get(timeout=2)]
    assert [item[0] for item in observed].count("ok") == 1
    errors = [item for item in observed if item[0] == "error"]
    assert len(errors) == 1
    assert errors[0][1] == "GoalLimitError"
    snapshot = lifecycle(tmp_path).repository.scan_for_mutation()
    assert len(set(snapshot.active_goal_ids)) == 3
