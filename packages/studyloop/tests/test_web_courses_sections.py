"""Tests for ``GET /api/courses/<course>/sections`` (U9).

Drives the WebUI's section dropdown. Reads from
``settings.content.base_path`` (not the review roots) and skips output
subdirs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402  # pyright: ignore[reportMissingImports]

from studyloop.web.app import create_app  # noqa: E402

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    study = tmp_path / "Study"
    course = study / "DataCamp"
    (course / "advanced-pandas").mkdir(parents=True)
    (course / "advanced-pandas" / "ch1.md").write_text("a", encoding="utf-8")
    (course / "advanced-pandas" / "ch2.md").write_text("b", encoding="utf-8")
    (course / "joins").mkdir()
    (course / "joins" / "intro.md").write_text("c", encoding="utf-8")
    (course / "flashcards").mkdir()  # output dir — must be skipped
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
    def test_returns_subdirs_with_file_counts(self, client: TestClient) -> None:
        resp = client.get("/api/courses/DataCamp/sections")
        assert resp.status_code == 200
        data = resp.json()
        slugs = {entry["slug"]: entry["file_count"] for entry in data}
        assert slugs == {"advanced-pandas": 2, "joins": 1}

    def test_skips_output_dirs_and_dot_dirs(self, client: TestClient) -> None:
        data = client.get("/api/courses/DataCamp/sections").json()
        names = {entry["slug"] for entry in data}
        assert "flashcards" not in names
        assert ".obsidian" not in names

    def test_missing_course_returns_404(self, client: TestClient) -> None:
        resp = client.get("/api/courses/NotARealCourse/sections")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()
