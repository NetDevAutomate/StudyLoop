"""Tests for ``GET /api/courses/<course>/sections`` (U9).

Drives the WebUI's section dropdown. A "section" is an individual lesson
**file** under the course (3-level tree: publisher/course/<lesson>.md).
Reads from ``settings.content.base_path`` (not the review roots) and skips
output subdirs / dot-dirs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

from studyloop.web.app import create_app

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    # 3-level: Study/<publisher>/<course>/...  course = "Complete_SQL".
    study = tmp_path / "Study"
    course = study / "CodeWithMosh" / "Complete_SQL"
    (course / "study-notes").mkdir(parents=True)
    (course / "study-notes" / "ch1.md").write_text("a", encoding="utf-8")
    (course / "study-notes" / "ch2.md").write_text("b", encoding="utf-8")
    (course / "study-notes" / "joins.md").write_text("c", encoding="utf-8")
    (course / "flashcards").mkdir()  # output dir — must be skipped
    (course / "flashcards" / "old-deck.json").write_text("{}", encoding="utf-8")
    (course / ".obsidian").mkdir()  # dot dir — must be skipped
    return study


@pytest.fixture
def client(vault: Path, monkeypatch: MonkeyPatch) -> TestClient:
    from studyloop.settings import ContentConfig, Settings

    s = Settings()
    s.content = ContentConfig(base_path=vault)
    monkeypatch.setattr("studyloop.settings.load_settings", lambda: s)
    return TestClient(create_app(study_dirs=[]))


class TestSectionsRoute:
    def test_returns_one_entry_per_lesson_file(self, client: TestClient) -> None:
        resp = client.get("/api/courses/Complete_SQL/sections?publisher=CodeWithMosh")
        assert resp.status_code == 200
        data = resp.json()
        # slug = lesson file path relative to the course dir (suffix stripped).
        slugs = {entry["slug"] for entry in data}
        assert slugs == {
            "study-notes/ch1",
            "study-notes/ch2",
            "study-notes/joins",
        }
        # Each entry carries a humanised name; no file_count (sections are files).
        for entry in data:
            assert "name" in entry

    def test_skips_output_dirs_and_dot_dirs(self, client: TestClient) -> None:
        data = client.get("/api/courses/Complete_SQL/sections?publisher=CodeWithMosh").json()
        slugs = {entry["slug"] for entry in data}
        assert not any("flashcards" in s for s in slugs)
        assert not any(".obsidian" in s for s in slugs)
        assert not any("old-deck" in s for s in slugs)

    def test_missing_course_returns_404(self, client: TestClient) -> None:
        resp = client.get("/api/courses/NotARealCourse/sections?publisher=CodeWithMosh")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()
