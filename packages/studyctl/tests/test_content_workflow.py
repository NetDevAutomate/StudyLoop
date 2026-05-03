"""Tests for content ingest planning."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from studyctl.content.storage import save_course_metadata
from studyctl.content.workflow import build_ingest_plan


def _write_material(path: Path, content: str = "x" * 120) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return hashlib.sha256(content.encode()).hexdigest()


def test_build_ingest_plan_marks_new_sources_create(tmp_path: Path) -> None:
    root = tmp_path / "Study" / "Python"
    note = root / "decorators.md"
    _write_material(note)

    plan = build_ingest_plan(source_roots=[root], base_path=tmp_path / "materials")

    assert len(plan) == 1
    assert plan[0].action == "create"
    assert plan[0].course_slug == "python"
    assert plan[0].course_dir == tmp_path / "materials" / "python"


def test_build_ingest_plan_marks_unchanged_sources_skip(tmp_path: Path) -> None:
    root = tmp_path / "Study" / "Python"
    note = root / "decorators.md"
    content_hash = _write_material(note)
    course_dir = tmp_path / "materials" / "python"
    save_course_metadata(
        course_dir,
        {"sources": [{"path": str(note), "hash": content_hash}]},
    )

    plan = build_ingest_plan(source_roots=[root], base_path=tmp_path / "materials")

    assert plan[0].action == "skip"


def test_build_ingest_plan_marks_changed_sources_update(tmp_path: Path) -> None:
    root = tmp_path / "Study" / "Python"
    note = root / "decorators.md"
    _write_material(note, "new content" * 20)
    course_dir = tmp_path / "materials" / "python"
    save_course_metadata(
        course_dir,
        {"sources": [{"path": str(note), "hash": "old-hash"}]},
    )

    plan = build_ingest_plan(source_roots=[root], base_path=tmp_path / "materials")

    assert plan[0].action == "update"


def test_build_ingest_plan_uses_explicit_course_slug(tmp_path: Path) -> None:
    root = tmp_path / "Study" / "Data Engineering"
    _write_material(root / "pipelines.md")

    plan = build_ingest_plan(
        source_roots=[root],
        base_path=tmp_path / "materials",
        course="Data Engineering",
    )

    assert plan[0].course_slug == "data-engineering"
