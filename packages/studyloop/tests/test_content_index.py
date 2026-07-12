"""Tests for the fast incremental ContentIndex (studyloop.content.index)."""

from __future__ import annotations

import json

import pytest

from studyloop.content.index import ContentIndex


@pytest.fixture()
def content_tree(tmp_path, monkeypatch):
    """A minimal on-disk content tree: one provider, one course, 2 lessons + artefacts.

    Patches ``content_base`` (used by ContentIndex.refresh) to point at the tree.
    Returns (base_path, db_path).
    """
    base = tmp_path / "study"
    course = base / "ArjanCodes" / "The Software Designer Mindset"
    course.mkdir(parents=True)
    (course / "01-abstraction.md").write_text("# Abstraction\n", encoding="utf-8")
    (course / "02-coupling.md").write_text("# Coupling\n", encoding="utf-8")
    (course / "deck.flashcards.json").write_text(
        json.dumps({"cards": [{"front": "q", "back": "a"}, {"front": "q2", "back": "a2"}]}),
        encoding="utf-8",
    )
    (course / "deck.quiz.json").write_text(
        json.dumps({"questions": [{"q": "1"}, {"q": "2"}, {"q": "3"}]}),
        encoding="utf-8",
    )

    monkeypatch.setattr("studyloop.content.index.content_base", lambda _settings=None: base)
    # load_settings is called but its result is ignored by our patched content_base
    monkeypatch.setattr("studyloop.content.index.load_settings", lambda: object())
    return base, tmp_path / "content_index.db"


def test_refresh_indexes_providers_courses_lessons_artefacts(content_tree) -> None:
    _base, db_path = content_tree
    idx = ContentIndex(db_path=db_path)

    stats = idx.refresh()

    assert stats.providers == 1
    assert stats.courses == 1
    assert stats.lessons == 2
    assert stats.artefacts == 2  # flashcards + quiz


def test_needs_refresh_true_when_empty_then_false_after_refresh(content_tree) -> None:
    _base, db_path = content_tree
    idx = ContentIndex(db_path=db_path)

    assert idx.needs_refresh() is True
    idx.refresh()
    assert idx.needs_refresh() is False


def test_get_tree_reflects_indexed_content(content_tree) -> None:
    _base, db_path = content_tree
    idx = ContentIndex(db_path=db_path)
    idx.refresh()

    tree = idx.get_tree()
    providers = tree["providers"]
    assert "ArjanCodes" in providers

    courses = providers["ArjanCodes"]["courses"]
    assert len(courses) == 1
    course = next(iter(courses.values()))
    assert course["title"] == "The Software Designer Mindset"
    assert len(course["lessons"]) == 2
    kinds = {a["kind"] for a in course["artefacts"]}
    assert kinds == {"flashcards", "quiz"}
    # item_count parsed from the JSON payloads
    counts = {a["kind"]: a["count"] for a in course["artefacts"]}
    assert counts["flashcards"] == 2
    assert counts["quiz"] == 3


def test_refresh_is_incremental_and_idempotent(content_tree) -> None:
    """A second refresh with no changes yields the same course count (INSERT OR REPLACE)."""
    _base, db_path = content_tree
    idx = ContentIndex(db_path=db_path)
    idx.refresh()
    first = idx.fingerprint()["total_courses"]

    idx.refresh()
    second = idx.fingerprint()["total_courses"]

    assert first == second == 1
