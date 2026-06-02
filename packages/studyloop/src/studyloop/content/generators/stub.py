"""Stub generator -- deterministic, offline, free.

Used by tests and dogfood runs that need the producer pipeline without
burning Ollama time or Bedrock dollars. Satisfies the ``CardGenerator``
Protocol; ``get_generator()`` returns this instance when
``CardGeneratorConfig.backend == "stub"``.

Three knobs control test scenarios:

* ``stub_latency_s`` -- per-call sleep, useful for asserting concurrent
  runner behaviour without slow real backends.
* ``stub_failure_mode`` -- ``"none" | "always" | "fail_titles"`` selects
  how the generator reports errors.
* ``stub_failure_titles`` -- when mode is ``"fail_titles"``, raise on
  exactly these titles. Lets a single test exercise partial-failure paths.

The deck content is **deterministic but title-keyed** so tests can assert
that the right source mapped to the right deck (no global state, no
random IDs leaking into snapshots).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from studyloop.content.generators import CardGenerationError
from studyloop.content.schemas import (
    FlashcardDeck,
    FlashcardItem,
    QuizDeck,
    QuizOption,
    QuizQuestion,
)

if TYPE_CHECKING:
    from studyloop.settings import CardGeneratorConfig


_DEFAULT_CARD_COUNT = 10


class StubGenerator:
    """In-memory generator that returns deterministic decks.

    Threading: safe to share across the existing thread-pool runner --
    no mutable state beyond the captured config.
    """

    def __init__(self, config: CardGeneratorConfig) -> None:
        self._config = config

    def generate_flashcards(
        self, source: str, title: str, count: int | None = None
    ) -> FlashcardDeck:
        self._maybe_sleep()
        self._maybe_fail(title)
        count = self._card_count(count)
        cards = [
            FlashcardItem(
                front=f"[{title}] stub front {i + 1}",
                back=f"[{title}] stub back {i + 1} (source len={len(source)})",
            )
            for i in range(count)
        ]
        return FlashcardDeck(title=title, cards=cards)

    def generate_quiz(self, source: str, title: str, count: int | None = None) -> QuizDeck:
        self._maybe_sleep()
        self._maybe_fail(title)
        count = self._card_count(count)
        questions = [
            QuizQuestion(
                question=f"[{title}] stub question {i + 1}? (source len={len(source)})",
                hint="",
                answerOptions=[
                    QuizOption(text="Correct option", isCorrect=True, rationale="stub correct"),
                    QuizOption(text="Wrong option A", isCorrect=False, rationale="stub wrong A"),
                    QuizOption(text="Wrong option B", isCorrect=False, rationale="stub wrong B"),
                ],
            )
            for i in range(count)
        ]
        return QuizDeck(title=title, questions=questions)

    def close(self) -> None:
        """No-op; present for parity with HTTP-backed generators."""

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _card_count(self, requested: int | None) -> int:
        if requested is not None:
            return requested
        return getattr(self._config, "stub_card_count", _DEFAULT_CARD_COUNT)

    def _maybe_sleep(self) -> None:
        latency = getattr(self._config, "stub_latency_s", 0.0)
        if latency > 0:
            time.sleep(latency)

    def _maybe_fail(self, title: str) -> None:
        mode = getattr(self._config, "stub_failure_mode", "none")
        if mode == "always":
            raise CardGenerationError(f"stub configured to always fail (title={title!r})")
        if mode == "fail_titles":
            failing = getattr(self._config, "stub_failure_titles", ())
            if title in failing:
                raise CardGenerationError(f"stub configured to fail this title (title={title!r})")


__all__ = ["StubGenerator"]
