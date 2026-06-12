"""Tests for Socratic note companion prompt generation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from studyloop.learning import note_companion

if TYPE_CHECKING:
    from pathlib import Path


def test_explicit_note_path_loads_and_chunks_by_heading(monkeypatch, tmp_path: Path) -> None:
    note = tmp_path / "Study" / "python.md"
    note.parent.mkdir()
    note.write_text(
        "# Decorators\nText\n\n## Wrapper\n```python\nprint('x')\n```",
        encoding="utf-8",
    )
    monkeypatch.setattr(note_companion, "allowed_note_roots", lambda: [note.parent.resolve()])

    pack = note_companion.build_note_companion_pack(note)

    assert pack.title == "Python"
    assert any(chunk.heading == "Decorators" for chunk in pack.chunks)
    assert any(chunk.kind == "code" for chunk in pack.chunks)
    assert "studyloop progress" in pack.suggested_command


def test_diagram_mode_includes_mermaid_aware_prompt(monkeypatch, tmp_path: Path) -> None:
    note = tmp_path / "Study" / "spark.md"
    note.parent.mkdir()
    note.write_text("# Shuffle\nA flow.", encoding="utf-8")
    monkeypatch.setattr(note_companion, "allowed_note_roots", lambda: [note.parent.resolve()])

    pack = note_companion.build_note_companion_pack(note, mode="diagram")

    assert "Mermaid" in pack.prompt
    assert "mermaid" in pack.prompt


def test_missing_note_fails_with_clear_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Note not found"):
        note_companion.resolve_note_path(tmp_path / "missing.md", roots=[tmp_path])


def test_outside_vault_path_fails(tmp_path: Path) -> None:
    allowed = tmp_path / "Study"
    outside = tmp_path / "Elsewhere" / "note.md"
    allowed.mkdir()
    outside.parent.mkdir()
    outside.write_text("# Outside", encoding="utf-8")

    with pytest.raises(ValueError, match="outside"):
        note_companion.resolve_note_path(outside, roots=[allowed.resolve()])
