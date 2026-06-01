"""Course-explorer API routes (M1 backend).

Three endpoints:

- ``GET /api/explorer/tree``
  Two-level walk of ``content.base_path``:  provider → courses.
  Response is cached on ``app.state`` keyed by the directory mtime.

- ``GET /api/explorer/courses/{course_id:path}/lessons``
  Walk a single course dir and return every source markdown file
  as a lesson entry.  ``course_id`` contains a slash (provider/course)
  so the route uses the ``{...:path}`` converter.

- ``GET /api/explorer/lesson/{lesson_id:path}/content``
  Read and return the raw markdown for one lesson.  Full traversal
  guard (resolve + is_relative_to + suffix allowlist).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

# Subdirs that hold generated output — skip when listing lessons or providers.
# Mirrors ``content/scope.py`` and ``routes/courses.py``; kept local so this
# module is self-contained.
_OUTPUT_SUBDIRS: frozenset[str] = frozenset({"flashcards", "quizzes"})
_SOURCE_SUFFIXES: frozenset[str] = frozenset({".md", ".markdown", ".txt"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _humanise(name: str) -> str:
    """Turn a directory name into a readable title.

    Replaces underscores and hyphens with spaces then applies title-case.
    Examples:
        "Complete_SQL_Mastery" → "Complete Sql Mastery"
        "code-with-mosh"       → "Code With Mosh"
    """
    return name.replace("_", " ").replace("-", " ").title()


def _build_tree(base: Path) -> list[dict[str, Any]]:
    """Walk *base* two levels deep and return the provider→course tree.

    Only directories are considered.  Dot-dirs and output dirs
    (``flashcards``, ``quizzes``) are skipped at both levels.
    Returns an empty list when *base* does not exist.
    """
    if not base.is_dir():
        return []

    providers: list[dict[str, Any]] = []
    for provider_dir in sorted(base.iterdir()):
        if not provider_dir.is_dir():
            continue
        name = provider_dir.name
        if name.startswith(".") or name in _OUTPUT_SUBDIRS:
            continue

        courses: list[dict[str, Any]] = []
        for course_dir in sorted(provider_dir.iterdir()):
            if not course_dir.is_dir():
                continue
            cname = course_dir.name
            if cname.startswith(".") or cname in _OUTPUT_SUBDIRS:
                continue
            course_id = f"{name}/{cname}"
            courses.append(
                {
                    "id": course_id,
                    "name": _humanise(cname),
                    "provider": name,
                }
            )

        providers.append(
            {
                "id": name,
                "name": _humanise(name),
                "courses": courses,
            }
        )
    return providers


def _base_mtime(base: Path) -> float:
    """Return mtime of *base* directory (0.0 if missing)."""
    try:
        return os.stat(base).st_mtime
    except OSError:
        return 0.0


# ---------------------------------------------------------------------------
# GET /api/explorer/tree
# ---------------------------------------------------------------------------


@router.get("/explorer/tree")
def explorer_tree(request: Request) -> list[dict[str, Any]]:
    """Return the two-level provider→course tree.

    Cached on ``app.state`` keyed by the mtime of ``content.base_path``.
    Returns ``[]`` when the base path is missing or empty — never 404/500.
    """
    from studyloop.settings import load_settings

    settings = load_settings()
    base = Path(settings.content.base_path).expanduser()

    current_mtime = _base_mtime(base)

    # Cache hit: return if base hasn't changed since last call.
    if (
        getattr(request.app.state, "explorer_tree_cache", None) is not None
        and getattr(request.app.state, "explorer_tree_mtime", -1.0) == current_mtime
    ):
        return request.app.state.explorer_tree_cache  # type: ignore[return-value]

    tree = _build_tree(base)
    request.app.state.explorer_tree_cache = tree
    request.app.state.explorer_tree_mtime = current_mtime
    return tree


# ---------------------------------------------------------------------------
# GET /api/explorer/courses/{course_id:path}/lessons
# ---------------------------------------------------------------------------


@router.get("/explorer/courses/{course_id:path}/lessons")
def explorer_lessons(course_id: str) -> list[dict[str, Any]]:
    """Return every source lesson file for *course_id* (``provider/course``).

    ``course_id`` contains a forward slash so the route uses the ``{...:path}``
    converter to capture it whole.

    Output subdirs (``flashcards``, ``quizzes``) and dot-dirs are skipped.
    Returns 404 when the course directory does not exist or when the
    ``course_id`` would escape ``content.base_path`` (traversal guard).
    """
    from studyloop.settings import load_settings

    settings = load_settings()
    base = Path(settings.content.base_path).expanduser()

    # Resolve candidate and guard against traversal in course_id.
    candidate = (base / course_id).resolve()
    if not candidate.is_relative_to(base.resolve()):
        raise HTTPException(status_code=404, detail=f"Course not found: {course_id}")
    if not candidate.is_dir():
        raise HTTPException(status_code=404, detail=f"Course not found: {course_id}")

    lessons: list[dict[str, Any]] = []
    for file_path in sorted(candidate.rglob("*")):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in _SOURCE_SUFFIXES:
            continue
        rel = file_path.relative_to(candidate)
        # Skip any path whose parts touch an output dir or a dot-dir.
        if any(part in _OUTPUT_SUBDIRS or part.startswith(".") for part in rel.parts):
            continue
        slug = str(rel.with_suffix(""))
        lesson_id = f"{course_id}/{slug}"
        lessons.append(
            {
                "id": lesson_id,
                "slug": slug,
                "name": file_path.stem.replace("-", " ").replace("_", " ").title(),
                "course_id": course_id,
            }
        )
    return lessons


# ---------------------------------------------------------------------------
# GET /api/explorer/lesson/{lesson_id:path}/content
# ---------------------------------------------------------------------------


@router.get("/explorer/lesson/{lesson_id:path}/content")
def explorer_lesson_content(lesson_id: str) -> dict[str, str]:
    """Return the raw markdown content for *lesson_id*.

    *lesson_id* is ``provider/course/relative/path`` (no suffix).  The
    handler tries each suffix in ``_SOURCE_SUFFIXES`` to locate the file.

    Security:
    - Resolved path must be a child of ``content.base_path`` (blocks
      ``../``, ``%2e%2e``, absolute paths, and symlink-escape).
    - Resolved suffix must be in ``_SOURCE_SUFFIXES`` (blocks ``.json``,
      ``.png``, etc.).
    - File must exist and be a regular file.
    """
    from studyloop.settings import load_settings

    settings = load_settings()
    base = Path(settings.content.base_path).expanduser().resolve()

    resolved: Path | None = None
    for suffix in _SOURCE_SUFFIXES:
        candidate = (base / lesson_id).with_suffix(suffix)
        try:
            r = candidate.resolve()
        except OSError:
            continue
        if not r.is_relative_to(base):
            raise HTTPException(status_code=404)
        if r.suffix.lower() not in _SOURCE_SUFFIXES:
            raise HTTPException(status_code=404)
        if r.is_file():
            resolved = r
            break

    if resolved is None:
        raise HTTPException(status_code=404)

    # Final guard: re-check after we found the file.
    if not resolved.is_relative_to(base):
        raise HTTPException(status_code=404)
    if resolved.suffix.lower() not in _SOURCE_SUFFIXES:
        raise HTTPException(status_code=404)

    content = resolved.read_text(encoding="utf-8")
    return {"content": content, "lesson_id": lesson_id}
