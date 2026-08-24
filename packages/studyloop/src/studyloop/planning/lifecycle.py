"""Authoritative application service for agentic study-plan mutations."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from markdown_it import MarkdownIt

from .contracts import (
    ActorContext,
    AuthorityError,
    Clock,
    DecideProposal,
    EvidenceValidationError,
    FoldedPlanningState,
    GoalLimitError,
    IdGenerator,
    ImportPlanDraft,
    LifecycleValidationError,
    PersistedProposal,
    PlanningBrief,
    PlanningCommand,
    PlanningInspectRef,
    PlanningRequest,
    PlanningResult,
    PlanningRunRef,
    PlanOutcome,
    ProposalConflictError,
    ProposalReview,
    RecordCheckpoint,
    RecordMilestoneOutcome,
    RecordTrustedEvidence,
    SubmitProposalDraft,
    SystemClock,
    TransitionPlanStatus,
    UuidIdGenerator,
)
from .digests import is_versioned_digest
from .evidence import EvidenceCatalogue
from .lifecycle_journal import (
    LifecycleJournalProjection,
    brief_payload,
    canonical_lifecycle_digest,
    persisted_proposal_payload,
)
from .lifecycle_proposals import ProposalPolicy, goal_set_digest
from .markdown import parse_plan, render_plan
from .models import (
    ConceptRef,
    DecisionRecord,
    EvidenceDisposition,
    EvidenceRef,
    Goal,
    LearningRecord,
    Milestone,
    PlanUnknown,
    Resource,
    StudyPlan,
)
from .repository import (
    CURRENT_PLAN_STATUSES,
    MAX_CURRENT_PLANS,
    IdempotencyConflictError,
    MutationIntent,
    PlanCapacityError,
    PlanConflictError,
    PlanningRef,
    PlanningRepository,
    PlanningView,
    PlanSnapshot,
    PrivateRunArtifact,
)

if TYPE_CHECKING:
    from .journal import JournalEvent

LIFECYCLE_SCHEMA_VERSION = 1
LIFECYCLE_POLICY_VERSION = 1
_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"active", "complete", "abandoned"}),
    "active": frozenset({"paused", "complete", "abandoned"}),
    "paused": frozenset({"active", "complete", "abandoned"}),
    "complete": frozenset(),
    "abandoned": frozenset(),
}
_ATTESTATION_CONFIRMATION = "I confirm this records my own completed practice"
_EXECUTABLE_MARKDOWN = re.compile(
    r"<\s*(?:script|iframe|object|embed)\b|javascript\s*:|\bon\w+\s*=",
    re.IGNORECASE,
)
_UNTRUSTED_IMPORT_MARKUP = re.compile(r"<!--|<\s*/?\s*[a-z][^>]*>", re.IGNORECASE)
_VERIFIED_CLAIMS = frozenset(
    {"demonstrated_skill", "verified_completion", "milestone_completion", "completed_practice"}
)


def _canonical_digest(domain: str, payload: object) -> str:
    return canonical_lifecycle_digest(domain, payload)


def _milestone_concept_ids(plan: StudyPlan, milestone: Milestone) -> set[str]:
    """Resolve legacy display-label links only when they identify one stable ID."""
    attached: set[str] = set()
    for label in {value for value in milestone.concepts if value.strip()}:
        matches = {
            concept.concept_id.strip()
            for concept in plan.concepts
            if concept.concept_id.strip() and concept.display_label == label
        }
        if len(matches) != 1:
            raise EvidenceValidationError(
                f"milestone has ambiguous concept label {label!r}; expected exactly one stable ID"
            )
        attached.update(matches)
    return attached


def _evidence_matches_milestone(item: EvidenceRef, plan: StudyPlan, milestone: Milestone) -> bool:
    """Require both a completion claim and a subject tied to this milestone."""
    if item.claim_kind not in _VERIFIED_CLAIMS:
        return False
    subject = item.subject_ref.strip()
    milestone_id = milestone.milestone_id.strip()
    exact_subjects = {
        f"milestone:{milestone_id}",
        f"plan:{plan.plan_id}/milestone:{milestone_id}",
    }
    if subject in exact_subjects:
        return True
    if not subject.startswith("concept:"):
        return False
    concept_id = subject.removeprefix("concept:").strip()
    if not concept_id:
        return False
    return concept_id in _milestone_concept_ids(plan, milestone)


def _contains_mermaid_fence(markdown: str) -> bool:
    """Reject actual CommonMark Mermaid fence tokens, including containers."""
    return any(
        token.type == "fence" and token.info.strip().split(maxsplit=1)[0].casefold() == "mermaid"
        for token in MarkdownIt("commonmark").parse(markdown)
        if token.info.strip()
    )


def _request_digest(request: PlanningRequest) -> str:
    return _canonical_digest(
        "studyloop.planning-request",
        {
            "mode": request.mode,
            "brain_dump_exact": request.brain_dump,
            "plan_id": request.plan_id.strip(),
            "source_references": [
                asdict(item)
                for item in sorted(
                    request.source_references,
                    key=lambda item: (
                        item.reference_id,
                        item.source_kind,
                        item.label,
                        item.content_digest,
                    ),
                )
            ],
            "evidence_ids": sorted(request.evidence_ids),
        },
    )


def _snapshot_context(snapshot: PlanSnapshot) -> list[dict[str, object]]:
    return [
        {
            "plan_id": view.plan.plan_id,
            "status": view.plan.status,
            "document_digest": view.document_digest,
            "structure_digest": view.structure_digest,
            "document_revision": view.plan.document_revision,
            "structure_revision": view.plan.structure_revision,
        }
        for view in sorted(snapshot.plans, key=lambda item: item.plan.plan_id)
        if view.plan.status in CURRENT_PLAN_STATUSES
    ]


def _brief_context_digest(
    request: PlanningRequest,
    snapshot: PlanSnapshot,
    evidence: tuple[EvidenceRef, ...],
) -> str:
    active_ids = tuple(sorted(set(snapshot.active_goal_ids)))
    return _canonical_digest(
        "studyloop.planning-brief-context",
        {
            "schema_version": LIFECYCLE_SCHEMA_VERSION,
            "policy_version": LIFECYCLE_POLICY_VERSION,
            "request": {
                "mode": request.mode,
                "brain_dump_exact": request.brain_dump,
                "plan_id": request.plan_id.strip(),
            },
            "current_plans": _snapshot_context(snapshot),
            "active_goal_ids": list(active_ids),
            "active_goal_set_digest": goal_set_digest(active_ids),
            "evidence": [
                asdict(item) for item in sorted(evidence, key=lambda item: item.evidence_id)
            ],
            "source_references": [
                asdict(item)
                for item in sorted(request.source_references, key=lambda item: item.reference_id)
            ],
        },
    )


def _find_view(snapshot: PlanSnapshot, plan_id: str) -> PlanningView | None:
    return next((view for view in snapshot.plans if view.plan.plan_id == plan_id), None)


class PlanningLifecycle:
    """Sole application seam for normal plan preparation and mutation."""

    def __init__(
        self,
        repository: PlanningRepository,
        *,
        clock: Clock | None = None,
        ids: IdGenerator | None = None,
        evidence: EvidenceCatalogue | None = None,
    ) -> None:
        self.repository = repository
        self.clock = clock or SystemClock()
        self.ids = ids or UuidIdGenerator()
        self.evidence = evidence or EvidenceCatalogue()
        self._journal_projection = LifecycleJournalProjection(repository)
        self._proposal_policy = ProposalPolicy(self.ids, self.clock)

    def prepare(self, request: PlanningRequest, actor: ActorContext) -> PlanningBrief:
        """Capture an exact learner dump and issue a deterministic planning brief."""
        self._require_actor(actor, {"model", "learner"}, "planning preparation")
        self._validate_request(request)
        digest = _request_digest(request)
        snapshot, state = self.repository.project(
            lambda current, events: (current, self._fold(events))
        )
        key = (actor.actor_id, request.idempotency_key)
        prior = state.request_keys.get(key)
        if prior is not None:
            prior_digest, run_id = prior
            if prior_digest != digest:
                raise IdempotencyConflictError(
                    "idempotency key was already used for a different planning request"
                )
            return state.briefs_by_run[run_id]

        if request.mode == "create" and snapshot.current_count >= MAX_CURRENT_PLANS:
            raise PlanCapacityError(
                f"maximum of {MAX_CURRENT_PLANS} current plans reached; "
                "complete or abandon one before creating another"
            )
        target = _find_view(snapshot, request.plan_id) if request.mode == "revise" else None
        if request.mode == "revise" and target is None:
            raise PlanConflictError(f"no study plan with id {request.plan_id!r}")
        if target is not None and target.plan.status in {"complete", "abandoned"}:
            raise LifecycleValidationError(
                f"terminal plan {request.plan_id!r} cannot be structurally revised"
            )
        if target is not None and (
            any(not item.goal_id.strip() for item in target.plan.goals)
            or any(not item.concept_id.strip() for item in target.plan.concepts)
            or any(not item.milestone_id.strip() for item in target.plan.milestones)
        ):
            raise LifecycleValidationError(
                "legacy plan lacks stable entity identities; repair identities losslessly "
                "before structural revision"
            )

        offered = self.evidence.offered(request.evidence_ids)
        context_digest = _brief_context_digest(request, snapshot, offered)
        run_id = self.ids.new_id("run")
        known_resources = tuple(
            Resource(**payload)
            for payload in {
                json.dumps(asdict(resource), sort_keys=True): asdict(resource)
                for view in snapshot.plans
                if view.plan.status in CURRENT_PLAN_STATUSES
                for resource in view.plan.resources
            }.values()
        )
        configured_topics = tuple(
            sorted(
                {
                    topic
                    for view in snapshot.plans
                    if view.plan.status in CURRENT_PLAN_STATUSES
                    for topic in view.plan.topics
                    if topic.strip()
                }
            )
        )
        unresolved_gaps = (
            tuple(item.question for item in target.plan.unknowns if item.status == "open")
            if target
            else ()
        )
        brief = PlanningBrief(
            schema_version=LIFECYCLE_SCHEMA_VERSION,
            policy_version=LIFECYCLE_POLICY_VERSION,
            run_id=run_id,
            mode=request.mode,
            raw_brain_dump=request.brain_dump,
            request_digest=digest,
            brief_context_digest=context_digest,
            plan_id=request.plan_id,
            target_document_digest=target.document_digest if target else "",
            target_structure_digest=target.structure_digest if target else "",
            target_document_revision=target.plan.document_revision if target else None,
            target_structure_revision=target.plan.structure_revision if target else None,
            target_plan=copy.deepcopy(target.plan) if target else None,
            current_count=snapshot.current_count,
            max_current=MAX_CURRENT_PLANS,
            active_goal_ids=tuple(sorted(set(snapshot.active_goal_ids))),
            active_goal_set_digest=goal_set_digest(tuple(sorted(set(snapshot.active_goal_ids)))),
            evidence=offered,
            source_references=request.source_references,
            known_resources=known_resources,
            configured_topics=configured_topics,
            unresolved_gaps=unresolved_gaps,
            invariants=(
                "At most three current plans",
                "At most three active goals unless the learner approves the exact goal set",
                "Tier-four context never proves progress or completion",
                "Structural changes require learner approval of the exact proposal digest",
            ),
            created_at=self.clock.now(),
        )
        brain_digest = _canonical_digest(
            "studyloop.private-brain-dump", {"content_exact": request.brain_dump}
        )
        metadata: dict[str, object] = {
            "lifecycle": {
                "type": "run_captured",
                "actor_id": actor.actor_id,
                "request_key": request.idempotency_key,
                "request_digest": digest,
                "brain_dump_artifact": "brain-dump.txt",
                "brain_dump_digest": brain_digest,
                "brief": brief_payload(brief, include_raw=False),
            }
        }

        def guard(current: PlanSnapshot, _events, _intent) -> None:
            if request.mode == "create" and current.current_count >= MAX_CURRENT_PLANS:
                raise PlanCapacityError(
                    f"maximum of {MAX_CURRENT_PLANS} current plans reached before capture"
                )
            if _brief_context_digest(request, current, offered) != context_digest:
                raise PlanConflictError("planning context changed while capturing the request")

        committed = self.repository.commit(
            MutationIntent(
                intent_id=self.ids.new_id("intent"),
                caller=actor.actor_id,
                idempotency_key=f"prepare:{request.idempotency_key}",
                idempotency_digest=digest,
                operation="journal",
                ref=PlanningRef(run_id),
                metadata=metadata,
                private_artifacts=(
                    PrivateRunArtifact(run_id, "brain-dump.txt", request.brain_dump),
                ),
            ),
            guard=guard,
        )
        if committed.status == "replayed":
            current = self.repository.project(lambda _snapshot, events: self._fold(events))
            _, winning_run_id = current.request_keys[key]
            return current.briefs_by_run[winning_run_id]
        return brief

    def inspect(self, ref: PlanningInspectRef) -> PlanningResult:
        """Inspect a plan or a journal-folded planning run/proposal."""
        if isinstance(ref, PlanningRef):
            return self.repository.inspect(ref)
        state = self.repository.project(lambda _snapshot, events: self._fold(events))
        if isinstance(ref, PlanningRunRef):
            try:
                return state.briefs_by_run[ref.run_id]
            except KeyError as error:
                raise PlanConflictError(f"no planning run with id {ref.run_id!r}") from error
        try:
            return state.proposals_by_id[ref.proposal_id].review
        except KeyError as error:
            raise PlanConflictError(f"no proposal with id {ref.proposal_id!r}") from error

    def handle(self, command: PlanningCommand) -> PlanningResult:
        """Dispatch one member of the closed planning command union."""
        payload = command.payload
        if isinstance(payload, SubmitProposalDraft):
            return self._submit(payload, command.actor)
        if isinstance(payload, DecideProposal):
            return self._decide(payload, command.actor)
        if isinstance(payload, RecordTrustedEvidence):
            return self._record_evidence(payload, command.actor)
        if isinstance(payload, RecordCheckpoint):
            return self._record_checkpoint(payload, command.actor)
        if isinstance(payload, RecordMilestoneOutcome):
            return self._record_milestone_outcome(payload, command.actor)
        if isinstance(payload, TransitionPlanStatus):
            return self._transition(payload, command.actor)
        if isinstance(payload, ImportPlanDraft):
            return self._import(payload, command.actor)
        raise LifecycleValidationError(f"unsupported planning command {type(payload).__name__}")

    def is_goal_override_valid(self, override_digest: str) -> bool:
        """Return whether an audited override matches the exact current goal set."""
        if not override_digest:
            return False
        snapshot, state = self.repository.project(
            lambda current, events: (current, self._fold(events))
        )
        recorded_ids = state.valid_goal_overrides.get(override_digest)
        current_ids = tuple(sorted(set(snapshot.active_goal_ids)))
        return (
            recorded_ids is not None
            and recorded_ids == current_ids
            and override_digest == goal_set_digest(current_ids)
        )

    def _submit(self, command: SubmitProposalDraft, actor: ActorContext) -> ProposalReview:
        self._require_actor(actor, {"model"}, "proposal submission")
        snapshot, state = self.repository.project(
            lambda current, events: (current, self._fold(events))
        )
        try:
            brief = state.briefs_by_run[command.run_id]
        except KeyError as error:
            raise ProposalConflictError(f"unknown planning run {command.run_id!r}") from error
        input_digest = _canonical_digest(
            "studyloop.proposal-draft-input",
            {
                "run_id": command.run_id,
                "brief_context_digest": command.brief_context_digest,
                "draft": asdict(command.draft),
            },
        )
        key = (actor.actor_id, command.idempotency_key)
        prior = state.proposal_keys.get(key)
        if prior is not None:
            prior_digest, proposal_id = prior
            if prior_digest != input_digest:
                raise IdempotencyConflictError(
                    "idempotency key was already used for a different proposal draft"
                )
            return state.proposals_by_id[proposal_id].review
        if command.brief_context_digest != brief.brief_context_digest:
            raise ProposalConflictError("proposal does not match the issued brief context digest")
        self._assert_brief_current(brief, snapshot)
        self._proposal_policy.validate_draft(command.draft, brief)

        proposal_id = self.ids.new_id("proposal")
        plan, alias_mapping = self._proposal_policy.assign_plan(command.draft, brief, snapshot)
        resulting_ids = self._proposal_policy.resulting_goal_ids(
            snapshot, plan, replaced_plan_id=brief.plan_id
        )
        resulting_digest = goal_set_digest(resulting_ids)
        proposal_digest = self._proposal_policy.proposal_digest(
            brief,
            command.draft,
            plan,
            alias_mapping,
            resulting_ids,
            resulting_digest,
        )
        prior_proposal = state.latest_proposal_by_run.get(command.run_id, "")
        review = ProposalReview(
            proposal_id=proposal_id,
            run_id=command.run_id,
            proposal_digest=proposal_digest,
            brief_context_digest=brief.brief_context_digest,
            mode=brief.mode,
            plan_preview=plan,
            markdown_preview=render_plan(plan),
            alias_mapping=tuple(sorted(alias_mapping.items())),
            resulting_active_goal_ids=resulting_ids,
            resulting_active_goal_set_digest=resulting_digest,
            supersedes_proposal_id=prior_proposal,
            created_at=self.clock.now(),
        )
        persisted = PersistedProposal(
            review=review,
            base_document_digest=brief.target_document_digest,
            base_structure_digest=brief.target_structure_digest,
            base_document_revision=brief.target_document_revision,
            base_structure_revision=brief.target_structure_revision,
            requested_status=command.draft.requested_status,
            evidence_dispositions=command.draft.evidence_dispositions,
            explicit_relations=tuple(plan.concept_relations),
            next_action=command.draft.next_action,
            goal_limit_override_requested=command.draft.goal_limit_override_requested,
            goal_limit_override_reason=command.draft.goal_limit_override_reason,
        )
        proposal_payload = persisted_proposal_payload(persisted)
        artifact_text = json.dumps(proposal_payload, ensure_ascii=False, sort_keys=True)
        metadata: dict[str, object] = {
            "lifecycle": {
                "type": "proposal_issued",
                "actor_id": actor.actor_id,
                "command_key": command.idempotency_key,
                "input_digest": input_digest,
                "artifact_digest": _canonical_digest(
                    "studyloop.private-proposal", {"content_exact": artifact_text}
                ),
                "proposal_id": proposal_id,
                "run_id": command.run_id,
                "proposal_artifact": f"{proposal_id}.json",
            }
        }

        def guard(current: PlanSnapshot, events: tuple[JournalEvent, ...], _intent) -> None:
            current_state = self._fold(events)
            if command.run_id not in current_state.briefs_by_run:
                raise ProposalConflictError("planning run disappeared before proposal submission")
            self._assert_brief_current(brief, current)
            decision = current_state.decisions_by_proposal.get(prior_proposal)
            if prior_proposal and decision is not None:
                raise ProposalConflictError("planning run already has a terminal proposal decision")

        committed = self.repository.commit(
            MutationIntent(
                intent_id=self.ids.new_id("intent"),
                caller=actor.actor_id,
                idempotency_key=f"proposal:{command.idempotency_key}",
                idempotency_digest=input_digest,
                operation="journal",
                ref=PlanningRef(plan.plan_id),
                metadata=metadata,
                private_artifacts=(
                    PrivateRunArtifact(
                        command.run_id,
                        f"{proposal_id}.json",
                        artifact_text,
                    ),
                ),
            ),
            guard=guard,
        )
        if committed.status == "replayed":
            current = self.repository.project(lambda _snapshot, events: self._fold(events))
            _, winning_proposal_id = current.proposal_keys[key]
            return current.proposals_by_id[winning_proposal_id].review
        return review

    def _decide(self, command: DecideProposal, actor: ActorContext) -> PlanOutcome:
        self._require_actor(actor, {"learner"}, "proposal decisions require learner authority")
        if command.decision not in {"approve", "reject"}:
            raise LifecycleValidationError("decision must be 'approve' or 'reject'")
        snapshot, state = self.repository.project(
            lambda current, events: (current, self._fold(events))
        )
        input_digest = _canonical_digest("studyloop.proposal-decision-input", asdict(command))
        key = (actor.actor_id, command.idempotency_key)
        prior = state.decision_keys.get(key)
        if prior is not None:
            prior_digest, outcome = prior
            if prior_digest != input_digest:
                raise IdempotencyConflictError(
                    "idempotency key was already used for a different proposal decision"
                )
            return outcome
        proposal = self._open_proposal(state, command.proposal_id)
        review = proposal.review
        if command.proposal_digest != review.proposal_digest:
            raise ProposalConflictError("decision proposal digest does not match issued proposal")
        latest = state.latest_proposal_by_run.get(review.run_id)
        if latest != review.proposal_id:
            raise ProposalConflictError(
                f"proposal {review.proposal_id!r} was superseded by {latest!r}"
            )
        brief = state.briefs_by_run[review.run_id]
        self._proposal_policy.validate_decision_cas(command, proposal)
        if command.decision == "reject":
            outcome = PlanOutcome("rejected", review.plan_preview.plan_id, review.proposal_id)
            metadata = self._decision_metadata(actor, command, input_digest, outcome)

            def rejection_guard(
                current_snapshot: PlanSnapshot,
                events: tuple[JournalEvent, ...],
                _intent,
            ) -> None:
                current = self._fold(events)
                self._open_proposal(current, command.proposal_id)
                if current.latest_proposal_by_run.get(review.run_id) != review.proposal_id:
                    raise ProposalConflictError("a newer proposal superseded this rejection")
                self._assert_brief_current(brief, current_snapshot)

            committed = self.repository.commit(
                MutationIntent(
                    intent_id=self.ids.new_id("intent"),
                    caller=actor.actor_id,
                    idempotency_key=f"decision:{command.idempotency_key}",
                    idempotency_digest=input_digest,
                    operation="journal",
                    ref=PlanningRef(review.plan_preview.plan_id),
                    metadata=metadata,
                ),
                guard=rejection_guard,
            )
            if committed.status == "replayed":
                return self._decision_replay(actor, command.idempotency_key, input_digest)
            return outcome

        plan = copy.deepcopy(review.plan_preview)
        for relation in plan.concept_relations:
            relation.decided_by = "learner"
        decision_reason = command.reason.strip()
        goal_ids = self._proposal_policy.resulting_goal_ids(
            snapshot, plan, replaced_plan_id=brief.plan_id
        )
        goal_digest = goal_set_digest(goal_ids)
        override_digest = ""
        if len(goal_ids) > 3:
            if not proposal.goal_limit_override_requested or not decision_reason:
                raise GoalLimitError("more than 3 active goals requires an explicit learner reason")
            override_digest = goal_digest
        if plan.status == "active":
            self._proposal_policy.require_ready(plan)
        decision_id = self.ids.new_id("decision")
        readable_reason = decision_reason
        if override_digest:
            readable_reason = f"Rule of Three override for {override_digest}: {decision_reason}"
        plan.decisions.append(
            DecisionRecord(
                decision_id=decision_id,
                proposal_id=review.proposal_id,
                outcome="approve",
                actor_kind="learner",
                channel=actor.channel,
                reason=readable_reason,
                decided_at=self.clock.now(),
            )
        )
        plan.updated = self.clock.now()
        outcome = PlanOutcome(
            "applied",
            plan.plan_id,
            review.proposal_id,
            goal_limit_override_digest=override_digest,
        )
        metadata = self._decision_metadata(
            actor,
            command,
            input_digest,
            outcome,
            active_goal_ids=goal_ids,
            active_goal_set_digest=goal_digest,
            override_reason=decision_reason if override_digest else "",
        )

        def approval_guard(
            current: PlanSnapshot,
            events: tuple[JournalEvent, ...],
            _intent,
        ) -> None:
            current_state = self._fold(events)
            self._open_proposal(current_state, command.proposal_id)
            latest_id = current_state.latest_proposal_by_run.get(review.run_id)
            if latest_id != review.proposal_id:
                raise ProposalConflictError("a newer proposal superseded this approval")
            self._assert_brief_current(brief, current)
            current_goal_ids = self._proposal_policy.resulting_goal_ids(
                current, plan, replaced_plan_id=brief.plan_id
            )
            if current_goal_ids != goal_ids:
                raise ProposalConflictError("active goal set changed before approval")
            if len(current_goal_ids) > 3 and not override_digest:
                raise GoalLimitError("approval would exceed 3 active goals")
            if len(current_goal_ids) > 3 and override_digest != goal_set_digest(current_goal_ids):
                raise GoalLimitError("Rule of Three override no longer matches the exact goal set")

        intent = MutationIntent(
            intent_id=self.ids.new_id("intent"),
            caller=actor.actor_id,
            idempotency_key=f"decision:{command.idempotency_key}",
            idempotency_digest=input_digest,
            operation="create" if brief.mode == "create" else "update",
            plan=plan,
            expected_document_digest=proposal.base_document_digest,
            expected_structure_digest=proposal.base_structure_digest,
            expected_document_revision=proposal.base_document_revision,
            expected_structure_revision=proposal.base_structure_revision,
            metadata=metadata,
        )
        committed = self.repository.commit(intent, guard=approval_guard)
        if committed.status == "replayed":
            return self._decision_replay(actor, command.idempotency_key, input_digest)
        return PlanOutcome(
            "applied",
            plan.plan_id,
            review.proposal_id,
            committed.document_digest or "",
            committed.structure_digest or "",
            committed.document_revision,
            committed.structure_revision,
            override_digest,
        )

    def _record_evidence(self, command: RecordTrustedEvidence, actor: ActorContext) -> PlanOutcome:
        self._require_actor(actor, {"recorder"}, "trusted evidence recording")
        input_digest = _canonical_digest("studyloop.lifecycle-command", asdict(command))
        replay = self._direct_replay(actor, command.idempotency_key, input_digest)
        if replay is not None:
            return replay
        evidence = self.evidence.resolve(command.evidence_ids)
        view = self.repository.inspect(PlanningRef(command.plan_id))
        plan = copy.deepcopy(view.plan)
        existing = {item.evidence_id: item for item in plan.evidence}
        for item in evidence:
            prior = existing.get(item.evidence_id)
            if prior is not None and prior != item:
                raise EvidenceValidationError(
                    f"plan evidence {item.evidence_id!r} has conflicting provenance"
                )
            if prior is None:
                plan.evidence.append(item)
        plan.updated = self.clock.now()
        return self._commit_direct_update(
            plan,
            view,
            actor,
            command.idempotency_key,
            "trusted_evidence_recorded",
            {"evidence_ids": list(command.evidence_ids)},
            status="recorded",
            input_digest=input_digest,
        )

    def _record_checkpoint(self, command: RecordCheckpoint, actor: ActorContext) -> PlanOutcome:
        self._require_actor(actor, {"recorder"}, "checkpoint recording")
        input_digest = _canonical_digest("studyloop.lifecycle-command", asdict(command))
        replay = self._direct_replay(actor, command.idempotency_key, input_digest)
        if replay is not None:
            return replay
        view = self.repository.inspect(PlanningRef(command.plan_id))
        plan = copy.deepcopy(view.plan)
        plan.checkpoints.append(command.checkpoint)
        plan.updated = self.clock.now()
        return self._commit_direct_update(
            plan,
            view,
            actor,
            command.idempotency_key,
            "checkpoint_recorded",
            {"checkpoint": asdict(command.checkpoint)},
            status="recorded",
            input_digest=input_digest,
        )

    def _record_milestone_outcome(
        self, command: RecordMilestoneOutcome, actor: ActorContext
    ) -> PlanOutcome:
        if command.outcome == "verified_complete":
            self._require_actor(actor, {"recorder"}, "verified milestone completion")
        elif command.outcome == "learner_attested":
            self._require_actor(actor, {"learner"}, "learner milestone attestation")
            if not command.reason.strip() or command.confirmation != _ATTESTATION_CONFIRMATION:
                raise EvidenceValidationError(
                    "learner attestation requires a milestone-specific reason "
                    "and explicit confirmation"
                )
        elif command.outcome == "incomplete":
            self._require_actor(actor, {"learner", "recorder"}, "milestone outcome")
        else:  # pragma: no cover - typed callers cannot construct this honestly
            raise LifecycleValidationError(f"unsupported milestone outcome {command.outcome!r}")

        input_digest = _canonical_digest("studyloop.lifecycle-command", asdict(command))
        replay = self._direct_replay(actor, command.idempotency_key, input_digest)
        if replay is not None:
            return replay
        evidence = self.evidence.resolve(command.evidence_ids)
        if command.outcome == "verified_complete" and (
            not evidence or any(item.tier != 1 for item in evidence)
        ):
            raise EvidenceValidationError(
                "verified milestone completion requires at least one tier 1 evidence item"
            )
        if command.outcome == "learner_attested" and (
            not evidence or any(item.tier != 3 for item in evidence)
        ):
            raise EvidenceValidationError("learner attestation requires tier 3 self-report")

        view = self.repository.inspect(PlanningRef(command.plan_id))
        plan = copy.deepcopy(view.plan)
        dispositions = {item.evidence_id: item.disposition for item in plan.evidence_dispositions}
        not_selected = [
            item.evidence_id
            for item in evidence
            if dispositions.get(item.evidence_id) != "selected"
        ]
        if not_selected:
            raise EvidenceValidationError(
                f"milestone outcomes require selected evidence; not selected: {not_selected}"
            )
        milestone = next(
            (item for item in plan.milestones if item.milestone_id == command.milestone_id),
            None,
        )
        if milestone is None:
            raise LifecycleValidationError(f"unknown milestone {command.milestone_id!r}")
        if command.outcome == "verified_complete":
            # Legacy milestones still store display labels. Even evidence that
            # names the milestone directly must not commit completion while
            # any of those labels has a missing or ambiguous stable identity.
            _milestone_concept_ids(plan, milestone)
            irrelevant = [
                item.evidence_id
                for item in evidence
                if not _evidence_matches_milestone(item, plan, milestone)
            ]
            if irrelevant:
                raise EvidenceValidationError(
                    "tier 1 evidence must carry a completion claim for the target milestone; "
                    f"irrelevant evidence: {irrelevant}"
                )
        if command.outcome == "verified_complete":
            milestone.done = True
            title = f"Verified milestone completion: {milestone.title}"
        elif command.outcome == "learner_attested":
            title = f"Learner-attested milestone outcome: {milestone.title}"
        else:
            milestone.done = False
            title = f"Milestone remains incomplete: {milestone.title}"
        plan.learning_records.append(
            LearningRecord(
                number=max((item.number for item in plan.learning_records), default=0) + 1,
                title=title,
                body=(
                    f"Outcome: {command.outcome}. Evidence: {', '.join(command.evidence_ids)}. "
                    f"Reason: {command.reason.strip()}"
                ).strip(),
            )
        )
        plan.updated = self.clock.now()
        return self._commit_direct_update(
            plan,
            view,
            actor,
            command.idempotency_key,
            "milestone_outcome_recorded",
            {
                "milestone_id": command.milestone_id,
                "outcome": command.outcome,
                "evidence_ids": list(command.evidence_ids),
            },
            status=command.outcome,
            input_digest=input_digest,
        )

    def _transition(self, command: TransitionPlanStatus, actor: ActorContext) -> PlanOutcome:
        self._require_actor(actor, {"learner"}, "plan status transitions require learner authority")
        input_digest = _canonical_digest("studyloop.lifecycle-command", asdict(command))
        replay = self._direct_replay(actor, command.idempotency_key, input_digest)
        if replay is not None:
            return replay
        view = self.repository.inspect(PlanningRef(command.plan_id))
        current = view.plan.status
        if current in {"complete", "abandoned"}:
            raise LifecycleValidationError(f"terminal status {current!r} cannot transition")
        if command.status not in _TRANSITIONS[current]:
            raise LifecycleValidationError(
                f"invalid plan status transition {current!r} -> {command.status!r}"
            )
        plan = copy.deepcopy(view.plan)
        plan.status = command.status
        plan.updated = self.clock.now()
        if plan.status == "active":
            self._proposal_policy.require_ready(plan)

        def guard(snapshot: PlanSnapshot, _events, _intent) -> None:
            ids = self._proposal_policy.resulting_goal_ids(
                snapshot, plan, replaced_plan_id=plan.plan_id
            )
            if len(ids) > 3:
                raise GoalLimitError("activation would exceed 3 active goals")

        return self._commit_direct_update(
            plan,
            view,
            actor,
            command.idempotency_key,
            "plan_status_transitioned",
            {"from": current, "to": command.status, "reason": command.reason},
            status="transitioned",
            input_digest=input_digest,
            guard=guard,
        )

    def _import(self, command: ImportPlanDraft, actor: ActorContext) -> PlanOutcome:
        self._require_actor(actor, {"learner"}, "plan import requires learner authority")
        input_digest = _canonical_digest("studyloop.lifecycle-command", asdict(command))
        replay = self._direct_replay(actor, command.idempotency_key, input_digest)
        if replay is not None:
            return replay
        if not command.markdown.strip():
            raise LifecycleValidationError("imported Markdown cannot be empty")
        if _EXECUTABLE_MARKDOWN.search(command.markdown):
            raise LifecycleValidationError("imported Markdown contains executable content")
        if _UNTRUSTED_IMPORT_MARKUP.search(command.markdown) or _contains_mermaid_fence(
            command.markdown
        ):
            raise LifecycleValidationError(
                "imported Markdown contains untrusted markup; "
                "foreign Mermaid, raw HTML, and concealed instructions are not accepted"
            )
        parsed = parse_plan(command.markdown)
        now = self.clock.now()
        plan_id = self.ids.new_id("plan")
        goal_mapping: dict[str, str] = {}
        goals: list[Goal] = []
        for item in parsed.goals:
            fresh = self.ids.new_id("goal")
            if item.goal_id:
                goal_mapping[item.goal_id] = fresh
            goals.append(Goal(fresh, item.title, item.reason, item.alignment_rationale, "active"))
        if not goals and parsed.milestones:
            fresh = self.ids.new_id("goal")
            goals.append(Goal(fresh, "Imported learning goal", "Imported context", "Review needed"))
        concepts = [
            ConceptRef(self.ids.new_id("concept"), item.display_label) for item in parsed.concepts
        ]
        concepts_by_label: dict[str, list[ConceptRef]] = {}
        for concept in concepts:
            concepts_by_label.setdefault(concept.display_label, []).append(concept)

        milestones: list[Milestone] = []
        for item in parsed.milestones:
            for label in {value for value in item.concepts if value.strip()}:
                matches = concepts_by_label.get(label, [])
                if len(matches) > 1:
                    raise LifecycleValidationError(
                        f"imported milestone has ambiguous concept label {label!r}"
                    )
                if not matches:
                    generated = ConceptRef(self.ids.new_id("concept"), label)
                    concepts.append(generated)
                    concepts_by_label[label] = [generated]
            goal_id = goal_mapping.get(item.goal_id, goals[0].goal_id if goals else "")
            milestones.append(
                Milestone(
                    item.title,
                    done=False,
                    concepts=list(item.concepts),
                    notes=item.notes,
                    milestone_id=self.ids.new_id("milestone"),
                    goal_id=goal_id,
                )
            )
        unknowns = [
            PlanUnknown(self.ids.new_id("unknown"), item.question, item.impact, "open")
            for item in parsed.unknowns
        ]
        import_evidence = EvidenceRef(
            evidence_id=self.ids.new_id("evidence"),
            source_kind="imported_plan",
            source_native_id=plan_id,
            source_revision="1",
            observed_at=now,
            ingested_at=now,
            tier=4,
            claim_kind="curriculum_context",
            subject_ref=f"plan:{plan_id}",
            provenance_digest=_canonical_digest(
                "studyloop.imported-plan", {"markdown_exact": command.markdown}
            ),
        )
        plan = StudyPlan(
            plan_id=plan_id,
            title=parsed.title,
            status="draft",
            created=now,
            updated=now,
            topics=list(parsed.topics),
            energy_floor=parsed.energy_floor,
            target_date=parsed.target_date,
            review_cadence_days=parsed.review_cadence_days,
            mission=parsed.mission,
            next_action=parsed.next_action,
            goals=goals,
            milestones=milestones,
            concepts=concepts,
            concept_relations=[],
            unknowns=unknowns,
            resources=list(parsed.resources),
            evidence=[import_evidence],
            evidence_dispositions=[
                EvidenceDisposition(
                    import_evidence.evidence_id,
                    "unresolved",
                    "Imported material is tier-4 context and needs learner review",
                )
            ],
            # Generic parsed notes may include unknown headings, foreign
            # Mermaid, or evidence-shaped prose. Imported documents are
            # untrusted curriculum context, so only typed recognised fields
            # cross this boundary in release one.
            notes="",
            decisions=[
                DecisionRecord(
                    self.ids.new_id("decision"),
                    "import",
                    "import_draft",
                    "learner",
                    actor.channel,
                    "Imported as untrusted draft context; completion claims stripped",
                    now,
                )
            ],
        )
        provisional = PlanOutcome("imported", plan_id)
        metadata: dict[str, object] = {
            "lifecycle": {
                "type": "plan_imported",
                "actor_id": actor.actor_id,
                "command_key": command.idempotency_key,
                "input_digest": input_digest,
                "outcome": asdict(provisional),
            }
        }

        def import_guard(snapshot: PlanSnapshot, _events, _intent) -> None:
            if snapshot.current_count >= 3:
                raise PlanCapacityError("cannot import: maximum of 3 current plans reached")

        committed = self.repository.commit(
            MutationIntent(
                intent_id=self.ids.new_id("intent"),
                caller=actor.actor_id,
                idempotency_key=f"import:{command.idempotency_key}",
                idempotency_digest=input_digest,
                operation="create",
                plan=plan,
                metadata=metadata,
            ),
            guard=import_guard,
        )
        if committed.status == "replayed":
            replay = self._direct_replay(actor, command.idempotency_key, input_digest)
            if replay is None:  # pragma: no cover - repository/journal invariant
                raise PlanConflictError("replayed import outcome is missing from the journal")
            return replay
        self.evidence.add_trusted(import_evidence)
        return PlanOutcome(
            "imported",
            plan_id,
            document_digest=committed.document_digest or "",
            structure_digest=committed.structure_digest or "",
            document_revision=committed.document_revision,
            structure_revision=committed.structure_revision,
        )

    def _commit_direct_update(
        self,
        plan: StudyPlan,
        view: PlanningView,
        actor: ActorContext,
        idempotency_key: str,
        event_type: str,
        details: dict[str, object],
        *,
        status: Any,
        input_digest: str,
        guard=None,
    ) -> PlanOutcome:
        provisional = PlanOutcome(status, plan.plan_id)
        metadata: dict[str, object] = {
            "lifecycle": {
                "type": event_type,
                "actor_id": actor.actor_id,
                "command_key": idempotency_key,
                "input_digest": input_digest,
                "details": details,
                "outcome": asdict(provisional),
            }
        }
        result = self.repository.commit(
            MutationIntent(
                intent_id=self.ids.new_id("intent"),
                caller=actor.actor_id,
                idempotency_key=f"{event_type}:{idempotency_key}",
                idempotency_digest=input_digest,
                operation="update",
                plan=plan,
                expected_document_digest=view.document_digest,
                expected_structure_digest=view.structure_digest,
                expected_document_revision=view.plan.document_revision,
                expected_structure_revision=view.plan.structure_revision,
                metadata=metadata,
            ),
            guard=guard,
        )
        if result.status == "replayed":
            replay = self._direct_replay(actor, idempotency_key, input_digest)
            if replay is None:  # pragma: no cover - repository/journal invariant
                raise PlanConflictError("replayed command outcome is missing from the journal")
            return replay
        return PlanOutcome(
            status,
            plan.plan_id,
            document_digest=result.document_digest or "",
            structure_digest=result.structure_digest or "",
            document_revision=result.document_revision,
            structure_revision=result.structure_revision,
        )

    def _direct_replay(
        self,
        actor: ActorContext,
        idempotency_key: str,
        input_digest: str,
    ) -> PlanOutcome | None:
        state = self.repository.project(lambda _snapshot, events: self._fold(events))
        prior = state.command_keys.get((actor.actor_id, idempotency_key))
        if prior is None:
            return None
        prior_digest, outcome = prior
        if prior_digest != input_digest:
            raise IdempotencyConflictError(
                "idempotency key was already used for a different lifecycle command"
            )
        return outcome

    def _decision_replay(
        self,
        actor: ActorContext,
        idempotency_key: str,
        input_digest: str,
    ) -> PlanOutcome:
        state = self.repository.project(lambda _snapshot, events: self._fold(events))
        prior = state.decision_keys.get((actor.actor_id, idempotency_key))
        if prior is None:  # pragma: no cover - repository/journal invariant
            raise PlanConflictError("replayed decision outcome is missing from the journal")
        prior_digest, outcome = prior
        if prior_digest != input_digest:  # pragma: no cover - repository checked under lock
            raise IdempotencyConflictError(
                "idempotency key was already used for a different proposal decision"
            )
        return outcome

    def _validate_request(self, request: PlanningRequest) -> None:
        if request.mode not in {"create", "revise"}:
            raise LifecycleValidationError("planning mode must be 'create' or 'revise'")
        if request.mode == "create" and not request.brain_dump.strip():
            raise LifecycleValidationError("a brain dump is required for plan creation")
        if request.mode == "revise" and not request.plan_id.strip():
            raise LifecycleValidationError("plan_id is required for plan revision")
        if not request.idempotency_key.strip():
            raise LifecycleValidationError("planning request idempotency key is required")
        for item in request.source_references:
            if not item.reference_id.strip() or not is_versioned_digest(item.content_digest):
                raise LifecycleValidationError(
                    "source references require an id and versioned content digest"
                )

    @staticmethod
    def _require_actor(actor: ActorContext, allowed: set[str], action: str) -> None:
        if actor.actor_kind not in allowed:
            expected = " or ".join(sorted(allowed))
            raise AuthorityError(f"{action} requires {expected} authority")

    def _assert_brief_current(self, brief: PlanningBrief, snapshot: PlanSnapshot) -> None:
        request = PlanningRequest(
            brief.mode,
            brief.raw_brain_dump,
            "projection-only",
            brief.plan_id,
            brief.source_references,
            tuple(item.evidence_id for item in brief.evidence),
        )
        offered = self.evidence.resolve(item.evidence_id for item in brief.evidence)
        if offered != brief.evidence:
            raise ProposalConflictError("offered evidence provenance changed")
        current = _brief_context_digest(request, snapshot, offered)
        if current != brief.brief_context_digest:
            raise ProposalConflictError("planning brief is stale because included context changed")

    @staticmethod
    def _open_proposal(state: FoldedPlanningState, proposal_id: str) -> PersistedProposal:
        try:
            proposal = state.proposals_by_id[proposal_id]
        except KeyError as error:
            raise ProposalConflictError(f"unknown proposal {proposal_id!r}") from error
        prior = state.decisions_by_proposal.get(proposal_id)
        if prior is not None:
            raise ProposalConflictError(f"proposal {proposal_id!r} is already {prior.status}")
        return proposal

    @staticmethod
    def _decision_metadata(
        actor: ActorContext,
        command: DecideProposal,
        input_digest: str,
        outcome: PlanOutcome,
        **extra: object,
    ) -> dict[str, object]:
        return {
            "lifecycle": {
                "type": "proposal_decided",
                "actor_id": actor.actor_id,
                "actor_kind": actor.actor_kind,
                "channel": actor.channel,
                "command_key": command.idempotency_key,
                "input_digest": input_digest,
                "proposal_id": command.proposal_id,
                "proposal_digest": command.proposal_digest,
                "decision": command.decision,
                "reason": command.reason,
                "outcome": asdict(outcome),
                **extra,
            }
        }

    def _fold(self, events: tuple[JournalEvent, ...]) -> FoldedPlanningState:
        return self._journal_projection.fold(events)
