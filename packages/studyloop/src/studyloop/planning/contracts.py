"""Typed public contracts for the agentic planning lifecycle.

Untrusted model payloads are deliberately nested below :class:`PlanningCommand`.
The trusted adapter creates the sibling :class:`ActorContext`; model JSON is
never decoded into authority-bearing fields.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Protocol

from .repository import PlanningRef, PlanningView

if TYPE_CHECKING:
    from .models import (
        Checkpoint,
        ConceptRelation,
        EvidenceDisposition,
        EvidenceRef,
        Mission,
        PlanUnknown,
        Resource,
        StudyPlan,
    )

ActorKind = Literal["model", "learner", "recorder"]
PlanningMode = Literal["create", "revise"]
PlanDecision = Literal["approve", "reject"]
ConceptRelationKind = Literal["equivalent", "broader", "narrower", "related", "distinct"]
EvidenceDispositionKind = Literal["selected", "rejected", "unresolved"]
MilestoneOutcomeKind = Literal["verified_complete", "learner_attested", "incomplete"]


class LifecycleError(RuntimeError):
    """Base error for deterministic lifecycle refusals."""


class AuthorityError(LifecycleError):
    """Raised when an adapter context lacks authority for a command."""


class LifecycleValidationError(LifecycleError):
    """Raised when a typed command violates a domain contract."""


class EvidenceValidationError(LifecycleValidationError):
    """Raised when provenance, tiers, or dispositions cannot be trusted."""


class GoalLimitError(LifecycleValidationError):
    """Raised when active goals exceed the Rule of Three without approval."""


class ProposalConflictError(LifecycleValidationError):
    """Raised when a proposal is stale, terminal, or no longer current."""


class Clock(Protocol):
    """Injectable audit clock; wall time never decides semantic validity."""

    def now(self) -> str: ...


class IdGenerator(Protocol):
    """Injectable persistent identity source."""

    def new_id(self, prefix: str) -> str: ...


class SystemClock:
    """UTC production clock."""

    def now(self) -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat()


class UuidIdGenerator:
    """Filesystem-safe production identities."""

    def new_id(self, prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex}"


@dataclass(frozen=True)
class ActorContext:
    """Authority asserted by a trusted adapter, not by command JSON."""

    actor_kind: ActorKind
    actor_id: str
    channel: str

    def __post_init__(self) -> None:
        if self.actor_kind not in {"model", "learner", "recorder"}:
            raise AuthorityError(f"unsupported actor kind {self.actor_kind!r}")
        if not self.actor_id.strip() or not self.channel.strip():
            raise AuthorityError("trusted actor id and channel are required")


@dataclass(frozen=True)
class SourceReference:
    """Learner-selected context identified by content, never by local path."""

    reference_id: str
    content_digest: str
    source_kind: str = "supplied_material"
    label: str = ""


@dataclass(frozen=True)
class PlanningRequest:
    mode: PlanningMode
    brain_dump: str
    idempotency_key: str
    plan_id: str = ""
    source_references: tuple[SourceReference, ...] = ()
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlanningRunRef:
    run_id: str


@dataclass(frozen=True)
class ProposalRef:
    proposal_id: str


@dataclass(frozen=True)
class PlanningBrief:
    schema_version: int
    policy_version: int
    run_id: str
    mode: PlanningMode
    raw_brain_dump: str
    request_digest: str
    brief_context_digest: str
    plan_id: str
    target_document_digest: str
    target_structure_digest: str
    target_document_revision: int | None
    target_structure_revision: int | None
    target_plan: StudyPlan | None
    current_count: int
    max_current: int
    active_goal_ids: tuple[str, ...]
    active_goal_set_digest: str
    evidence: tuple[EvidenceRef, ...]
    source_references: tuple[SourceReference, ...]
    known_resources: tuple[Resource, ...]
    configured_topics: tuple[str, ...]
    unresolved_gaps: tuple[str, ...]
    invariants: tuple[str, ...]
    created_at: str


@dataclass(frozen=True)
class GoalProposal:
    alias: str
    title: str
    reason: str
    alignment_rationale: str
    status: str = "active"
    existing_goal_id: str = ""


@dataclass(frozen=True)
class ConceptProposal:
    alias: str
    display_label: str
    existing_concept_id: str = ""


@dataclass(frozen=True)
class ConceptRelationProposal:
    source_alias: str
    target_alias: str
    relation: ConceptRelationKind
    reason: str
    provenance: str


@dataclass(frozen=True)
class MilestoneProposal:
    alias: str
    goal_alias: str
    title: str
    notes: str = ""
    concept_aliases: tuple[str, ...] = ()
    existing_milestone_id: str = ""


@dataclass(frozen=True)
class PlanProposalDraft:
    title: str
    mission: Mission
    goals: tuple[GoalProposal, ...]
    milestones: tuple[MilestoneProposal, ...]
    topics: tuple[str, ...] = ()
    concepts: tuple[ConceptProposal, ...] = ()
    concept_relations: tuple[ConceptRelationProposal, ...] = ()
    evidence_dispositions: tuple[EvidenceDisposition, ...] = ()
    resources: tuple[Resource, ...] = ()
    unknowns: tuple[PlanUnknown, ...] = ()
    next_action: str = ""
    requested_status: str = "draft"
    target_date: str = ""
    energy_floor: int = 3
    review_cadence_days: int = 3
    goal_limit_override_requested: bool = False
    goal_limit_override_reason: str = ""


@dataclass(frozen=True)
class SubmitProposalDraft:
    run_id: str
    idempotency_key: str
    brief_context_digest: str
    draft: PlanProposalDraft


@dataclass(frozen=True)
class DecideProposal:
    proposal_id: str
    proposal_digest: str
    decision: PlanDecision
    idempotency_key: str
    reason: str = ""
    expected_document_digest: str = ""
    expected_structure_digest: str = ""
    expected_document_revision: int | None = None
    expected_structure_revision: int | None = None


@dataclass(frozen=True)
class RecordTrustedEvidence:
    plan_id: str
    evidence_ids: tuple[str, ...]
    idempotency_key: str


@dataclass(frozen=True)
class RecordCheckpoint:
    plan_id: str
    checkpoint: Checkpoint
    idempotency_key: str


@dataclass(frozen=True)
class RecordMilestoneOutcome:
    plan_id: str
    milestone_id: str
    outcome: MilestoneOutcomeKind
    evidence_ids: tuple[str, ...]
    idempotency_key: str
    reason: str = ""
    confirmation: str = ""


@dataclass(frozen=True)
class TransitionPlanStatus:
    plan_id: str
    status: str
    idempotency_key: str
    reason: str = ""


@dataclass(frozen=True)
class ImportPlanDraft:
    markdown: str
    idempotency_key: str


type PlanningCommandPayload = (
    SubmitProposalDraft
    | DecideProposal
    | RecordTrustedEvidence
    | RecordCheckpoint
    | RecordMilestoneOutcome
    | TransitionPlanStatus
    | ImportPlanDraft
)


@dataclass(frozen=True)
class PlanningCommand:
    """Trusted actor context paired with one closed untrusted payload union."""

    actor: ActorContext
    payload: PlanningCommandPayload


@dataclass(frozen=True)
class ProposalReview:
    proposal_id: str
    run_id: str
    proposal_digest: str
    brief_context_digest: str
    mode: PlanningMode
    plan_preview: StudyPlan
    markdown_preview: str
    alias_mapping: tuple[tuple[str, str], ...]
    resulting_active_goal_ids: tuple[str, ...]
    resulting_active_goal_set_digest: str
    validation_blockers: tuple[str, ...] = ()
    nudges: tuple[str, ...] = ()
    supersedes_proposal_id: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class PlanOutcome:
    status: Literal[
        "applied",
        "rejected",
        "recorded",
        "verified_complete",
        "learner_attested",
        "incomplete",
        "transitioned",
        "imported",
    ]
    plan_id: str
    proposal_id: str = ""
    document_digest: str = ""
    structure_digest: str = ""
    document_revision: int | None = None
    structure_revision: int | None = None
    goal_limit_override_digest: str = ""
    message: str = ""


type PlanningResult = PlanningBrief | PlanningView | ProposalReview | PlanOutcome
type PlanningInspectRef = PlanningRef | PlanningRunRef | ProposalRef


@dataclass(frozen=True)
class PersistedProposal:
    """Internal journal projection; exported only for deterministic folding."""

    review: ProposalReview
    base_document_digest: str = ""
    base_structure_digest: str = ""
    base_document_revision: int | None = None
    base_structure_revision: int | None = None
    requested_status: str = "draft"
    evidence_dispositions: tuple[EvidenceDisposition, ...] = ()
    explicit_relations: tuple[ConceptRelation, ...] = ()
    next_action: str = ""
    goal_limit_override_requested: bool = False
    goal_limit_override_reason: str = ""


@dataclass(frozen=True)
class FoldedPlanningState:
    briefs_by_run: dict[str, PlanningBrief] = field(default_factory=dict)
    proposals_by_id: dict[str, PersistedProposal] = field(default_factory=dict)
    latest_proposal_by_run: dict[str, str] = field(default_factory=dict)
    decisions_by_proposal: dict[str, PlanOutcome] = field(default_factory=dict)
    request_keys: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)
    proposal_keys: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)
    decision_keys: dict[tuple[str, str], tuple[str, PlanOutcome]] = field(default_factory=dict)
    command_keys: dict[tuple[str, str], tuple[str, PlanOutcome]] = field(default_factory=dict)
    valid_goal_overrides: dict[str, tuple[str, ...]] = field(default_factory=dict)
