"""Service layer for review operations.

Thin wrapper functions that delegate to :mod:`studyctl.review_db` and
:mod:`studyctl.review_loader`.  This module is the bridge between
consumer interfaces (CLI, web, MCP) and the data layer.

Rules enforced by design:
- NO framework imports (no click, no fastapi, no textual).
- All functions are pure delegation with minimal orchestration.
- Type annotations on every public function.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from studyctl import review_db, review_loader

if TYPE_CHECKING:
    from pathlib import Path

    from studyctl.review_db import CardProgress
    from studyctl.review_loader import Flashcard, QuizQuestion


def get_cards(
    course: str,
    directory: Path,
) -> tuple[list[Flashcard], list[QuizQuestion]]:
    """Load flashcards and quiz questions for a course directory.

    Uses :func:`review_loader.find_content_dirs` to locate the
    ``flashcards/`` and ``quizzes/`` sub-directories, then delegates
    to :func:`review_loader.load_flashcards` and
    :func:`review_loader.load_quizzes`.

    Args:
        course: Course identifier (used for logging context, not filtering).
        directory: Root directory that contains flashcard/quiz content.

    Returns:
        A tuple of (flashcards, quiz_questions).  Either list may be
        empty if no content is found.
    """
    fc_dir, quiz_dir = review_loader.find_content_dirs(directory)

    flashcards: list[Flashcard] = []
    quizzes: list[QuizQuestion] = []

    if fc_dir is not None:
        flashcards = review_loader.load_flashcards(fc_dir)
    if quiz_dir is not None:
        quizzes = review_loader.load_quizzes(quiz_dir)

    return flashcards, quizzes


def record_review(
    course: str,
    card_type: str,
    card_hash: str,
    correct: bool,
    response_time_ms: int | None = None,
) -> None:
    """Record a single card review result.

    Delegates to :func:`review_db.record_card_review` which handles
    SM-2 interval calculation and persistence.

    Args:
        course: Course identifier.
        card_type: Either ``"flashcard"`` or ``"quiz"``.
        card_hash: Stable hash identifying the card.
        correct: Whether the answer was correct.
        response_time_ms: Optional response time in milliseconds.
    """
    review_db.record_card_review(
        course=course,
        card_type=card_type,
        card_hash=card_hash,
        correct=correct,
        response_time_ms=response_time_ms,
    )


def get_stats(course: str) -> dict:
    """Get summary statistics for a course.

    Returns a dict with keys: ``total_reviews``, ``unique_cards``,
    ``due_today``, ``mastered``.

    Args:
        course: Course identifier.

    Returns:
        Statistics dictionary.  Returns zeroed stats if no reviews exist.
    """
    return review_db.get_course_stats(course=course)


def get_due(course: str) -> list[CardProgress]:
    """Get cards that are due for spaced-repetition review.

    Args:
        course: Course identifier.

    Returns:
        List of :class:`~studyctl.review_db.CardProgress` entries
        whose ``next_review`` date is today or earlier, ordered by
        earliest due first.
    """
    return review_db.get_due_cards(course=course)


def get_wrong(course: str) -> set[str]:
    """Get card hashes that were answered incorrectly in the most recent session.

    Useful for "retry wrong answers" flows where the consumer wants to
    re-present only the cards the learner got wrong.

    Args:
        course: Course identifier.

    Returns:
        Set of card hash strings.  Empty set if no sessions exist.
    """
    return review_db.get_wrong_hashes(course=course)
