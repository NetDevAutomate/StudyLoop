"""Tests for the stub generator backend (U1).

The stub satisfies the ``CardGenerator`` Protocol with deterministic,
title-keyed output -- no HTTP, no I/O. Used by the rest of the
generation-panel suite (U2-U11) so the producer pipeline can be
exercised end-to-end without burning Ollama time or Bedrock dollars.
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("pydantic")

from studyloop.content.generators import (  # noqa: E402
    CardGenerationError,
    CardGenerator,
    get_generator,
)
from studyloop.content.generators.stub import StubGenerator  # noqa: E402
from studyloop.content.schemas import FlashcardDeck, QuizDeck  # noqa: E402
from studyloop.settings import CardGeneratorConfig  # noqa: E402


def _config(**overrides: object) -> CardGeneratorConfig:
    """Build a stub-backend config with optional knob overrides."""
    base = CardGeneratorConfig(backend="stub")
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


class TestFactory:
    def test_get_generator_returns_stub_for_stub_backend(self) -> None:
        gen = get_generator(_config())
        assert isinstance(gen, StubGenerator)
        # Protocol satisfaction is structural; assert it explicitly so a
        # signature drift is caught here rather than at first WS call.
        assert isinstance(gen, CardGenerator)


class TestHappyPath:
    def test_flashcards_default_count_and_title_keying(self) -> None:
        gen = StubGenerator(_config())
        deck = gen.generate_flashcards(source="some markdown source", title="Pandas Basics")
        assert isinstance(deck, FlashcardDeck)
        assert deck.title == "Pandas Basics"
        assert len(deck.cards) == 10
        # Title is woven into card content -- lets U4 tests assert source-mapping.
        assert deck.cards[0].front.startswith("[Pandas Basics]")
        assert "source len=20" in deck.cards[0].back

    def test_quiz_has_exactly_one_correct_per_question(self) -> None:
        gen = StubGenerator(_config())
        deck = gen.generate_quiz(source="src", title="SQL Joins")
        assert isinstance(deck, QuizDeck)
        for q in deck.questions:
            correct = sum(1 for opt in q.answer_options if opt.is_correct)
            assert correct == 1, f"question {q.question!r} has {correct} correct"

    def test_card_count_override_respected(self) -> None:
        gen = StubGenerator(_config(stub_card_count=3))
        flash = gen.generate_flashcards(source="x", title="t")
        quiz = gen.generate_quiz(source="x", title="t")
        assert len(flash.cards) == 3
        assert len(quiz.questions) == 3


class TestFailureModes:
    def test_always_fail_raises_card_generation_error(self) -> None:
        gen = StubGenerator(_config(stub_failure_mode="always"))
        with pytest.raises(CardGenerationError, match="always fail"):
            gen.generate_flashcards(source="x", title="any-title")
        with pytest.raises(CardGenerationError, match="always fail"):
            gen.generate_quiz(source="x", title="any-title")

    def test_fail_titles_only_targets_named_titles(self) -> None:
        gen = StubGenerator(
            _config(stub_failure_mode="fail_titles", stub_failure_titles=("BadOne",)),
        )
        # Failing title raises.
        with pytest.raises(CardGenerationError, match="fail this title"):
            gen.generate_flashcards(source="x", title="BadOne")
        # Other titles succeed -- partial-failure shape that U4 needs.
        deck = gen.generate_flashcards(source="x", title="GoodOne")
        assert deck.title == "GoodOne"

    def test_failure_mode_none_never_raises(self) -> None:
        gen = StubGenerator(_config(stub_failure_mode="none"))
        # Even with failure_titles populated, mode=none means no failures.
        gen._config.stub_failure_titles = ("anything",)  # type: ignore[attr-defined]
        deck = gen.generate_flashcards(source="x", title="anything")
        assert deck.title == "anything"


class TestLatency:
    def test_latency_knob_sleeps_per_call(self) -> None:
        gen = StubGenerator(_config(stub_latency_s=0.05))
        t0 = time.monotonic()
        gen.generate_flashcards(source="x", title="t")
        elapsed = time.monotonic() - t0
        # Allow generous slack for CI variance; the assertion is "did it
        # sleep at all", not exact timing.
        assert elapsed >= 0.04, f"expected sleep ~0.05s, got {elapsed:.4f}s"

    def test_close_is_idempotent_noop(self) -> None:
        gen = StubGenerator(_config())
        gen.close()
        gen.close()
