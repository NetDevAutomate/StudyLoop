"""Deterministic card generator used only by the test suite.

This module lives outside ``src/`` so it cannot be imported from an installed
StudyLoop wheel.  It implements the production ``CardGenerator`` protocol and
is injected at the factory seam by unit tests or ``_content_test_server.py``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from studyloop.content.generators import CardGenerationError
from studyloop.content.schemas import (
    FlashcardDeck,
    FlashcardItem,
    PracticeDeck,
    PracticeTask,
    PracticeVerification,
    QuizDeck,
    QuizOption,
    QuizQuestion,
)


@dataclass
class GeneratorFixtureConfig:
    card_count: int = 10
    latency_s: float = 0.0
    failure_mode: str = "none"
    failure_titles: tuple[str, ...] = ()


class DeterministicTestGenerator:
    """Return validated, title-keyed decks without contacting a model."""

    def __init__(self, config: GeneratorFixtureConfig | None = None) -> None:
        self._config = config or GeneratorFixtureConfig()

    def generate_flashcards(
        self, source: str, title: str, count: int | None = None
    ) -> FlashcardDeck:
        self._prepare(title)
        cards = [
            FlashcardItem(
                front=f"[{title}] test question {index + 1}",
                back=f"[{title}] test answer {index + 1} (source len={len(source)})",
            )
            for index in range(count or self._config.card_count)
        ]
        return FlashcardDeck(title=title, cards=cards)

    def generate_quiz(self, source: str, title: str, count: int | None = None) -> QuizDeck:
        self._prepare(title)
        questions = [
            QuizQuestion(
                question=f"[{title}] test question {index + 1}? (source len={len(source)})",
                hint="",
                answerOptions=[
                    QuizOption(text="Expected", isCorrect=True, rationale="test expected"),
                    QuizOption(text="Alternative A", isCorrect=False, rationale="test alternative"),
                    QuizOption(text="Alternative B", isCorrect=False, rationale="test alternative"),
                ],
            )
            for index in range(count or self._config.card_count)
        ]
        return QuizDeck(title=title, questions=questions)

    def generate_practice(self, source: str, title: str) -> PracticeDeck:
        self._prepare(title)
        tasks = [
            PracticeTask(
                taskType="debug" if index % 2 else "build",
                prompt=f"[{title}] test practice task {index + 1}",
                setup=f"Use this source excerpt length as input: {len(source)}",
                successCriteria=["A concrete attempt exists", "The result is checked"],
                hint="Start with the smallest runnable version.",
                expectedLearningOutcome=f"Apply {title} concept {index + 1} hands-on.",
                verification=PracticeVerification(
                    kind="rubric",
                    successCriteria=["A concrete attempt exists", "The result is checked"],
                    expectedArtifacts=[],
                    rubric=["Names the concept", "Includes one edge case"],
                    evidencePrompts=["What changed?", "What would fail?"],
                    timeoutSeconds=60,
                ),
            )
            for index in range(min(self._config.card_count, 6))
        ]
        return PracticeDeck(title=title, tasks=tasks)

    def close(self) -> None:
        """Match the production generator lifecycle contract."""

    def _prepare(self, title: str) -> None:
        if self._config.latency_s > 0:
            time.sleep(self._config.latency_s)
        if self._config.failure_mode == "always":
            raise CardGenerationError(f"test generator configured to always fail ({title!r})")
        if self._config.failure_mode == "fail_titles" and title in self._config.failure_titles:
            raise CardGenerationError(f"test generator configured to fail this title ({title!r})")


__all__ = ["DeterministicTestGenerator", "GeneratorFixtureConfig"]
