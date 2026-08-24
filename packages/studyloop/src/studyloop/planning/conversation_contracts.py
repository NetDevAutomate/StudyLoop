"""Durable contracts for the confined planning conversation runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .contracts import PlanningRequest

PRIVACY_NOTICE = (
    "Planning text and proposals are stored locally for recovery and may remain "
    "after rejection or replacement. StudyLoop sends the bounded planning context "
    "to your configured model. This release provides no automatic expiry."
)


class PlanningConversationError(RuntimeError):
    """Base error for a bounded planning conversation."""


class ConversationConflictError(PlanningConversationError):
    """A durable compare-and-swap or idempotency precondition failed."""


class ConversationRefusedError(PlanningConversationError):
    """Input fell outside the confined planning conversation contract."""


@dataclass(frozen=True, slots=True)
class PlanningConversationBounds:
    max_model_rounds: int = 8
    max_tool_calls: int = 8
    max_model_events: int = 512
    max_output_tokens: int = 4096
    max_output_characters: int = 32_000
    max_input_characters: int = 120_000
    max_tool_name_characters: int = 128
    max_tool_argument_characters: int = 64_000
    turn_timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        values = (
            self.max_model_rounds,
            self.max_tool_calls,
            self.max_model_events,
            self.max_output_tokens,
            self.max_output_characters,
            self.max_input_characters,
            self.max_tool_name_characters,
            self.max_tool_argument_characters,
        )
        if any(isinstance(value, bool) or value <= 0 for value in values):
            raise ValueError("planning conversation bounds must be positive integers")
        if not 0 < self.turn_timeout_seconds <= 300:
            raise ValueError("planning conversation timeout must be between 0 and 300 seconds")


@dataclass(frozen=True, slots=True)
class ConversationRecord:
    conversation_id: str
    mode: Literal["create", "revise"]
    plan_id: str
    created_at: float


@dataclass(frozen=True, slots=True)
class LearnerTurn:
    turn_id: str
    text: str
    planning_request: PlanningRequest


@dataclass(frozen=True, slots=True)
class AttachContext:
    conversation_id: str
    context_id: str
    label: str
    content: str


@dataclass(frozen=True, slots=True)
class ContextAttachment:
    conversation_id: str
    context_id: str
    ordinal: int
    label: str
    content: str
    content_digest: str


@dataclass(frozen=True, slots=True)
class CaptureLearnerTurn:
    conversation_id: str
    turn: LearnerTurn


@dataclass(frozen=True, slots=True)
class TurnReceipt:
    conversation_id: str
    turn_id: str
    status: str
    turn_version: int
    brief_context_digest: str
    context_ids: tuple[str, ...]
    context_digests: tuple[str, ...]
    privacy_notice: str = PRIVACY_NOTICE


@dataclass(frozen=True, slots=True)
class TurnRecord:
    conversation_id: str
    turn_id: str
    learner_text: str
    status: str
    turn_version: int
    brief_context_digest: str
    planning_run_id: str


@dataclass(frozen=True, slots=True)
class BeginModelAttempt:
    conversation_id: str
    turn_id: str
    expected_turn_version: int
    retry_of_attempt_id: str | None
    owner_id: str = ""


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    attempt_id: str
    conversation_id: str
    turn_id: str
    attempt_seq: int
    status: Literal["active", "completed", "interrupted"]
    turn_version: int
    retry_of_attempt_id: str | None = None
    owner_id: str = ""
    lease_expires_at: float = 0.0


@dataclass(frozen=True, slots=True)
class CompleteModelAttempt:
    conversation_id: str
    turn_id: str
    attempt_id: str
    expected_turn_version: int
    expected_owner_id: str = ""


@dataclass(frozen=True, slots=True)
class MarkAttemptInterrupted:
    conversation_id: str
    turn_id: str
    attempt_id: str
    expected_turn_version: int
    private_reason: str
    expected_owner_id: str = ""
    require_expired_lease: bool = False


@dataclass(frozen=True, slots=True)
class FinalizeAssistantMessage:
    conversation_id: str
    turn_id: str
    attempt_id: str
    content: str
    expected_owner_id: str = ""


@dataclass(frozen=True, slots=True)
class MessageRecord:
    message_id: str
    conversation_id: str
    turn_id: str
    attempt_id: str
    role: Literal["assistant", "learner"]
    content: str
    outbox_seq: int


@dataclass(frozen=True, slots=True)
class PrepareCapabilityCall:
    conversation_id: str
    turn_id: str
    attempt_id: str
    tool_call_id: str
    name: str
    arguments: Mapping[str, object]
    run_id: str
    lifecycle_idempotency_key: str
    expected_owner_id: str = ""


@dataclass(frozen=True, slots=True)
class CapabilityIntent:
    intent_id: str
    conversation_id: str
    turn_id: str
    attempt_id: str
    tool_call_id: str
    name: str
    arguments: Mapping[str, object]
    run_id: str
    payload_digest: str
    lifecycle_idempotency_key: str
    status: Literal["prepared", "dispatching", "projected", "refused"]


@dataclass(frozen=True, slots=True)
class ProjectCapabilityResult:
    intent_id: str
    status: Literal["projected", "refused"]
    payload: Mapping[str, object]
    expected_owner_id: str = ""


@dataclass(frozen=True, slots=True)
class StoredCapabilityResult:
    intent_id: str
    status: Literal["projected", "refused"]
    payload: Mapping[str, object]
    outbox_seq: int


@dataclass(frozen=True, slots=True)
class PrepareDecisionIntent:
    conversation_id: str
    proposal_id: str
    proposal_digest: str
    base_document_digest: str
    base_structure_digest: str
    outcome: Literal["approve", "reject"]
    lifecycle_idempotency_key: str
    base_document_revision: int | None = None
    base_structure_revision: int | None = None


@dataclass(frozen=True, slots=True)
class DecisionIntent:
    intent_id: str
    conversation_id: str
    proposal_id: str
    payload_digest: str
    lifecycle_idempotency_key: str
    status: Literal["prepared", "dispatching", "projected", "refused"]


@dataclass(frozen=True, slots=True)
class ProjectDecisionResult:
    intent_id: str
    status: Literal["projected", "refused"]
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class DecisionProjection:
    intent_id: str
    status: Literal["projected", "refused"]
    payload: Mapping[str, object]
    outbox_seq: int


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    conversation_id: str
    sequence: int
    event_type: str
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    conversation_id: str
    interrupted_attempt_ids: tuple[str, ...] = ()
    projected_capability_ids: tuple[str, ...] = ()
    refused_capability_ids: tuple[str, ...] = ()
    completed_attempt_ids: tuple[str, ...] = ()
