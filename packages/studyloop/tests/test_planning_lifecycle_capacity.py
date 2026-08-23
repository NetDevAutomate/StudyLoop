"""Capacity and Rule-of-Three contracts, including locked decisions."""

from __future__ import annotations

import multiprocessing
from pathlib import Path

import pytest
from planning_lifecycle_support import LEARNER, MODEL, canonical_plan, lifecycle, store_plan

from studyloop.planning import (
    DecideProposal,
    Goal,
    GoalLimitError,
    GoalProposal,
    MilestoneProposal,
    Mission,
    PlanningCommand,
    PlanningRef,
    PlanningRequest,
    PlanProposalDraft,
    SubmitProposalDraft,
    TransitionPlanStatus,
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
