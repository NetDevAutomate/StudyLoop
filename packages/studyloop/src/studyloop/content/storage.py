"""Course-centric storage management.

Each course has a directory under ``content.base_path`` with a standard
subdirectory layout for chapters, audio, flashcards, quizzes, video,
and slides. A ``metadata.json`` file tracks notebook IDs, syllabus
state, and generation history.
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

COURSE_SUBDIRS = ("chapters", "audio", "flashcards", "quizzes", "practice", "video", "slides")


def get_course_dir(base_path: Path, slug: str) -> Path:
    """Return course directory, creating subdirs if needed."""
    course_dir = base_path / slug
    for subdir in COURSE_SUBDIRS:
        (course_dir / subdir).mkdir(parents=True, exist_ok=True)
    return course_dir


def slugify(title: str) -> str:
    """Convert a book/course title to a filesystem-safe slug."""
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug[:60].strip("-")


def list_courses(base_path: Path) -> list[dict]:
    """List all courses under the base path.

    Returns a list of dicts with keys: slug, path, metadata.
    """
    if not base_path.is_dir():
        return []

    courses = []
    for child in sorted(base_path.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        meta = load_course_metadata(child)
        courses.append(
            {
                "slug": child.name,
                "path": child,
                "metadata": meta,
            }
        )
    return courses


def load_course_metadata(course_dir: Path) -> dict:
    """Load metadata.json (notebook IDs, syllabus state, generation history)."""
    meta_path = course_dir / "metadata.json"
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read %s: %s", meta_path, exc)
        return {}


def save_course_metadata(course_dir: Path, metadata: dict) -> None:
    """Save metadata.json atomically (write to .tmp, rename)."""
    meta_path = course_dir / "metadata.json"
    course_dir.mkdir(parents=True, exist_ok=True)

    # Atomic write: write to temp file in same dir, then rename
    fd, tmp_path = tempfile.mkstemp(dir=course_dir, prefix=".metadata-", suffix=".tmp")
    try:
        tmp = Path(tmp_path)
        tmp.write_text(json.dumps(metadata, indent=2, default=str))
        tmp.replace(meta_path)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise
    finally:
        import os

        os.close(fd)


def next_unique_path(directory: Path, stem: str, suffix: str) -> Path:
    """Return the first non-existing path in the form ``directory/<stem>[-N]<suffix>``.

    Used by the content-generation panel's ``on_existing="suffix"``
    policy: when a deck file already exists, append the smallest
    integer that makes the filename unique rather than overwriting.

    The bare ``<stem><suffix>`` is checked first; if free, returned
    as-is. Otherwise tries ``-1``, ``-2``, ... up to ``9999`` (after
    which something has gone very wrong and we raise rather than
    spin forever).

    Args:
        directory: Where the file will be written. Not created here --
            the caller's ``write_json`` does that.
        stem: Filename stem WITHOUT the suffix (e.g. ``"advanced-pandas-flashcards"``).
        suffix: Filename suffix INCLUDING the dot (e.g. ``".json"``).

    Returns:
        A ``Path`` that does not currently exist.

    Raises:
        RuntimeError: After 9999 attempts -- a sanity ceiling, never
            expected to trip in real use.
    """
    if not suffix.startswith("."):
        suffix = "." + suffix
    base = directory / f"{stem}{suffix}"
    if not base.exists():
        return base
    for n in range(1, 10000):
        candidate = directory / f"{stem}-{n}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(
        f"next_unique_path exhausted 9999 attempts for {directory}/{stem}{suffix}"
    )


def check_content_dependencies() -> list[str]:
    """Check pandoc, mmdc, typst availability.

    Returns list of missing tools with install instructions.
    """
    import shutil

    missing = []
    if not shutil.which("pandoc"):
        missing.append("pandoc (install: brew install pandoc)")
    if not shutil.which("mmdc"):
        missing.append("mmdc / mermaid-cli (install: npm install -g @mermaid-js/mermaid-cli)")
    return missing
