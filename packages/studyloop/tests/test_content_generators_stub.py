"""Tests for the deterministic generator kept inside the test suite.

The stub satisfies the ``CardGenerator`` Protocol with deterministic,
title-keyed output -- no HTTP, no I/O. Used by the rest of the
generation-panel suite (U2-U11) so the producer pipeline can be
exercised end-to-end without burning Ollama time or Bedrock dollars.
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("pydantic")

from _content_generator import DeterministicTestGenerator, GeneratorFixtureConfig

from studyloop.content.generators import CardGenerationError, CardGenerator, get_generator
from studyloop.content.generators.prompts import (
    FLASHCARD_USER_PROMPT_TEMPLATE,
    QUIZ_USER_PROMPT_TEMPLATE,
)
from studyloop.content.schemas import FlashcardDeck, PracticeDeck, QuizDeck
from studyloop.settings import CardGeneratorConfig


def _config(**overrides: object) -> GeneratorFixtureConfig:
    """Build test-only generator configuration from the legacy knob names."""
    mapped = {key.removeprefix("stub_"): value for key, value in overrides.items()}
    return GeneratorFixtureConfig(**mapped)  # type: ignore[arg-type]


class TestFactory:
    def test_test_generator_satisfies_production_protocol(self) -> None:
        gen = DeterministicTestGenerator(_config())
        assert isinstance(gen, CardGenerator)

    def test_production_factory_rejects_test_backend(self) -> None:
        with pytest.raises(ValueError, match=r"Unknown card_generator\.backend"):
            get_generator(CardGeneratorConfig(backend="stub"))


class TestHappyPath:
    def test_flashcards_default_count_and_title_keying(self) -> None:
        gen = DeterministicTestGenerator(_config())
        deck = gen.generate_flashcards(source="some markdown source", title="Pandas Basics")
        assert isinstance(deck, FlashcardDeck)
        assert deck.title == "Pandas Basics"
        assert len(deck.cards) == 10
        # Title is woven into card content -- lets U4 tests assert source-mapping.
        assert deck.cards[0].front.startswith("[Pandas Basics]")
        assert "source len=20" in deck.cards[0].back

    def test_quiz_has_exactly_one_correct_per_question(self) -> None:
        gen = DeterministicTestGenerator(_config())
        deck = gen.generate_quiz(source="src", title="SQL Joins")
        assert isinstance(deck, QuizDeck)
        for q in deck.questions:
            correct = sum(1 for opt in q.answer_options if opt.is_correct)
            assert correct == 1, f"question {q.question!r} has {correct} correct"

    def test_practice_tasks_are_hands_on(self) -> None:
        gen = DeterministicTestGenerator(_config(stub_card_count=3))
        deck = gen.generate_practice(source="src", title="SQL Joins")

        assert isinstance(deck, PracticeDeck)
        assert len(deck.tasks) == 3
        assert deck.tasks[0].prompt.startswith("[SQL Joins]")
        assert deck.tasks[0].success_criteria

    def test_card_count_override_respected(self) -> None:
        gen = DeterministicTestGenerator(_config(stub_card_count=3))
        flash = gen.generate_flashcards(source="x", title="t")
        quiz = gen.generate_quiz(source="x", title="t")
        assert len(flash.cards) == 3
        assert len(quiz.questions) == 3

    def test_per_call_count_overrides_stub_default(self) -> None:
        gen = DeterministicTestGenerator(_config(stub_card_count=3))

        flash = gen.generate_flashcards(source="x", title="t", count=5)
        quiz = gen.generate_quiz(source="x", title="t", count=7)

        assert len(flash.cards) == 5
        assert len(quiz.questions) == 7


class TestPromptCounts:
    def test_shared_flashcard_prompt_includes_requested_count(self) -> None:
        prompt = FLASHCARD_USER_PROMPT_TEMPLATE.format(
            title="Pandas",
            source="groupby notes",
            count=25,
        )

        assert "Produce exactly 25 flashcards" in prompt

    def test_shared_quiz_prompt_includes_requested_count(self) -> None:
        prompt = QUIZ_USER_PROMPT_TEMPLATE.format(
            title="Joins",
            source="join notes",
            count=5,
        )

        assert "Produce exactly 5 multiple-choice questions" in prompt


class TestFailureModes:
    def test_always_fail_raises_card_generation_error(self) -> None:
        gen = DeterministicTestGenerator(_config(stub_failure_mode="always"))
        with pytest.raises(CardGenerationError, match="always fail"):
            gen.generate_flashcards(source="x", title="any-title")
        with pytest.raises(CardGenerationError, match="always fail"):
            gen.generate_quiz(source="x", title="any-title")
        with pytest.raises(CardGenerationError, match="always fail"):
            gen.generate_practice(source="x", title="any-title")

    def test_fail_titles_only_targets_named_titles(self) -> None:
        gen = DeterministicTestGenerator(
            _config(stub_failure_mode="fail_titles", stub_failure_titles=("BadOne",)),
        )
        # Failing title raises.
        with pytest.raises(CardGenerationError, match="fail this title"):
            gen.generate_flashcards(source="x", title="BadOne")
        # Other titles succeed -- partial-failure shape that U4 needs.
        deck = gen.generate_flashcards(source="x", title="GoodOne")
        assert deck.title == "GoodOne"

    def test_failure_mode_none_never_raises(self) -> None:
        gen = DeterministicTestGenerator(_config(stub_failure_mode="none"))
        # Even with failure_titles populated, mode=none means no failures.
        gen._config.failure_titles = ("anything",)
        deck = gen.generate_flashcards(source="x", title="anything")
        assert deck.title == "anything"


class TestLatency:
    def test_latency_knob_sleeps_per_call(self) -> None:
        gen = DeterministicTestGenerator(_config(stub_latency_s=0.05))
        t0 = time.monotonic()
        gen.generate_flashcards(source="x", title="t")
        elapsed = time.monotonic() - t0
        # Allow generous slack for CI variance; the assertion is "did it
        # sleep at all", not exact timing.
        assert elapsed >= 0.04, f"expected sleep ~0.05s, got {elapsed:.4f}s"

    def test_close_is_idempotent_noop(self) -> None:
        gen = DeterministicTestGenerator(_config())
        gen.close()
        gen.close()
