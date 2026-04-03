"""Course API routes — list courses, sources, stats, due, wrong."""

from __future__ import annotations

from fastapi import APIRouter, Request

from studyctl.review_loader import (
    discover_directories,
    find_content_dirs,
    load_flashcards,
    load_quizzes,
)
from studyctl.services.review import get_due, get_stats, get_wrong

router = APIRouter()


def _get_dirs(request: Request) -> list[str]:
    return request.app.state.study_dirs


@router.get("/courses")
def list_courses(request: Request) -> list[dict]:
    """List all courses with card counts and review stats."""
    courses = discover_directories(_get_dirs(request))
    result = []
    for name, path in courses:
        fc_dir, quiz_dir = find_content_dirs(path)
        fc_count = len(load_flashcards(fc_dir)) if fc_dir else 0
        quiz_count = len(load_quizzes(quiz_dir)) if quiz_dir else 0
        due = len(get_due(name))
        stats = get_stats(name)
        result.append(
            {
                "name": name,
                "flashcard_count": fc_count,
                "quiz_count": quiz_count,
                "due_count": due,
                "total_reviews": stats.get("total_reviews", 0),
                "mastered": stats.get("mastered", 0),
            }
        )
    return result


@router.get("/sources/{course}")
def list_sources(request: Request, course: str, mode: str = "flashcards") -> list[str]:
    """List unique source names for a course (flat string array for app.js compat)."""
    courses = discover_directories(_get_dirs(request))
    match = next(((n, p) for n, p in courses if n == course), None)
    if not match:
        return []
    _, path = match
    fc_dir, quiz_dir = find_content_dirs(path)
    sources: set[str] = set()
    if mode == "flashcards" and fc_dir:
        for c in load_flashcards(fc_dir):
            if c.source:
                sources.add(c.source)
    elif mode == "quiz" and quiz_dir:
        for q in load_quizzes(quiz_dir):
            if q.source:
                sources.add(q.source)
    return sorted(sources)


@router.get("/stats/{course}")
def course_stats(course: str) -> dict:
    """Get review statistics for a course."""
    return get_stats(course)


@router.get("/due/{course}")
def due_cards(course: str) -> list[dict]:
    """Get cards due for review."""
    cards = get_due(course)
    return [
        {
            "card_hash": c.card_hash,
            "ease_factor": c.ease_factor,
            "interval_days": c.interval_days,
            "next_review": c.next_review,
        }
        for c in cards
    ]


@router.get("/wrong/{course}")
def wrong_cards(course: str) -> list[str]:
    """Get card hashes answered incorrectly in the most recent session."""
    return list(get_wrong(course))
