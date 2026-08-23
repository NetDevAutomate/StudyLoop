"""Proposal, decision, import, and transition contracts."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

import pytest
from planning_lifecycle_support import (
    LEARNER,
    MODEL,
    RECORDER,
    canonical_plan,
    evidence_ref,
    lifecycle,
    store_plan,
)

from studyloop.planning import (
    AuthorityError,
    Checkpoint,
    ConceptProposal,
    ConceptRef,
    ConceptRelationProposal,
    DecideProposal,
    EvidenceDisposition,
    Goal,
    GoalProposal,
    IdempotencyConflictError,
    ImportPlanDraft,
    LifecycleValidationError,
    Milestone,
    MilestoneProposal,
    Mission,
    PlanCapacityError,
    PlanConflictError,
    PlanningCommand,
    PlanningRef,
    PlanningRequest,
    PlanProposalDraft,
    ProposalConflictError,
    ProposalRef,
    RecordCheckpoint,
    RecordTrustedEvidence,
    Resource,
    SubmitProposalDraft,
    TransitionPlanStatus,
)
from studyloop.planning.lifecycle_proposals import ProposalPolicy

if TYPE_CHECKING:
    from pathlib import Path


def _draft(*, status: str = "draft") -> PlanProposalDraft:
    return PlanProposalDraft(
        title="Understand protocols",
        mission=Mission(
            why="Reason clearly about network boundaries",
            success=["Trace one protocol exchange"],
            out_of_scope=["Collecting more notes"],
        ),
        topics=("networking",),
        goals=(GoalProposal("protocol-goal", "Trace protocols", "Needed", "Matches mission"),),
        concepts=(
            ConceptProposal("abc", "abc-vs-protocol"),
            ConceptProposal("protocol", "protocols"),
        ),
        concept_relations=(
            ConceptRelationProposal(
                "abc",
                "protocol",
                "distinct",
                "The labels refer to different learner concepts",
                "learner-review-required",
            ),
        ),
        milestones=(
            MilestoneProposal(
                "trace-one",
                "protocol-goal",
                "Trace one exchange",
                concept_aliases=("protocol",),
            ),
        ),
        resources=(Resource("Course outline", "https://example.test/course"),),
        next_action="Trace one request and response",
        requested_status=status,
    )


def _proposal(service, *, key: str = "proposal-1"):
    brief = service.prepare(PlanningRequest("create", "Protocols are confusing", "run-1"), MODEL)
    review = service.handle(
        PlanningCommand(
            MODEL,
            SubmitProposalDraft(
                run_id=brief.run_id,
                idempotency_key=key,
                brief_context_digest=brief.brief_context_digest,
                draft=_draft(),
            ),
        )
    )
    return brief, review


def test_submission_assigns_ids_and_persists_no_canonical_markdown(tmp_path: Path) -> None:
    service = lifecycle(tmp_path)
    _, review = _proposal(service)

    assert review.proposal_id.startswith("proposal-")
    assert review.proposal_digest.startswith("sha256:v1:")
    assert review.plan_preview.plan_id.startswith("plan-")
    assert review.plan_preview.goals[0].goal_id
    assert review.plan_preview.goals[0].goal_id != "protocol-goal"
    assert review.plan_preview.concepts[0].concept_id != "abc"
    assert review.plan_preview.next_action == "Trace one request and response"
    assert "Next action:" not in review.plan_preview.notes
    assert "flowchart TD" in review.markdown_preview
    assert not list((tmp_path / "plans").glob("*.md"))
    assert service.inspect(ProposalRef(review.proposal_id)) == review
    proposal_artifact = tmp_path / "private-runs" / review.run_id / f"{review.proposal_id}.json"
    assert proposal_artifact.is_file()
    assert proposal_artifact.stat().st_mode & 0o777 == 0o600
    assert review.plan_preview.title not in (tmp_path / "planning-journal.jsonl").read_text()


def test_proposal_digest_omits_audit_time_and_free_form_review_prose(tmp_path: Path) -> None:
    service = lifecycle(tmp_path)
    brief, review = _proposal(service)
    changed = deepcopy(review.plan_preview)
    changed.created = "2035-01-01T00:00:00+00:00"
    changed.updated = "2035-01-02T00:00:00+00:00"
    changed.notes = "Reviewer prose that is not part of the assigned proposal."

    digest = ProposalPolicy.proposal_digest(
        brief,
        _draft(),
        changed,
        dict(review.alias_mapping),
        review.resulting_active_goal_ids,
        review.resulting_active_goal_set_digest,
    )

    assert digest == review.proposal_digest


def test_similar_concept_labels_remain_distinct_without_explicit_relation(
    tmp_path: Path,
) -> None:
    service = lifecycle(tmp_path)
    brief = service.prepare(PlanningRequest("create", "ABC and protocols", "run"), MODEL)
    draft = PlanProposalDraft(**{**_draft().__dict__, "concept_relations": ()})
    review = service.handle(
        PlanningCommand(
            MODEL,
            SubmitProposalDraft(brief.run_id, "proposal", brief.brief_context_digest, draft),
        )
    )

    assert len({item.concept_id for item in review.plan_preview.concepts}) == 2
    assert review.plan_preview.concept_relations == []


def test_submission_idempotency_replays_and_changed_payload_conflicts(tmp_path: Path) -> None:
    service = lifecycle(tmp_path)
    brief, review = _proposal(service, key="stable-proposal")
    command = SubmitProposalDraft(
        brief.run_id,
        "stable-proposal",
        brief.brief_context_digest,
        _draft(),
    )

    assert lifecycle(tmp_path).handle(PlanningCommand(MODEL, command)) == review
    changed = PlanProposalDraft(**{**_draft().__dict__, "title": "Changed title"})
    with pytest.raises(IdempotencyConflictError, match="different proposal draft"):
        lifecycle(tmp_path).handle(
            PlanningCommand(
                MODEL,
                SubmitProposalDraft(
                    brief.run_id,
                    "stable-proposal",
                    brief.brief_context_digest,
                    changed,
                ),
            )
        )


def test_model_cannot_decide_and_denial_creates_no_privileged_event(tmp_path: Path) -> None:
    service = lifecycle(tmp_path)
    _, review = _proposal(service)
    journal = tmp_path / "planning-journal.jsonl"
    before = journal.read_bytes()

    command = DecideProposal(
        proposal_id=review.proposal_id,
        proposal_digest=review.proposal_digest,
        decision="approve",
        idempotency_key="decision-1",
    )
    with pytest.raises(AuthorityError, match="learner authority"):
        service.handle(PlanningCommand(MODEL, command))

    assert journal.read_bytes() == before
    assert not list((tmp_path / "plans").glob("*.md"))


def test_new_proposal_supersedes_older_open_proposal(tmp_path: Path) -> None:
    service = lifecycle(tmp_path)
    brief, older = _proposal(service)
    newer_draft = PlanProposalDraft(**{**_draft().__dict__, "title": "Better scoped"})
    newer = service.handle(
        PlanningCommand(
            MODEL,
            SubmitProposalDraft(
                brief.run_id,
                "proposal-2",
                brief.brief_context_digest,
                newer_draft,
            ),
        )
    )

    assert newer.supersedes_proposal_id == older.proposal_id
    with pytest.raises(ProposalConflictError, match="superseded"):
        service.handle(
            PlanningCommand(
                LEARNER,
                DecideProposal(older.proposal_id, older.proposal_digest, "approve", "old"),
            )
        )


def test_exact_learner_approval_applies_and_fold_survives_restart(tmp_path: Path) -> None:
    service = lifecycle(tmp_path)
    _, review = _proposal(service)
    decision = DecideProposal(
        proposal_id=review.proposal_id,
        proposal_digest=review.proposal_digest,
        decision="approve",
        idempotency_key="decision-1",
    )

    applied = service.handle(PlanningCommand(LEARNER, decision))
    replay = lifecycle(tmp_path).handle(PlanningCommand(LEARNER, decision))

    assert applied.status == "applied"
    assert replay == applied
    view = lifecycle(tmp_path).inspect(PlanningRef(applied.plan_id))
    assert view.plan.status == "draft"
    assert view.plan.decisions[-1].proposal_id == review.proposal_id
    assert view.plan.concept_relations[0].relation == "distinct"


def test_revise_preserves_explicit_existing_ids_and_allocates_only_new_aliases(
    tmp_path: Path,
) -> None:
    target = canonical_plan("target", goal_ids=("goal-target",))
    target.goals = [Goal("goal-existing", "Existing goal", "Still needed", "Still aligned")]
    target.concepts = [ConceptRef("concept-existing", "protocols")]
    target.milestones = [
        Milestone(
            "Existing step",
            milestone_id="milestone-existing",
            goal_id="goal-existing",
            concepts=["protocols"],
        )
    ]
    store_plan(tmp_path, target)
    service = lifecycle(tmp_path)
    brief = service.prepare(
        PlanningRequest("revise", "Add one focused goal", "revise-run", plan_id="target"),
        MODEL,
    )
    draft = PlanProposalDraft(
        title="Target revised",
        mission=target.mission,
        goals=(
            GoalProposal(
                "keep-goal",
                "Existing goal",
                "Still needed",
                "Still aligned",
                existing_goal_id="goal-existing",
            ),
            GoalProposal("new-goal", "New goal", "New need", "Same mission"),
        ),
        concepts=(
            ConceptProposal("keep-concept", "protocols", "concept-existing"),
            ConceptProposal("new-concept", "wire format"),
        ),
        milestones=(
            MilestoneProposal(
                "keep-step",
                "keep-goal",
                "Existing step",
                concept_aliases=("keep-concept",),
                existing_milestone_id="milestone-existing",
            ),
            MilestoneProposal(
                "new-step",
                "new-goal",
                "Trace the wire format",
                concept_aliases=("new-concept",),
            ),
        ),
        next_action="Trace the existing step",
    )
    review = service.handle(
        PlanningCommand(
            MODEL,
            SubmitProposalDraft(brief.run_id, "revise-proposal", brief.brief_context_digest, draft),
        )
    )
    outcome = service.handle(
        PlanningCommand(
            LEARNER,
            DecideProposal(
                review.proposal_id,
                review.proposal_digest,
                "approve",
                "revise-decision",
                expected_document_digest=brief.target_document_digest,
                expected_structure_digest=brief.target_structure_digest,
                expected_document_revision=brief.target_document_revision,
                expected_structure_revision=brief.target_structure_revision,
            ),
        )
    )
    plan = service.inspect(PlanningRef(outcome.plan_id)).plan

    assert next(goal.goal_id for goal in plan.goals) == "goal-existing"
    assert plan.goals[1].goal_id not in {"new-goal", "goal-existing"}
    assert plan.concepts[0].concept_id == "concept-existing"
    assert plan.concepts[1].concept_id not in {"new-concept", "concept-existing"}
    assert plan.milestones[0].milestone_id == "milestone-existing"


def test_rejection_is_journal_only_and_conflicting_second_decision_refuses(
    tmp_path: Path,
) -> None:
    service = lifecycle(tmp_path)
    _, review = _proposal(service)
    rejected = service.handle(
        PlanningCommand(
            LEARNER,
            DecideProposal(
                review.proposal_id,
                review.proposal_digest,
                "reject",
                "decision-reject",
                reason="This is not my intent",
            ),
        )
    )

    assert rejected.status == "rejected"
    assert not list((tmp_path / "plans").glob("*.md"))
    with pytest.raises(ProposalConflictError, match="already rejected"):
        service.handle(
            PlanningCommand(
                LEARNER,
                DecideProposal(
                    review.proposal_id,
                    review.proposal_digest,
                    "approve",
                    "decision-after-reject",
                ),
            )
        )


def test_checkpoint_after_submission_makes_revision_approval_stale(tmp_path: Path) -> None:
    target = canonical_plan("target", goal_ids=("goal-target",))
    store_plan(tmp_path, target)
    service = lifecycle(tmp_path)
    brief = service.prepare(
        PlanningRequest("revise", "Keep structure", "run", plan_id="target"), MODEL
    )
    draft = PlanProposalDraft(
        title=target.title,
        mission=target.mission,
        goals=(
            GoalProposal(
                "g", "Existing", "Needed", "Aligned", existing_goal_id=target.goals[0].goal_id
            ),
        ),
        milestones=(
            MilestoneProposal(
                "m",
                "g",
                target.milestones[0].title,
                existing_milestone_id=target.milestones[0].milestone_id,
            ),
        ),
        next_action="Continue",
    )
    review = service.handle(
        PlanningCommand(
            MODEL,
            SubmitProposalDraft(brief.run_id, "proposal", brief.brief_context_digest, draft),
        )
    )
    service.handle(
        PlanningCommand(
            RECORDER,
            RecordCheckpoint(
                "target",
                Checkpoint("mid", "on-track", "2026-08-23T14:00:00+00:00"),
                "checkpoint",
            ),
        )
    )

    with pytest.raises(ProposalConflictError, match="stale"):
        service.handle(
            PlanningCommand(
                LEARNER,
                DecideProposal(
                    review.proposal_id,
                    review.proposal_digest,
                    "approve",
                    "decision",
                    expected_document_digest=brief.target_document_digest,
                    expected_structure_digest=brief.target_structure_digest,
                    expected_document_revision=brief.target_document_revision,
                    expected_structure_revision=brief.target_structure_revision,
                ),
            )
        )


def test_trusted_evidence_after_submission_makes_revision_approval_stale(
    tmp_path: Path,
) -> None:
    item = evidence_ref("practice-1", source_kind="studyloop_practice", tier=1)
    target = canonical_plan("target", goal_ids=("goal-target",))
    store_plan(tmp_path, target)
    service = lifecycle(tmp_path, evidence=(item,))
    brief = service.prepare(
        PlanningRequest("revise", "Keep structure", "run", plan_id="target"), MODEL
    )
    draft = PlanProposalDraft(
        title=target.title,
        mission=target.mission,
        goals=(GoalProposal("g", "Existing", "Needed", "Aligned", existing_goal_id="goal-target"),),
        milestones=(
            MilestoneProposal(
                "m",
                "g",
                target.milestones[0].title,
                existing_milestone_id=target.milestones[0].milestone_id,
            ),
        ),
        evidence_dispositions=(EvidenceDisposition(item.evidence_id, "selected", "Relevant"),),
        next_action="Continue",
    )
    review = service.handle(
        PlanningCommand(
            MODEL,
            SubmitProposalDraft(brief.run_id, "proposal", brief.brief_context_digest, draft),
        )
    )
    service.handle(
        PlanningCommand(
            RECORDER,
            RecordTrustedEvidence("target", (item.evidence_id,), "new-evidence"),
        )
    )

    with pytest.raises(ProposalConflictError, match="stale"):
        service.handle(
            PlanningCommand(
                LEARNER,
                DecideProposal(
                    review.proposal_id,
                    review.proposal_digest,
                    "approve",
                    "decision",
                    expected_document_digest=brief.target_document_digest,
                    expected_structure_digest=brief.target_structure_digest,
                    expected_document_revision=brief.target_document_revision,
                    expected_structure_revision=brief.target_structure_revision,
                ),
            )
        )


def test_requested_activation_refuses_incomplete_readiness(tmp_path: Path) -> None:
    service = lifecycle(tmp_path)
    brief = service.prepare(PlanningRequest("create", "Help", "run"), MODEL)
    draft = PlanProposalDraft(
        title="Not ready",
        mission=Mission(why="I know why", success=[]),
        goals=(GoalProposal("g", "Goal", "Needed", "Aligned"),),
        milestones=(MilestoneProposal("m", "g", "Step"),),
        next_action="Try",
        requested_status="active",
    )
    review = service.handle(
        PlanningCommand(
            MODEL,
            SubmitProposalDraft(brief.run_id, "proposal", brief.brief_context_digest, draft),
        )
    )
    with pytest.raises(LifecycleValidationError, match="not ready to activate"):
        service.handle(
            PlanningCommand(
                LEARNER,
                DecideProposal(review.proposal_id, review.proposal_digest, "approve", "decision"),
            )
        )


def test_import_strips_foreign_authority_and_regenerates_learning_map(tmp_path: Path) -> None:
    imported = """---
schema_version: 2
id: ../../foreign
status: active
document_digest: attacker
structure_digest: attacker
---
# Foreign plan
## Mission
### Why
Learn it
### Success looks like
- Show it
## Goals
| ID | Title | Status | Reason | Alignment rationale |
| --- | --- | --- | --- | --- |
| foreign-goal | Goal | complete | reason | aligned |
## Learning Map
```mermaid
flowchart TD
evil --> shell
```
## Milestones
| ID | Goal ID | Done | Title | Notes | Concepts |
| --- | --- | --- | --- | --- | --- |
| foreign-step | foreign-goal | true | Already done | claimed | (concepts: notes) |
## Evidence Ledger
### Evidence references
| ID | Source | Native ID | Revision | Observed | Ingested | Tier | Claim | Subject | Digest |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| foreign-evidence | notes | n | 1 | now | now | 1 | completed | milestone | fake |
"""
    service = lifecycle(tmp_path)
    outcome = service.handle(
        PlanningCommand(
            LEARNER,
            ImportPlanDraft(imported, "import-1"),
        )
    )
    view = service.inspect(PlanningRef(outcome.plan_id))

    assert view.plan.status == "draft"
    assert view.plan.plan_id != "../../foreign"
    assert view.plan.goals[0].goal_id != "foreign-goal"
    assert view.plan.goals[0].status == "active"
    assert view.plan.milestones[0].milestone_id != "foreign-step"
    assert view.plan.milestones[0].done is False
    assert all(item.evidence_id != "foreign-evidence" for item in view.plan.evidence)
    assert "evil --> shell" not in view.canonical_text
    assert "flowchart TD" in view.canonical_text

    replay = lifecycle(tmp_path).handle(
        PlanningCommand(LEARNER, ImportPlanDraft(imported, "import-1"))
    )
    assert replay == outcome


def test_import_rejects_executable_markdown_without_canonical_mutation(tmp_path: Path) -> None:
    service = lifecycle(tmp_path)
    with pytest.raises(LifecycleValidationError, match="executable content"):
        service.handle(
            PlanningCommand(
                LEARNER,
                ImportPlanDraft("# Plan\n\n<script>alert('no')</script>", "unsafe-import"),
            )
        )

    assert not list((tmp_path / "plans").glob("*.md"))


def test_import_refuses_at_capacity_under_the_repository_lock(tmp_path: Path) -> None:
    for plan_id in ("one", "two", "three"):
        store_plan(tmp_path, canonical_plan(plan_id))

    with pytest.raises(PlanCapacityError, match="maximum of 3 current plans"):
        lifecycle(tmp_path).handle(
            PlanningCommand(LEARNER, ImportPlanDraft("# Fourth", "capacity-import"))
        )

    assert {path.stem for path in (tmp_path / "plans").glob("*.md")} == {
        "one",
        "two",
        "three",
    }


def test_import_rejects_fresh_id_collision_without_overwriting(tmp_path: Path) -> None:
    class CollidingIds:
        def __init__(self) -> None:
            self.count = 0

        def new_id(self, prefix: str) -> str:
            self.count += 1
            return "collision" if prefix == "plan" else f"{prefix}-collision-{self.count}"

    original = canonical_plan("collision")
    store_plan(tmp_path, original)

    with pytest.raises(PlanConflictError, match="already exists"):
        lifecycle(tmp_path, ids=CollidingIds()).handle(
            PlanningCommand(LEARNER, ImportPlanDraft("# Attacker replacement", "collision-import"))
        )

    assert lifecycle(tmp_path).inspect(PlanningRef("collision")).plan.title == original.title


def test_invalid_status_transition_is_deterministic(tmp_path: Path) -> None:
    service = lifecycle(tmp_path)
    _, review = _proposal(service)
    applied = service.handle(
        PlanningCommand(
            LEARNER,
            DecideProposal(review.proposal_id, review.proposal_digest, "approve", "approve"),
        )
    )
    service.handle(
        PlanningCommand(
            LEARNER,
            TransitionPlanStatus(applied.plan_id, "abandoned", "abandon"),
        )
    )

    with pytest.raises(LifecycleValidationError, match="terminal status 'abandoned'"):
        service.handle(
            PlanningCommand(
                LEARNER,
                TransitionPlanStatus(applied.plan_id, "active", "reactivate"),
            )
        )
