"""Course API routes — list courses, sources, sections, stats, due, wrong."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from studyloop.review_loader import (
    discover_directories,
    find_content_dirs,
    load_flashcards,
    load_quizzes,
)
from studyloop.services.review import get_due, get_stats, get_wrong, list_course_summaries

router = APIRouter()


# Output subdirs to skip when listing sections — these hold generated
# decks, not source markdown. Mirrors content/scope.py's _OUTPUT_SUBDIRS
# but kept local so the route module is self-contained.
_OUTPUT_SUBDIRS = frozenset({"flashcards", "quizzes"})
_SOURCE_SUFFIXES = frozenset({".md", ".markdown", ".txt"})


def _get_dirs(request: Request) -> list[str]:
    return request.app.state.study_dirs


@router.get("/courses")
def list_courses(request: Request) -> list[dict]:
    """List all courses with card counts and review stats."""
    return list_course_summaries(_get_dirs(request))


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


@router.get("/courses/{course}/sections")
def list_course_sections(course: str) -> list[dict]:
    """Return source sections (subdirs of ``Study/<course>/``).

    Drives the WebUI's Section dropdown when scope=section. Reads
    directly from the configured ``content.base_path`` rather than the
    ``app.state.study_dirs`` review roots, because section listing is
    about *source* material, not the rendered output dirs the reviewer
    walks.

    Returns one entry per readable subdir, with a ``file_count`` count
    of source markdown / text files. Output subdirs (``flashcards/``,
    ``quizzes/``) and dot-dirs are skipped.
    """
    from studyloop.settings import load_settings

    settings = load_settings()
    course_dir = Path(settings.content.base_path).expanduser() / course
    if not course_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Course not found: {course}")

    entries: list[dict] = []
    for child in sorted(course_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith(".") or child.name in _OUTPUT_SUBDIRS:
            continue
        file_count = sum(
            1
            for p in child.rglob("*")
            if p.is_file() and p.suffix.lower() in _SOURCE_SUFFIXES
        )
        entries.append(
            {
                "slug": child.name,
                "name": child.name.replace("-", " ").replace("_", " ").title(),
                "file_count": file_count,
            }
        )
    return entries
