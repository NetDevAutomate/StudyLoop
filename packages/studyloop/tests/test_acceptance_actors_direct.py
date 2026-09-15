"""DirectActor: plain OpenAI/Anthropic HTTP client, no gateway required.

HTTP layer is stubbed via respx -- no network in this unit tier.
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
from acceptance.actors.direct import (  # noqa: E402
    ENV_MODEL,
    ENV_PROVIDER,
    DirectActor,
    resolve_direct_profile,
)
from acceptance.actors.protocol import ActorError, TokenUsage  # noqa: E402


class EchoMentor:
    async def send(self, message: str) -> str:
        return f"mentor said: {message}"


class TestResolveDirectProfile:
    def test_unknown_provider_slug_raises_actor_error(self) -> None:
        with pytest.raises(ActorError):
            resolve_direct_profile("not-a-real-provider")

    def test_bedrock_is_a_known_provider_but_unsupported_by_this_backend(self) -> None:
        with pytest.raises(ActorError, match="bedrock"):
            resolve_direct_profile("bedrock")

    def test_openai_and_anthropic_are_supported(self) -> None:
        assert resolve_direct_profile("openai").adapter == "openai_compat"
        assert resolve_direct_profile("anthropic").adapter == "anthropic_compat"


class TestFromEnv:
    def test_missing_api_key_names_the_providers_auth_env(self) -> None:
        with pytest.raises(ActorError) as exc:
            DirectActor.from_env({ENV_PROVIDER: "openai"})
        assert "OPENAI_API_KEY" in str(exc.value)

    def test_defaults_to_openai_when_provider_unset(self) -> None:
        actor = DirectActor.from_env({"OPENAI_API_KEY": "k"})
        assert actor._profile.slug == "openai"

    def test_anthropic_provider_reads_its_own_auth_env(self) -> None:
        actor = DirectActor.from_env({ENV_PROVIDER: "anthropic", "ANTHROPIC_API_KEY": "k"})
        assert actor._profile.slug == "anthropic"

    def test_explicit_model_overrides_the_default(self) -> None:
        actor = DirectActor.from_env({"OPENAI_API_KEY": "k", ENV_MODEL: "gpt-4o"})
        assert actor._model.id == "gpt-4o"

    def test_unknown_model_id_raises_actor_error(self) -> None:
        with pytest.raises(ActorError):
            DirectActor.from_env({"OPENAI_API_KEY": "k", ENV_MODEL: "not-a-real-model"})


@pytest.mark.asyncio
class TestOpenAIWireShape:
    @respx.mock
    async def test_bearer_auth_and_content_round_trip(self) -> None:
        route = respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [{"message": {"role": "assistant", "content": "a decorator!"}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 4},
                },
            )
        )
        actor = DirectActor.from_env({"OPENAI_API_KEY": "sk-test"}, budget=BudgetGuard(max_turns=1))

        result = await actor.converse(EchoMentor())

        assert route.called
        assert route.calls.last.request.headers["Authorization"] == "Bearer sk-test"
        assert result.transcript[0].learner_message == "a decorator!"
        assert result.transcript[0].usage == TokenUsage(input_tokens=3, output_tokens=4)
        await actor.aclose()


@pytest.mark.asyncio
class TestAnthropicWireShape:
    @respx.mock
    async def test_x_api_key_header_and_messages_shape(self) -> None:
        route = respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": "a closure!"}],
                    "usage": {"input_tokens": 5, "output_tokens": 6},
                },
            )
        )
        actor = DirectActor.from_env(
            {
                ENV_PROVIDER: "anthropic",
                "ANTHROPIC_API_KEY": "ak-test",  # pragma: allowlist secret
            },
            budget=BudgetGuard(max_turns=1),
        )

        result = await actor.converse(EchoMentor())

        assert route.called
        request = route.calls.last.request
        assert request.headers["x-api-key"] == "ak-test"
        assert "anthropic-version" in request.headers
        assert "Authorization" not in request.headers
        assert result.transcript[0].learner_message == "a closure!"
        assert result.transcript[0].usage == TokenUsage(input_tokens=5, output_tokens=6)
        await actor.aclose()

    @respx.mock
    async def test_opening_turn_seeds_a_placeholder_user_message(self) -> None:
        """The Messages API requires a non-empty messages list starting
        with a user turn; on turn 0 there is no mentor reply yet."""
        import json as _json

        route = respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                200, json={"content": [{"type": "text", "text": "hi"}], "usage": {}}
            )
        )
        actor = DirectActor.from_env(
            {
                ENV_PROVIDER: "anthropic",
                "ANTHROPIC_API_KEY": "ak-test",  # pragma: allowlist secret
            },
            budget=BudgetGuard(max_turns=1),
        )
        await actor.converse(EchoMentor())

        payload = _json.loads(route.calls.last.request.content)
        assert payload["messages"], "messages must be non-empty on the opening turn"
        assert payload["messages"][0]["role"] == "user"
        await actor.aclose()
