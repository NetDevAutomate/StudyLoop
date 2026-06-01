"""Tests for the Anthropic Messages-compatible adapter (U1.5).

HTTP layer is stubbed via ``respx`` so these tests run offline. Live
provider smokes are gated separately by ``@pytest.mark.live_provider``.

Covers the Anthropic Messages provider and the shared adapter robustness
(tool_result-correction retries, inline-XML tool-call fallback, transient-retry)
that any Anthropic-compat shim relies on.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
import respx

from studyloop.content.generators import CardGenerationError
from studyloop.content.generators.anthropic_compat import AnthropicCompatGenerator
from studyloop.content.generators.provider_profiles import get_model, get_profile
from studyloop.content.schemas import FlashcardDeck, QuizDeck
from studyloop.settings import CardGeneratorConfig


@pytest.fixture
def anthropic_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-anthropic")
    yield "test-key-anthropic"


def _tool_use_response(tool_name: str, deck_payload: dict) -> dict:
    """Build a minimal Anthropic Messages response with a tool_use block."""
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": tool_name,
                "input": deck_payload,
            }
        ],
        "model": "claude-haiku-4-5",
        "stop_reason": "tool_use",
    }


def _make_generator(provider: str, model: str) -> AnthropicCompatGenerator:
    profile = get_profile(provider)
    entry = get_model(profile, model)
    cfg = CardGeneratorConfig(
        backend="anthropic_compat",
        provider=provider,
        model=model,
        request_timeout=5.0,
        max_retries=1,
    )
    return AnthropicCompatGenerator(cfg, profile, entry)


class TestAuth:
    def test_missing_env_var_raises_with_actionable_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        # Ensure the encrypted store also has nothing (else the store would
        # satisfy the key and no error would be raised).
        monkeypatch.setattr("studyloop.secrets.get_secret", lambda name: None)
        with pytest.raises(CardGenerationError) as exc:
            _make_generator("anthropic", "claude-haiku-4-5")
        msg = str(exc.value)
        assert "ANTHROPIC_API_KEY" in msg

    def test_reads_key_from_encrypted_store_when_env_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A key in the encrypted store must be consumed even with no env var.

        Regression for the audit gap: adapters read os.environ only and ignored
        the encrypted store, so a key added via the Generate panel had zero
        effect on generation.
        """
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        # Simulate a key present in the encrypted store (get_secret resolves
        # store -> env -> None; here the store wins).
        monkeypatch.setattr(
            "studyloop.secrets.get_secret",
            lambda name: "stored-key-xyz" if name == "anthropic" else None,
        )
        gen = _make_generator("anthropic", "claude-haiku-4-5")
        try:
            assert gen._client.headers["x-api-key"] == "stored-key-xyz"
        finally:
            gen.close()

    def test_missing_everywhere_raises_actionable_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No env var AND no stored key -> actionable error naming both paths."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr("studyloop.secrets.get_secret", lambda name: None)
        with pytest.raises(CardGenerationError) as exc:
            _make_generator("anthropic", "claude-haiku-4-5")
        msg = str(exc.value)
        assert "ANTHROPIC_API_KEY" in msg  # names the env var
        assert "Generate panel" in msg  # points at the new UI affordance

    @pytest.mark.usefixtures("anthropic_key")
    def test_x_api_key_header_set(self) -> None:
        gen = _make_generator("anthropic", "claude-haiku-4-5")
        try:
            assert gen._client.headers["x-api-key"] == "test-key-anthropic"
            # anthropic-version is required by the API.
            assert gen._client.headers["anthropic-version"]
        finally:
            gen.close()


class TestHappyPath:
    @pytest.mark.usefixtures("anthropic_key")
    @respx.mock
    def test_flashcards_round_trip(self) -> None:
        gen = _make_generator("anthropic", "claude-haiku-4-5")
        try:
            deck_payload = {
                "title": "T",
                "cards": [{"front": "Q?", "back": "A."}],
            }
            route = respx.post("https://api.anthropic.com/v1/messages").mock(
                return_value=httpx.Response(
                    200, json=_tool_use_response("emit_flashcard_deck", deck_payload)
                )
            )
            deck = gen.generate_flashcards(source="src", title="T")
            assert isinstance(deck, FlashcardDeck)
            assert deck.title == "T"
            assert route.called
            sent = json.loads(route.calls[0].request.content)
            # Anthropic-specific wire shape that the OpenAI adapter does NOT
            # send. Captures the spec divergence we care about.
            assert sent["model"] == "claude-haiku-4-5"
            assert sent["tool_choice"] == {"type": "tool", "name": "emit_flashcard_deck"}
            assert "system" in sent  # Anthropic puts system at top level
            assert sent["max_tokens"] > 0
            # Thinking field absent for non-thinking model.
            assert "thinking" not in sent
        finally:
            gen.close()

    @pytest.mark.usefixtures("anthropic_key")
    @respx.mock
    def test_quiz_round_trip(self) -> None:
        gen = _make_generator("anthropic", "claude-haiku-4-5")
        try:
            deck_payload = {
                "title": "Joins",
                "questions": [
                    {
                        "question": "When?",
                        "answerOptions": [
                            {"text": "yes", "isCorrect": True, "rationale": "ok"},
                            {"text": "no", "isCorrect": False, "rationale": "not"},
                        ],
                    }
                ],
            }
            respx.post("https://api.anthropic.com/v1/messages").mock(
                return_value=httpx.Response(
                    200, json=_tool_use_response("emit_quiz_deck", deck_payload)
                )
            )
            deck = gen.generate_quiz(source="src", title="Joins")
            assert isinstance(deck, QuizDeck)
            assert len(deck.questions) == 1
        finally:
            gen.close()


class TestRetry:
    @pytest.mark.usefixtures("anthropic_key")
    @respx.mock
    def test_validation_failure_triggers_correction_then_succeeds(self) -> None:
        gen = _make_generator("anthropic", "claude-haiku-4-5")
        try:
            bad = {"title": "X"}  # missing cards
            good = {"title": "X", "cards": [{"front": "Q?", "back": "A."}]}
            route = respx.post("https://api.anthropic.com/v1/messages").mock(
                side_effect=[
                    httpx.Response(
                        200, json=_tool_use_response("emit_flashcard_deck", bad)
                    ),
                    httpx.Response(
                        200, json=_tool_use_response("emit_flashcard_deck", good)
                    ),
                ]
            )
            deck = gen.generate_flashcards(source="x", title="X")
            assert deck.title == "X"
            assert route.call_count == 2
            second_body = json.loads(route.calls[1].request.content)
            messages = second_body["messages"]
            # The correction MUST be delivered as a tool_result block (not a
            # plain-text user turn): Anthropic's protocol requires the user turn
            # after an assistant tool_use to carry a tool_result for that
            # tool_use id. MiniMax's shim enforces this strictly (error 2013).
            corrections = [
                m
                for m in messages
                if m.get("role") == "user" and isinstance(m.get("content"), list)
            ]
            assert corrections, "expected a tool_result correction turn"
            block = corrections[-1]["content"][0]
            assert block["type"] == "tool_result"
            assert block["tool_use_id"] == "toolu_1"  # references the prior tool_use
            assert "did not validate" in block["content"]
            # Protocol sanity: every assistant tool_use turn is immediately
            # followed by a user tool_result turn (valid alternation).
            for i, m in enumerate(messages[:-1]):
                if m.get("role") == "assistant" and isinstance(m.get("content"), list):
                    has_tool_use = any(
                        b.get("type") == "tool_use" for b in m["content"]
                    )
                    if has_tool_use:
                        nxt = messages[i + 1]
                        assert nxt["role"] == "user"
                        assert isinstance(nxt["content"], list)
                        assert nxt["content"][0]["type"] == "tool_result"
        finally:
            gen.close()

    @pytest.mark.usefixtures("anthropic_key")
    @respx.mock
    def test_retry_sends_tool_result_not_plain_text(self) -> None:
        # The schema-correction retry must deliver its correction as a
        # tool_result block, never a plain-text user turn after an assistant
        # tool_use. This is required by the Anthropic Messages protocol;
        # strict Anthropic-compat shims reject the plain-text form outright
        # (this was the MiniMax error-2013 regression, kept as protocol coverage).
        gen = _make_generator("anthropic", "claude-haiku-4-5")
        try:
            bad = {"title": "X"}  # missing cards -> validation fails first
            good = {"title": "X", "cards": [{"front": "Q?", "back": "A."}]}
            route = respx.post("https://api.anthropic.com/v1/messages").mock(
                side_effect=[
                    httpx.Response(
                        200, json=_tool_use_response("emit_flashcard_deck", bad)
                    ),
                    httpx.Response(
                        200, json=_tool_use_response("emit_flashcard_deck", good)
                    ),
                ]
            )
            deck = gen.generate_flashcards(source="x", title="X")
            assert deck.title == "X"
            second_body = json.loads(route.calls[1].request.content)
            # No plain-text user turn allowed after the tool_use.
            for m in second_body["messages"]:
                if m["role"] == "user" and m is not second_body["messages"][0]:
                    assert isinstance(m["content"], list)
                    assert m["content"][0]["type"] == "tool_result"
        finally:
            gen.close()


class TestInlineToolCallFallback:
    """Some Anthropic-compat shims intermittently emit the tool call as inline
    XML markup in a text block (``<…:tool_call><invoke ...><parameter ...>``)
    instead of a native ``tool_use`` block. The adapter must parse this fallback
    so generation doesn't fail when a shim narrates the tool call as text.
    (Originally surfaced on MiniMax M2.7; kept as provider-agnostic coverage.)
    """

    @staticmethod
    def _inline_xml_response(tool_name: str, params: dict) -> dict:
        # A text block whose text is the invoke markup; each param value as JSON.
        param_xml = "".join(
            f'<parameter name="{k}">{json.dumps(v)}</parameter>' for k, v in params.items()
        )
        markup = (
            f"<tool_call>\n<invoke name=\"{tool_name}\">\n{param_xml}\n"
            f"</invoke>\n</tool_call>"
        )
        return {
            "id": "msg_inline",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": markup}],
            "model": "claude-haiku-4-5",
            "stop_reason": "end_turn",
        }

    @pytest.mark.usefixtures("anthropic_key")
    @respx.mock
    def test_inline_xml_quiz_is_parsed(self) -> None:
        gen = _make_generator("anthropic", "claude-haiku-4-5")
        try:
            questions = [
                {
                    "question": "CHAR vs VARCHAR storage?",
                    "answerOptions": [
                        {"text": "CHAR pads", "isCorrect": True, "rationale": "fixed width"},
                        {"text": "VARCHAR pads", "isCorrect": False, "rationale": "no"},
                    ],
                }
            ]
            respx.post("https://api.anthropic.com/v1/messages").mock(
                return_value=httpx.Response(
                    200,
                    json=self._inline_xml_response("emit_quiz_deck", {
                        "title": "DT", "questions": questions,
                    }),
                )
            )
            deck = gen.generate_quiz(source="src", title="DT")
            assert isinstance(deck, QuizDeck)
            assert deck.title == "DT"
            assert len(deck.questions) == 1
            assert deck.questions[0].answer_options[0].is_correct is True
        finally:
            gen.close()

    @pytest.mark.usefixtures("anthropic_key")
    @respx.mock
    def test_inline_xml_flashcards_is_parsed(self) -> None:
        gen = _make_generator("anthropic", "claude-haiku-4-5")
        try:
            cards = [{"front": "Q?", "back": "A."}, {"front": "Q2?", "back": "A2."}]
            respx.post("https://api.anthropic.com/v1/messages").mock(
                return_value=httpx.Response(
                    200,
                    json=self._inline_xml_response("emit_flashcard_deck", {
                        "title": "T", "cards": cards,
                    }),
                )
            )
            deck = gen.generate_flashcards(source="src", title="T")
            assert isinstance(deck, FlashcardDeck)
            assert len(deck.cards) == 2
        finally:
            gen.close()

    @pytest.mark.usefixtures("anthropic_key")
    @respx.mock
    def test_transient_extraction_failure_is_retried(self) -> None:
        # A shim may intermittently return an unparseable response (no tool_use,
        # no recognisable inline markup). A single bad emission must NOT hard-fail
        # the whole generation — the adapter retries within its budget and
        # succeeds on the next, valid response.
        gen = _make_generator("anthropic", "claude-haiku-4-5")  # default max_retries=2
        try:
            garbled = {
                "content": [{"type": "text", "text": "thinking out loud, no tool here"}],
                "role": "assistant",
            }
            good = _tool_use_response(
                "emit_flashcard_deck", {"title": "T", "cards": [{"front": "Q?", "back": "A."}]}
            )
            route = respx.post("https://api.anthropic.com/v1/messages").mock(
                side_effect=[
                    httpx.Response(200, json=garbled),  # transient bad emission
                    httpx.Response(200, json=good),      # retry succeeds
                ]
            )
            deck = gen.generate_flashcards(source="x", title="T")
            assert deck.title == "T"
            assert route.call_count == 2  # proved it retried, didn't hard-fail
        finally:
            gen.close()

    @pytest.mark.usefixtures("anthropic_key")
    @respx.mock
    def test_genuinely_textonly_still_raises(self) -> None:
        # A real refusal (no invoke markup) must still raise — the fallback is
        # narrow and must not swallow genuine no-tool responses.
        gen = _make_generator("anthropic", "claude-haiku-4-5")
        try:
            respx.post("https://api.anthropic.com/v1/messages").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "content": [{"type": "text", "text": "I cannot help with that."}],
                        "role": "assistant",
                    },
                )
            )
            with pytest.raises(CardGenerationError, match="missing tool_use"):
                gen.generate_flashcards(source="x", title="X")
        finally:
            gen.close()


class TestErrorHandling:
    @pytest.mark.usefixtures("anthropic_key")
    @respx.mock
    def test_http_429_surfaces(self) -> None:
        gen = _make_generator("anthropic", "claude-haiku-4-5")
        try:
            respx.post("https://api.anthropic.com/v1/messages").mock(
                return_value=httpx.Response(429, text="rate limited")
            )
            with pytest.raises(CardGenerationError, match="HTTP 429"):
                gen.generate_flashcards(source="x", title="X")
        finally:
            gen.close()

    @pytest.mark.usefixtures("anthropic_key")
    @respx.mock
    def test_text_only_response_raises_with_text_preview(self) -> None:
        # Anthropic returned text instead of using the forced tool.
        gen = _make_generator("anthropic", "claude-haiku-4-5")
        try:
            respx.post("https://api.anthropic.com/v1/messages").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "content": [{"type": "text", "text": "I refuse to use tools."}],
                        "role": "assistant",
                    },
                )
            )
            with pytest.raises(CardGenerationError, match="missing tool_use"):
                gen.generate_flashcards(source="x", title="X")
        finally:
            gen.close()


class TestFactoryDispatch:
    @pytest.mark.usefixtures("anthropic_key")
    def test_get_generator_routes_anthropic_compat_to_adapter(self) -> None:
        from studyloop.content.generators import get_generator

        gen = get_generator(
            CardGeneratorConfig(
                backend="anthropic_compat",
                provider="anthropic",
                model="claude-haiku-4-5",
            )
        )
        try:
            assert isinstance(gen, AnthropicCompatGenerator)
        finally:
            gen.close()

    @pytest.mark.usefixtures("anthropic_key")
    def test_default_model_used_when_model_field_empty(self) -> None:
        from studyloop.content.generators import get_generator

        gen = get_generator(
            CardGeneratorConfig(
                backend="anthropic_compat",
                provider="anthropic",
                # No model set -- should default to first cheap entry.
            )
        )
        try:
            assert gen._model.cost_tier == "cheap"
        finally:
            gen.close()
