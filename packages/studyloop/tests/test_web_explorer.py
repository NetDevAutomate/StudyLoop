"""Tests for the course-explorer API routes (M1 backend).

Covers:
- GET /api/explorer/tree
- GET /api/explorer/courses/{course_id:path}/lessons
- GET /api/explorer/lesson/{lesson_id:path}/content
- GET /api/explorer/search

Security: path traversal guard (../, %2e%2e, absolute, symlink-escape,
non-allowlist suffix).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from shutil import rmtree
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


def _make_tree_client(base: Path, monkeypatch: MonkeyPatch) -> TestClient:
    from studyloop.settings import ContentConfig, Settings

    s = Settings()
    s.content = ContentConfig(base_path=base)
    monkeypatch.setattr("studyloop.settings.load_settings", lambda: s)
    return TestClient(create_app(study_dirs=[]))


def _tree_course_ids(response_body: list[dict[str, object]]) -> set[str]:
    course_ids: set[str] = set()
    for provider in response_body:
        for course in provider["courses"]:  # type: ignore[index]
            course_ids.add(course["id"])
    return course_ids


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

    def test_cache_refreshes_when_nested_course_is_added(
        self, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        first_course = tmp_path / "Provider" / "Course_One"
        first_course.mkdir(parents=True)
        (first_course / "intro.md").write_text("# Intro", encoding="utf-8")
        client = _make_tree_client(tmp_path, monkeypatch)

        before = client.get("/api/explorer/tree").json()
        assert _tree_course_ids(before) == {"Provider/Course_One"}

        second_course = tmp_path / "Provider" / "Course_Two"
        second_course.mkdir()
        (second_course / "lesson.md").write_text("# Lesson", encoding="utf-8")

        after = client.get("/api/explorer/tree").json()
        assert _tree_course_ids(after) == {"Provider/Course_One", "Provider/Course_Two"}

    def test_cache_refreshes_when_nested_course_is_deleted(
        self, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        first_course = tmp_path / "Provider" / "Course_One"
        second_course = tmp_path / "Provider" / "Course_Two"
        first_course.mkdir(parents=True)
        second_course.mkdir()
        (first_course / "intro.md").write_text("# Intro", encoding="utf-8")
        (second_course / "lesson.md").write_text("# Lesson", encoding="utf-8")
        client = _make_tree_client(tmp_path, monkeypatch)

        before = client.get("/api/explorer/tree").json()
        assert _tree_course_ids(before) == {"Provider/Course_One", "Provider/Course_Two"}

        rmtree(second_course)

        after = client.get("/api/explorer/tree").json()
        assert _tree_course_ids(after) == {"Provider/Course_One"}

    def test_output_dirs_do_not_change_tree_fingerprint(
        self, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        from studyloop.web.routes.explorer import _tree_fingerprint

        course = tmp_path / "Provider" / "Course_One"
        course.mkdir(parents=True)
        (course / "intro.md").write_text("# Intro", encoding="utf-8")
        client = _make_tree_client(tmp_path, monkeypatch)

        before = client.get("/api/explorer/tree").json()
        before_fingerprint = _tree_fingerprint(tmp_path)
        assert _tree_course_ids(before) == {"Provider/Course_One"}

        flashcards = course / "flashcards"
        flashcards.mkdir()
        (flashcards / "generated.md").write_text("# Generated", encoding="utf-8")

        after = client.get("/api/explorer/tree").json()
        assert _tree_fingerprint(tmp_path) == before_fingerprint
        assert after == before


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


# ---------------------------------------------------------------------------
# F1: non-deterministic file selection (suffix priority)
# ---------------------------------------------------------------------------


class TestSuffixPriority:
    """F1 — .md must win deterministically when both .md and .txt exist."""

    def test_md_wins_over_txt(self, vault: Path, monkeypatch: MonkeyPatch) -> None:
        """When dup.md and dup.txt both exist, the content endpoint returns .md."""
        course_dir = vault / "CodeWithMosh" / "Complete_SQL_Mastery"
        (course_dir / "dup.md").write_text("MD content", encoding="utf-8")
        (course_dir / "dup.txt").write_text("TXT content", encoding="utf-8")

        from studyloop.settings import ContentConfig, Settings

        s = Settings()
        s.content = ContentConfig(base_path=vault)
        monkeypatch.setattr("studyloop.settings.load_settings", lambda: s)
        c = TestClient(create_app(study_dirs=[]))

        resp = c.get("/api/explorer/lesson/CodeWithMosh/Complete_SQL_Mastery/dup/content")
        assert resp.status_code == 200
        assert resp.json()["content"] == "MD content"

    def test_markdown_wins_over_txt(self, vault: Path, monkeypatch: MonkeyPatch) -> None:
        """.markdown wins over .txt when no .md exists."""
        course_dir = vault / "CodeWithMosh" / "Complete_SQL_Mastery"
        (course_dir / "note.markdown").write_text("MARKDOWN content", encoding="utf-8")
        (course_dir / "note.txt").write_text("TXT content", encoding="utf-8")

        from studyloop.settings import ContentConfig, Settings

        s = Settings()
        s.content = ContentConfig(base_path=vault)
        monkeypatch.setattr("studyloop.settings.load_settings", lambda: s)
        c = TestClient(create_app(study_dirs=[]))

        resp = c.get("/api/explorer/lesson/CodeWithMosh/Complete_SQL_Mastery/note/content")
        assert resp.status_code == 200
        assert resp.json()["content"] == "MARKDOWN content"


# ---------------------------------------------------------------------------
# F6: non-UTF-8 bytes → must return 200 (best-effort render), not 500
# ---------------------------------------------------------------------------


class TestNonUtf8Content:
    """F6 — files with non-UTF-8 bytes must return 200 with replaced chars, not 500."""

    def test_non_utf8_returns_200(self, vault: Path, monkeypatch: MonkeyPatch) -> None:
        course_dir = vault / "CodeWithMosh" / "Complete_SQL_Mastery"
        # Write raw bytes that are not valid UTF-8.
        (course_dir / "bad_encoding.md").write_bytes(b"# T\xff\xfetitle")

        from studyloop.settings import ContentConfig, Settings

        s = Settings()
        s.content = ContentConfig(base_path=vault)
        monkeypatch.setattr("studyloop.settings.load_settings", lambda: s)
        c = TestClient(create_app(study_dirs=[]))

        resp = c.get("/api/explorer/lesson/CodeWithMosh/Complete_SQL_Mastery/bad_encoding/content")
        assert resp.status_code == 200
        body = resp.json()
        assert "content" in body
        # Content must be a string (replacement chars used, not an exception).
        assert isinstance(body["content"], str)


# ---------------------------------------------------------------------------
# SEC-001: symlink filename leak in lessons listing
# ---------------------------------------------------------------------------


class TestLessonsSymlinkLeak:
    """SEC-001 — symlink targets outside the vault must not appear in lessons list."""

    @pytest.mark.skipif(sys.platform == "win32", reason="symlinks not reliable on Windows")
    def test_symlink_escape_not_listed(self, vault: Path, monkeypatch: MonkeyPatch) -> None:
        import tempfile

        course_dir = vault / "CodeWithMosh" / "Complete_SQL_Mastery"
        # Ensure a normal lesson exists.
        (course_dir / "real_lesson.md").write_text("# Real", encoding="utf-8")

        with tempfile.TemporaryDirectory() as truly_outside:
            outside = Path(truly_outside)
            # A file outside the vault with an allowlisted suffix.
            outside_file = outside / "escape.md"
            outside_file.write_text("LEAKED", encoding="utf-8")

            # Symlink inside the course pointing to the outside file.
            link = course_dir / "escape.md"
            link.symlink_to(outside_file)

            from studyloop.settings import ContentConfig, Settings

            s = Settings()
            s.content = ContentConfig(base_path=vault)
            monkeypatch.setattr("studyloop.settings.load_settings", lambda: s)
            c = TestClient(create_app(study_dirs=[]))

            resp = c.get("/api/explorer/courses/CodeWithMosh/Complete_SQL_Mastery/lessons")
            assert resp.status_code == 200
            slugs = {lesson["slug"] for lesson in resp.json()}
            assert "real_lesson" in slugs
            assert "escape" not in slugs


# ---------------------------------------------------------------------------
# Search fixture helpers
# ---------------------------------------------------------------------------


def _make_search_client(vault: Path, tmp_path: Path, monkeypatch: MonkeyPatch) -> TestClient:
    """Build a TestClient with search settings: vault content + isolated FTS db."""
    from studyloop.settings import ContentConfig, Settings

    s = Settings()
    s.content = ContentConfig(base_path=vault)
    # session_db in tmp so explorer_fts.db lands in tmp (sibling to sessions.db)
    s.session_db = tmp_path / "sessions.db"
    monkeypatch.setattr("studyloop.settings.load_settings", lambda: s)
    return TestClient(create_app(study_dirs=[]))


# ---------------------------------------------------------------------------
# Phase 4: GET /api/explorer/search
# ---------------------------------------------------------------------------


class TestExplorerSearch:
    """FTS5 search endpoint: body hits, stemming, guards, shape, mtime, delete."""

    # ------------------------------------------------------------------
    # Basic plumbing
    # ------------------------------------------------------------------

    def test_returns_200_and_results_key(
        self, vault: Path, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        """A valid query returns 200 with a results list."""
        # Plant a lesson with a distinctive body term
        (vault / "CodeWithMosh" / "Complete_SQL_Mastery" / "study-notes" / "ch1.md").write_text(
            "# Chapter 1\nThis chapter covers window functions in SQL.",
            encoding="utf-8",
        )
        c = _make_search_client(vault, tmp_path, monkeypatch)
        resp = c.get("/api/explorer/search?q=window+functions")
        assert resp.status_code == 200
        body = resp.json()
        assert "results" in body
        assert isinstance(body["results"], list)

    def test_body_hit_not_title_match(
        self, vault: Path, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        """Search returns a lesson whose body contains the term but whose title does not."""
        # ch1.md title is "Ch1" — no mention of "closure"
        (vault / "CodeWithMosh" / "Complete_SQL_Mastery" / "study-notes" / "ch1.md").write_text(
            "# Ch1\nA closure captures its enclosing scope.",
            encoding="utf-8",
        )
        c = _make_search_client(vault, tmp_path, monkeypatch)
        resp = c.get("/api/explorer/search?q=closure")
        assert resp.status_code == 200
        ids = [r["lesson_id"] for r in resp.json()["results"]]
        assert any("ch1" in lid for lid in ids), f"Expected ch1 in results, got: {ids}"

    # ------------------------------------------------------------------
    # Porter stemming
    # ------------------------------------------------------------------

    def test_porter_stemming(self, vault: Path, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
        """Searching 'decorators' matches a lesson body containing 'decorator'."""
        (vault / "CodeWithMosh" / "Python_Pro" / "intro.md").write_text(
            "# Intro\nA decorator wraps a function to extend its behaviour.",
            encoding="utf-8",
        )
        c = _make_search_client(vault, tmp_path, monkeypatch)
        resp = c.get("/api/explorer/search?q=decorators")
        assert resp.status_code == 200
        ids = [r["lesson_id"] for r in resp.json()["results"]]
        assert any("intro" in lid for lid in ids), (
            f"Porter stemming failed — expected intro in {ids}"
        )

    # ------------------------------------------------------------------
    # Short / empty query guards
    # ------------------------------------------------------------------

    def test_empty_query_returns_empty(
        self, vault: Path, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        """An empty q returns {"results": []} with 200."""
        c = _make_search_client(vault, tmp_path, monkeypatch)
        resp = c.get("/api/explorer/search?q=")
        assert resp.status_code == 200
        assert resp.json() == {"results": []}

    def test_single_char_query_returns_empty(
        self, vault: Path, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        """A single-character q returns {"results": []} — no error, no FTS call."""
        c = _make_search_client(vault, tmp_path, monkeypatch)
        resp = c.get("/api/explorer/search?q=x")
        assert resp.status_code == 200
        assert resp.json() == {"results": []}

    def test_whitespace_only_query_returns_empty(
        self, vault: Path, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        """Whitespace-only q is treated as empty."""
        c = _make_search_client(vault, tmp_path, monkeypatch)
        resp = c.get("/api/explorer/search?q=   ")
        assert resp.status_code == 200
        assert resp.json() == {"results": []}

    # ------------------------------------------------------------------
    # FTS5 injection / special-char safety
    # ------------------------------------------------------------------

    def test_fts_special_chars_no_error(
        self, vault: Path, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        """Queries with FTS5-special chars return 200, not 500 from a MATCH syntax error."""
        c = _make_search_client(vault, tmp_path, monkeypatch)
        for dangerous in ['"hello"', "* AND OR", "(unbalanced", "title:foo", 'say "hello"']:
            resp = c.get(f"/api/explorer/search?q={dangerous}")
            assert resp.status_code == 200, (
                f"Expected 200 for q={dangerous!r}, got {resp.status_code}"
            )

    def test_fts_double_quote_in_term_no_error(
        self, vault: Path, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        """A query containing a literal double-quote does not crash the FTS MATCH."""
        c = _make_search_client(vault, tmp_path, monkeypatch)
        resp = c.get('/api/explorer/search?q="quoted+phrase"')
        assert resp.status_code == 200

    # ------------------------------------------------------------------
    # Result shape
    # ------------------------------------------------------------------

    def test_result_shape_and_excerpt_mark(
        self, vault: Path, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        """Each result has the required fields; excerpt contains <mark> on a hit."""
        (vault / "CodeWithMosh" / "Python_Pro" / "intro.md").write_text(
            "# Intro\nGenerators are lazy iterators that yield values one at a time.",
            encoding="utf-8",
        )
        c = _make_search_client(vault, tmp_path, monkeypatch)
        resp = c.get("/api/explorer/search?q=generators")
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) > 0, "Expected at least one result"
        r = results[0]
        for field in ("lesson_id", "course_id", "provider", "title", "excerpt"):
            assert field in r, f"Missing field {field!r} in result {r}"
        # excerpt should contain a <mark> highlighting the matched term
        assert "<mark>" in r["excerpt"], f"Expected <mark> in excerpt, got: {r['excerpt']!r}"

    # ------------------------------------------------------------------
    # Mtime refresh: re-index on file change
    # ------------------------------------------------------------------

    def test_mtime_refresh_picks_up_new_content(
        self, vault: Path, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        """After a lesson file changes, the next search returns the updated content."""
        lesson = vault / "CodeWithMosh" / "Python_Pro" / "intro.md"
        lesson.write_text("# Intro\nThis is about inheritance.", encoding="utf-8")
        c = _make_search_client(vault, tmp_path, monkeypatch)

        # First search — seeds the FTS index with 'inheritance'
        resp = c.get("/api/explorer/search?q=inheritance")
        assert resp.status_code == 200
        before_ids = [r["lesson_id"] for r in resp.json()["results"]]
        assert any("intro" in lid for lid in before_ids), (
            "Baseline: expected intro for 'inheritance'"
        )

        # Overwrite lesson with new content + bump mtime explicitly
        lesson.write_text("# Intro\nThis is about metaclasses.", encoding="utf-8")
        new_mtime = time.time() + 2  # definitely newer than indexed mtime
        import os

        os.utime(lesson, (new_mtime, new_mtime))

        # Search for the OLD term — should NOT find it after re-index
        resp2 = c.get("/api/explorer/search?q=inheritance")
        assert resp2.status_code == 200
        after_ids = [r["lesson_id"] for r in resp2.json()["results"]]
        assert not any("intro" in lid for lid in after_ids), (
            f"Old term should not match after re-index, but got: {after_ids}"
        )

        # Search for the NEW term — should find it
        resp3 = c.get("/api/explorer/search?q=metaclasses")
        assert resp3.status_code == 200
        new_ids = [r["lesson_id"] for r in resp3.json()["results"]]
        assert any("intro" in lid for lid in new_ids), (
            f"New term 'metaclasses' not found after re-index; got: {new_ids}"
        )

    # ------------------------------------------------------------------
    # Deleted file no longer appears
    # ------------------------------------------------------------------

    def test_deleted_lesson_removed_from_index(
        self, vault: Path, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        """A lesson deleted from disk does not appear in subsequent search results."""
        lesson = vault / "CodeWithMosh" / "Python_Pro" / "intro.md"
        lesson.write_text("# Intro\nCoroutines enable cooperative multitasking.", encoding="utf-8")
        c = _make_search_client(vault, tmp_path, monkeypatch)

        # First search — populate index
        resp = c.get("/api/explorer/search?q=coroutines")
        assert resp.status_code == 200
        before = [r["lesson_id"] for r in resp.json()["results"]]
        assert any("intro" in lid for lid in before), "Baseline: expected intro for 'coroutines'"

        # Delete the lesson
        lesson.unlink()

        # Search again — deleted lesson must not appear
        resp2 = c.get("/api/explorer/search?q=coroutines")
        assert resp2.status_code == 200
        after = [r["lesson_id"] for r in resp2.json()["results"]]
        assert not any("intro" in lid for lid in after), f"Deleted lesson still in results: {after}"
