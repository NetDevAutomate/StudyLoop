"""Tests for the card-generator Protocol, Ollama backend, and factory (D2).

Most tests mock the HTTP transport so they run offline in CI. One
integration-marked test hits a real localhost Ollama and is deselected
by default via ``addopts = "-m 'not integration'"`` in pyproject.toml.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

pydantic = pytest.importorskip("pydantic")
httpx = pytest.importorskip("httpx")


from studyctl.content.generators import (  # noqa: E402
    CardGenerationError,
    CardGenerator,
    get_generator,
)
from studyctl.content.generators.ollama import OllamaGenerator  # noqa: E402
from studyctl.content.schemas import FlashcardDeck, QuizDeck  # noqa: E402
from studyctl.settings import CardGeneratorConfig, OllamaBackendConfig  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config() -> CardGeneratorConfig:
    """Default config with short timeout -- unit tests should never hit the net."""
    return CardGeneratorConfig(
        backend="ollama",
        temperature=0.1,
        max_retries=2,
        request_timeout=5.0,
        ollama=OllamaBackendConfig(
            base_url="http://test-ollama:11434",
            model="qwen2.5:14b",
        ),
    )


@pytest.fixture
def valid_flashcard_json() -> str:
    return json.dumps(
        {
            "title": "Python Collections",
            "cards": [
                {"front": "What does Counter do?", "back": "Counts hashable objects."},
                {
                    "front": "When to use deque?",
                    "back": "Fast appends and pops at both ends.",
                },
            ],
        }
    )


@pytest.fixture
def valid_quiz_json() -> str:
    return json.dumps(
        {
            "title": "Python Collections",
            "questions": [
                {
                    "question": "Which collection is O(1) for left-append?",
                    "hint": "Think double-ended queues.",
                    "answerOptions": [
                        {
                            "text": "list",
                            "isCorrect": False,
                            "rationale": "list.insert(0, x) is O(n).",
                        },
                        {
                            "text": "deque",
                            "isCorrect": True,
                            "rationale": "deque.appendleft is O(1).",
                        },
                        {
                            "text": "tuple",
                            "isCorrect": False,
                            "rationale": "tuples are immutable.",
                        },
                        {
                            "text": "set",
                            "isCorrect": False,
                            "rationale": "sets are unordered.",
                        },
                    ],
                }
            ],
        }
    )


def _ollama_chat_response(content: str) -> dict[str, Any]:
    """Shape of a non-streaming /api/chat response -- only the fields we read."""
    return {
        "model": "qwen2.5:14b",
        "message": {"role": "assistant", "content": content},
        "done": True,
    }


def _make_generator(
    config: CardGeneratorConfig,
    handler: httpx.MockTransport,
) -> OllamaGenerator:
    """Build an OllamaGenerator with the httpx client swapped for a mock."""
    gen = OllamaGenerator(config)
    gen._client.close()
    gen._client = httpx.Client(base_url=config.ollama.base_url, transport=handler)
    return gen


# ---------------------------------------------------------------------------
# Protocol + factory tests
# ---------------------------------------------------------------------------


class TestFactory:
    def test_returns_ollama_generator_for_ollama_backend(self, config: CardGeneratorConfig) -> None:
        gen = get_generator(config)
        assert isinstance(gen, OllamaGenerator)
        gen.close()

    def test_structural_protocol_compliance(self, config: CardGeneratorConfig) -> None:
        """``OllamaGenerator`` satisfies the ``CardGenerator`` Protocol."""
        gen = get_generator(config)
        try:
            assert isinstance(gen, CardGenerator)
        finally:
            gen.close()

    def test_unknown_backend_raises_valueerror(self) -> None:
        cfg = CardGeneratorConfig(backend="definitely-not-a-backend")
        with pytest.raises(ValueError, match=r"Unknown card_generator\.backend"):
            get_generator(cfg)

    def test_backend_name_is_case_insensitive(self) -> None:
        cfg = CardGeneratorConfig(backend="Ollama")
        gen = get_generator(cfg)
        assert isinstance(gen, OllamaGenerator)
        gen.close()


# ---------------------------------------------------------------------------
# OllamaGenerator -- happy paths
# ---------------------------------------------------------------------------


class TestGenerateFlashcardsHappyPath:
    def test_valid_response_produces_flashcard_deck(
        self,
        config: CardGeneratorConfig,
        valid_flashcard_json: str,
    ) -> None:
        captured_requests: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append(json.loads(request.content))
            return httpx.Response(200, json=_ollama_chat_response(valid_flashcard_json))

        gen = _make_generator(config, httpx.MockTransport(handler))
        try:
            deck = gen.generate_flashcards(
                source="# Python Collections\n\ndeque is great for queues.",
                title="Python Collections",
            )
        finally:
            gen.close()

        assert isinstance(deck, FlashcardDeck)
        assert deck.title == "Python Collections"
        assert len(deck.cards) == 2
        assert deck.cards[0].front.startswith("What does Counter")

        # Verify the request shape: endpoint, model, format (schema), temperature.
        assert len(captured_requests) == 1
        req = captured_requests[0]
        assert req["model"] == "qwen2.5:14b"
        assert req["stream"] is False
        assert req["options"]["temperature"] == pytest.approx(0.1)
        # format is the pydantic JSON schema -- must be a dict, not the literal "json"
        assert isinstance(req["format"], dict)
        assert "properties" in req["format"]
        # messages: system + user
        assert [m["role"] for m in req["messages"]] == ["system", "user"]
        assert "expert educator" in req["messages"][0]["content"]
        assert "Python Collections" in req["messages"][1]["content"]

    def test_caller_title_overrides_model_title(
        self,
        config: CardGeneratorConfig,
    ) -> None:
        """Generator overwrites model-chosen title with the caller's title."""
        payload = json.dumps(
            {
                "title": "Model Picked A Different Title",
                "cards": [{"front": "Q?", "back": "A."}],
            }
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_ollama_chat_response(payload))

        gen = _make_generator(config, httpx.MockTransport(handler))
        try:
            deck = gen.generate_flashcards(source="stuff", title="Caller Title")
        finally:
            gen.close()

        assert deck.title == "Caller Title"


class TestGenerateQuizHappyPath:
    def test_valid_response_produces_quiz_deck(
        self,
        config: CardGeneratorConfig,
        valid_quiz_json: str,
    ) -> None:
        captured_requests: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append(json.loads(request.content))
            return httpx.Response(200, json=_ollama_chat_response(valid_quiz_json))

        gen = _make_generator(config, httpx.MockTransport(handler))
        try:
            deck = gen.generate_quiz(source="Source", title="Python Collections")
        finally:
            gen.close()

        assert isinstance(deck, QuizDeck)
        assert len(deck.questions) == 1
        q = deck.questions[0]
        assert len(q.answer_options) == 4
        correct = [o for o in q.answer_options if o.is_correct]
        assert len(correct) == 1
        assert correct[0].text == "deque"

        # Quiz uses the quiz system prompt, not the flashcard one.
        req = captured_requests[0]
        assert "quiz" in req["messages"][0]["content"].lower()


# ---------------------------------------------------------------------------
# OllamaGenerator -- retry / recovery behaviour
# ---------------------------------------------------------------------------


class TestRetries:
    def test_malformed_json_then_valid_recovers(
        self,
        config: CardGeneratorConfig,
        valid_flashcard_json: str,
    ) -> None:
        responses = iter(
            [
                _ollama_chat_response("this is not JSON at all"),
                _ollama_chat_response(valid_flashcard_json),
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=next(responses))

        gen = _make_generator(config, httpx.MockTransport(handler))
        try:
            deck = gen.generate_flashcards(source="src", title="T")
        finally:
            gen.close()

        assert deck.title == "T"

    def test_schema_violation_then_valid_recovers(
        self,
        config: CardGeneratorConfig,
        valid_flashcard_json: str,
    ) -> None:
        # First response is valid JSON but wrong schema (empty cards list).
        bad_then_good = iter(
            [
                _ollama_chat_response(json.dumps({"title": "T", "cards": []})),
                _ollama_chat_response(valid_flashcard_json),
            ]
        )
        captured_messages: list[list[dict[str, str]]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            captured_messages.append(payload["messages"])
            return httpx.Response(200, json=next(bad_then_good))

        gen = _make_generator(config, httpx.MockTransport(handler))
        try:
            deck = gen.generate_flashcards(source="src", title="T")
        finally:
            gen.close()

        assert deck is not None
        # Second call should include the assistant's bad reply and a correction turn.
        second_call = captured_messages[1]
        assert [m["role"] for m in second_call] == [
            "system",
            "user",
            "assistant",
            "user",
        ]
        assert "invalid" in second_call[-1]["content"].lower()

    def test_exhausted_retries_raises_cardgenerationerror(
        self, config: CardGeneratorConfig
    ) -> None:
        # Always returns garbage.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_ollama_chat_response("nope"))

        gen = _make_generator(config, httpx.MockTransport(handler))
        try:
            with pytest.raises(CardGenerationError, match="failed to produce"):
                gen.generate_flashcards(source="src", title="T")
        finally:
            gen.close()


# ---------------------------------------------------------------------------
# OllamaGenerator -- transport / error surface
# ---------------------------------------------------------------------------


class TestTransportErrors:
    def test_connect_error_raises_cardgenerationerror(self, config: CardGeneratorConfig) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        gen = _make_generator(config, httpx.MockTransport(handler))
        try:
            with pytest.raises(CardGenerationError, match="Could not reach Ollama"):
                gen.generate_flashcards(source="src", title="T")
        finally:
            gen.close()

    def test_http_500_raises_cardgenerationerror(self, config: CardGeneratorConfig) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        gen = _make_generator(config, httpx.MockTransport(handler))
        try:
            with pytest.raises(CardGenerationError, match="HTTP 500"):
                gen.generate_flashcards(source="src", title="T")
        finally:
            gen.close()

    def test_http_404_model_not_found_raises_cardgenerationerror(
        self, config: CardGeneratorConfig
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "model 'qwen2.5:14b' not found"})

        gen = _make_generator(config, httpx.MockTransport(handler))
        try:
            with pytest.raises(CardGenerationError, match="HTTP 404"):
                gen.generate_flashcards(source="src", title="T")
        finally:
            gen.close()

    def test_missing_message_content_raises_cardgenerationerror(
        self, config: CardGeneratorConfig
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"model": "x", "message": {}, "done": True})

        gen = _make_generator(config, httpx.MockTransport(handler))
        try:
            with pytest.raises(CardGenerationError, match="missing string"):
                gen.generate_flashcards(source="src", title="T")
        finally:
            gen.close()

    def test_non_json_200_response_raises_cardgenerationerror(
        self, config: CardGeneratorConfig
    ) -> None:
        """A 200 response that is not valid JSON (e.g., proxy error page)
        must surface as ``CardGenerationError``, not a raw ``JSONDecodeError``."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                text="<html><body>Gateway proxy error</body></html>",
                headers={"content-type": "text/html"},
            )

        gen = _make_generator(config, httpx.MockTransport(handler))
        try:
            with pytest.raises(CardGenerationError, match="non-JSON response"):
                gen.generate_flashcards(source="src", title="T")
        finally:
            gen.close()


# ---------------------------------------------------------------------------
# OllamaGenerator -- context manager
# ---------------------------------------------------------------------------


class TestContextManager:
    def test_with_statement_closes_client(
        self,
        config: CardGeneratorConfig,
        valid_flashcard_json: str,
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_ollama_chat_response(valid_flashcard_json))

        with OllamaGenerator(config) as gen:
            # Swap in mock transport so the test runs offline.
            gen._client.close()
            gen._client = httpx.Client(
                base_url=config.ollama.base_url, transport=httpx.MockTransport(handler)
            )
            deck = gen.generate_flashcards(source="src", title="T")
            assert deck.title == "T"
            assert not gen._client.is_closed

        # After the `with` block exits, the client must be closed.
        assert gen._client.is_closed

    def test_close_is_idempotent(self, config: CardGeneratorConfig) -> None:
        gen = OllamaGenerator(config)
        gen.close()
        # Second close must not raise.
        gen.close()
        assert gen._client.is_closed


# ---------------------------------------------------------------------------
# Live integration test -- requires real Ollama. Deselected by default.
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestLiveOllama:
    """Hit a real local Ollama at ``localhost:11434``.

    Run with: ``pytest -m integration tests/test_content_generators.py``.
    Requires the configured model to be pulled (``ollama pull qwen2.5:7b``
    for a quick run; the default is ``qwen2.5:14b``).
    """

    def test_generate_flashcards_against_real_ollama(self) -> None:
        cfg = CardGeneratorConfig(
            # Use the smaller model for a faster integration check.
            ollama=OllamaBackendConfig(model="qwen2.5:7b"),
            request_timeout=120.0,
        )
        gen = OllamaGenerator(cfg)
        source = (
            "# Python `collections.Counter`\n\n"
            "`Counter` is a dict subclass for counting hashable objects. "
            "Construct from any iterable. Common methods: `most_common(n)`, "
            "`elements()`, arithmetic operators for multiset operations."
        )
        try:
            deck = gen.generate_flashcards(source=source, title="Python Counter basics")
        finally:
            gen.close()

        assert isinstance(deck, FlashcardDeck)
        assert deck.title == "Python Counter basics"
        assert len(deck.cards) >= 3
