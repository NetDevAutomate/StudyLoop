"""Content pipeline service layer.

Framework-agnostic wrappers for content pipeline operations. Used by
CLI, future FastAPI web UI, and MCP server.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from studyctl.content import storage

if TYPE_CHECKING:
    from pathlib import Path


def list_courses(base_path: Path) -> list[dict]:
    """List all courses under the content base path."""
    return storage.list_courses(base_path)


def get_course(base_path: Path, slug: str) -> Path:
    """Get or create a course directory with standard subdirs."""
    return storage.get_course_dir(base_path, slug)


def slugify_title(title: str) -> str:
    """Convert a book/course title to a filesystem-safe slug."""
    return storage.slugify(title)


def get_metadata(course_dir: Path) -> dict:
    """Load course metadata (notebook IDs, syllabus state, generation history)."""
    return storage.load_course_metadata(course_dir)


def save_metadata(course_dir: Path, metadata: dict) -> None:
    """Save course metadata atomically."""
    storage.save_course_metadata(course_dir, metadata)
