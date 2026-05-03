"""Tests for course progress aggregation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from click.testing import CliRunner

from studyctl.cli import cli
from studyctl.content.storage import save_course_metadata
from studyctl.review_db import record_card_review, record_session

if TYPE_CHECKING:
    from pathlib import Path


def test_summarize_course_progress_combines_content_and_review_state(tmp_path: Path) -> None:
    from studyctl.progress import summarize_course_progress

    base_path = tmp_path / "materials"
    course_dir = base_path / "python"
    (course_dir / "flashcards").mkdir(parents=True)
    (course_dir / "flashcards" / "deck.json").write_text("[]")
    (course_dir / "quizzes").mkdir()
    (course_dir / "quizzes" / "quiz.json").write_text("{}")
    save_course_metadata(
        course_dir,
        {
            "title": "Python",
            "notebook_id": "nb-python",
            "sources": [
                {"path": "/notes/decorators.md", "hash": "hash-1"},
                {"path": "/notes/generators.md", "hash": "hash-2"},
            ],
        },
    )
    db_path = tmp_path / "sessions.db"
    record_card_review("python", "flashcard", "card-1", True, db_path=db_path)
    record_card_review("python", "quiz", "card-2", False, db_path=db_path)
    record_session("python", "flashcards", 2, 1, db_path=db_path)

    summary = summarize_course_progress(base_path=base_path, db_path=db_path)

    assert len(summary.courses) == 1
    course = summary.courses[0]
    assert course.slug == "python"
    assert course.title == "Python"
    assert course.source_count == 2
    assert course.flashcard_files == 1
    assert course.quiz_files == 1
    assert course.review.unique_cards == 2
    assert course.review.total_reviews == 2
    assert course.review.sessions == 1
    assert summary.totals["sources"] == 2
    assert summary.totals["unique_cards"] == 2


def test_summarize_course_progress_can_filter_one_course(tmp_path: Path) -> None:
    from studyctl.progress import summarize_course_progress

    for slug in ("python", "sql"):
        save_course_metadata(tmp_path / "materials" / slug, {"title": slug.upper(), "sources": []})

    summary = summarize_course_progress(base_path=tmp_path / "materials", course="sql")

    assert [course.slug for course in summary.courses] == ["sql"]


def test_progress_command_prints_json_summary(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "sessions.db"
    base_path = tmp_path / "materials"
    config_path.write_text(
        f"""
session_db: {db_path}
content:
  base_path: {base_path}
"""
    )
    monkeypatch.setenv("STUDYCTL_CONFIG", str(config_path))
    save_course_metadata(base_path / "python", {"title": "Python", "sources": [{"path": "a"}]})
    record_card_review("python", "flashcard", "card-1", True, db_path=db_path)

    result = CliRunner().invoke(cli, ["progress", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["courses"][0]["slug"] == "python"
    assert payload["courses"][0]["review"]["unique_cards"] == 1


def test_progress_command_keeps_existing_record_mode(monkeypatch) -> None:
    monkeypatch.setattr("studyctl.history.record_progress", lambda *a, **kw: True)

    result = CliRunner().invoke(
        cli,
        [
            "progress",
            "list comprehensions",
            "--topic",
            "python",
            "--confidence",
            "confident",
        ],
    )

    assert result.exit_code == 0
    assert "Recorded" in result.output
