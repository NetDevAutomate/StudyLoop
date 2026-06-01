"""Course-explorer API routes (M1 backend).

Four endpoints:

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

- ``GET /api/explorer/search?q=<term>&limit=20``
  Two-tier full-text search over lesson bodies via SQLite FTS5.
  Lazy-builds ``explorer_fts.db`` on first call; refreshes stale
  entries on each call (mtime-based incremental re-index).
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

# Module-level lock: FTS lazy-build + refresh must be single-threaded to
# avoid concurrent writers racing on the same sqlite file.
_fts_lock = threading.Lock()

# Subdirs that hold generated output — skip when listing lessons or providers.
# Mirrors ``content/scope.py`` and ``routes/courses.py``; kept local so this
# module is self-contained.
_OUTPUT_SUBDIRS: frozenset[str] = frozenset({"flashcards", "quizzes"})
_SOURCE_SUFFIXES: frozenset[str] = frozenset({".md", ".markdown", ".txt"})
# Ordered probe sequence for the content endpoint: .md wins over .markdown wins over .txt.
# Iterating a frozenset is PYTHONHASHSEED-dependent; this tuple is deterministic.
_SUFFIX_PRIORITY: tuple[str, ...] = (".md", ".markdown", ".txt")


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
# FTS5 search helpers
# ---------------------------------------------------------------------------


def _fts_db_path() -> Path:
    """Return the path to the FTS cache db (sibling of sessions.db).

    This is a *derived cache* — it can be deleted and rebuilt at any time.
    It intentionally lives in its own file so it never touches the session DB
    and requires no schema migration.
    """
    from studyloop.settings import load_settings

    settings = load_settings()
    return Path(settings.session_db).parent / "explorer_fts.db"


def _sanitize_fts_query(q: str) -> str:
    """Wrap *q* as a literal FTS5 phrase to neutralise operator injection.

    FTS5 MATCH treats bare terms like ``AND``, ``OR``, ``NOT``, ``*``,
    ``"…"``, ``(``, ``)`` as operators.  Wrapping the whole user input
    in double-quotes turns it into a phrase search so arbitrary input is
    always treated as a literal string, never an FTS expression.

    Double-quotes inside *q* are escaped by doubling them (SQL string
    escaping inside the FTS quoted-phrase syntax).
    """
    escaped = q.replace('"', '""')
    return f'"{escaped}"'


def _walk_lessons(base: Path) -> list[dict[str, Any]]:
    """Return a flat list of all source lesson files under *base*.

    Each entry has the keys: lesson_id, course_id, provider, title, path, mtime.
    Uses the same skip-rules as ``_build_tree`` and ``explorer_lessons``.
    """
    if not base.is_dir():
        return []

    results: list[dict[str, Any]] = []
    resolved_base = base.resolve()

    for provider_dir in sorted(base.iterdir()):
        if not provider_dir.is_dir():
            continue
        name = provider_dir.name
        if name.startswith(".") or name in _OUTPUT_SUBDIRS:
            continue

        for course_dir in sorted(provider_dir.iterdir()):
            if not course_dir.is_dir():
                continue
            cname = course_dir.name
            if cname.startswith(".") or cname in _OUTPUT_SUBDIRS:
                continue
            course_id = f"{name}/{cname}"

            for file_path in sorted(course_dir.rglob("*")):
                if not file_path.is_file():
                    continue
                if file_path.suffix.lower() not in _SOURCE_SUFFIXES:
                    continue
                try:
                    resolved = file_path.resolve()
                except OSError:
                    continue
                if not resolved.is_relative_to(resolved_base):
                    continue  # symlink escape
                rel = file_path.relative_to(course_dir)
                if any(part in _OUTPUT_SUBDIRS or part.startswith(".") for part in rel.parts):
                    continue
                slug = str(rel.with_suffix(""))
                lesson_id = f"{course_id}/{slug}"
                try:
                    mtime = os.stat(file_path).st_mtime
                except OSError:
                    continue
                title = file_path.stem.replace("-", " ").replace("_", " ").title()
                results.append(
                    {
                        "lesson_id": lesson_id,
                        "course_id": course_id,
                        "provider": name,
                        "title": title,
                        "path": str(resolved),
                        "mtime": mtime,
                    }
                )
    return results


def _ensure_fts_schema(conn: sqlite3.Connection) -> None:
    """Create the FTS5 virtual table and meta table if they don't exist."""
    conn.executescript(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS lesson_fts USING fts5(
            lesson_id UNINDEXED,
            course_id UNINDEXED,
            provider  UNINDEXED,
            title,
            body,
            tokenize='porter unicode61'
        );
        CREATE TABLE IF NOT EXISTS lesson_index_meta (
            lesson_id TEXT PRIMARY KEY,
            file_path TEXT NOT NULL,
            mtime     REAL NOT NULL
        );
        """
    )
    conn.commit()


def _refresh_fts_index(conn: sqlite3.Connection, base: Path) -> None:
    """Incrementally synchronise the FTS index with the current vault.

    Walk order:
    1. Walk all current lesson files → build a map lesson_id → {path, mtime}.
    2. Load the existing meta table → build a map lesson_id → {path, mtime}.
    3. New lessons (in current, not in meta) → INSERT.
    4. Changed lessons (mtime changed) → DELETE old + INSERT new.
    5. Deleted lessons (in meta, not in current) → DELETE.
    """
    current_lessons = {entry["lesson_id"]: entry for entry in _walk_lessons(base)}

    cur = conn.execute("SELECT lesson_id, file_path, mtime FROM lesson_index_meta")
    indexed: dict[str, dict[str, Any]] = {}
    for row in cur.fetchall():
        indexed[row[0]] = {"path": row[1], "mtime": row[2]}

    to_add: list[dict[str, Any]] = []
    to_delete: list[str] = []

    for lesson_id, entry in current_lessons.items():
        if lesson_id not in indexed:
            to_add.append(entry)
        elif abs(entry["mtime"] - indexed[lesson_id]["mtime"]) > 0.01:
            # mtime changed — re-index
            to_delete.append(lesson_id)
            to_add.append(entry)

    for lesson_id in indexed:
        if lesson_id not in current_lessons:
            to_delete.append(lesson_id)

    if to_delete:
        placeholders = ",".join("?" * len(to_delete))
        conn.execute(f"DELETE FROM lesson_fts WHERE lesson_id IN ({placeholders})", to_delete)
        conn.execute(
            f"DELETE FROM lesson_index_meta WHERE lesson_id IN ({placeholders})", to_delete
        )

    for entry in to_add:
        try:
            body = Path(entry["path"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        conn.execute(
            "INSERT INTO lesson_fts(lesson_id, course_id, provider, title, body) "
            "VALUES (?, ?, ?, ?, ?)",
            (entry["lesson_id"], entry["course_id"], entry["provider"], entry["title"], body),
        )
        conn.execute(
            "INSERT OR REPLACE INTO lesson_index_meta"
            "(lesson_id, file_path, mtime) VALUES (?, ?, ?)",
            (entry["lesson_id"], entry["path"], entry["mtime"]),
        )

    conn.commit()


def _run_fts_search(db_path: Path, base: Path, q: str, limit: int) -> list[dict[str, Any]]:
    """Open (or create) the FTS db, refresh the index, execute the query.

    Returns a list of result dicts with keys:
        lesson_id, course_id, provider, title, excerpt
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        _ensure_fts_schema(conn)
        _refresh_fts_index(conn, base)

        fts_query = _sanitize_fts_query(q)
        rows = conn.execute(
            """
            SELECT lesson_id, course_id, provider, title,
                   snippet(lesson_fts, 4, '<mark>', '</mark>', '…', 16) AS excerpt,
                   bm25(lesson_fts, 1.0, 1.0, 1.0, 5.0, 1.0) AS score
            FROM lesson_fts
            WHERE lesson_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (fts_query, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        # Defensive: any FTS error returns empty rather than 500.
        return []
    finally:
        conn.close()

    return [
        {
            "lesson_id": row["lesson_id"],
            "course_id": row["course_id"],
            "provider": row["provider"],
            "title": row["title"],
            "excerpt": row["excerpt"] or "",
        }
        for row in rows
    ]


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
        if not file_path.resolve().is_relative_to(base.resolve()):
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
    for suffix in _SUFFIX_PRIORITY:
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

    content = resolved.read_text(encoding="utf-8", errors="replace")
    return {"content": content, "lesson_id": lesson_id}


# ---------------------------------------------------------------------------
# GET /api/explorer/search
# ---------------------------------------------------------------------------


@router.get("/explorer/search")
def explorer_search(q: str = "", limit: int = 20) -> dict[str, Any]:
    """Full-text search over lesson bodies via SQLite FTS5.

    Query parameter:
        ``q``     — search term (URI-decoded by FastAPI).
        ``limit`` — max results to return (default 20).

    Guards:
        - Empty or whitespace-only ``q`` → ``{"results": []}``.
        - ``len(q.strip()) < 2``          → ``{"results": []}``.

    FTS injection safety:
        The user query is wrapped as a quoted FTS5 phrase so operators
        (``AND``, ``OR``, ``*``, ``"``, ``(``, ``)`` etc.) are treated
        as literal characters, never as FTS syntax.

    Excerpt XSS safety:
        ``snippet()`` returns plain text with ``<mark>`` / ``</mark>``
        tags inserted by SQLite itself around matching terms.  The lesson
        body is never stored as HTML — it is the raw markdown text — so
        no HTML injection risk exists in the stored content.  The frontend
        receives a string that may contain ``<mark>`` tags; it must use
        ``x-text`` for the surrounding title (no HTML) and, for the
        excerpt, either ``x-text`` (loses highlighting) or a safe
        escape-then-allow-mark approach.  The backend does not sanitise
        the excerpt because it controls the only HTML in it (the
        ``<mark>`` tags it added via ``snippet()``).

    Lazy build + mtime refresh:
        On first call the FTS index is built from the full vault walk.
        On subsequent calls only files whose mtime changed are re-indexed;
        files deleted from disk are removed from the index.
    """
    q_stripped = q.strip()
    if len(q_stripped) < 2:
        return {"results": []}

    from studyloop.settings import load_settings

    settings = load_settings()
    base = Path(settings.content.base_path).expanduser()
    db_path = _fts_db_path()

    with _fts_lock:
        results = _run_fts_search(db_path, base, q_stripped, limit)

    return {"results": results}
