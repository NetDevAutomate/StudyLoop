"""``ACTOR=scripted`` -- B1's deterministic, CI-safe default (council D-16).

Wraps ``tests/acceptance/turn_script.py``'s loader behind the
:class:`~acceptance.actors.protocol.LearnerActor` protocol: each learner
message sent to the mentor is exactly ``Turn.prompt``, byte-for-byte, in
script order, with no LLM anywhere on the learner side.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from acceptance.actors.budget import BudgetGuard
from acceptance.actors.protocol import (
    ConversationResult,
    LearnerTurn,
    TerminationOutcome,
    TokenUsage,
)

if TYPE_CHECKING:
    import asyncio

    from acceptance.actors.protocol import MentorTransport
    from acceptance.turn_script import TurnScript


class ScriptedActor:
    """Replays a versioned turn script (see ``acceptance/turn_script.py``)."""

    name = "scripted"

    def __init__(self, turn_script: TurnScript, *, budget: BudgetGuard | None = None) -> None:
        self._script = turn_script
        # One turn per scripted line by default; a caller may pass a
        # tighter BudgetGuard to prove the "capped before the script ends"
        # path (used by this backend's own budget-exhaustion test).
        self._budget = budget or BudgetGuard(max_turns=len(turn_script.turns))

    async def converse(
        self,
        mentor: MentorTransport,
        *,
        cancel: asyncio.Event | None = None,
    ) -> ConversationResult:
        transcript: list[LearnerTurn] = []
        for turn in self._script.turns:
            if cancel is not None and cancel.is_set():
                return ConversationResult(
                    outcome=TerminationOutcome.CANCELLED, transcript=tuple(transcript)
                )
            if not self._budget.has_budget_for_next_turn():
                return ConversationResult(
                    outcome=TerminationOutcome.BUDGET_EXHAUSTED, transcript=tuple(transcript)
                )
            try:
                mentor_reply = await mentor.send(turn.prompt)
            except Exception as exc:  # becomes an outcome, never a raise
                return ConversationResult(
                    outcome=TerminationOutcome.ERRORED,
                    transcript=tuple(transcript),
                    error=str(exc),
                )
            transcript.append(
                LearnerTurn(
                    learner_message=turn.prompt,
                    mentor_reply=mentor_reply,
                    usage=TokenUsage.zero(),
                )
            )
            self._budget.record_turn(output_tokens=0)
        return ConversationResult(
            outcome=TerminationOutcome.COMPLETED, transcript=tuple(transcript)
        )

    async def aclose(self) -> None:
        return None


__all__ = ["ScriptedActor"]
