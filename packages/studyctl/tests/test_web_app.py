"""Tests for FastAPI web app — API endpoints via TestClient."""

from __future__ import annotations

from typing import TYPE_CHECKING

pytest = __import__("pytest")
pytest.importorskip("fastapi")

from unittest.mock import patch  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from studyctl.web.app import create_app  # noqa: E402

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create a TestClient with a temp study directory."""
    # Create a course with flashcards and quizzes
    course_dir = tmp_path / "test-course"
    fc_dir = course_dir / "flashcards"
    fc_dir.mkdir(parents=True)
    quiz_dir = course_dir / "quizzes"
    quiz_dir.mkdir(parents=True)

    import json

    fc_dir.joinpath("ch1-flashcards.json").write_text(
        json.dumps(
            {
                "title": "Chapter 1",
                "cards": [
                    {"front": "What is Python?", "back": "A programming language"},
                    {"front": "What is a list?", "back": "An ordered collection"},
                ],
            }
        )
    )
    quiz_dir.joinpath("ch1-quiz.json").write_text(
        json.dumps(
            {
                "title": "Chapter 1 Quiz",
                "questions": [
                    {
                        "question": "Which is a Python type?",
                        "answerOptions": [
                            {"text": "int", "isCorrect": True},
                            {"text": "foo", "isCorrect": False},
                        ],
                    }
                ],
            }
        )
    )

    app = create_app(study_dirs=[str(course_dir)])
    return TestClient(app)


class TestIndex:
    def test_root_returns_html(self, client: TestClient) -> None:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_security_headers(self, client: TestClient) -> None:
        resp = client.get("/")
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"


class TestCoursesAPI:
    def test_list_courses(self, client: TestClient) -> None:
        resp = client.get("/api/courses")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "test-course"
        assert data[0]["flashcard_count"] == 2
        assert data[0]["quiz_count"] == 1

    def test_sources_returns_flat_strings(self, client: TestClient) -> None:
        resp = client.get("/api/sources/test-course?mode=flashcards")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert isinstance(data[0], str)

    def test_stats(self, client: TestClient) -> None:
        resp = client.get("/api/stats/test-course")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_reviews" in data

    def test_due(self, client: TestClient) -> None:
        resp = client.get("/api/due/test-course")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_wrong(self, client: TestClient) -> None:
        resp = client.get("/api/wrong/test-course")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestCardsAPI:
    def test_get_flashcards(self, client: TestClient) -> None:
        resp = client.get("/api/cards/test-course?mode=flashcards")
        assert resp.status_code == 200
        cards = resp.json()
        assert len(cards) == 2
        assert cards[0]["type"] == "flashcard"
        assert cards[0]["front"] == "What is Python?"

    def test_get_quizzes(self, client: TestClient) -> None:
        resp = client.get("/api/cards/test-course?mode=quiz")
        assert resp.status_code == 200
        questions = resp.json()
        assert len(questions) == 1
        assert questions[0]["type"] == "quiz"

    def test_missing_course_404(self, client: TestClient) -> None:
        resp = client.get("/api/cards/nonexistent")
        assert resp.status_code == 404

    def test_post_review(self, client: TestClient, tmp_path: Path) -> None:
        with patch("studyctl.web.routes.cards.record_card_review"):
            resp = client.post(
                "/api/review",
                json={
                    "course": "test-course",
                    "card_hash": "abc123",
                    "correct": True,
                },
            )
            assert resp.status_code == 200
            assert resp.json()["ok"] is True


class TestHistoryAPI:
    def test_get_history_empty(self, client: TestClient) -> None:
        resp = client.get("/api/history")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_post_session(self, client: TestClient) -> None:
        with patch("studyctl.web.routes.history.record_session"):
            resp = client.post(
                "/api/session",
                json={
                    "course": "test-course",
                    "total": 10,
                    "correct": 8,
                },
            )
            assert resp.status_code == 200
            assert resp.json()["ok"] is True


class TestStaticFiles:
    def test_css_served(self, client: TestClient) -> None:
        resp = client.get("/style.css")
        assert resp.status_code == 200
        assert "text/css" in resp.headers["content-type"]

    def test_js_served(self, client: TestClient) -> None:
        resp = client.get("/app.js")
        assert resp.status_code == 200

    def test_manifest_served(self, client: TestClient) -> None:
        resp = client.get("/manifest.json")
        assert resp.status_code == 200
