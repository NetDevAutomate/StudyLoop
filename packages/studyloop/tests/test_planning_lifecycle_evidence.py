"""Trusted evidence hierarchy and milestone outcome contracts."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from planning_lifecycle_support import LEARNER, MODEL, RECORDER, evidence_ref, lifecycle

from studyloop.planning import (
    Checkpoint,
    DecideProposal,
    EvidenceDisposition,
    EvidenceValidationError,
    GoalProposal,
    IdempotencyConflictError,
    MilestoneProposal,
    Mission,
    PlanningCommand,
    PlanningRef,
    PlanningRequest,
    PlanProposalDraft,
    RecordCheckpoint,
    RecordMilestoneOutcome,
    RecordTrustedEvidence,
    SubmitProposalDraft,
)

if TYPE_CHECKING:
    from pathlib import Path


def _draft(dispositions: tuple[EvidenceDisposition, ...]) -> PlanProposalDraft:
    return PlanProposalDraft(
        title="Evidence plan",
        mission=Mission(why="Practise deliberately", success=["Demonstrate protocols"]),
        goals=(GoalProposal("g", "Protocols", "Needed", "Aligned"),),
        milestones=(MilestoneProposal("m", "g", "Trace protocols"),),
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


def _accepted_plan(tmp_path: Path, evidence, *, disposition: str = "selected"):
    service = lifecycle(tmp_path, evidence=evidence)
    brief = service.prepare(PlanningRequest("create", "Help", "run"), MODEL)
    dispositions = tuple(
        EvidenceDisposition(item.evidence_id, disposition, "Relevant but not proof")
        for item in evidence
    )
    review = service.handle(
        PlanningCommand(
            MODEL,
            SubmitProposalDraft(
                brief.run_id,
                "proposal",
                brief.brief_context_digest,
                _draft(dispositions),
            ),
        )
    )
    outcome = service.handle(
        PlanningCommand(
            LEARNER,
            DecideProposal(review.proposal_id, review.proposal_digest, "approve", "decision"),
        )
    )
    return service, outcome.plan_id, review.plan_preview.milestones[0].milestone_id


@pytest.mark.parametrize("disposition", ["rejected", "unresolved"])
def test_rejected_or_unresolved_evidence_cannot_prove_completion(
    tmp_path: Path, disposition: str
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

    assert service.inspect(PlanningRef(plan_id)).plan.milestones[0].done is False


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


def test_verified_completion_and_learner_attestation_are_visibly_distinct(
    tmp_path: Path,
) -> None:
    verified = evidence_ref("practice-1", source_kind="studyloop_practice", tier=1)
    self_report = evidence_ref("self-1", source_kind="learner_self_report", tier=3)
    service, plan_id, milestone_id = _accepted_plan(tmp_path, (verified, self_report))

    attested = service.handle(
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
        )
    )
    attested_view = service.inspect(PlanningRef(plan_id))
    assert attested.status == "learner_attested"
    assert attested_view.plan.milestones[0].done is False
    assert "learner-attested" in attested_view.plan.learning_records[-1].title.lower()

    verified_outcome = service.handle(
        PlanningCommand(
            RECORDER,
            RecordMilestoneOutcome(
                plan_id,
                milestone_id,
                "verified_complete",
                (verified.evidence_id,),
                "verify",
            ),
        )
    )
    verified_view = service.inspect(PlanningRef(plan_id))
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
    assert service.inspect(PlanningRef(plan_id)).plan.milestones[0].done is False


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
