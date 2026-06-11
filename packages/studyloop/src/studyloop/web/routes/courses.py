"""Course API routes — list courses, sources, sections, stats, due, wrong."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from studyloop.content.scope import ScopeResolutionError, resolve_content_path
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
def list_course_sections(course: str, publisher: str = "") -> list[dict]:
    """Return source sections (individual lesson **files**) for a course.

    A "section" is one lesson markdown file under
    ``Study/<publisher>/<course>/`` (typically inside ``study-notes/`` or
    ``lessons/``, sometimes flat). Drives the WebUI's Section dropdown when
    scope=section. Reads from ``content.base_path`` (source material), not
    the ``app.state.study_dirs`` review roots.

    ``publisher`` is optional for the legacy flat layout. The ``slug`` is the
    file's path relative to the course dir (suffix stripped) so the scope
    resolver can match it back to the exact file; ``name`` is a humanised
    title. Output subdirs and dot-dirs are skipped.
    """
    from studyloop.settings import load_settings

    settings = load_settings()
    base = Path(settings.content.base_path).expanduser().resolve()
    try:
        course_dir = resolve_content_path(base, publisher, course)
    except ScopeResolutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not course_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Course not found: {course}")

    entries: list[dict] = []
    for path in sorted(course_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _SOURCE_SUFFIXES:
            continue
        rel = path.relative_to(course_dir)
        if any(part in _OUTPUT_SUBDIRS or part.startswith(".") for part in rel.parts):
            continue
        slug = str(rel.with_suffix(""))
        entries.append(
            {
                "slug": slug,
                "name": path.stem.replace("-", " ").replace("_", " ").title(),
            }
        )
    return entries
