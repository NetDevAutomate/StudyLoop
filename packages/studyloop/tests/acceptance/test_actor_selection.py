"""The selected ACTOR is buildable, or named-skips -- inside the real gate.

Marked ``acceptance``, so this only runs under ``STUDYLOOP_ACC=1`` and goes
through the tier's OWN gate fixture (``conftest._acceptance_gate``): it is
the one test that proves the whole selection path end to end -- the gate
accepts the actor name, ``learner_actor_factory`` either builds it or skips
naming the missing variable, and what comes back satisfies the protocol.

Its hermetic mentor is the named exception council D-16 allows: this is a
PLUMBING test of the actor seam, not a live journey, so no real harness is
started and none is claimed to be.
"""

from __future__ import annotations

import pytest

from .actors.protocol import ConversationResult, LearnerActor, TerminationOutcome
from .conftest import selected_actor
from .turn_script import load_turn_script

pytestmark = [pytest.mark.acceptance]


class _HermeticMentor:
    """A fake mentor -- named as such, per D-16. Never a real harness."""

    def __init__(self) -> None:
        self.received: list[str] = []

    async def send(self, message: str) -> str:
        self.received.append(message)
        return f"(hermetic mentor) you said: {message}"


def test_selected_actor_is_buildable_or_skips_by_name(learner_actor_factory) -> None:
    script = load_turn_script({"version": 1, "turns": [{"prompt": "What is a closure?"}]})
    actor = learner_actor_factory(turn_script=script)

    assert isinstance(actor, LearnerActor)
    assert actor.name == selected_actor()


@pytest.mark.asyncio
async def test_selected_actor_produces_a_transcript_against_a_hermetic_mentor(
    learner_actor_factory,
) -> None:
    script = load_turn_script({"version": 1, "turns": [{"prompt": "What is a closure?"}]})
    actor = learner_actor_factory(turn_script=script)
    mentor = _HermeticMentor()

    try:
        result = await actor.converse(mentor)
    finally:
        await actor.aclose()

    assert isinstance(result, ConversationResult)
    assert isinstance(result.outcome, TerminationOutcome)
    # Actors produce turns, never verdicts -- rubric judging is a later
    # lane's job, so this asserts the SHAPE, not the content.
    for turn in result.transcript:
        assert isinstance(turn.learner_message, str)
        assert isinstance(turn.mentor_reply, str)
