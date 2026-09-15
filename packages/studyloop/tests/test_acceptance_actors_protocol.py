"""Protocol conformance for every LearnerActor backend (council D-15).

Outside tests/acceptance/ and unmarked -- same rationale as
test_acceptance_turn_script.py / test_acceptance_isolation.py: this tests
the plumbing (a Protocol, a factory, a budget guard), never a live
product session, so it belongs in ``just test``'s default run.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_tests_dir = Path(__file__).parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from acceptance.actors.budget import BudgetGuard  # noqa: E402
from acceptance.actors.direct import DirectActor  # noqa: E402
from acceptance.actors.gateway import GatewayActor  # noqa: E402
from acceptance.actors.harness import HarnessActor  # noqa: E402
from acceptance.actors.protocol import (  # noqa: E402
    ActorError,
    ConversationResult,
    LearnerActor,
    MentorTransport,
    TerminationOutcome,
    TokenUsage,
)
from acceptance.actors.scripted import ScriptedActor  # noqa: E402
from acceptance.turn_script import load_turn_script  # noqa: E402


def _one_turn_script():
    return load_turn_script({"version": 1, "turns": [{"prompt": "What is a closure?"}]})


class EchoMentor:
    """A minimal fake MentorTransport: echoes the learner's message back."""

    def __init__(self) -> None:
        self.received: list[str] = []

    async def send(self, message: str) -> str:
        self.received.append(message)
        return f"mentor-reply-to:{message}"


class NeverEndingMentor:
    """A fake mentor whose replies never let the caller decide to stop --
    used to prove the budget guard is what stops a non-terminating
    conversation, not any cleverness on the mentor side."""

    async def send(self, message: str) -> str:
        return "tell me more"


class TestMentorTransportProtocol:
    def test_echo_mentor_satisfies_mentor_transport(self) -> None:
        assert isinstance(EchoMentor(), MentorTransport)

    def test_plain_object_does_not_satisfy_mentor_transport(self) -> None:
        assert not isinstance(object(), MentorTransport)


class TestLearnerActorConformance:
    """Every concrete backend must structurally satisfy LearnerActor."""

    def test_scripted_actor_conforms(self) -> None:
        actor = ScriptedActor(_one_turn_script())
        assert isinstance(actor, LearnerActor)
        assert actor.name == "scripted"

    def test_gateway_actor_conforms(self) -> None:
        actor = GatewayActor(base_url="http://127.0.0.1:4000", api_key="k", model="m")
        assert isinstance(actor, LearnerActor)
        assert actor.name == "gateway"

    def test_direct_actor_conforms(self) -> None:
        from studyloop.content.generators.provider_profiles import default_model, get_profile

        profile = get_profile("openai")
        model = default_model(profile)
        actor = DirectActor(profile=profile, model=model, api_key="k")
        assert isinstance(actor, LearnerActor)
        assert actor.name == "direct"

    def test_harness_actor_conforms(self, tmp_path: Path) -> None:
        actor = HarnessActor(command=("sh",), socket_dir=tmp_path / "sock")
        assert isinstance(actor, LearnerActor)
        assert actor.name == "harness"

    def test_plain_object_does_not_conform(self) -> None:
        assert not isinstance(object(), LearnerActor)


@pytest.mark.asyncio
class TestConversationResultShape:
    async def test_completed_scripted_run_returns_full_transcript(self) -> None:
        script = load_turn_script(
            {
                "version": 1,
                "turns": [{"prompt": "What is a decorator?"}, {"prompt": "And a closure?"}],
            }
        )
        actor = ScriptedActor(script)
        mentor = EchoMentor()
        result = await actor.converse(mentor)

        assert isinstance(result, ConversationResult)
        assert result.outcome is TerminationOutcome.COMPLETED
        assert result.error is None
        assert len(result.transcript) == 2
        assert result.transcript[0].learner_message == "What is a decorator?"
        assert result.transcript[0].mentor_reply == "mentor-reply-to:What is a decorator?"
        assert result.transcript[0].usage == TokenUsage(input_tokens=0, output_tokens=0)
        await actor.aclose()

    async def test_cancellation_stops_before_the_next_turn(self) -> None:
        script = load_turn_script(
            {
                "version": 1,
                "turns": [{"prompt": "one"}, {"prompt": "two"}, {"prompt": "three"}],
            }
        )
        actor = ScriptedActor(script)
        mentor = EchoMentor()
        cancel = asyncio.Event()
        cancel.set()  # already cancelled before the first turn even starts

        result = await actor.converse(mentor, cancel=cancel)

        assert result.outcome is TerminationOutcome.CANCELLED
        assert result.transcript == ()
        assert mentor.received == []
        await actor.aclose()

    async def test_mentor_transport_error_becomes_errored_outcome_not_a_raise(self) -> None:
        script = load_turn_script({"version": 1, "turns": [{"prompt": "hello"}]})
        actor = ScriptedActor(script)

        class BrokenMentor:
            async def send(self, message: str) -> str:
                raise RuntimeError("transport died")

        result = await actor.converse(BrokenMentor())

        assert result.outcome is TerminationOutcome.ERRORED
        assert result.error == "transport died"
        assert result.transcript == ()
        await actor.aclose()


@pytest.mark.asyncio
class TestBudgetExhaustionAcrossActors:
    """ "a non-terminating fake conversation aborts at max-turns and reports
    budget-exhausted" -- the exact TESTS FIRST scenario from lanes.json,
    proven once against the shared scripted-loop shape and once against
    the shared LLM loop (gateway/direct share ``_loop.run_llm_conversation``,
    so proving it via a fake generator covers both)."""

    async def test_scripted_actor_stops_at_max_turns_before_the_script_ends(self) -> None:
        script = load_turn_script(
            {"version": 1, "turns": [{"prompt": "one"}, {"prompt": "two"}, {"prompt": "three"}]}
        )
        actor = ScriptedActor(script, budget=BudgetGuard(max_turns=2))
        result = await actor.converse(EchoMentor())

        assert result.outcome is TerminationOutcome.BUDGET_EXHAUSTED
        assert len(result.transcript) == 2
        await actor.aclose()

    async def test_llm_loop_never_naturally_completes_and_aborts_at_max_turns(self) -> None:
        from acceptance.actors._loop import run_llm_conversation

        budget = BudgetGuard(max_turns=3)
        calls = 0

        async def never_ending_generate(history):
            nonlocal calls
            calls += 1
            return f"learner-turn-{calls}", TokenUsage(input_tokens=10, output_tokens=5)

        result = await run_llm_conversation(
            generate=never_ending_generate,
            mentor=NeverEndingMentor(),
            budget=budget,
            cancel=None,
        )

        assert result.outcome is TerminationOutcome.BUDGET_EXHAUSTED
        assert len(result.transcript) == 3
        assert calls == 3


class TestActorErrorIsLoud:
    def test_actor_error_is_a_value_error(self) -> None:
        assert issubclass(ActorError, ValueError)
