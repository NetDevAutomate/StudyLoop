"""Tests for the OpenAI Chat Completions-compatible adapter (U1.5).

HTTP layer is stubbed via ``respx`` so these tests run offline. Live
provider smokes are gated separately by ``@pytest.mark.live_provider``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
import pytest
import respx

from studyloop.content.generators import CardGenerationError
from studyloop.content.generators.openai_compat import OpenAICompatGenerator
from studyloop.content.generators.provider_profiles import get_model, get_profile
from studyloop.content.schemas import FlashcardDeck, QuizDeck
from studyloop.settings import CardGeneratorConfig

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def openrouter_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Set a fake OpenRouter key for tests that build the adapter."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-openrouter")
    yield "test-key-openrouter"


@pytest.fixture
def openai_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-openai")
    yield "test-key-openai"


def _flashcard_tool_call_response(deck_payload: dict) -> dict:
    """Build a minimal OpenAI Chat Completions response with a tool_call."""
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "emit_flashcard_deck",
                                "arguments": json.dumps(deck_payload),
                            },
                        }
                    ],
                },
            }
        ],
    }


def _quiz_tool_call_response(deck_payload: dict) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "emit_quiz_deck",
                                "arguments": json.dumps(deck_payload),
                            },
                        }
                    ],
                }
            }
        ]
    }


def _make_generator(provider: str, model: str) -> OpenAICompatGenerator:
    profile = get_profile(provider)
    entry = get_model(profile, model)
    cfg = CardGeneratorConfig(
        backend="openai_compat",
        provider=provider,
        model=model,
        request_timeout=5.0,
        max_retries=1,
    )
    return OpenAICompatGenerator(cfg, profile, entry)


class TestAuth:
    def test_missing_env_var_raises_with_actionable_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with pytest.raises(CardGenerationError) as exc:
            _make_generator("openrouter", "anthropic/claude-haiku-4-5")
        msg = str(exc.value)
        assert "OPENROUTER_API_KEY" in msg
        assert ".env" in msg

    @pytest.mark.usefixtures("openrouter_key")
    def test_authorization_header_set_to_bearer_key(self) -> None:
        gen = _make_generator("openrouter", "anthropic/claude-haiku-4-5")
        try:
            assert gen._client.headers["Authorization"] == "Bearer test-key-openrouter"
        finally:
            gen.close()


class TestHappyPath:
    @pytest.mark.usefixtures("openrouter_key")
    @respx.mock
    def test_flashcards_round_trip(self) -> None:
        gen = _make_generator("openrouter", "anthropic/claude-haiku-4-5")
        try:
            deck_payload = {
                "title": "Pandas Basics",
                "cards": [{"front": "What is a DataFrame?", "back": "A 2D table."}],
            }
            route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
                return_value=httpx.Response(200, json=_flashcard_tool_call_response(deck_payload))
            )
            deck = gen.generate_flashcards(source="pandas src", title="Pandas Basics")
            assert isinstance(deck, FlashcardDeck)
            assert deck.title == "Pandas Basics"
            assert len(deck.cards) == 1
            assert route.called
            # Verify wire shape -- this is what catches "tool_choice
            # accidentally optional" regressions.
            sent = route.calls[0].request
            body = json.loads(sent.content)
            assert body["model"] == "anthropic/claude-haiku-4-5"
            assert body["tool_choice"]["function"]["name"] == "emit_flashcard_deck"
            assert body["tools"][0]["function"]["name"] == "emit_flashcard_deck"
        finally:
            gen.close()

    @pytest.mark.usefixtures("openrouter_key")
    @respx.mock
    def test_quiz_round_trip(self) -> None:
        gen = _make_generator("openrouter", "anthropic/claude-haiku-4-5")
        try:
            deck_payload = {
                "title": "Joins",
                "questions": [
                    {
                        "question": "When do you use INNER JOIN?",
                        "answerOptions": [
                            {
                                "text": "When both sides must match",
                                "isCorrect": True,
                                "rationale": "definition",
                            },
                            {"text": "Always", "isCorrect": False, "rationale": "no"},
                        ],
                    }
                ],
            }
            respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
                return_value=httpx.Response(200, json=_quiz_tool_call_response(deck_payload))
            )
            deck = gen.generate_quiz(source="joins src", title="Joins")
            assert isinstance(deck, QuizDeck)
            assert len(deck.questions) == 1
        finally:
            gen.close()


class TestRetry:
    @pytest.mark.usefixtures("openrouter_key")
    @respx.mock
    def test_validation_failure_triggers_correction_then_succeeds(self) -> None:
        gen = _make_generator("openrouter", "anthropic/claude-haiku-4-5")
        try:
            bad_payload = {"title": "X"}  # missing cards array
            good_payload = {
                "title": "X",
                "cards": [{"front": "Q?", "back": "A."}],
            }
            route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
                side_effect=[
                    httpx.Response(200, json=_flashcard_tool_call_response(bad_payload)),
                    httpx.Response(200, json=_flashcard_tool_call_response(good_payload)),
                ]
            )
            deck = gen.generate_flashcards(source="x", title="X")
            assert deck.title == "X"
            assert route.call_count == 2
            # Second request should include the correction context.
            second_body = json.loads(route.calls[1].request.content)
            messages = second_body["messages"]
            # System + user + (assistant bad reply) + correction user.
            # Correction lives in a 'user' message with non-None content.
            assert any(
                m.get("role") == "user"
                and isinstance(m.get("content"), str)
                and "did not validate" in m["content"]
                for m in messages
            )
        finally:
            gen.close()

    @pytest.mark.usefixtures("openrouter_key")
    @respx.mock
    def test_exhausted_retries_raise_card_generation_error(self) -> None:
        gen = _make_generator("openrouter", "anthropic/claude-haiku-4-5")
        try:
            bad = {"title": "X"}  # always fails validation
            respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
                return_value=httpx.Response(200, json=_flashcard_tool_call_response(bad))
            )
            with pytest.raises(CardGenerationError, match="invalid payload"):
                gen.generate_flashcards(source="x", title="X")
        finally:
            gen.close()


class TestErrorHandling:
    @pytest.mark.usefixtures("openrouter_key")
    @respx.mock
    def test_http_error_status_surfaces_card_generation_error(self) -> None:
        gen = _make_generator("openrouter", "anthropic/claude-haiku-4-5")
        try:
            respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
                return_value=httpx.Response(429, text="rate limited")
            )
            with pytest.raises(CardGenerationError, match="HTTP 429"):
                gen.generate_flashcards(source="x", title="X")
        finally:
            gen.close()

    @pytest.mark.usefixtures("openrouter_key")
    @respx.mock
    def test_missing_tool_calls_raises_with_text_content(self) -> None:
        gen = _make_generator("openrouter", "anthropic/claude-haiku-4-5")
        try:
            # Provider returned a plain text reply instead of using the
            # forced tool. Real failure mode for some models.
            respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
                return_value=httpx.Response(
                    200,
                    json={"choices": [{"message": {"role": "assistant", "content": "I refuse."}}]},
                )
            )
            with pytest.raises(CardGenerationError, match="missing tool_calls"):
                gen.generate_flashcards(source="x", title="X")
        finally:
            gen.close()


class TestThinkingTimeout:
    @pytest.mark.usefixtures("openai_key")
    def test_thinking_model_gets_3x_timeout(self) -> None:
        # Pick a thinking model from the OpenAI profile.
        gen = _make_generator("openai", "o3-mini")
        try:
            base = gen._config.request_timeout
            # httpx exposes timeout as a Timeout object; .read holds the
            # configured per-attempt read timeout.
            assert gen._client.timeout.read == base * 3.0
        finally:
            gen.close()

    @pytest.mark.usefixtures("openai_key")
    def test_non_thinking_model_uses_base_timeout(self) -> None:
        gen = _make_generator("openai", "gpt-4o-mini")
        try:
            base = gen._config.request_timeout
            assert gen._client.timeout.read == base
        finally:
            gen.close()


class TestFactoryDispatch:
    @pytest.mark.usefixtures("openrouter_key")
    def test_get_generator_routes_openai_compat_to_adapter(self) -> None:
        from studyloop.content.generators import get_generator

        gen = get_generator(
            CardGeneratorConfig(
                backend="openai_compat",
                provider="openrouter",
                model="anthropic/claude-haiku-4-5",
            )
        )
        try:
            assert isinstance(gen, OpenAICompatGenerator)
        finally:
            gen.close()

    def test_compat_backend_without_provider_raises(self) -> None:
        from studyloop.content.generators import get_generator

        with pytest.raises(ValueError, match=r"requires card_generator\.provider"):
            get_generator(CardGeneratorConfig(backend="openai_compat"))

    def test_provider_adapter_mismatch_raises(self) -> None:
        # anthropic is anthropic_compat; asking for it via openai_compat is a
        # config bug we want to catch loudly at startup.
        from studyloop.content.generators import get_generator

        with pytest.raises(ValueError, match="anthropic_compat"):
            get_generator(
                CardGeneratorConfig(
                    backend="openai_compat",
                    provider="anthropic",
                    model="claude-haiku-4-5",
                )
            )
