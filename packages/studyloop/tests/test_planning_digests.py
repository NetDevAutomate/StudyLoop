"""Versioned digest contracts for canonical planning documents."""

from __future__ import annotations

from copy import deepcopy

import pytest

from studyloop.planning.digests import (
    compute_document_digest,
    compute_structure_digest,
)
from studyloop.planning.markdown import render_plan
from studyloop.planning.models import (
    Checkpoint,
    ConceptRef,
    ConceptRelation,
    DecisionRecord,
    EvidenceDisposition,
    EvidenceRef,
    Goal,
    LearningRecord,
    Milestone,
    Mission,
    PlanUnknown,
    Resource,
    StudyPlan,
)


def _plan() -> StudyPlan:
    return StudyPlan(
        plan_id="digests",
        title="Digest contract",
        status="active",
        created="2026-08-20T10:00:00+00:00",
        updated="2026-08-20T10:01:00+00:00",
        topics=["python"],
        mission=Mission(
            why="Learn safely.",
            success=["Explain file-first transactions"],
            constraints=["Keep recovery deterministic"],
        ),
        next_action="Trace a failed write.",
        goals=[Goal("goal-1", "Transactions", "Needed", "Mission aligned")],
        milestones=[
            Milestone(
                "Recover a write",
                milestone_id="milestone-1",
                goal_id="goal-1",
                concepts=["recovery"],
            )
        ],
        concepts=[ConceptRef("concept-recovery", "Recovery")],
        concept_relations=[
            ConceptRelation(
                "concept-recovery",
                "concept-durability",
                "related",
                "Recovery depends on durability.",
                "learner",
            )
        ],
        unknowns=[PlanUnknown("unknown-1", "Which filesystem?", "Durability varies")],
        resources=[Resource("Filesystem guide", "https://example.test/fs")],
        evidence=[
            EvidenceRef(
                evidence_id="evidence-1",
                source_kind="studyloop_practice",
                source_native_id="practice-1",
                source_revision="1",
                observed_at="2026-08-20T09:00:00+00:00",
                ingested_at="2026-08-20T09:01:00+00:00",
                tier=1,
                claim_kind="demonstrated_skill",
                subject_ref="concept:recovery",
                provenance_digest="sha256:evidence",
            )
        ],
        checkpoints=[
            Checkpoint(
                phase="mid",
                verdict="on-track",
                at="2026-08-20T10:02:00+00:00",
                summary="Recovered once.",
            )
        ],
        decisions=[
            DecisionRecord(
                decision_id="decision-1",
                proposal_id="proposal-1",
                outcome="approve",
                actor_kind="learner",
                channel="web",
                reason="Matches intent.",
                decided_at="2026-08-20T10:03:00+00:00",
            )
        ],
    )


def test_document_digest_is_versioned_and_excludes_its_own_field() -> None:
    plan = _plan()
    without_digest = render_plan(plan)
    plan.document_digest = "sha256:v1:" + ("f" * 64)
    with_digest = render_plan(plan)

    digest = compute_document_digest(without_digest)

    assert digest == compute_document_digest(with_digest)
    assert digest.startswith("sha256:v1:")
    assert len(digest.removeprefix("sha256:v1:")) == 64


def test_wall_clock_timestamps_do_not_change_structure_digest() -> None:
    original = _plan()
    later = deepcopy(original)
    later.created = "2030-01-01T00:00:00+00:00"
    later.updated = "2030-01-02T00:00:00+00:00"
    later.evidence[0].observed_at = "2030-01-03T00:00:00+00:00"
    later.evidence[0].ingested_at = "2030-01-04T00:00:00+00:00"
    later.checkpoints[0].at = "2030-01-05T00:00:00+00:00"
    later.decisions[0].decided_at = "2030-01-06T00:00:00+00:00"

    assert compute_structure_digest(later) == compute_structure_digest(original)


def test_derived_mermaid_changes_document_but_not_structure_digest() -> None:
    plan = _plan()
    canonical = render_plan(plan)
    changed_derived_map = canonical.replace("flowchart TD", "flowchart LR")

    assert compute_document_digest(changed_derived_map) != compute_document_digest(canonical)
    assert compute_structure_digest(plan) == compute_structure_digest(deepcopy(plan))


def test_audit_and_free_form_fields_are_document_only() -> None:
    original = _plan()
    changed = deepcopy(original)
    changed.notes = "A free-form learner note."
    changed.evidence_dispositions.append(
        EvidenceDisposition("evidence-1", "selected", "Useful context")
    )
    changed.learning_records.append(LearningRecord(1, "An audit insight"))
    changed.evidence[0].claim_kind = "different_audit_claim"
    changed.evidence[0].provenance_digest = "sha256:changed-evidence"
    changed.checkpoints[0].summary = "Different audit summary."
    changed.decisions[0].reason = "Different audit reason."
    changed.document_revision = 99
    changed.structure_revision = 99
    changed.document_digest = "sha256:v1:" + ("a" * 64)
    changed.structure_digest = "sha256:v1:" + ("b" * 64)
    changed.brief_context_digest = "sha256:v1:" + ("c" * 64)

    assert compute_structure_digest(changed) == compute_structure_digest(original)
    assert compute_document_digest(render_plan(changed)) != compute_document_digest(
        render_plan(original)
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda plan: setattr(plan, "title", "Changed title"),
        lambda plan: setattr(plan, "status", "paused"),
        lambda plan: setattr(plan.mission, "why", "Changed mission"),
        lambda plan: setattr(plan, "next_action", "Trace a recovered write."),
        lambda plan: setattr(plan.goals[0], "title", "Changed goal"),
        lambda plan: setattr(plan.milestones[0], "title", "Changed milestone"),
        lambda plan: plan.topics.append("sql"),
        lambda plan: setattr(plan.concepts[0], "display_label", "Durable recovery"),
        lambda plan: setattr(plan.concept_relations[0], "relation", "broader"),
        lambda plan: setattr(plan.unknowns[0], "question", "Which operating system?"),
        lambda plan: setattr(plan.resources[0], "url", "https://example.test/changed"),
    ],
    ids=[
        "title",
        "status",
        "mission",
        "next-action",
        "goal",
        "milestone",
        "topics",
        "concept",
        "concept-relation",
        "unknown",
        "resource",
    ],
)
def test_each_structural_change_changes_structure_digest(mutate) -> None:
    original = _plan()
    changed = deepcopy(original)

    mutate(changed)

    assert compute_structure_digest(changed) != compute_structure_digest(original)
