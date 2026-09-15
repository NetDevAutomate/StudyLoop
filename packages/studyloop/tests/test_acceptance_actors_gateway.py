"""GatewayActor: the openai-compatible client at the LiteLLM base URL.

HTTP layer is stubbed via respx -- no network in this unit tier. Outside
tests/acceptance/ and unmarked, same rationale as
test_openai_compat_generator.py's own respx-stubbed tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
import respx

_tests_dir = Path(__file__).parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from acceptance.actors.budget import BudgetGuard  # noqa: E402
from acceptance.actors.gateway import (  # noqa: E402
    ENV_API_KEY,
    ENV_BASE_URL,
    ENV_MODEL,
    GatewayActor,
)
from acceptance.actors.protocol import ActorError, TerminationOutcome, TokenUsage  # noqa: E402


class EchoMentor:
    async def send(self, message: str) -> str:
        return f"mentor said: {message}"


def _completion_response(content: str, *, prompt_tokens: int = 12, completion_tokens: int = 7):
    return {
        "id": "chatcmpl-test",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


class TestFromEnv:
    def test_missing_api_key_and_model_raises_actor_error_naming_both(self) -> None:
        with pytest.raises(ActorError) as exc:
            GatewayActor.from_env({})
        assert ENV_API_KEY in str(exc.value)
        assert ENV_MODEL in str(exc.value)

    def test_missing_only_model_names_only_model(self) -> None:
        with pytest.raises(ActorError) as exc:
            GatewayActor.from_env({ENV_API_KEY: "k"})
        assert ENV_MODEL in str(exc.value)
        assert ENV_API_KEY not in str(exc.value)

    def test_builds_with_default_base_url_when_unset(self) -> None:
        actor = GatewayActor.from_env({ENV_API_KEY: "k", ENV_MODEL: "m"})
        assert actor.name == "gateway"

    def test_honours_explicit_base_url_override(self) -> None:
        env = {ENV_API_KEY: "k", ENV_MODEL: "m", ENV_BASE_URL: "http://example.invalid:9999"}
        actor = GatewayActor.from_env(env)
        assert actor._client.base_url == httpx.URL("http://example.invalid:9999")


@pytest.mark.asyncio
class TestConverse:
    @respx.mock
    async def test_one_turn_round_trip_reads_content_and_usage(self) -> None:
        route = respx.post("http://127.0.0.1:4000/chat/completions").mock(
            return_value=httpx.Response(200, json=_completion_response("What is a decorator?"))
        )
        actor = GatewayActor(
            base_url="http://127.0.0.1:4000",
            api_key="k",
            model="test-model",
            budget=BudgetGuard(max_turns=1),
        )
        mentor = EchoMentor()

        result = await actor.converse(mentor)

        assert route.called
        request_body = route.calls.last.request.content
        import json as _json

        payload = _json.loads(request_body)
        assert payload["model"] == "test-model"
        assert route.calls.last.request.headers["Authorization"] == "Bearer k"

        assert result.outcome is TerminationOutcome.BUDGET_EXHAUSTED
        assert len(result.transcript) == 1
        turn = result.transcript[0]
        assert turn.learner_message == "What is a decorator?"
        assert turn.mentor_reply == "mentor said: What is a decorator?"
        assert turn.usage == TokenUsage(input_tokens=12, output_tokens=7)
        await actor.aclose()

    @respx.mock
    async def test_missing_usage_field_reports_unknown_not_zero(self) -> None:
        respx.post("http://127.0.0.1:4000/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={"choices": [{"message": {"role": "assistant", "content": "hi"}}]},
            )
        )
        actor = GatewayActor(
            base_url="http://127.0.0.1:4000",
            api_key="k",
            model="test-model",
            budget=BudgetGuard(max_turns=1),
        )
        result = await actor.converse(EchoMentor())
        assert result.transcript[0].usage == TokenUsage(input_tokens=None, output_tokens=None)
        await actor.aclose()

    @respx.mock
    async def test_http_error_response_becomes_errored_outcome(self) -> None:
        respx.post("http://127.0.0.1:4000/chat/completions").mock(
            return_value=httpx.Response(500, text="upstream exploded")
        )
        actor = GatewayActor(
            base_url="http://127.0.0.1:4000",
            api_key="k",
            model="test-model",
            budget=BudgetGuard(max_turns=3),
        )
        result = await actor.converse(EchoMentor())
        assert result.outcome is TerminationOutcome.ERRORED
        assert result.error is not None
        assert result.transcript == ()
        await actor.aclose()
