"""Scope resolver for the content-generation panel (U3).

Translates a user-facing scope request ("generate decks for the
DataCamp course" / "for the advanced-pandas section" / "for topics I'm
struggling on this week") into a flat list of
:class:`ResolvedSource` -- one entry per markdown source we'll
hand to a generator.

Pure function: takes a scope request + ``Settings``, returns a list,
raises :class:`ScopeResolutionError` on miss. No FastAPI imports here
so the resolver is testable from a script and reusable from a future
CLI ``content generate-from-scope`` command.

The on-disk shape this resolver depends on is whatever's already under
``content.base_path`` (defaults to ``~/study-materials``):

    Study/
      <CourseProvider>/
        <section>/
          *.md
        *.md
        flashcards/    <-- existing output dir, skipped
        quizzes/       <-- existing output dir, skipped

The same layout the existing ``content generate-cards`` CLI walks, so
the new resolver and the old CLI agree on what counts as a source.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from studyloop.settings import Settings


# Section subdirs that are *output* dirs, not source dirs. Skipping
# them prevents a "course" scope from re-feeding generated decks back
# into the generator.
_OUTPUT_SUBDIRS = frozenset({"flashcards", "quizzes"})

# Markdown / text suffixes treated as source. Mirrors the existing CLI
# at packages/studyloop/src/studyloop/cli/_content.py:339-355.
_SOURCE_SUFFIXES = frozenset({".md", ".markdown", ".txt"})


class ScopeResolutionError(ValueError):
    """Raised when a scope request can't be resolved to ≥1 sources.

    Subclassing ``ValueError`` so callers that already trap it keep
    working; the explicit subclass lets HTTP routes map this to a 4xx.
    """


@dataclass(frozen=True, slots=True)
class ResolvedSource:
    """One unit of source material that will become one or more decks.

    ``identifier`` is the slug used for the output filename; the
    generator's ``write_json`` call places ``<identifier>-flashcards.json``
    and ``<identifier>-quiz.json`` in the course's output dirs.

    ``markdown_text`` is the concatenated contents of all markdown files
    in the section / source dir, separated by blank lines. The
    concatenation is intentional -- the existing ``generate-cards`` CLI
    treats one source per `GenerationTask`, not one file per task.
    """

    identifier: str
    title: str
    markdown_text: str


@dataclass(frozen=True, slots=True)
class ScopeRequest:
    """Validated scope spec consumed by :func:`resolve_scope`.

    The on-disk tree is three levels: ``base/<publisher>/<course>/`` with
    markdown lesson files beneath the course (typically in a ``study-notes/``
    or ``lessons/`` subdir, sometimes flat). The unit of generation is the
    individual lesson **file** -- what the UI calls a "section".

    ``kind`` selects which fields are required:

    - ``course``: ``publisher`` + ``course`` -- generates one deck per
      lesson file found under the course.
    - ``section``: ``publisher`` + ``course`` + ``section`` -- the section
      is the relative path (from the course dir) of a single lesson file.
    - ``topic_struggles``: ``publisher`` + ``course`` (where decks land) +
      ``window_days``; ``topic_slug`` optional (when set, narrows to one
      topic; when None, returns all struggling topics in window).

    ``publisher`` defaults to empty for backwards compatibility with the
    legacy flat layout (courses directly under ``base``); when empty the
    course dir resolves to ``base/<course>`` as before.

    Validation lives in U5's pydantic layer; this dataclass is the
    post-validation shape so the resolver can stay framework-free.
    """

    kind: Literal["course", "section", "topic_struggles"]
    course: str
    publisher: str = ""
    section: str = ""
    topic_slug: str = ""
    window_days: int = 14


@dataclass(frozen=True, slots=True)
class _StrugglingTopicRow:
    topic: str
    concept: str
    source_course: str | None = None
    source_section: str | None = None
    source_publisher: str | None = None


def resolve_scope(
    request: ScopeRequest, settings: Settings, db_path: Path | None = None
) -> list[ResolvedSource]:
    """Resolve a scope to a list of sources ready for generation.

    Args:
        request: The validated scope spec.
        settings: Loaded settings (provides ``content.base_path``).
        db_path: Override the SQLite path used by ``topic_struggles``.
            Defaults to ``settings.session_db``. Tests pass an
            in-memory or tmp-dir path here.

    Returns:
        A non-empty list of :class:`ResolvedSource`. Empty results
        raise rather than returning ``[]`` -- "nothing to generate"
        is a user-facing error worth surfacing as 404, not a silent
        success at the WS layer.

    Raises:
        ScopeResolutionError: missing course directory, missing
            section, empty matching set, etc.
    """
    base = content_base(settings)
    # 3-level tree: base/<publisher>/<course>/. publisher is optional for
    # backwards compatibility with the legacy flat layout (base/<course>).
    course_dir = resolve_content_path(base, request.publisher, request.course)
    if not course_dir.is_dir():
        raise ScopeResolutionError(
            f"Course directory not found: {course_dir} "
            f"(content.base_path={base}, publisher={request.publisher!r}, "
            f"course={request.course!r})"
        )

    if request.kind == "course":
        return _resolve_course(course_dir)
    if request.kind == "section":
        if not request.section:
            # Phrased WITHOUT "not found" so the HTTP layer maps this to a
            # 400 (ill-formed request) rather than a 404 (no such section).
            raise ScopeResolutionError(
                "scope.kind='section' requires a non-empty section (lesson file)."
            )
        return _resolve_section(course_dir, request.section)
    if request.kind == "topic_struggles":
        return _resolve_topic_struggles(
            course_dir=course_dir,
            publisher=request.publisher,
            course=request.course,
            window_days=request.window_days,
            topic_slug=request.topic_slug or None,
            db_path=db_path or settings.session_db,
        )
    raise ScopeResolutionError(f"Unknown scope kind: {request.kind!r}")


def content_base(settings: Settings) -> Path:
    """Return the configured content base as a resolved absolute path."""
    return Path(settings.content.base_path).expanduser().resolve()


def resolve_content_path(base: Path, *parts: str) -> Path:
    """Resolve user-selected content path parts under ``base``.

    All caller-controlled path segments must remain inside ``base`` after
    resolution. This blocks ``..`` traversal, absolute paths, and symlink
    escapes while still allowing normal nested lesson paths.
    """
    base = base.expanduser().resolve()
    path = base
    for part in parts:
        if not part:
            continue
        raw = Path(part)
        if raw.is_absolute():
            raise ScopeResolutionError(f"Content path must be relative: {part!r}")
        if ".." in raw.parts:
            raise ScopeResolutionError(f"Content path must not contain '..': {part!r}")
        path = path / raw
    resolved = path.resolve()
    if resolved != base and not resolved.is_relative_to(base):
        raise ScopeResolutionError(f"Content path escapes content.base_path: {path}")
    return resolved


# ---------------------------------------------------------------------------
# Per-kind resolvers
# ---------------------------------------------------------------------------


def _iter_source_files(course_dir: Path) -> list[Path]:
    """Return every markdown lesson file under ``course_dir``, sorted.

    A "section" is an individual lesson file. Files inside reserved output
    subdirs (``flashcards/``, ``quizzes/``) and dot-dirs are excluded so a
    course scope never re-feeds generated decks back into the generator.
    """
    files: list[Path] = []
    for path in sorted(course_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _SOURCE_SUFFIXES:
            continue
        rel = path.relative_to(course_dir)
        if any(part in _OUTPUT_SUBDIRS or part.startswith(".") for part in rel.parts):
            continue
        files.append(path)
    return files


def _file_source(course_dir: Path, path: Path, seen: set[str]) -> ResolvedSource | None:
    """Build one :class:`ResolvedSource` from a single lesson file.

    Identifier is the slugified file stem (clean deck filenames for the
    common flat ``study-notes/*.md`` layout); on a stem collision across
    subdirs we fall back to the slug of the file's relative path so the
    output names stay unique within a job. Returns None for empty files.
    """
    text = ""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    if not text:
        return None
    identifier = _slugify(path.stem)
    if not identifier or identifier in seen:
        rel = path.relative_to(course_dir).with_suffix("")
        identifier = _slugify("-".join(rel.parts))
    seen.add(identifier)
    return ResolvedSource(
        identifier=identifier,
        title=_humanise(path.stem),
        markdown_text=text,
    )


def _resolve_course(course_dir: Path) -> list[ResolvedSource]:
    """One source per lesson **file** under the course.

    Each markdown file becomes its own deck. Raises only if the course
    contains no readable source files at all.
    """
    seen: set[str] = set()
    sources: list[ResolvedSource] = []
    for path in _iter_source_files(course_dir):
        src = _file_source(course_dir, path, seen)
        if src is not None:
            sources.append(src)
    if not sources:
        raise ScopeResolutionError(f"Course {course_dir.name!r} has no readable lesson markdown.")
    return sources


def _resolve_section(course_dir: Path, section_name: str) -> list[ResolvedSource]:
    """One source for the named lesson file.

    ``section_name`` is the lesson file's path relative to the course dir
    (e.g. ``study-notes/getting-started.md``). For convenience the suffix
    may be omitted and a bare stem is matched against the course's files.
    """
    candidate = resolve_content_path(course_dir, section_name)
    path: Path | None = None
    if candidate.is_file():
        path = candidate
    else:
        # Match by relative path (suffix-optional) or by bare stem.
        section_noext = str(Path(section_name).with_suffix(""))
        wanted_rel = _slugify(section_noext.replace("/", "-"))
        wanted_stem = _slugify(Path(section_name).stem)
        for f in _iter_source_files(course_dir):
            rel_noext = "-".join(f.relative_to(course_dir).with_suffix("").parts)
            if _slugify(rel_noext) == wanted_rel or _slugify(f.stem) == wanted_stem:
                path = f
                break
    if path is None or not path.is_file():
        raise ScopeResolutionError(
            f"Section (lesson file) not found: {section_name!r} under course {course_dir.name!r}"
        )
    if any(part in _OUTPUT_SUBDIRS for part in path.relative_to(course_dir).parts):
        raise ScopeResolutionError(f"Section {section_name!r} is inside a reserved output dir.")
    src = _file_source(course_dir, path, set())
    if src is None:
        raise ScopeResolutionError(f"Section file {path} has no readable markdown.")
    return [src]


def _resolve_topic_struggles(
    *,
    course_dir: Path,
    publisher: str,
    course: str,
    window_days: int,
    topic_slug: str | None,
    db_path: Path,
) -> list[ResolvedSource]:
    """One source per topic flagged 'struggling' in the window.

    For each struggling topic, find a markdown source under the course
    by case-insensitive substring match on the topic slug. Topics with
    zero source matches are skipped (the user might be struggling on
    a concept they've not yet captured notes for; that's a content gap
    we don't want to silently pretend doesn't exist, but we also don't
    want to fail the whole scope -- so we skip and require ≥1 hit
    overall).
    """
    if window_days < 1 or window_days > 90:
        raise ScopeResolutionError(f"window_days must be in [1, 90], got {window_days}")
    cutoff = (datetime.now(UTC) - timedelta(days=window_days)).isoformat()
    rows = _query_struggling_topics(db_path, cutoff, topic_slug)
    if not rows:
        raise ScopeResolutionError(
            f"No struggling topics found in last {window_days} day(s) "
            f"(filter: topic_slug={topic_slug!r})."
        )

    sources: list[ResolvedSource] = []
    seen_identifiers: set[str] = set()
    for row in rows:
        source = _resolve_struggling_topic_row(
            course_dir=course_dir,
            publisher=publisher,
            course=course,
            row=row,
        )
        if source is None or source.identifier in seen_identifiers:
            continue
        seen_identifiers.add(source.identifier)
        sources.append(source)
    if not sources:
        raise ScopeResolutionError(
            f"Found {len(rows)} struggling topic(s) but none had matching "
            f"source markdown under {course_dir}. Topics: {[r.topic for r in rows]!r}"
        )
    return sources


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _concatenate_markdown(directory: Path) -> str:
    """Read all source files under ``directory`` recursively and join them.

    Two-blank-line separator preserves chapter boundaries for the
    generator while staying valid markdown.
    """
    parts: list[str] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _SOURCE_SUFFIXES:
            continue
        # Skip files inside reserved output subdirs (covers
        # `<section>/flashcards/old.md` regression cases).
        if any(part in _OUTPUT_SUBDIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # Tolerate weird files; the resolver shouldn't fail because
            # one stray binary slipped into a sources dir.
            continue
        if text.strip():
            parts.append(text.strip())
    return "\n\n".join(parts)


def _find_markdown_for_topic(course_dir: Path, topic: str) -> Path | None:
    """Locate a markdown source matching ``topic`` under ``course_dir``.

    Strategy: case-insensitive substring match on the topic against
    file/dir basenames. Directories trump files (a section subdir is
    preferred over a one-off note). Returns None if nothing matches.
    """
    needle = _slugify(topic).replace("-", "")
    if not needle:
        return None
    # Prefer a matching directory.
    for child in sorted(course_dir.rglob("*")):
        if not child.is_dir() or child.name in _OUTPUT_SUBDIRS:
            continue
        if needle in _slugify(child.name).replace("-", ""):
            return child
    # Fall back to a matching file.
    for child in sorted(course_dir.rglob("*")):
        if not child.is_file() or child.suffix.lower() not in _SOURCE_SUFFIXES:
            continue
        if any(part in _OUTPUT_SUBDIRS for part in child.parts):
            continue
        if needle in _slugify(child.stem).replace("-", ""):
            return child
    return None


def _resolve_struggling_topic_row(
    *,
    course_dir: Path,
    publisher: str,
    course: str,
    row: _StrugglingTopicRow,
) -> ResolvedSource | None:
    """Resolve one struggle row, preferring exact course/section provenance."""
    if row.source_course or row.source_publisher or row.source_section:
        if not _provenance_matches_scope(row, publisher=publisher, course=course):
            return None
        if row.source_section:
            try:
                return _resolve_section(course_dir, row.source_section)[0]
            except ScopeResolutionError:
                return None

    match = _find_markdown_for_topic(course_dir, row.topic)
    if match is None:
        return None
    markdown_text = (
        _concatenate_markdown(match) if match.is_dir() else match.read_text(encoding="utf-8")
    )
    if not markdown_text:
        return None
    return ResolvedSource(
        identifier=_slugify(row.topic),
        title=_humanise(row.topic),
        markdown_text=markdown_text,
    )


def _provenance_matches_scope(row: _StrugglingTopicRow, *, publisher: str, course: str) -> bool:
    """Return whether row-level provenance belongs to the requested course scope."""
    if row.source_publisher and publisher and _slugify(row.source_publisher) != _slugify(publisher):
        return False
    if row.source_course:
        course_slug = _slugify(course)
        full_slug = _slugify(f"{publisher}/{course}") if publisher else course_slug
        source_slug = _slugify(row.source_course)
        if source_slug not in {course_slug, full_slug}:
            return False
    return True


def _row_matches_topic_slug(row: _StrugglingTopicRow, topic_slug: str | None) -> bool:
    """Match current topic filters against either legacy topic or section provenance."""
    if not topic_slug:
        return True
    wanted = _slugify(topic_slug)
    candidates = [row.topic, row.concept]
    if row.source_section:
        candidates.extend([row.source_section, Path(row.source_section).stem])
    return any(_slugify(candidate) == wanted for candidate in candidates if candidate)


def _study_progress_columns(conn: sqlite3.Connection) -> set[str]:
    try:
        return {r["name"] for r in conn.execute("PRAGMA table_info(study_progress)")}
    except sqlite3.OperationalError:
        return set()


def _query_struggling_topics(
    db_path: Path, cutoff_iso: str, topic_slug: str | None
) -> list[_StrugglingTopicRow]:
    """Return struggling ``study_progress`` rows matching the filter.

    Uses ``confidence='struggling'`` (matches the filter at
    ``history/sessions.py:244-249`` which also includes 'learning';
    we narrow to just struggling because those are the high-priority
    "make me a deck" candidates).
    """
    if not Path(db_path).is_file():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        columns = _study_progress_columns(conn)
        optional_source_cols = [
            col for col in ("source_course", "source_section", "source_publisher") if col in columns
        ]
        select_cols = ["topic", "concept", *optional_source_cols]
        rows = conn.execute(
            f"""
            SELECT {", ".join(select_cols)}
            FROM study_progress
            WHERE confidence = 'struggling'
              AND last_seen > ?
            ORDER BY lower(topic), lower(concept)
            """,
            (cutoff_iso,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
    struggle_rows = []
    for r in rows:
        source_course = r["source_course"] if "source_course" in optional_source_cols else None
        source_section = r["source_section"] if "source_section" in optional_source_cols else None
        source_publisher = (
            r["source_publisher"] if "source_publisher" in optional_source_cols else None
        )
        struggle_rows.append(
            _StrugglingTopicRow(
                topic=r["topic"],
                concept=r["concept"],
                source_course=source_course,
                source_section=source_section,
                source_publisher=source_publisher,
            )
        )
    return [row for row in struggle_rows if _row_matches_topic_slug(row, topic_slug)]


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    """Lowercase, dash-separated, alpha-num-only.

    Matches the convention in ``content/storage.py``'s slugify;
    duplicating here to keep the resolver dependency-free at import
    time. Tests assert parity if storage.slugify drifts.
    """
    return _SLUG_RE.sub("-", text.strip().lower()).strip("-")


def _humanise(text: str) -> str:
    """Convert a slug-like name into a Title-Cased title for deck names."""
    return text.replace("_", " ").replace("-", " ").strip().title()


__all__ = [
    "ResolvedSource",
    "ScopeRequest",
    "ScopeResolutionError",
    "resolve_scope",
]
