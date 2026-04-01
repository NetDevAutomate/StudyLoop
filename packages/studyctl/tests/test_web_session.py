"""Tests for live session dashboard — API + SSE endpoints."""

from __future__ import annotations

pytest = __import__("pytest")
pytest.importorskip("fastapi")

from unittest.mock import patch  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from studyctl.session_state import TopicEntry  # noqa: E402
from studyctl.web.app import create_app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    """TestClient for session endpoint testing."""
    app = create_app(study_dirs=[])
    return TestClient(app)


class TestSessionPage:
    def test_session_page_returns_html(self, client: TestClient) -> None:
        resp = client.get("/session")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "session-dashboard" in resp.text

    def test_session_page_loads_htmx(self, client: TestClient) -> None:
        resp = client.get("/session")
        assert "htmx.org" in resp.text

    def test_session_page_loads_alpine(self, client: TestClient) -> None:
        resp = client.get("/session")
        assert "alpinejs" in resp.text


class TestSessionStateAPI:
    def test_no_active_session(self, client: TestClient) -> None:
        with (
            patch("studyctl.web.routes.session.read_session_state", return_value={}),
            patch("studyctl.web.routes.session.parse_topics_file", return_value=[]),
            patch("studyctl.web.routes.session.parse_parking_file", return_value=[]),
        ):
            resp = client.get("/api/session/state")
            assert resp.status_code == 200
            data = resp.json()
            assert data["topics"] == []
            assert data["parking"] == []

    def test_active_session_returns_full_state(self, client: TestClient) -> None:
        mock_state = {
            "study_session_id": "abc123",
            "topic": "Spark Internals",
            "energy": 7,
            "start_time": "2026-03-28T10:00:00",
        }
        mock_topics = [
            TopicEntry(
                time="10:05",
                topic="Spark partitioning",
                status="win",
                note="Basic concepts clicked",
            ),
            TopicEntry(
                time="10:15",
                topic="SQL windows",
                status="struggling",
                note="Re-explained twice",
            ),
        ]
        with (
            patch(
                "studyctl.web.routes.session.read_session_state",
                return_value=mock_state,
            ),
            patch(
                "studyctl.web.routes.session.parse_topics_file",
                return_value=mock_topics,
            ),
            patch("studyctl.web.routes.session.parse_parking_file", return_value=[]),
        ):
            resp = client.get("/api/session/state")
            data = resp.json()
            assert data["study_session_id"] == "abc123"
            assert data["topic"] == "Spark Internals"
            assert len(data["topics"]) == 2
            assert data["topics"][0]["status"] == "win"
            assert data["topics"][1]["status"] == "struggling"


class TestSessionSSE:
    """SSE format tests.

    The SSE generator runs in an infinite async loop, which makes it
    difficult to test via TestClient.stream() without hanging. Instead
    we test the rendering pipeline directly — the SSE endpoint is a thin
    wrapper that polls files and yields render output.
    """

    def test_sse_render_produces_valid_sse_format(self) -> None:
        """Verify the render pipeline produces valid SSE event format."""
        from studyctl.web.routes.session import _render_update

        state = {
            "mode": "active",
            "topic": "Test Topic",
            "energy": 7,
            "topics": [{"time": "10:00", "topic": "Spark", "status": "win", "note": "OK"}],
            "parking": [],
        }
        html = _render_update(state)
        # SSE data lines cannot contain raw newlines
        escaped = html.replace("\n", "")
        sse_line = f"event: session-update\ndata: {escaped}\n\n"
        assert sse_line.count("\n\n") == 1  # Exactly one blank line delimiter
        assert "activity-feed" in sse_line
        assert "counter-wins" in sse_line
        assert "session-meta" in sse_line


class TestRenderFunctions:
    """Test the HTML rendering helper functions directly."""

    def test_render_activity_feed_empty(self) -> None:
        from studyctl.web.routes.session import _render_activity_feed

        html = _render_activity_feed({"topics": [], "parking": []})
        assert "activity-empty" in html
        assert "Waiting for session activity" in html

    def test_render_activity_feed_with_topics(self) -> None:
        from studyctl.web.routes.session import _render_activity_feed

        state = {
            "topics": [
                {
                    "time": "10:05",
                    "topic": "Spark",
                    "status": "win",
                    "note": "Got it",
                },
                {
                    "time": "10:15",
                    "topic": "SQL",
                    "status": "struggling",
                    "note": "",
                },
            ],
            "parking": [{"question": "How does GIL work?"}],
        }
        html = _render_activity_feed(state)
        assert "status-win" in html
        assert "status-struggling" in html
        assert "\u2713" in html  # ✓ shape
        assert "\u25b2" in html  # ▲ shape
        assert "Spark" in html
        assert "SQL" in html

    def test_render_activity_feed_parking(self) -> None:
        from studyctl.web.routes.session import _render_activity_feed

        html = _render_activity_feed({"topics": [], "parking": [{"question": "GIL question"}]})
        assert "status-parked" in html
        assert "GIL question" in html
        assert "\u25cb" in html  # ○ shape

    def test_render_counters(self) -> None:
        from studyctl.web.routes.session import _render_counters

        state = {
            "topics": [
                {"status": "win"},
                {"status": "insight"},
                {"status": "struggling"},
                {"status": "learning"},
            ],
            "parking": [{"question": "q1"}, {"question": "q2"}],
        }
        html = _render_counters(state)
        assert "WINS: 2" in html
        assert "PARKED: 2" in html
        assert "REVIEW: 1" in html
        assert 'hx-swap-oob="true"' in html

    def test_render_summary(self) -> None:
        from studyctl.web.routes.session import _render_summary

        state = {
            "topic": "Spark Internals",
            "topics": [
                {"status": "win", "topic": "Partitioning", "note": "Got it"},
                {"status": "struggling", "topic": "SQL windows", "note": ""},
            ],
            "parking": [{"question": "GIL vs multiprocessing"}],
        }
        html = _render_summary(state)
        assert "Session Complete" in html
        assert "Spark Internals" in html
        assert "Partitioning" in html
        assert "SQL windows" in html
        assert "GIL vs multiprocessing" in html
        assert "session-summary" in html

    def test_render_update_active_session(self) -> None:
        from studyctl.web.routes.session import _render_update

        state = {
            "mode": "active",
            "topic": "Test",
            "energy": 5,
            "topics": [],
            "parking": [],
        }
        html = _render_update(state)
        assert "activity-feed" in html
        assert "counter-wins" in html
        assert "session-meta" in html

    def test_render_update_ended_session(self) -> None:
        from studyctl.web.routes.session import _render_update

        state = {
            "mode": "ended",
            "topic": "Test",
            "topics": [{"status": "win", "topic": "A", "note": ""}],
            "parking": [],
        }
        html = _render_update(state)
        assert "session-summary" in html
        assert "Session Complete" in html

    def test_html_escaping(self) -> None:
        from studyctl.web.routes.session import _render_activity_feed

        state = {
            "topics": [
                {
                    "time": "10:00",
                    "topic": "<script>alert('xss')</script>",
                    "status": "learning",
                    "note": "",
                }
            ],
            "parking": [],
        }
        html = _render_activity_feed(state)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
