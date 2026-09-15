"""ScriptedActor: byte-stable replay of a turn script (council D-16 scoping).

Outside tests/acceptance/ and unmarked -- no LLM, no network, no live
product session; same rationale as test_acceptance_turn_script.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_tests_dir = Path(__file__).parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from acceptance.actors.protocol import TerminationOutcome, TokenUsage  # noqa: E402
from acceptance.actors.scripted import ScriptedActor  # noqa: E402
from acceptance.turn_script import load_turn_script  # noqa: E402


class RecordingMentor:
    def __init__(self, replies: list[str]) -> None:
        self._replies = iter(replies)
        self.received: list[str] = []

    async def send(self, message: str) -> str:
        self.received.append(message)
        return next(self._replies)


@pytest.mark.asyncio
class TestByteStableReplay:
    async def test_learner_messages_are_exactly_the_scripted_prompts(self) -> None:
        script = load_turn_script(
            {
                "version": 1,
                "turns": [
                    {"prompt": "In one sentence, what is a Python decorator?"},
                    {"prompt": "And a closure?"},
                ],
            }
        )
        mentor = RecordingMentor(["a decorator wraps a function.", "a closure captures scope."])
        actor = ScriptedActor(script)

        result = await actor.converse(mentor)

        # Byte-stable: exactly what the script said, no whitespace/casing
        # drift, no LLM anywhere in between.
        assert mentor.received == [
            "In one sentence, what is a Python decorator?",
            "And a closure?",
        ]
        assert [t.learner_message for t in result.transcript] == mentor.received
        assert [t.mentor_reply for t in result.transcript] == [
            "a decorator wraps a function.",
            "a closure captures scope.",
        ]
        assert result.outcome is TerminationOutcome.COMPLETED
        await actor.aclose()

    async def test_usage_is_a_known_zero_not_an_unknown(self) -> None:
        """ScriptedActor has no LLM at all -- it KNOWS zero tokens were
        spent, so it reports 0/0, never the "unknown" None/None a backend
        that genuinely cannot observe usage would report."""
        script = load_turn_script({"version": 1, "turns": [{"prompt": "hi"}]})
        actor = ScriptedActor(script)
        result = await actor.converse(RecordingMentor(["hello"]))

        assert result.transcript[0].usage == TokenUsage(input_tokens=0, output_tokens=0)
        await actor.aclose()

    async def test_empty_turn_list_is_impossible_via_the_loader(self) -> None:
        """turn_script.load_turn_script already rejects an empty 'turns'
        list -- ScriptedActor never has to handle a zero-turn script."""
        from acceptance.turn_script import TurnScriptError

        with pytest.raises(TurnScriptError):
            load_turn_script({"version": 1, "turns": []})
