"""Crash-replayable learner decision adapter for conversation proposals."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from .compat import outcome_payload, require_outcome, require_proposal
from .contracts import ActorContext, DecideProposal, PlanningCommand, ProposalRef
from .conversation_contracts import (
    DecisionIntent,
    DecisionProjection,
    PrepareDecisionIntent,
    ProjectDecisionResult,
)

if TYPE_CHECKING:
    from .conversation_store import ConversationStore
    from .lifecycle import PlanningLifecycle


class ConversationDecisionAdapter:
    """Persist exact learner intent before crossing into the plan lifecycle."""

    def __init__(self, store: ConversationStore, lifecycle: PlanningLifecycle) -> None:
        self.store = store
        self.lifecycle = lifecycle

    def prepare_intent(self, command: PrepareDecisionIntent) -> DecisionIntent:
        review = require_proposal(self.lifecycle.inspect(ProposalRef(command.proposal_id)))
        if review.proposal_digest != command.proposal_digest:
            from .conversation_contracts import ConversationConflictError

            raise ConversationConflictError("decision does not match the displayed proposal")
        run_ids = {turn.planning_run_id for turn in self.store.list_turns(command.conversation_id)}
        if review.run_id not in run_ids:
            from .conversation_contracts import ConversationConflictError

            raise ConversationConflictError("proposal is outside this conversation")
        return self.store.prepare_decision_intent(command)

    def decide(self, intent_id: str, actor: ActorContext) -> DecisionProjection:
        projected = self.store.get_decision_projection(intent_id)
        if projected is not None:
            return projected
        self.store.mark_decision_dispatching(intent_id)
        _intent, payload = self.store.get_decision_intent(intent_id)
        command = self._command(payload)
        outcome = require_outcome(self.lifecycle.handle(PlanningCommand(actor, command)))
        return self.store.project_decision_result(
            ProjectDecisionResult(intent_id, "projected", outcome_payload(outcome))
        )

    def recover(self, intent_id: str, actor: ActorContext) -> DecisionProjection:
        """Replay the original stable lifecycle key and project its durable result."""
        return self.decide(intent_id, actor)

    @staticmethod
    def _command(payload: dict[str, object]) -> DecideProposal:
        return DecideProposal(
            proposal_id=str(payload["proposal_id"]),
            proposal_digest=str(payload["proposal_digest"]),
            decision=cast("object", payload["outcome"]),  # type: ignore[arg-type]
            idempotency_key=str(payload["lifecycle_idempotency_key"]),
            expected_document_digest=str(payload["base_document_digest"]),
            expected_structure_digest=str(payload["base_structure_digest"]),
            expected_document_revision=cast("int | None", payload["base_document_revision"]),
            expected_structure_revision=cast("int | None", payload["base_structure_revision"]),
        )


__all__ = ["ConversationDecisionAdapter"]
