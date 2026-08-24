"""Narrow compatibility translations into typed lifecycle contracts.

These helpers deliberately contain no persistence.  They translate the old
questionnaire-shaped plan into the proposal schema while authority remains in
the trusted CLI or HTTP adapter.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import cast

from .contracts import (
    ConceptProposal,
    ConceptRelationKind,
    ConceptRelationProposal,
    GoalProposal,
    LifecycleValidationError,
    MilestoneProposal,
    PlanningBrief,
    PlanningResult,
    PlanOutcome,
    PlanProposalDraft,
    ProposalReview,
)
from .models import EvidenceDisposition, StudyPlan
from .repository import PlanningView
from .store import validate_plan_id


class PreferredPlanIdGenerator:
    """Keep the legacy readable plan slug without accepting model authority."""

    def __init__(self, preferred_plan_id: str) -> None:
        self.preferred_plan_id = validate_plan_id(preferred_plan_id)
        self._used_plan_id = False

    def new_id(self, prefix: str) -> str:
        if prefix == "plan" and not self._used_plan_id:
            self._used_plan_id = True
            return self.preferred_plan_id
        return f"{prefix}-{uuid.uuid4().hex}"


def _evidence_dispositions(plan: StudyPlan) -> tuple[EvidenceDisposition, ...]:
    existing = {item.evidence_id: item for item in plan.evidence_dispositions}
    return tuple(
        existing.get(
            item.evidence_id,
            EvidenceDisposition(
                item.evidence_id,
                "unresolved",
                "Existing evidence needs explicit learner review",
            ),
        )
        for item in plan.evidence
    )


def proposal_draft_from_plan(plan: StudyPlan, *, revise: bool = False) -> PlanProposalDraft:
    """Translate a legacy structured plan into a learner-reviewable proposal."""
    goals = list(plan.goals)
    if len(goals) > 3:
        raise LifecycleValidationError(
            "compatibility revision contains more than three goals; "
            "use the planning agent to review all goals without truncation"
        )
    if revise:
        identities = {
            "goal": [item.goal_id for item in plan.goals],
            "concept": [item.concept_id for item in plan.concepts],
            "milestone": [item.milestone_id for item in plan.milestones],
        }
        for label, values in identities.items():
            nonblank = [value for value in values if value]
            if len(nonblank) != len(set(nonblank)):
                raise LifecycleValidationError(
                    f"compatibility revision contains duplicate {label} ids; "
                    "use the planning agent to repair identities without cross-linking"
                )
        normalised_labels: dict[str, list[str]] = {}
        for concept in plan.concepts:
            normalised = " ".join(concept.display_label.casefold().split())
            if normalised:
                normalised_labels.setdefault(normalised, []).append(concept.concept_id)
        if any(len(ids) > 1 for ids in normalised_labels.values()):
            raise LifecycleValidationError(
                "compatibility revision contains duplicate concept labels; "
                "use explicit concept identities before revising milestone links"
            )
        if len(goals) > 1 and any(not item.goal_id for item in goals):
            raise LifecycleValidationError(
                "compatibility revision has multiple goals with blank identity; "
                "use the planning agent to repair goal-to-milestone links"
            )
        known_goal_ids = {item.goal_id for item in goals if item.goal_id}
        for milestone in plan.milestones:
            if milestone.goal_id and milestone.goal_id not in known_goal_ids:
                raise LifecycleValidationError(
                    "compatibility revision contains a milestone with an unknown goal id; "
                    "use the planning agent to repair the link without guessing"
                )
            if len(goals) > 1 and not milestone.goal_id:
                raise LifecycleValidationError(
                    "compatibility revision contains a milestone with a blank goal id; "
                    "use the planning agent to repair the ambiguous link"
                )
    if not goals:
        from .models import Goal

        goals = [
            Goal(
                "",
                plan.title,
                plan.mission.why or "Clarify why this plan matters",
                "Directly supports the plan mission",
            )
        ]
    goal_aliases = [f"goal-{index}" for index in range(1, len(goals) + 1)]
    goal_alias_by_id: dict[str, str] = {}
    for item, alias in zip(goals, goal_aliases, strict=True):
        if item.goal_id and item.goal_id not in goal_alias_by_id:
            goal_alias_by_id[item.goal_id] = alias
    fallback_goal_alias = goal_aliases[0]
    seen_goal_ids: set[str] = set()
    goal_proposal_items: list[GoalProposal] = []
    for item, alias in zip(goals, goal_aliases, strict=True):
        existing_goal_id = ""
        if revise and item.goal_id and item.goal_id not in seen_goal_ids:
            existing_goal_id = item.goal_id
            seen_goal_ids.add(item.goal_id)
        goal_proposal_items.append(
            GoalProposal(
                alias=alias,
                title=item.title,
                reason=item.reason,
                alignment_rationale=item.alignment_rationale,
                status=item.status,
                existing_goal_id=existing_goal_id,
            )
        )
    goal_proposals = tuple(goal_proposal_items)

    concept_rows: list[tuple[str, str]] = [
        (concept.display_label, concept.concept_id)
        for concept in plan.concepts
        if concept.display_label.strip()
    ]
    known_labels = {label for label, _concept_id in concept_rows}
    for milestone in plan.milestones:
        for label in milestone.concepts:
            if label.strip() and label not in known_labels:
                concept_rows.append((label, ""))
                known_labels.add(label)
    concept_by_label: dict[str, str] = {}
    concept_alias_by_id: dict[str, str] = {}
    seen_concept_ids: set[str] = set()
    concept_items: list[ConceptProposal] = []
    for index, (label, concept_id) in enumerate(concept_rows, 1):
        alias = f"concept-{index}"
        concept_by_label.setdefault(label, alias)
        existing_concept_id = ""
        if revise and concept_id and concept_id not in seen_concept_ids:
            existing_concept_id = concept_id
            seen_concept_ids.add(concept_id)
            concept_alias_by_id[concept_id] = alias
        concept_items.append(
            ConceptProposal(
                alias=alias,
                display_label=label,
                existing_concept_id=existing_concept_id,
            )
        )
    concepts = tuple(concept_items)
    relation_items: list[ConceptRelationProposal] = []
    for relation in plan.concept_relations:
        source_alias = concept_alias_by_id.get(relation.source_ref)
        target_alias = concept_alias_by_id.get(relation.target_ref)
        if not source_alias or not target_alias:
            raise LifecycleValidationError(
                "compatibility revision contains a concept relation with unresolved identity; "
                "use the planning agent to repair it without data loss"
            )
        if relation.relation not in {"equivalent", "broader", "narrower", "related", "distinct"}:
            raise LifecycleValidationError(
                f"compatibility revision contains unsupported relation {relation.relation!r}"
            )
        relation_items.append(
            ConceptRelationProposal(
                source_alias,
                target_alias,
                cast("ConceptRelationKind", relation.relation),
                relation.reason,
                "preserved from the learner-reviewed canonical plan",
            )
        )
    seen_milestone_ids: set[str] = set()
    milestone_items: list[MilestoneProposal] = []
    for index, item in enumerate(plan.milestones, 1):
        existing_milestone_id = ""
        if revise and item.milestone_id and item.milestone_id not in seen_milestone_ids:
            existing_milestone_id = item.milestone_id
            seen_milestone_ids.add(item.milestone_id)
        milestone_items.append(
            MilestoneProposal(
                alias=f"milestone-{index}",
                goal_alias=goal_alias_by_id.get(item.goal_id, fallback_goal_alias),
                title=item.title,
                notes=item.notes,
                concept_aliases=tuple(
                    concept_by_label[label] for label in item.concepts if label in concept_by_label
                ),
                existing_milestone_id=existing_milestone_id,
            )
        )
    milestones = tuple(milestone_items)
    next_action = plan.next_action.strip()
    if not next_action:
        next_action = (
            f"Start: {plan.milestones[0].title}"
            if plan.milestones
            else "Review this draft and choose the first concrete study action"
        )
    return PlanProposalDraft(
        title=plan.title,
        mission=plan.mission,
        goals=goal_proposals,
        milestones=milestones,
        topics=tuple(plan.topics),
        concepts=concepts,
        concept_relations=tuple(relation_items),
        evidence_dispositions=_evidence_dispositions(plan),
        resources=tuple(plan.resources),
        unknowns=tuple(plan.unknowns),
        next_action=next_action,
        requested_status=plan.status if revise else "draft",
        target_date=plan.target_date,
        energy_floor=plan.energy_floor,
        review_cadence_days=plan.review_cadence_days,
    )


def proposal_payload(
    review: ProposalReview, brief: PlanningBrief | None = None
) -> dict[str, object]:
    """Stable compatibility DTO containing the exact decision CAS values."""
    return {
        "proposal_id": review.proposal_id,
        "proposal_digest": review.proposal_digest,
        "plan_id": review.plan_preview.plan_id,
        "plan": review.plan_preview.summary(),
        "markdown": review.markdown_preview,
        "blockers": list(review.validation_blockers),
        "nudges": list(review.nudges),
        "expected": {
            "expected_document_digest": brief.target_document_digest,
            "expected_structure_digest": brief.target_structure_digest,
            "expected_document_revision": brief.target_document_revision,
            "expected_structure_revision": brief.target_structure_revision,
        }
        if review.mode == "revise" and brief is not None
        else {},
    }


def outcome_payload(outcome: object) -> dict[str, object]:
    """Dataclass outcome as a JSON-safe object without inventing fields."""
    return asdict(outcome)  # type: ignore[arg-type]


def require_proposal(result: PlanningResult) -> ProposalReview:
    """Narrow the lifecycle union at a trusted adapter boundary."""
    if not isinstance(result, ProposalReview):
        raise LifecycleValidationError(
            f"lifecycle returned {type(result).__name__}, expected ProposalReview"
        )
    return result


def require_outcome(result: PlanningResult) -> PlanOutcome:
    """Narrow a mutation result and fail closed on an internal contract breach."""
    if not isinstance(result, PlanOutcome):
        raise LifecycleValidationError(
            f"lifecycle returned {type(result).__name__}, expected PlanOutcome"
        )
    return result


def require_view(result: PlanningResult) -> PlanningView:
    """Narrow a canonical-plan inspection result."""
    if not isinstance(result, PlanningView):
        raise LifecycleValidationError(
            f"lifecycle returned {type(result).__name__}, expected PlanningView"
        )
    return result


__all__ = [
    "PreferredPlanIdGenerator",
    "outcome_payload",
    "proposal_draft_from_plan",
    "proposal_payload",
    "require_outcome",
    "require_proposal",
    "require_view",
]
