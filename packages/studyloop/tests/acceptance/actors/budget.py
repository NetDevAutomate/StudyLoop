"""``BudgetGuard`` -- the per-run cap shared by every ``LearnerActor`` backend.

Council D-15: every LLM actor enforces a per-run budget guard -- max turns
AND max output tokens, hard abort. The guard is plain data with a
check-before-you-act query (:meth:`BudgetGuard.has_budget_for_next_turn`)
plus a record call (:meth:`BudgetGuard.record_turn`) made after a turn
completes -- it never discards a turn that already happened, and it never
raises: a backend calls ``has_budget_for_next_turn()`` before starting the
NEXT turn and turns a ``False`` into
``TerminationOutcome.BUDGET_EXHAUSTED`` itself (see
:func:`acceptance.actors._loop.run_llm_conversation` for the shared LLM
loop, and ``scripted.py``/``harness.py`` for the other two).

The scripted actor uses this too, even though it has no LLM and no output
tokens to spend: a misconfigured or looping mentor transport must still be
capped on turn count.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BudgetGuard:
    """Hard caps on one conversation: turn count and cumulative output tokens.

    ``max_output_tokens=None`` means "no token cap" -- a backend that
    cannot observe usage (``harness``; ``scripted`` has no tokens at all)
    can only ever be capped on turn count, and that is fine: it still
    passes ``None`` for every turn's ``output_tokens``, which this class
    never counts against the cap (an unknown spend is never assumed to be
    zero, but it is also never assumed to be a violation).
    """

    max_turns: int
    max_output_tokens: int | None = None
    _turns_taken: int = field(default=0, init=False, repr=False)
    _output_tokens_spent: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.max_turns < 1:
            raise ValueError(f"max_turns must be >= 1, got {self.max_turns}")
        if self.max_output_tokens is not None and self.max_output_tokens < 0:
            raise ValueError(
                f"max_output_tokens must be >= 0 or None, got {self.max_output_tokens}"
            )

    def has_budget_for_next_turn(self) -> bool:
        """``True`` if another turn may be attempted without busting the cap.

        Called BEFORE a turn starts. A backend that gets ``False`` here
        must stop and report ``TerminationOutcome.BUDGET_EXHAUSTED`` rather
        than attempting (and then discarding) one more turn.
        """
        if self._turns_taken >= self.max_turns:
            return False
        return not (
            self.max_output_tokens is not None
            and self._output_tokens_spent >= self.max_output_tokens
        )

    def record_turn(self, output_tokens: int | None) -> None:
        """Record one FULLY completed turn's spend. Never raises."""
        self._turns_taken += 1
        if output_tokens is not None:
            self._output_tokens_spent += output_tokens

    @property
    def turns_taken(self) -> int:
        return self._turns_taken

    @property
    def output_tokens_spent(self) -> int:
        return self._output_tokens_spent


__all__ = ["BudgetGuard"]
