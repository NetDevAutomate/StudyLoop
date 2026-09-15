"""The conversation loop shared by every LLM-backed ``LearnerActor``.

``gateway`` and ``direct`` differ only in how they call out to a model
(:mod:`.gateway`, :mod:`.direct`) -- the turn-taking, budget-checking,
cancellation-checking, and error-to-outcome mapping is identical, so it
lives here once rather than twice.

Scoping note (left out of this lane deliberately, not an oversight): an LLM
backend built on this loop has no way to decide the conversation is
naturally over -- there is no heuristic here for "the student seems
satisfied, stop". That is exactly why the budget guard exists and exactly
what the contract's own test asks for: "a non-terminating fake conversation
aborts at max-turns and reports budget-exhausted". A real natural-completion
signal (the model itself saying it is done, or a rubric-driven stop) is a
judgement call that belongs to a later lane -- most likely B4, which already
owns rubric judging -- not something to invent here and lock in un-reviewed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from acceptance.actors.protocol import (
    ConversationResult,
    LearnerTurn,
    TerminationOutcome,
    TokenUsage,
)

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Sequence

    from acceptance.actors.budget import BudgetGuard
    from acceptance.actors.protocol import MentorTransport


class _Generate(Protocol):
    async def __call__(self, history: Sequence[dict[str, str]]) -> tuple[str, TokenUsage]: ...


async def run_llm_conversation(
    *,
    generate: _Generate,
    mentor: MentorTransport,
    budget: BudgetGuard,
    cancel: asyncio.Event | None,
) -> ConversationResult:
    """Drive turns until budget/cancel/error stops the loop.

    ``generate`` is awaited with the running history (learner turns tagged
    ``"assistant"``, mentor replies tagged ``"user"`` -- from the LEARNER's
    own point of view, it is replying to the mentor's "user" turns) and
    must return ``(learner_message, usage)``; it never raises for an
    expected condition -- any exception it raises is treated as
    ``TerminationOutcome.ERRORED``, same as a ``mentor.send()`` failure.
    """
    transcript: list[LearnerTurn] = []
    history: list[dict[str, str]] = []
    while True:
        if cancel is not None and cancel.is_set():
            return ConversationResult(
                outcome=TerminationOutcome.CANCELLED, transcript=tuple(transcript)
            )
        if not budget.has_budget_for_next_turn():
            return ConversationResult(
                outcome=TerminationOutcome.BUDGET_EXHAUSTED, transcript=tuple(transcript)
            )

        try:
            learner_message, usage = await generate(tuple(history))
        except Exception as exc:  # becomes an outcome, never a raise
            return ConversationResult(
                outcome=TerminationOutcome.ERRORED,
                transcript=tuple(transcript),
                error=str(exc),
            )

        try:
            mentor_reply = await mentor.send(learner_message)
        except Exception as exc:  # becomes an outcome, never a raise
            return ConversationResult(
                outcome=TerminationOutcome.ERRORED,
                transcript=tuple(transcript),
                error=str(exc),
            )

        transcript.append(
            LearnerTurn(learner_message=learner_message, mentor_reply=mentor_reply, usage=usage)
        )
        history.append({"role": "assistant", "content": learner_message})
        history.append({"role": "user", "content": mentor_reply})
        budget.record_turn(usage.output_tokens)


__all__ = ["run_llm_conversation"]
