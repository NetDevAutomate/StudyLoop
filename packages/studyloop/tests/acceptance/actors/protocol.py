"""The ``LearnerActor`` protocol: the seam every actor backend implements.

Council D-15 (unanimous, ``reviews/2026-09-15-acceptance-harness/``):
``CardGenerator`` (``studyloop.content.generators``) is a FLASHCARD
protocol and must never be reused for conversation, even though its SHAPE
-- a ``runtime_checkable`` ``Protocol`` plus a factory function keyed off a
config value -- is exactly the idiom to repeat here. This module is that
repeat, with its own conversation-shaped members instead.

Design decisions worth stating up front:

- **Never raises for an expected outcome.** A budget cap, a cancellation
  request, or a transport failure are not exceptional to a caller grading
  the result (B4's rubric judge) -- they are one of four
  :class:`TerminationOutcome` values on a :class:`ConversationResult` that
  is *always* returned, never raised. "Its transcript is always captured"
  (council D-15) only holds if a caller can rely on getting one back even
  when a run went wrong.
- **Token usage is honest, not guessed.** :class:`TokenUsage` fields are
  ``None`` -- not ``0`` -- when a backend cannot observe them (the
  ``harness`` backend; a mentor transport that errors before an LLM
  backend's usage-bearing response arrives). ``0`` is reserved for a
  backend that KNOWS no tokens were spent (``scripted`` -- there is no LLM
  on the learner side at all).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import asyncio


class ActorError(ValueError):
    """A loud, non-skippable actor failure: unknown actor name, or a
    configuration combination that cannot possibly work.

    Distinguished from a *named skip* (see :func:`acceptance.actors.factory.
    skip_reason`): a missing credential is something a contributor can fix
    by exporting a variable and re-running; an unknown ``ACTOR`` name, or a
    ``direct`` provider slug that does not exist, is a typo the run should
    fail on immediately, not skip past quietly (docs/acceptance-testing.md,
    "Rules that keep the tier honest").
    """


class TerminationOutcome(StrEnum):
    """Why a :class:`LearnerActor`'s conversation stopped."""

    #: The actor's own logic decided the conversation was over (e.g. the
    #: scripted actor's turn script ran out). LLM-backed actors in this
    #: lane never report this -- see ``gateway``/``direct``'s module
    #: docstrings for the scoping note (no natural-completion heuristic is
    #: implemented; left to a later lane / B4's rubric).
    COMPLETED = "completed"
    #: The shared :class:`~acceptance.actors.budget.BudgetGuard` ran out of
    #: turns or output tokens before the conversation otherwise ended.
    BUDGET_EXHAUSTED = "budget-exhausted"
    #: The caller signalled cancellation (the ``cancel`` event was set)
    #: before the conversation otherwise ended.
    CANCELLED = "cancelled"
    #: The mentor transport, or the actor's own backend call, raised.
    #: ``ConversationResult.error`` carries a human-readable reason.
    ERRORED = "errored"


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Token accounting for one learner turn.

    ``None`` means "unknown", reported honestly rather than guessed at
    (council D-15) -- see the module docstring's second bullet.
    """

    input_tokens: int | None
    output_tokens: int | None

    @classmethod
    def unknown(cls) -> TokenUsage:
        """The ``harness`` backend's usage: a generic harness gives us its
        terminal output, not a token count."""
        return cls(input_tokens=None, output_tokens=None)

    @classmethod
    def zero(cls) -> TokenUsage:
        """The ``scripted`` backend's usage: no LLM call happened at all,
        so the true count -- not an unknown placeholder -- is zero."""
        return cls(input_tokens=0, output_tokens=0)


@dataclass(frozen=True, slots=True)
class LearnerTurn:
    """One complete exchange: what the learner said, and the mentor's reply."""

    learner_message: str
    mentor_reply: str
    usage: TokenUsage


@dataclass(frozen=True, slots=True)
class ConversationResult:
    """The normalized transcript a :class:`LearnerActor` hands back.

    ``transcript`` holds every FULLY completed turn up to the point the
    conversation stopped, on every outcome including ``errored`` and
    ``cancelled`` -- a partial transcript is still graded material, not
    discarded material (council D-15).
    """

    outcome: TerminationOutcome
    transcript: tuple[LearnerTurn, ...]
    error: str | None = None


@runtime_checkable
class MentorTransport(Protocol):
    """What a :class:`LearnerActor` talks to: the mentor side of the exchange.

    Deliberately one method: send the learner's message, get the mentor's
    reply back. A live acceptance test binds this to a real harness session
    (ACP, PTY, or tmux transport); a unit test binds it to an in-memory
    fake. The mentor itself is never simulated in a LIVE acceptance test
    (council D-16) -- only unit/plumbing tests use a fake transport.
    """

    async def send(self, message: str) -> str: ...


@runtime_checkable
class LearnerActor(Protocol):
    """Protocol for the four pluggable learner backends (council D-15).

    ``name`` is the ``STUDYLOOP_ACC_ACTOR`` value this backend answers to
    (see :mod:`acceptance.actors.factory`).
    """

    name: str

    async def converse(
        self,
        mentor: MentorTransport,
        *,
        cancel: asyncio.Event | None = None,
    ) -> ConversationResult:
        """Drive a full conversation against ``mentor``; never raises.

        ``cancel``, when given, is polled cooperatively between turns (not
        via ``asyncio.Task.cancel()`` mid-call) -- a set event stops the
        NEXT turn from starting and returns
        ``TerminationOutcome.CANCELLED`` with the transcript captured so
        far.
        """
        ...

    async def aclose(self) -> None:
        """Release any resources (HTTP clients, tmux sessions, ...)."""
        ...
