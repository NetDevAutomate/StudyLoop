"""Shared deterministic fixtures for planning lifecycle contract tests."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from studyloop.planning import (
    ActorContext,
    EvidenceCatalogue,
    EvidenceRef,
    Goal,
    IdGenerator,
    Milestone,
    Mission,
    MutationIntent,
    PlanningLifecycle,
    PlanningPaths,
    PlanningRepository,
    StudyPlan,
)

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class FixedClock:
    value: str = "2026-08-23T12:00:00+00:00"

    def now(self) -> str:
        return self.value


class PrefixIds:
    _instances = 0

    def __init__(self) -> None:
        type(self)._instances += 1
        self.namespace = f"{os.getpid()}-{type(self)._instances}"
        self.counts: dict[str, int] = {}

    def new_id(self, prefix: str) -> str:
        count = self.counts.get(prefix, 0) + 1
        self.counts[prefix] = count
        return f"{prefix}-{self.namespace}-{count:04d}"


MODEL = ActorContext("model", "architect", "mcp")
LEARNER = ActorContext("learner", "local-learner", "web")
RECORDER = ActorContext("recorder", "studyloop", "internal")


def paths(root: Path) -> PlanningPaths:
    return PlanningPaths.in_root(root)


def lifecycle(
    root: Path,
    *,
    evidence: tuple[EvidenceRef, ...] = (),
    ids: IdGenerator | None = None,
) -> PlanningLifecycle:
    return PlanningLifecycle(
        PlanningRepository(paths(root), index_refresher=None),
        clock=FixedClock(),
        ids=ids or PrefixIds(),
        evidence=EvidenceCatalogue(evidence),
    )


def evidence_ref(
    evidence_id: str,
    *,
    source_kind: str,
    tier: int,
    subject_ref: str = "concept:protocols",
) -> EvidenceRef:
    return EvidenceRef(
        evidence_id=evidence_id,
        source_kind=source_kind,
        source_native_id=f"native-{evidence_id}",
        source_revision="1",
        observed_at="2026-08-22T10:00:00+00:00",
        ingested_at="2026-08-23T10:00:00+00:00",
        tier=tier,
        claim_kind="demonstrated_skill" if tier == 1 else "context",
        subject_ref=subject_ref,
        provenance_digest=f"sha256:v1:{evidence_id.zfill(64)[-64:]}",
    )


def canonical_plan(
    plan_id: str,
    *,
    status: str = "draft",
    goal_ids: tuple[str, ...] = (),
) -> StudyPlan:
    goals = [Goal(goal_id, goal_id, "Needed", "Supports mission") for goal_id in goal_ids]
    return StudyPlan(
        plan_id=plan_id,
        title=plan_id.replace("-", " ").title(),
        status=status,
        created="2026-08-20T10:00:00+00:00",
        updated="2026-08-20T10:00:00+00:00",
        mission=Mission(why="Learn safely", success=["Demonstrate it"]),
        goals=goals,
        milestones=[
            Milestone(
                f"Practise {goal.goal_id}",
                milestone_id=f"milestone-{goal.goal_id}",
                goal_id=goal.goal_id,
            )
            for goal in goals
        ],
    )


def store_plan(root: Path, plan: StudyPlan, *, suffix: str = "") -> None:
    repository = PlanningRepository(paths(root), index_refresher=None)
    repository.commit(
        MutationIntent(
            intent_id=f"seed-{plan.plan_id}{suffix}",
            caller="test-seed",
            idempotency_key=f"seed-{plan.plan_id}{suffix}",
            plan=plan,
        )
    )
