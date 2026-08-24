"""Trusted evidence hierarchy and milestone outcome contracts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import pytest
from planning_lifecycle_support import (
    LEARNER,
    MODEL,
    RECORDER,
    PrefixIds,
    evidence_ref,
    lifecycle,
    store_plan,
)

from studyloop.planning import (
    Checkpoint,
    ConceptProposal,
    ConceptRef,
    DecideProposal,
    EvidenceDisposition,
    EvidenceRef,
    EvidenceValidationError,
    Goal,
    GoalProposal,
    IdempotencyConflictError,
    LifecycleValidationError,
    Milestone,
    MilestoneProposal,
    Mission,
    PlanningCommand,
    PlanningLifecycle,
    PlanningRef,
    PlanningRequest,
    PlanProposalDraft,
    RecordCheckpoint,
    RecordMilestoneOutcome,
    RecordTrustedEvidence,
    StudyPlan,
    SubmitProposalDraft,
)
from studyloop.planning.compat import require_outcome, require_proposal, require_view

if TYPE_CHECKING:
    from pathlib import Path


def _draft(dispositions: tuple[EvidenceDisposition, ...]) -> PlanProposalDraft:
    return PlanProposalDraft(
        title="Evidence plan",
        mission=Mission(why="Practise deliberately", success=["Demonstrate protocols"]),
        goals=(GoalProposal("g", "Protocols", "Needed", "Aligned"),),
        milestones=(
            MilestoneProposal("m", "g", "Trace protocols", concept_aliases=("protocols",)),
        ),
        concepts=(ConceptProposal("protocols", "protocols"),),
        evidence_dispositions=dispositions,
        next_action="Trace one exchange",
    )


def test_submission_requires_exact_disposition_coverage_and_known_ids(tmp_path: Path) -> None:
    note = evidence_ref("note-1", source_kind="notes", tier=4)
    verified = evidence_ref("practice-1", source_kind="studyloop_practice", tier=1)
    service = lifecycle(tmp_path, evidence=(note, verified))
    brief = service.prepare(PlanningRequest("create", "Help", "run"), MODEL)

    with pytest.raises(EvidenceValidationError, match="exactly once"):
        service.handle(
            PlanningCommand(
                MODEL,
                SubmitProposalDraft(
                    brief.run_id,
                    "missing-disposition",
                    brief.brief_context_digest,
                    _draft((EvidenceDisposition("note-1", "selected", "Useful"),)),
                ),
            )
        )

    with pytest.raises(EvidenceValidationError, match="unknown evidence"):
        service.handle(
            PlanningCommand(
                MODEL,
                SubmitProposalDraft(
                    brief.run_id,
                    "unknown-disposition",
                    brief.brief_context_digest,
                    _draft(
                        (
                            EvidenceDisposition("note-1", "selected", "Useful"),
                            EvidenceDisposition("made-up", "selected", "Pretend"),
                        )
                    ),
                ),
            )
        )

    with pytest.raises(EvidenceValidationError, match="exactly once"):
        service.handle(
            PlanningCommand(
                MODEL,
                SubmitProposalDraft(
                    brief.run_id,
                    "duplicate-disposition",
                    brief.brief_context_digest,
                    _draft(
                        (
                            EvidenceDisposition("note-1", "selected", "Useful"),
                            EvidenceDisposition("note-1", "rejected", "Duplicate"),
                        )
                    ),
                ),
            )
        )


def test_proposal_cannot_supply_or_reclassify_evidence_tiers(tmp_path: Path) -> None:
    forged = evidence_ref("forged", source_kind="notes", tier=1)
    with pytest.raises(EvidenceValidationError, match="tier 4"):
        lifecycle(tmp_path, evidence=(forged,))


def _accepted_plan(
    tmp_path: Path,
    evidence: tuple[EvidenceRef, ...],
    *,
    disposition: Literal["selected", "rejected", "unresolved"] = "selected",
) -> tuple[PlanningLifecycle, str, str]:
    ids = PrefixIds()
    expected_concept_id = f"concept-{ids.namespace}-0001"
    for item in evidence:
        if item.subject_ref == "concept:protocols":
            item.subject_ref = f"concept:{expected_concept_id}"
    service = lifecycle(tmp_path, evidence=evidence, ids=ids)
    brief = service.prepare(PlanningRequest("create", "Help", "run"), MODEL)
    dispositions = tuple(
        EvidenceDisposition(item.evidence_id, disposition, "Relevant but not proof")
        for item in evidence
    )
    review = require_proposal(
        service.handle(
            PlanningCommand(
                MODEL,
                SubmitProposalDraft(
                    brief.run_id,
                    "proposal",
                    brief.brief_context_digest,
                    _draft(dispositions),
                ),
            ),
        )
    )
    outcome = require_outcome(
        service.handle(
            PlanningCommand(
                LEARNER,
                DecideProposal(review.proposal_id, review.proposal_digest, "approve", "decision"),
            )
        )
    )
    return service, outcome.plan_id, review.plan_preview.milestones[0].milestone_id


@pytest.mark.parametrize("disposition", ["rejected", "unresolved"])
def test_rejected_or_unresolved_evidence_cannot_prove_completion(
    tmp_path: Path, disposition: Literal["rejected", "unresolved"]
) -> None:
    verified = evidence_ref("practice-1", source_kind="studyloop_practice", tier=1)
    service, plan_id, milestone_id = _accepted_plan(tmp_path, (verified,), disposition=disposition)

    with pytest.raises(EvidenceValidationError, match="selected"):
        service.handle(
            PlanningCommand(
                RECORDER,
                RecordMilestoneOutcome(
                    plan_id,
                    milestone_id,
                    "verified_complete",
                    (verified.evidence_id,),
                    f"not-proof-{disposition}",
                ),
            )
        )


def test_tier_four_context_and_checkpoint_never_mark_completion(tmp_path: Path) -> None:
    note = evidence_ref("note-1", source_kind="notes", tier=4)
    service, plan_id, milestone_id = _accepted_plan(tmp_path, (note,))
    service.handle(
        PlanningCommand(
            RECORDER,
            RecordTrustedEvidence(plan_id, (note.evidence_id,), "record-note"),
        )
    )
    service.handle(
        PlanningCommand(
            RECORDER,
            RecordCheckpoint(
                plan_id,
                Checkpoint("mid", "complete", "2026-08-23T13:00:00+00:00", "Looks done"),
                "checkpoint",
            ),
        )
    )

    with pytest.raises(EvidenceValidationError, match="tier 1"):
        service.handle(
            PlanningCommand(
                RECORDER,
                RecordMilestoneOutcome(
                    plan_id,
                    milestone_id,
                    "verified_complete",
                    (note.evidence_id,),
                    "complete-from-note",
                ),
            )
        )

    assert require_view(service.inspect(PlanningRef(plan_id))).plan.milestones[0].done is False


def test_checkpoint_command_replays_after_restart_and_changed_payload_conflicts(
    tmp_path: Path,
) -> None:
    service, plan_id, _ = _accepted_plan(tmp_path, ())
    command = RecordCheckpoint(
        plan_id,
        Checkpoint("mid", "on-track", "2026-08-23T13:00:00+00:00", "Steady"),
        "checkpoint-replay",
    )
    first = service.handle(PlanningCommand(RECORDER, command))
    replay = lifecycle(tmp_path).handle(PlanningCommand(RECORDER, command))

    assert replay == first
    with pytest.raises(IdempotencyConflictError, match="different lifecycle command"):
        lifecycle(tmp_path).handle(
            PlanningCommand(
                RECORDER,
                RecordCheckpoint(
                    plan_id,
                    Checkpoint(
                        "mid",
                        "at-risk",
                        "2026-08-23T13:00:00+00:00",
                        "Changed",
                    ),
                    "checkpoint-replay",
                ),
            )
        )


def test_incomplete_milestone_outcome_replays_after_restart(tmp_path: Path) -> None:
    service, plan_id, milestone_id = _accepted_plan(tmp_path, ())
    command = RecordMilestoneOutcome(
        plan_id,
        milestone_id,
        "incomplete",
        (),
        "incomplete-replay",
        reason="More practice is needed",
    )

    first = service.handle(PlanningCommand(LEARNER, command))
    replay = lifecycle(tmp_path).handle(PlanningCommand(LEARNER, command))

    assert replay == first


def test_verified_completion_and_learner_attestation_are_visibly_distinct(
    tmp_path: Path,
) -> None:
    verified = evidence_ref("practice-1", source_kind="studyloop_practice", tier=1)
    self_report = evidence_ref("self-1", source_kind="learner_self_report", tier=3)
    service, plan_id, milestone_id = _accepted_plan(tmp_path, (verified, self_report))
    assert verified.subject_ref == (
        f"concept:{require_view(service.inspect(PlanningRef(plan_id))).plan.concepts[0].concept_id}"
    )

    attested = require_outcome(
        service.handle(
            PlanningCommand(
                LEARNER,
                RecordMilestoneOutcome(
                    plan_id,
                    milestone_id,
                    "learner_attested",
                    (self_report.evidence_id,),
                    "attest",
                    reason="I traced it myself without following an answer",
                    confirmation="I confirm this records my own completed practice",
                ),
            ),
        )
    )
    attested_view = require_view(service.inspect(PlanningRef(plan_id)))
    assert attested.status == "learner_attested"
    assert attested_view.plan.milestones[0].done is False
    assert "learner-attested" in attested_view.plan.learning_records[-1].title.lower()

    verified_outcome = require_outcome(
        service.handle(
            PlanningCommand(
                RECORDER,
                RecordMilestoneOutcome(
                    plan_id,
                    milestone_id,
                    "verified_complete",
                    (verified.evidence_id,),
                    "verify",
                ),
            ),
        )
    )
    verified_view = require_view(service.inspect(PlanningRef(plan_id)))
    assert verified_outcome.status == "verified_complete"
    assert verified_view.plan.milestones[0].done is True
    assert "verified" in verified_view.plan.learning_records[-1].title.lower()


def test_tier_one_evidence_must_match_the_target_milestone(tmp_path: Path) -> None:
    unrelated = evidence_ref(
        "practice-other",
        source_kind="studyloop_practice",
        tier=1,
        subject_ref="milestone:some-other-milestone",
    )
    service, plan_id, milestone_id = _accepted_plan(tmp_path, (unrelated,))

    with pytest.raises(EvidenceValidationError, match="target milestone"):
        service.handle(
            PlanningCommand(
                RECORDER,
                RecordMilestoneOutcome(
                    plan_id,
                    milestone_id,
                    "verified_complete",
                    (unrelated.evidence_id,),
                    "irrelevant-tier-one",
                ),
            )
        )
    assert require_view(service.inspect(PlanningRef(plan_id))).plan.milestones[0].done is False


def test_tier_one_evidence_must_carry_a_completion_claim(tmp_path: Path) -> None:
    wrong_claim = evidence_ref(
        "practice-context",
        source_kind="studyloop_practice",
        tier=1,
        subject_ref="concept:protocols",
    )
    wrong_claim.claim_kind = "curriculum_context"
    service, plan_id, milestone_id = _accepted_plan(tmp_path, (wrong_claim,))

    with pytest.raises(EvidenceValidationError, match="completion claim"):
        service.handle(
            PlanningCommand(
                RECORDER,
                RecordMilestoneOutcome(
                    plan_id,
                    milestone_id,
                    "verified_complete",
                    (wrong_claim.evidence_id,),
                    "wrong-claim",
                ),
            )
        )


@pytest.mark.parametrize("subject", ["concept:sql", "concept:no"])
def test_overlapping_or_nested_labels_do_not_match_milestone_titles(
    tmp_path: Path, subject: str
) -> None:
    evidence = evidence_ref(
        f"overlap-{subject.removeprefix('concept:')}",
        source_kind="studyloop_practice",
        tier=1,
        subject_ref=subject,
    )
    service = lifecycle(tmp_path, evidence=(evidence,))
    brief = service.prepare(PlanningRequest("create", "Help", "overlap-run"), MODEL)
    draft = PlanProposalDraft(
        title="NoSQL plan",
        mission=Mission(why="Learn storage", success=["Explain it"]),
        goals=(GoalProposal("g", "Storage", "Needed", "Aligned"),),
        milestones=(MilestoneProposal("m", "g", "Learn NoSQL storage"),),
        evidence_dispositions=(EvidenceDisposition(evidence.evidence_id, "selected", "Candidate"),),
        next_action="Trace storage",
    )
    review = require_proposal(
        service.handle(
            PlanningCommand(
                MODEL,
                SubmitProposalDraft(
                    brief.run_id,
                    "overlap-proposal",
                    brief.brief_context_digest,
                    draft,
                ),
            ),
        )
    )
    applied = require_outcome(
        service.handle(
            PlanningCommand(
                LEARNER,
                DecideProposal(
                    review.proposal_id,
                    review.proposal_digest,
                    "approve",
                    "overlap-decision",
                ),
            ),
        )
    )
    milestone_id = (
        require_view(service.inspect(PlanningRef(applied.plan_id))).plan.milestones[0].milestone_id
    )
    with pytest.raises(EvidenceValidationError, match="target milestone"):
        service.handle(
            PlanningCommand(
                RECORDER,
                RecordMilestoneOutcome(
                    applied.plan_id,
                    milestone_id,
                    "verified_complete",
                    (evidence.evidence_id,),
                    "overlap-complete",
                ),
            )
        )


def test_unlinked_case_colliding_concept_id_cannot_verify_milestone(tmp_path: Path) -> None:
    evidence = evidence_ref(
        "unlinked-sql",
        source_kind="studyloop_practice",
        tier=1,
        subject_ref="concept:c-unlinked",
    )
    plan = StudyPlan(
        "concept-identity",
        "Concept identity",
        mission=Mission(why="Keep identity exact", success=["Demonstrate SQL"]),
        goals=[Goal("g-1", "SQL", "Needed", "Aligned")],
        concepts=[ConceptRef("c-linked", "SQL"), ConceptRef("c-unlinked", "sql")],
        milestones=[Milestone("Practise SQL", concepts=["SQL"], milestone_id="m-1", goal_id="g-1")],
        evidence=[evidence],
        evidence_dispositions=[EvidenceDisposition(evidence.evidence_id, "selected", "Candidate")],
    )
    store_plan(tmp_path, plan)
    service = lifecycle(tmp_path, evidence=(evidence,))
    with pytest.raises(EvidenceValidationError, match="target milestone"):
        service.handle(
            PlanningCommand(
                RECORDER,
                RecordMilestoneOutcome(
                    plan.plan_id,
                    "m-1",
                    "verified_complete",
                    (evidence.evidence_id,),
                    "unlinked-case-collision",
                ),
            )
        )


@pytest.mark.parametrize("subject_ref", ["concept:c-unlinked", "milestone:m-1"])
def test_ambiguous_duplicate_concepts_block_all_verified_completion(
    tmp_path: Path, subject_ref: str
) -> None:
    evidence = evidence_ref(
        f"ambiguous-{subject_ref.replace(':', '-')}",
        source_kind="studyloop_practice",
        tier=1,
        subject_ref=subject_ref,
    )
    plan = StudyPlan(
        "duplicate-concept-identity",
        "Duplicate concept identity",
        mission=Mission(why="Keep identity exact", success=["Demonstrate SQL"]),
        goals=[Goal("g-1", "SQL", "Needed", "Aligned")],
        concepts=[ConceptRef("c-linked", "SQL"), ConceptRef("c-unlinked", "SQL")],
        milestones=[Milestone("Practise SQL", concepts=["SQL"], milestone_id="m-1", goal_id="g-1")],
        evidence=[evidence],
        evidence_dispositions=[EvidenceDisposition(evidence.evidence_id, "selected", "Candidate")],
    )
    store_plan(tmp_path, plan)
    service = lifecycle(tmp_path, evidence=(evidence,))

    with pytest.raises(EvidenceValidationError, match="ambiguous concept label"):
        service.handle(
            PlanningCommand(
                RECORDER,
                RecordMilestoneOutcome(
                    plan.plan_id,
                    "m-1",
                    "verified_complete",
                    (evidence.evidence_id,),
                    "ambiguous-duplicate",
                ),
            )
        )

    assert require_view(service.inspect(PlanningRef(plan.plan_id))).plan.milestones[0].done is False


def test_proposal_rejects_case_or_whitespace_colliding_concept_labels(tmp_path: Path) -> None:
    service = lifecycle(tmp_path)
    brief = service.prepare(PlanningRequest("create", "Help", "label-collision"), MODEL)
    draft = PlanProposalDraft(
        title="Collision",
        mission=Mission(why="Keep identity", success=["Explain it"]),
        goals=(GoalProposal("g", "SQL", "Needed", "Aligned"),),
        concepts=(ConceptProposal("linked", "SQL"), ConceptProposal("unlinked", " sql ")),
        milestones=(MilestoneProposal("m", "g", "Practise", concept_aliases=("linked",)),),
        next_action="Practise",
    )
    with pytest.raises(LifecycleValidationError, match="unique after normalisation"):
        service.handle(
            PlanningCommand(
                MODEL,
                SubmitProposalDraft(
                    brief.run_id,
                    "label-collision-proposal",
                    brief.brief_context_digest,
                    draft,
                ),
            )
        )
