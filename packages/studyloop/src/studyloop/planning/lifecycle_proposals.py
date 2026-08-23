"""Proposal validation, identity assignment, and activation policy."""

from __future__ import annotations

import copy
from dataclasses import asdict
from typing import TYPE_CHECKING

from .authoring import lifecycle_readiness
from .contracts import (
    Clock,
    DecideProposal,
    EvidenceValidationError,
    IdGenerator,
    LifecycleValidationError,
    PersistedProposal,
    PlanningBrief,
    PlanProposalDraft,
    ProposalConflictError,
)
from .digests import structure_projection
from .lifecycle_journal import canonical_lifecycle_digest
from .models import ConceptRef, ConceptRelation, Goal, Milestone, PlanUnknown, StudyPlan

if TYPE_CHECKING:
    from .repository import PlanSnapshot

_RELATIONS = frozenset({"equivalent", "broader", "narrower", "related", "distinct"})
_DISPOSITIONS = frozenset({"selected", "rejected", "unresolved"})


def goal_set_digest(goal_ids: tuple[str, ...]) -> str:
    return canonical_lifecycle_digest(
        "studyloop.active-goal-set", {"goal_ids": sorted(set(goal_ids))}
    )


def _active_goal_ids(plans: tuple[StudyPlan, ...]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                goal.goal_id
                for plan in plans
                if plan.status == "active"
                for goal in plan.goals
                if goal.status == "active" and goal.goal_id.strip()
            }
        )
    )


class ProposalPolicy:
    """Pure proposal rules kept behind the public lifecycle facade."""

    def __init__(self, ids: IdGenerator, clock: Clock) -> None:
        self.ids = ids
        self.clock = clock

    def validate_draft(self, draft: PlanProposalDraft, brief: PlanningBrief) -> None:
        if not draft.title.strip() or not draft.mission.why.strip():
            raise LifecycleValidationError("proposal title and mission are required")
        if not draft.next_action.strip():
            raise LifecycleValidationError("proposal requires one concrete next action")
        if draft.requested_status not in {"draft", "active"}:
            raise LifecycleValidationError("proposal status must be draft or active")
        if not 1 <= len(draft.goals) <= 3:
            raise LifecycleValidationError("a proposal must contain one to three aligned goals")
        self._unique_aliases("goal", [item.alias for item in draft.goals])
        self._unique_aliases("milestone", [item.alias for item in draft.milestones])
        self._unique_aliases("concept", [item.alias for item in draft.concepts])
        goal_aliases = {item.alias for item in draft.goals}
        concept_aliases = {item.alias for item in draft.concepts}
        target = brief.target_plan
        offered_goals = {item.goal_id for item in target.goals} if target else set()
        offered_concepts = {item.concept_id for item in target.concepts} if target else set()
        offered_milestones = {item.milestone_id for item in target.milestones} if target else set()
        referenced_goals = [item.existing_goal_id for item in draft.goals if item.existing_goal_id]
        referenced_concepts = [
            item.existing_concept_id for item in draft.concepts if item.existing_concept_id
        ]
        referenced_milestones = [
            item.existing_milestone_id for item in draft.milestones if item.existing_milestone_id
        ]
        references = (referenced_goals, referenced_concepts, referenced_milestones)
        if brief.mode == "create" and any(references):
            raise LifecycleValidationError("create proposals cannot reference existing entity ids")
        for label, referenced, offered in (
            ("goal", referenced_goals, offered_goals),
            ("concept", referenced_concepts, offered_concepts),
            ("milestone", referenced_milestones, offered_milestones),
        ):
            if set(referenced) - offered:
                raise LifecycleValidationError(
                    f"proposal references a {label} id absent from the revise brief"
                )
            if len(referenced) != len(set(referenced)):
                raise LifecycleValidationError(
                    f"an existing {label} id may be referenced only once"
                )
        for item in draft.goals:
            values = (item.alias, item.title, item.reason, item.alignment_rationale)
            if not all(" ".join(value.strip().split()) for value in values):
                raise LifecycleValidationError("every goal needs title, reason, and alignment")
            if item.status != "active":
                raise LifecycleValidationError("release-one proposal goals must be active")
        for item in draft.milestones:
            if item.goal_alias not in goal_aliases:
                raise LifecycleValidationError(
                    f"milestone {item.alias!r} references unknown goal alias"
                )
            unknown = set(item.concept_aliases) - concept_aliases
            if unknown:
                raise LifecycleValidationError(
                    f"milestone {item.alias!r} references unknown concepts {sorted(unknown)}"
                )
        seen_relations: set[tuple[str, str, str]] = set()
        for relation in draft.concept_relations:
            if (
                relation.source_alias not in concept_aliases
                or relation.target_alias not in concept_aliases
            ):
                raise LifecycleValidationError(
                    "concept relation references an unknown concept alias"
                )
            if relation.relation not in _RELATIONS or not relation.reason.strip():
                raise LifecycleValidationError(
                    "concept relation requires a supported type and reason"
                )
            identity = (relation.source_alias, relation.target_alias, relation.relation)
            if identity in seen_relations:
                raise LifecycleValidationError("duplicate concept relation")
            seen_relations.add(identity)
        offered_ids = [item.evidence_id for item in brief.evidence]
        disposition_ids = [item.evidence_id for item in draft.evidence_dispositions]
        if len(disposition_ids) != len(set(disposition_ids)):
            raise EvidenceValidationError("every offered evidence id must appear exactly once")
        unknown_ids = set(disposition_ids) - set(offered_ids)
        if unknown_ids:
            raise EvidenceValidationError(f"unknown evidence ids: {sorted(unknown_ids)}")
        if set(disposition_ids) != set(offered_ids):
            raise EvidenceValidationError("every offered evidence id must appear exactly once")
        for disposition in draft.evidence_dispositions:
            if disposition.disposition not in _DISPOSITIONS:
                raise EvidenceValidationError(
                    f"unsupported evidence disposition {disposition.disposition!r}"
                )
            if (
                disposition.disposition in {"rejected", "unresolved"}
                and not disposition.reason.strip()
            ):
                raise EvidenceValidationError(
                    f"{disposition.disposition} evidence requires a visible reason"
                )

    @staticmethod
    def _unique_aliases(label: str, aliases: list[str]) -> None:
        if any(not item.strip() for item in aliases) or len(set(aliases)) != len(aliases):
            raise LifecycleValidationError(f"{label} aliases must be nonblank and unique")

    def assign_plan(
        self,
        draft: PlanProposalDraft,
        brief: PlanningBrief,
        snapshot: PlanSnapshot,
    ) -> tuple[StudyPlan, dict[str, str]]:
        base_view = (
            next(
                (view for view in snapshot.plans if view.plan.plan_id == brief.plan_id),
                None,
            )
            if brief.mode == "revise"
            else None
        )
        base = copy.deepcopy(base_view.plan) if base_view is not None else None
        aliases: dict[str, str] = {}
        for item in draft.goals:
            aliases[f"goal:{item.alias}"] = item.existing_goal_id or self.ids.new_id("goal")
        for item in draft.concepts:
            aliases[f"concept:{item.alias}"] = item.existing_concept_id or self.ids.new_id(
                "concept"
            )
        for item in draft.milestones:
            aliases[f"milestone:{item.alias}"] = item.existing_milestone_id or self.ids.new_id(
                "milestone"
            )
        goals = [
            Goal(
                aliases[f"goal:{item.alias}"],
                item.title.strip(),
                item.reason.strip(),
                item.alignment_rationale.strip(),
                item.status,
            )
            for item in draft.goals
        ]
        concepts = [
            ConceptRef(aliases[f"concept:{item.alias}"], item.display_label.strip())
            for item in draft.concepts
        ]
        concept_labels = {item.alias: item.display_label.strip() for item in draft.concepts}
        milestones = [
            Milestone(
                item.title.strip(),
                done=False,
                concepts=[concept_labels[alias] for alias in item.concept_aliases],
                notes=item.notes.strip(),
                milestone_id=aliases[f"milestone:{item.alias}"],
                goal_id=aliases[f"goal:{item.goal_alias}"],
            )
            for item in draft.milestones
        ]
        relations = [
            ConceptRelation(
                aliases[f"concept:{item.source_alias}"],
                aliases[f"concept:{item.target_alias}"],
                item.relation,
                item.reason.strip(),
                "pending-learner-approval",
            )
            for item in draft.concept_relations
        ]
        now = self.clock.now()
        plan = StudyPlan(
            plan_id=brief.plan_id if brief.mode == "revise" else self.ids.new_id("plan"),
            title=draft.title.strip(),
            status=draft.requested_status,
            created=base.created if base else now,
            updated=now,
            topics=list(draft.topics),
            energy_floor=draft.energy_floor,
            target_date=draft.target_date,
            review_cadence_days=draft.review_cadence_days,
            mission=copy.deepcopy(draft.mission),
            next_action=draft.next_action.strip(),
            goals=goals,
            milestones=milestones,
            concepts=concepts,
            concept_relations=relations,
            unknowns=[
                PlanUnknown(self.ids.new_id("unknown"), item.question, item.impact, item.status)
                for item in draft.unknowns
            ],
            resources=list(draft.resources),
            evidence=list(brief.evidence),
            evidence_dispositions=list(draft.evidence_dispositions),
            learning_records=list(base.learning_records) if base else [],
            checkpoints=list(base.checkpoints) if base else [],
            decisions=list(base.decisions) if base else [],
            notes=base.notes if base else "",
            brief_context_digest=brief.brief_context_digest,
        )
        return plan, aliases

    @staticmethod
    def proposal_digest(
        brief: PlanningBrief,
        draft: PlanProposalDraft,
        plan: StudyPlan,
        aliases: dict[str, str],
        active_goal_ids: tuple[str, ...],
        active_goal_digest: str,
    ) -> str:
        return canonical_lifecycle_digest(
            "studyloop.planning-proposal",
            {
                "brief_context_digest": brief.brief_context_digest,
                "mode": brief.mode,
                "assigned_plan": structure_projection(plan),
                "alias_mapping": sorted(aliases.items()),
                "base": {
                    "document_digest": brief.target_document_digest,
                    "structure_digest": brief.target_structure_digest,
                    "document_revision": brief.target_document_revision,
                    "structure_revision": brief.target_structure_revision,
                },
                "requested_status": draft.requested_status,
                "resulting_active_goal_ids": list(active_goal_ids),
                "resulting_active_goal_set_digest": active_goal_digest,
                "evidence_dispositions": [asdict(item) for item in draft.evidence_dispositions],
                "explicit_concept_relations": [asdict(item) for item in plan.concept_relations],
                "relation_provenance": [asdict(item) for item in draft.concept_relations],
                "next_action": draft.next_action.strip(),
                "goal_limit_override": {
                    "requested": draft.goal_limit_override_requested,
                    "reason": draft.goal_limit_override_reason.strip(),
                },
            },
        )

    @staticmethod
    def resulting_goal_ids(
        snapshot: PlanSnapshot,
        candidate: StudyPlan,
        *,
        replaced_plan_id: str,
    ) -> tuple[str, ...]:
        plans = tuple(
            [view.plan for view in snapshot.plans if view.plan.plan_id != replaced_plan_id]
            + [candidate]
        )
        return _active_goal_ids(plans)

    @staticmethod
    def validate_decision_cas(command: DecideProposal, proposal: PersistedProposal) -> None:
        supplied = (
            command.expected_document_digest,
            command.expected_structure_digest,
            command.expected_document_revision,
            command.expected_structure_revision,
        )
        if proposal.review.mode == "create":
            if any(value not in {"", None} for value in supplied):
                raise ProposalConflictError("create decision unexpectedly supplies target CAS")
            return
        expected = (
            proposal.base_document_digest,
            proposal.base_structure_digest,
            proposal.base_document_revision,
            proposal.base_structure_revision,
        )
        if any(value in {"", None} for value in supplied) or supplied != expected:
            raise ProposalConflictError("revision decision requires the exact complete target CAS")

    @staticmethod
    def require_ready(plan: StudyPlan) -> None:
        result = lifecycle_readiness(plan)
        if not result["ready"]:
            raise LifecycleValidationError(
                "plan is not ready to activate: " + "; ".join(result["blockers"])
            )
