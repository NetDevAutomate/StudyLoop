"""Unit tests for :class:`BedrockGenerator`.

Uses ``botocore.stub.Stubber`` to mock the ``bedrock-runtime.converse``
call so tests run offline. The stubber validates that our code sends
the expected request shape too, which is important because Converse's
tool-use wire format is strict.

One integration-marked test hits real Bedrock; deselected by default.
"""

from __future__ import annotations

from typing import Any

import pytest

pydantic = pytest.importorskip("pydantic")
boto3 = pytest.importorskip("boto3")
botocore = pytest.importorskip("botocore")

from botocore.stub import Stubber  # noqa: E402

from studyctl.content.generators import (  # noqa: E402
    CardGenerationError,
    CardGenerator,
    get_generator,
)
from studyctl.content.generators.bedrock import (  # noqa: E402
    _FLASHCARD_TOOL_NAME,
    _QUIZ_TOOL_NAME,
    BedrockGenerator,
)
from studyctl.content.schemas import FlashcardDeck, QuizDeck  # noqa: E402
from studyctl.settings import BedrockBackendConfig, CardGeneratorConfig  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config() -> CardGeneratorConfig:
    """Bedrock-backed config with profile-fallback disabled for tests."""
    return CardGeneratorConfig(
        backend="bedrock",
        temperature=0.1,
        max_retries=2,
        request_timeout=30.0,
        bedrock=BedrockBackendConfig(
            model="us.anthropic.claude-sonnet-4-6",
            region="us-east-1",
            profile="bedrock-prod",
            profile_fallback="",
            max_tokens=4000,
            # Region fallback disabled by default in unit tests.
            fallback_region="",
            fallback_model="",
        ),
    )


@pytest.fixture
def config_with_region_fallback() -> CardGeneratorConfig:
    """Bedrock-backed config with eu-west-1 fallback enabled."""
    return CardGeneratorConfig(
        backend="bedrock",
        temperature=0.1,
        max_retries=0,  # keep tests tight; one attempt per call
        request_timeout=30.0,
        bedrock=BedrockBackendConfig(
            model="us.anthropic.claude-sonnet-4-6",
            region="us-east-1",
            profile="bedrock-prod",
            profile_fallback="",
            max_tokens=4000,
            fallback_region="eu-west-1",
            fallback_model="eu.anthropic.claude-sonnet-4-6",
        ),
    )


@pytest.fixture
def valid_flashcard_payload() -> dict:
    return {
        "title": "Python Collections",
        "cards": [
            {"front": "What does Counter do?", "back": "Counts hashable objects."},
            {
                "front": "When to use deque?",
                "back": "Fast appends and pops at both ends.",
            },
        ],
    }


@pytest.fixture
def valid_quiz_payload() -> dict:
    return {
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


def _converse_tool_use_response(
    *,
    tool_name: str,
    tool_input: dict,
    tool_use_id: str = "tu-1",
    stop_reason: str = "tool_use",
) -> dict[str, Any]:
    """Shape of a Converse response where the model invoked our forced tool."""
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": tool_use_id,
                            "name": tool_name,
                            "input": tool_input,
                        }
                    }
                ],
            }
        },
        "stopReason": stop_reason,
        "usage": {"inputTokens": 100, "outputTokens": 50, "totalTokens": 150},
        "metrics": {"latencyMs": 500},
    }


def _make_stubbed_generator(
    config: CardGeneratorConfig,
) -> tuple[BedrockGenerator, Stubber]:
    """Build a BedrockGenerator whose ``_client`` is a stubbed bedrock-runtime.

    Avoids the real ``_build_client`` path (which wants AWS creds) by
    constructing the object with ``__new__`` and wiring fields manually.
    Unit tests that don't exercise the region-fallback path leave the
    fallback client unset (``None``) so a throttle on the primary
    propagates immediately instead of trying to hit a second stub.
    """
    gen = BedrockGenerator.__new__(BedrockGenerator)
    gen._config = config  # type: ignore[attr-defined]
    gen._bedrock = config.bedrock  # type: ignore[attr-defined]
    client = boto3.client(
        "bedrock-runtime",
        region_name=config.bedrock.region,
        aws_access_key_id="test",
        aws_secret_access_key="test",  # pragma: allowlist secret
    )
    gen._client = client  # type: ignore[attr-defined]
    gen._client_model = config.bedrock.model  # type: ignore[attr-defined]
    gen._fallback_client = None  # type: ignore[attr-defined]
    gen._fallback_model = None  # type: ignore[attr-defined]
    stubber = Stubber(client)
    return gen, stubber


def _make_stubbed_generator_with_fallback(
    config: CardGeneratorConfig,
) -> tuple[BedrockGenerator, Stubber, Stubber]:
    """Build a BedrockGenerator with both primary and fallback stubbed.

    Used by the region-fallback tests. Returns ``(gen, primary_stubber,
    fallback_stubber)``.
    """
    gen = BedrockGenerator.__new__(BedrockGenerator)
    gen._config = config  # type: ignore[attr-defined]
    gen._bedrock = config.bedrock  # type: ignore[attr-defined]
    primary = boto3.client(
        "bedrock-runtime",
        region_name=config.bedrock.region,
        aws_access_key_id="test",
        aws_secret_access_key="test",  # pragma: allowlist secret
    )
    fallback = boto3.client(
        "bedrock-runtime",
        region_name=config.bedrock.fallback_region or "eu-west-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",  # pragma: allowlist secret
    )
    gen._client = primary  # type: ignore[attr-defined]
    gen._client_model = config.bedrock.model  # type: ignore[attr-defined]
    gen._fallback_client = fallback  # type: ignore[attr-defined]
    gen._fallback_model = config.bedrock.fallback_model  # type: ignore[attr-defined]
    return gen, Stubber(primary), Stubber(fallback)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestFactory:
    def test_factory_returns_bedrock_generator_for_bedrock_backend(
        self, config: CardGeneratorConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Factory dispatch returns a BedrockGenerator for backend='bedrock'.

        Stubs out ``_build_client`` so the test doesn't touch real AWS
        credentials -- we're verifying routing, not AWS connectivity.
        ``_build_client`` now takes keyword args (region, model) and
        returns a ``(client, model)`` tuple.
        """
        monkeypatch.setattr(
            BedrockGenerator,
            "_build_client",
            lambda self, *, region, model: (object(), model),
        )
        gen = get_generator(config)
        try:
            assert isinstance(gen, BedrockGenerator)
            assert isinstance(gen, CardGenerator)
        finally:
            gen.close()


# ---------------------------------------------------------------------------
# Happy-path generation
# ---------------------------------------------------------------------------


class TestGenerateFlashcardsHappyPath:
    def test_valid_tool_use_response_produces_flashcard_deck(
        self,
        config: CardGeneratorConfig,
        valid_flashcard_payload: dict,
    ) -> None:
        gen, stubber = _make_stubbed_generator(config)
        stubber.add_response(
            "converse",
            _converse_tool_use_response(
                tool_name=_FLASHCARD_TOOL_NAME,
                tool_input=valid_flashcard_payload,
            ),
        )

        with stubber:
            deck = gen.generate_flashcards(source="src", title="Python Collections")

        assert isinstance(deck, FlashcardDeck)
        assert deck.title == "Python Collections"
        assert len(deck.cards) == 2

    def test_caller_title_overrides_model_title(
        self,
        config: CardGeneratorConfig,
    ) -> None:
        """Bedrock backend must overwrite model-chosen title with caller's title."""
        payload = {
            "title": "Model Picked Different",
            "cards": [{"front": "Q?", "back": "A."}],
        }
        gen, stubber = _make_stubbed_generator(config)
        stubber.add_response(
            "converse",
            _converse_tool_use_response(tool_name=_FLASHCARD_TOOL_NAME, tool_input=payload),
        )
        with stubber:
            deck = gen.generate_flashcards(source="src", title="Caller Wins")
        assert deck.title == "Caller Wins"


class TestGenerateQuizHappyPath:
    def test_valid_tool_use_response_produces_quiz_deck(
        self,
        config: CardGeneratorConfig,
        valid_quiz_payload: dict,
    ) -> None:
        gen, stubber = _make_stubbed_generator(config)
        stubber.add_response(
            "converse",
            _converse_tool_use_response(tool_name=_QUIZ_TOOL_NAME, tool_input=valid_quiz_payload),
        )
        with stubber:
            deck = gen.generate_quiz(source="src", title="Python Collections")
        assert isinstance(deck, QuizDeck)
        assert len(deck.questions) == 1
        correct = [o for o in deck.questions[0].answer_options if o.is_correct]
        assert len(correct) == 1
        assert correct[0].text == "deque"


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------


class TestRetries:
    def test_schema_violation_then_valid_recovers(
        self,
        config: CardGeneratorConfig,
        valid_flashcard_payload: dict,
    ) -> None:
        # First response has an empty cards list -- valid JSON, wrong schema.
        bad_payload = {"title": "T", "cards": []}

        gen, stubber = _make_stubbed_generator(config)
        stubber.add_response(
            "converse",
            _converse_tool_use_response(tool_name=_FLASHCARD_TOOL_NAME, tool_input=bad_payload),
        )
        stubber.add_response(
            "converse",
            _converse_tool_use_response(
                tool_name=_FLASHCARD_TOOL_NAME, tool_input=valid_flashcard_payload
            ),
        )

        with stubber:
            deck = gen.generate_flashcards(source="src", title="T")
        assert deck.title == "T"

    def test_exhausted_retries_raises_cardgenerationerror(
        self, config: CardGeneratorConfig
    ) -> None:
        bad_payload = {"title": "T", "cards": []}

        gen, stubber = _make_stubbed_generator(config)
        # max_retries=2 → 3 total attempts → 3 stubbed responses.
        for _ in range(config.max_retries + 1):
            stubber.add_response(
                "converse",
                _converse_tool_use_response(tool_name=_FLASHCARD_TOOL_NAME, tool_input=bad_payload),
            )

        with stubber, pytest.raises(CardGenerationError, match="failed to produce valid output"):
            gen.generate_flashcards(source="src", title="T")

    def test_quiz_schema_violation_then_valid_recovers(
        self,
        config: CardGeneratorConfig,
        valid_quiz_payload: dict,
    ) -> None:
        """Quiz-specific retry. The quiz schema has nested ``answerOptions``
        with a camelCase ``isCorrect`` alias -- verify retry handles this
        shape correctly (not just the flashcard shape)."""
        # Bad payload: zero correct options -- violates _check_exactly_one_correct.
        bad_payload = {
            "title": "T",
            "questions": [
                {
                    "question": "Q?",
                    "answerOptions": [
                        {"text": "A", "isCorrect": False},
                        {"text": "B", "isCorrect": False},
                    ],
                }
            ],
        }
        gen, stubber = _make_stubbed_generator(config)
        stubber.add_response(
            "converse",
            _converse_tool_use_response(tool_name=_QUIZ_TOOL_NAME, tool_input=bad_payload),
        )
        stubber.add_response(
            "converse",
            _converse_tool_use_response(tool_name=_QUIZ_TOOL_NAME, tool_input=valid_quiz_payload),
        )

        with stubber:
            deck = gen.generate_quiz(source="src", title="T")
        assert deck.title == "T"
        assert len(deck.questions[0].answer_options) == 4


# ---------------------------------------------------------------------------
# Error surface
# ---------------------------------------------------------------------------


class TestErrors:
    def test_client_error_raises_cardgenerationerror(self, config: CardGeneratorConfig) -> None:
        gen, stubber = _make_stubbed_generator(config)
        stubber.add_client_error(
            "converse",
            service_error_code="AccessDeniedException",
            service_message="You do not have access to model ...",
            http_status_code=403,
        )
        with stubber, pytest.raises(CardGenerationError, match="AccessDeniedException"):
            gen.generate_flashcards(source="src", title="T")

    def test_throttling_raises_cardgenerationerror(self, config: CardGeneratorConfig) -> None:
        gen, stubber = _make_stubbed_generator(config)
        stubber.add_client_error(
            "converse",
            service_error_code="ThrottlingException",
            service_message="Rate exceeded",
            http_status_code=429,
        )
        with stubber, pytest.raises(CardGenerationError, match="ThrottlingException"):
            gen.generate_flashcards(source="src", title="T")

    def test_missing_tool_use_raises_cardgenerationerror(self, config: CardGeneratorConfig) -> None:
        """Model ignored toolChoice and emitted plain text instead."""
        response_without_tool_use = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": "I refuse to emit JSON."}],
                }
            },
            "stopReason": "end_turn",
            "usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15},
            "metrics": {"latencyMs": 100},
        }
        gen, stubber = _make_stubbed_generator(config)
        stubber.add_response("converse", response_without_tool_use)
        with stubber, pytest.raises(CardGenerationError, match="did not call the forced tool"):
            gen.generate_flashcards(source="src", title="T")

    def test_tool_input_not_a_dict_raises_cardgenerationerror(
        self, config: CardGeneratorConfig
    ) -> None:
        """Defensive: boto3 can't actually produce this, but guard anyway."""
        weird_response = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": "x",
                                "name": _FLASHCARD_TOOL_NAME,
                                "input": "not a dict",
                            }
                        }
                    ],
                }
            },
            "stopReason": "tool_use",
            "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
            "metrics": {"latencyMs": 50},
        }
        gen, stubber = _make_stubbed_generator(config)
        stubber.add_response("converse", weird_response)
        with stubber, pytest.raises(CardGenerationError, match="not a dict"):
            gen.generate_flashcards(source="src", title="T")


# ---------------------------------------------------------------------------
# Profile fallback
# ---------------------------------------------------------------------------


class TestProfileFallback:
    def test_missing_bedrock_extra_raises_helpful_error(
        self, monkeypatch: pytest.MonkeyPatch, config: CardGeneratorConfig
    ) -> None:
        """If boto3 import fails, surface a 'pip install studyctl[bedrock]' hint."""
        import builtins

        real_import = builtins.__import__

        def blocked_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "boto3":
                raise ImportError("no boto3")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocked_import)

        with pytest.raises(CardGenerationError, match=r"pip install 'studyctl\[bedrock\]'"):
            BedrockGenerator(config)

    def test_both_profiles_missing_raises_cardgenerationerror(
        self, config: CardGeneratorConfig
    ) -> None:
        cfg = CardGeneratorConfig(
            backend="bedrock",
            bedrock=BedrockBackendConfig(
                profile="this-profile-does-not-exist-xyz",
                profile_fallback="also-does-not-exist-abc",
            ),
        )
        with pytest.raises(CardGenerationError, match="Could not authenticate"):
            BedrockGenerator(cfg)


# ---------------------------------------------------------------------------
# Region fallback on throttle
# ---------------------------------------------------------------------------


class TestRegionFallback:
    def test_throttle_falls_back_to_secondary_region(
        self,
        config_with_region_fallback: CardGeneratorConfig,
        valid_flashcard_payload: dict,
    ) -> None:
        """Primary throttled → fallback region returns valid response."""
        gen, primary, fallback = _make_stubbed_generator_with_fallback(config_with_region_fallback)
        primary.add_client_error(
            "converse",
            service_error_code="ThrottlingException",
            service_message="Rate exceeded for inference profile",
            http_status_code=429,
        )
        fallback.add_response(
            "converse",
            _converse_tool_use_response(
                tool_name=_FLASHCARD_TOOL_NAME, tool_input=valid_flashcard_payload
            ),
        )
        with primary, fallback:
            deck = gen.generate_flashcards(source="src", title="T")
        assert deck.title == "T"
        primary.assert_no_pending_responses()
        fallback.assert_no_pending_responses()

    def test_non_throttle_error_does_not_fall_back(
        self, config_with_region_fallback: CardGeneratorConfig
    ) -> None:
        """AccessDeniedException → propagates immediately, no fallback.

        Fallback is only for capacity issues. Auth problems in the
        primary region will still fail in the fallback (same account,
        same IAM).
        """
        gen, primary, fallback = _make_stubbed_generator_with_fallback(config_with_region_fallback)
        primary.add_client_error(
            "converse",
            service_error_code="AccessDeniedException",
            service_message="You do not have access to model",
            http_status_code=403,
        )
        # fallback should never be called -- no response queued
        with primary, fallback, pytest.raises(CardGenerationError, match="AccessDeniedException"):
            gen.generate_flashcards(source="src", title="T")
        primary.assert_no_pending_responses()
        # assert_no_pending_responses passes on unused stubber too

    def test_throttle_without_fallback_configured_propagates(
        self,
        config: CardGeneratorConfig,  # fallback_region="" via fixture
    ) -> None:
        """Throttle on primary with no fallback configured → surface the error."""
        gen, stubber = _make_stubbed_generator(config)
        stubber.add_client_error(
            "converse",
            service_error_code="ThrottlingException",
            service_message="Rate exceeded",
            http_status_code=429,
        )
        with stubber, pytest.raises(CardGenerationError, match="ThrottlingException"):
            gen.generate_flashcards(source="src", title="T")


# ---------------------------------------------------------------------------
# Live integration test -- requires real Bedrock + bedrock-prod profile.
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestLiveBedrock:
    """Hits real Bedrock using the ``bedrock-prod`` profile.

    Run with: ``pytest -m integration tests/test_content_generators_bedrock.py``.
    Requires AWS credentials configured and model access enabled in the
    configured region.
    """

    def test_generate_flashcards_against_real_bedrock(self) -> None:
        cfg = CardGeneratorConfig(
            backend="bedrock",
            max_retries=1,
            bedrock=BedrockBackendConfig(
                model="us.anthropic.claude-sonnet-4-6",
                region="us-east-1",
                profile="bedrock-prod",
                profile_fallback="bedrock-local",
            ),
        )
        gen = BedrockGenerator(cfg)
        source = (
            "# Python `collections.Counter`\n\n"
            "`Counter` is a dict subclass for counting hashable objects. "
            "Common methods: `most_common(n)`, `elements()`, arithmetic "
            "operators for multiset operations."
        )
        try:
            deck = gen.generate_flashcards(source=source, title="Python Counter basics")
        finally:
            gen.close()

        assert isinstance(deck, FlashcardDeck)
        assert deck.title == "Python Counter basics"
        assert len(deck.cards) >= 3
