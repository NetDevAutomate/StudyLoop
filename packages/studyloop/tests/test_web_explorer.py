"""Tests for the course-explorer API routes (M1 backend).

Covers:
- GET /api/explorer/tree
- GET /api/explorer/courses/{course_id:path}/lessons
- GET /api/explorer/lesson/{lesson_id:path}/content

Security: path traversal guard (../, %2e%2e, absolute, symlink-escape,
non-allowlist suffix).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

from studyloop.web.app import create_app

if TYPE_CHECKING:
    from pytest import MonkeyPatch


# ---------------------------------------------------------------------------
# Shared vault fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """Create a minimal two-level study vault.

    Layout:
        <tmp>/
          CodeWithMosh/
            Complete_SQL_Mastery/
              study-notes/
                ch1.md
                ch2.md
              flashcards/         <- output dir, must be skipped in lessons
                deck.json
              quizzes/            <- output dir, must be skipped in lessons
                q.json
              .hidden/            <- dot-dir, must be skipped
                note.md
            Python_Pro/
              intro.md
          .obsidian/              <- dot-dir at provider level, must be skipped
    """
    base = tmp_path
    sql = base / "CodeWithMosh" / "Complete_SQL_Mastery"
    (sql / "study-notes").mkdir(parents=True)
    (sql / "study-notes" / "ch1.md").write_text("# Chapter 1\nHello", encoding="utf-8")
    (sql / "study-notes" / "ch2.md").write_text("# Chapter 2\nWorld", encoding="utf-8")
    (sql / "flashcards").mkdir()
    (sql / "flashcards" / "deck.json").write_text("{}", encoding="utf-8")
    (sql / "quizzes").mkdir()
    (sql / "quizzes" / "q.json").write_text("{}", encoding="utf-8")
    (sql / ".hidden").mkdir()
    (sql / ".hidden" / "note.md").write_text("secret", encoding="utf-8")

    py = base / "CodeWithMosh" / "Python_Pro"
    py.mkdir(parents=True)
    (py / "intro.md").write_text("# Intro", encoding="utf-8")

    (base / ".obsidian").mkdir()

    return base


@pytest.fixture
def client(vault: Path, monkeypatch: MonkeyPatch) -> TestClient:
    from studyloop.settings import ContentConfig, Settings

    s = Settings()
    s.content = ContentConfig(base_path=vault)
    monkeypatch.setattr("studyloop.settings.load_settings", lambda: s)
    return TestClient(create_app(study_dirs=[]))


# ---------------------------------------------------------------------------
# GET /api/explorer/tree
# ---------------------------------------------------------------------------


class TestExplorerTree:
    def test_returns_list(self, client: TestClient) -> None:
        resp = client.get("/api/explorer/tree")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_provider_shape(self, client: TestClient) -> None:
        data = client.get("/api/explorer/tree").json()
        assert len(data) == 1
        provider = data[0]
        assert provider["id"] == "CodeWithMosh"
        assert provider["name"] == "Codewithmosh"
        assert "courses" in provider

    def test_course_shape(self, client: TestClient) -> None:
        data = client.get("/api/explorer/tree").json()
        courses = data[0]["courses"]
        ids = {c["id"] for c in courses}
        assert "CodeWithMosh/Complete_SQL_Mastery" in ids
        assert "CodeWithMosh/Python_Pro" in ids

    def test_course_name_humanised(self, client: TestClient) -> None:
        data = client.get("/api/explorer/tree").json()
        courses = {c["id"]: c for c in data[0]["courses"]}
        assert courses["CodeWithMosh/Complete_SQL_Mastery"]["name"] == "Complete Sql Mastery"
        assert courses["CodeWithMosh/Python_Pro"]["name"] == "Python Pro"

    def test_course_carries_provider(self, client: TestClient) -> None:
        data = client.get("/api/explorer/tree").json()
        for course in data[0]["courses"]:
            assert course["provider"] == "CodeWithMosh"

    def test_skips_dot_dirs(self, client: TestClient) -> None:
        data = client.get("/api/explorer/tree").json()
        provider_ids = {p["id"] for p in data}
        assert ".obsidian" not in provider_ids

    def test_skips_output_dirs_as_providers(self, vault: Path, monkeypatch: MonkeyPatch) -> None:
        # Create flashcards/ at base level (shouldn't become a provider)
        (vault / "flashcards").mkdir(exist_ok=True)
        (vault / "flashcards" / "SomeCourse").mkdir()
        from studyloop.settings import ContentConfig, Settings

        s = Settings()
        s.content = ContentConfig(base_path=vault)
        monkeypatch.setattr("studyloop.settings.load_settings", lambda: s)
        c = TestClient(create_app(study_dirs=[]))
        data = c.get("/api/explorer/tree").json()
        provider_ids = {p["id"] for p in data}
        assert "flashcards" not in provider_ids

    def test_empty_on_missing_base(self, monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
        from studyloop.settings import ContentConfig, Settings

        s = Settings()
        s.content = ContentConfig(base_path=tmp_path / "does_not_exist")
        monkeypatch.setattr("studyloop.settings.load_settings", lambda: s)
        c = TestClient(create_app(study_dirs=[]))
        resp = c.get("/api/explorer/tree")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_cache_hit_returns_same_data(self, client: TestClient) -> None:
        r1 = client.get("/api/explorer/tree").json()
        r2 = client.get("/api/explorer/tree").json()
        assert r1 == r2


# ---------------------------------------------------------------------------
# GET /api/explorer/courses/{course_id:path}/lessons
# ---------------------------------------------------------------------------


class TestExplorerLessons:
    def test_returns_lessons_list(self, client: TestClient) -> None:
        resp = client.get("/api/explorer/courses/CodeWithMosh/Complete_SQL_Mastery/lessons")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2  # ch1, ch2 — intro is in Python_Pro

    def test_lesson_shape(self, client: TestClient) -> None:
        resp = client.get("/api/explorer/courses/CodeWithMosh/Complete_SQL_Mastery/lessons")
        lessons = {entry["slug"]: entry for entry in resp.json()}
        assert "study-notes/ch1" in lessons
        ch1 = lessons["study-notes/ch1"]
        assert ch1["id"] == "CodeWithMosh/Complete_SQL_Mastery/study-notes/ch1"
        assert ch1["name"] == "Ch1"
        assert ch1["course_id"] == "CodeWithMosh/Complete_SQL_Mastery"

    def test_lesson_name_humanised(self, client: TestClient) -> None:
        # Python_Pro/intro.md -> name = "Intro"
        resp = client.get("/api/explorer/courses/CodeWithMosh/Python_Pro/lessons")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Intro"

    def test_skips_output_dirs(self, client: TestClient) -> None:
        resp = client.get("/api/explorer/courses/CodeWithMosh/Complete_SQL_Mastery/lessons")
        slugs = {lesson["slug"] for lesson in resp.json()}
        assert not any("flashcards" in s for s in slugs)
        assert not any("quizzes" in s for s in slugs)

    def test_skips_dot_dirs(self, client: TestClient) -> None:
        resp = client.get("/api/explorer/courses/CodeWithMosh/Complete_SQL_Mastery/lessons")
        slugs = {lesson["slug"] for lesson in resp.json()}
        assert not any(".hidden" in s for s in slugs)

    def test_missing_course_404(self, client: TestClient) -> None:
        resp = client.get("/api/explorer/courses/CodeWithMosh/NoSuchCourse/lessons")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_missing_provider_404(self, client: TestClient) -> None:
        resp = client.get("/api/explorer/courses/NoProvider/SomeCourse/lessons")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/explorer/lesson/{lesson_id:path}/content
# ---------------------------------------------------------------------------


class TestExplorerContent:
    def test_returns_content(self, client: TestClient) -> None:
        resp = client.get(
            "/api/explorer/lesson/CodeWithMosh/Complete_SQL_Mastery/study-notes/ch1/content"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "content" in body
        assert "# Chapter 1" in body["content"]

    def test_echoes_lesson_id(self, client: TestClient) -> None:
        lesson_id = "CodeWithMosh/Complete_SQL_Mastery/study-notes/ch1"
        resp = client.get(f"/api/explorer/lesson/{lesson_id}/content")
        assert resp.json()["lesson_id"] == lesson_id

    def test_missing_lesson_404(self, client: TestClient) -> None:
        resp = client.get(
            "/api/explorer/lesson/CodeWithMosh/Complete_SQL_Mastery/study-notes/missing/content"
        )
        assert resp.status_code == 404

    def test_missing_course_404(self, client: TestClient) -> None:
        resp = client.get("/api/explorer/lesson/CodeWithMosh/NoSuchCourse/intro/content")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Security: traversal guard
# ---------------------------------------------------------------------------


class TestExplorerTraversalGuard:
    """All attacks must yield 404 or 422 (routing-blocked)."""

    def test_dotdot_in_lesson_path(self, client: TestClient) -> None:
        resp = client.get(
            "/api/explorer/lesson/CodeWithMosh/Complete_SQL_Mastery/../../../etc/passwd/content"
        )
        assert resp.status_code in (404, 422)

    def test_percent_encoded_dotdot(self, client: TestClient) -> None:
        # %2e%2e URL-encoded traversal attempt
        resp = client.get(
            "/api/explorer/lesson/CodeWithMosh/Complete_SQL_Mastery/%2e%2e/%2e%2e/etc/passwd/content",
            follow_redirects=False,
        )
        assert resp.status_code in (404, 422)

    def test_absolute_path_blocked(self, client: TestClient, vault: Path) -> None:
        # Absolute path injected as lesson_id (no leading slash — FastAPI strips it)
        # Encode it as a relative-looking path using the full vault path minus leading /
        abs_path = str(vault / "CodeWithMosh" / "Complete_SQL_Mastery" / "study-notes" / "ch1")
        # strip leading /
        relative_form = abs_path.lstrip("/")
        resp = client.get(f"/api/explorer/lesson/{relative_form}/content")
        # Must NOT return 200 — path escapes base
        assert resp.status_code in (404, 422)

    def test_dotdot_in_course_id(self, client: TestClient) -> None:
        resp = client.get("/api/explorer/courses/CodeWithMosh/../../../etc/lessons")
        assert resp.status_code in (404, 422)

    def test_json_suffix_blocked(self, client: TestClient) -> None:
        # Attempt to read a .json file via the content endpoint
        resp = client.get(
            "/api/explorer/lesson/CodeWithMosh/Complete_SQL_Mastery/flashcards/deck.json/content"
        )
        # Either suffix check catches it (404) or path routing rejects (422)
        # We must NOT get 200 with JSON file contents
        assert resp.status_code in (404, 422)

    def test_png_suffix_blocked(self, vault: Path, monkeypatch: MonkeyPatch) -> None:
        # Plant a .png file
        png = vault / "CodeWithMosh" / "Complete_SQL_Mastery" / "study-notes" / "image.png"
        png.write_bytes(b"\x89PNG")
        from studyloop.settings import ContentConfig, Settings

        s = Settings()
        s.content = ContentConfig(base_path=vault)
        monkeypatch.setattr("studyloop.settings.load_settings", lambda: s)
        c = TestClient(create_app(study_dirs=[]))
        resp = c.get(
            "/api/explorer/lesson/CodeWithMosh/Complete_SQL_Mastery/study-notes/image.png/content"
        )
        assert resp.status_code in (404, 422)

    @pytest.mark.skipif(sys.platform == "win32", reason="symlinks not reliable on Windows")
    def test_symlink_escape_blocked(
        self, vault: Path, monkeypatch: MonkeyPatch, tmp_path: Path
    ) -> None:
        # Create a symlink inside vault that points to a directory OUTSIDE vault.
        # vault == tmp_path, so we need a sibling tempdir at the same level.
        import tempfile

        with tempfile.TemporaryDirectory() as truly_outside:
            outside = Path(truly_outside)
            (outside / "secret.md").write_text("TOP SECRET", encoding="utf-8")

            link_dir = vault / "CodeWithMosh" / "Complete_SQL_Mastery" / "study-notes" / "escape"
            link_dir.symlink_to(outside)

            from studyloop.settings import ContentConfig, Settings

            s = Settings()
            s.content = ContentConfig(base_path=vault)
            monkeypatch.setattr("studyloop.settings.load_settings", lambda: s)
            c = TestClient(create_app(study_dirs=[]))
            resp = c.get(
                "/api/explorer/lesson/CodeWithMosh/Complete_SQL_Mastery/study-notes/escape/secret/content"
            )
            assert resp.status_code == 404
