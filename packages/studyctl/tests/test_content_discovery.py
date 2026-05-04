"""Tests for study material discovery."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from studyctl.content.discovery import discover_materials


def _write_material(path: Path, content: str | bytes | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = content if content is not None else ("x" * 120)
    if isinstance(payload, bytes):
        path.write_bytes(payload)
    else:
        path.write_text(payload)


def test_discover_materials_finds_supported_files(tmp_path: Path) -> None:
    root = tmp_path / "Study" / "Python"
    _write_material(root / "Decorators.md")
    _write_material(root / "chapter-01.pdf", b"%PDF-1.4\n" + b"x" * 120)
    _write_material(root / "notes.txt")

    materials = discover_materials([root])

    assert [material.kind for material in materials] == ["markdown", "pdf", "text"]
    assert [material.title for material in materials] == ["Decorators", "Chapter 01", "Notes"]


def test_discover_materials_skips_low_value_files(tmp_path: Path) -> None:
    root = tmp_path / "Study"
    _write_material(root / ".obsidian" / "workspace.json")
    _write_material(root / "node_modules" / "package.txt")
    _write_material(root / "Courses.md")
    _write_material(root / "tiny.md", "too small")
    _write_material(root / "image.png", b"x" * 120)
    _write_material(root / "real-note.md")

    materials = discover_materials([root])

    assert [material.path.name for material in materials] == ["real-note.md"]


def test_discover_materials_deduplicates_overlapping_roots(tmp_path: Path) -> None:
    root = tmp_path / "Study"
    child = root / "Python"
    _write_material(child / "generators.md")

    materials = discover_materials([root, child])

    assert len(materials) == 1
    assert materials[0].path == child / "generators.md"


def test_discover_materials_ignores_missing_roots(tmp_path: Path) -> None:
    assert discover_materials([tmp_path / "missing"]) == []
