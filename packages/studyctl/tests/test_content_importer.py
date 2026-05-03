"""Tests for generated review artefact imports."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from studyctl.content.importer import import_review_artefacts
from studyctl.content.storage import load_course_metadata


def _write_flashcards(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "title": "Intro",
                "cards": [{"front": "What is ETL?", "back": "Extract, Transform, Load"}],
            }
        )
    )


def _write_quiz(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "title": "Intro Quiz",
                "questions": [
                    {
                        "question": "What does ETL stand for?",
                        "answerOptions": [
                            {"text": "Extract, Transform, Load", "isCorrect": True},
                            {"text": "Easy To Learn", "isCorrect": False},
                        ],
                    }
                ],
            }
        )
    )


def test_import_review_artefacts_copies_valid_files(tmp_path: Path) -> None:
    source = tmp_path / "downloads"
    _write_flashcards(source / "intro-flashcards.json")
    _write_quiz(source / "intro-quiz.json")

    results = import_review_artefacts(
        source_dir=source,
        base_path=tmp_path / "materials",
        course="Python",
    )

    assert [result.action for result in results] == ["imported", "imported"]
    assert (tmp_path / "materials" / "python" / "flashcards" / "intro-flashcards.json").exists()
    assert (tmp_path / "materials" / "python" / "quizzes" / "intro-quiz.json").exists()
    metadata = load_course_metadata(tmp_path / "materials" / "python")
    assert metadata["review_imports"][0]["imported"] == 2


def test_import_review_artefacts_dry_run_does_not_copy(tmp_path: Path) -> None:
    source = tmp_path / "downloads"
    _write_flashcards(source / "intro-flashcards.json")

    results = import_review_artefacts(
        source_dir=source,
        base_path=tmp_path / "materials",
        course="Python",
        dry_run=True,
    )

    assert results[0].action == "imported"
    assert not (tmp_path / "materials" / "python").exists()


def test_import_review_artefacts_skips_unchanged_files(tmp_path: Path) -> None:
    source = tmp_path / "downloads"
    _write_flashcards(source / "intro-flashcards.json")
    import_review_artefacts(source_dir=source, base_path=tmp_path / "materials", course="Python")

    results = import_review_artefacts(
        source_dir=source,
        base_path=tmp_path / "materials",
        course="Python",
    )

    assert results[0].action == "skipped"


def test_import_review_artefacts_reports_invalid_files(tmp_path: Path) -> None:
    source = tmp_path / "downloads"
    source.mkdir()
    (source / "bad-flashcards.json").write_text(json.dumps({"cards": [{"front": "Q"}]}))

    results = import_review_artefacts(
        source_dir=source,
        base_path=tmp_path / "materials",
        course="Python",
    )

    assert results[0].action == "invalid"
    assert "front" in results[0].message
