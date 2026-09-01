"""Tests for live session dashboard — API + SSE endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast, get_type_hints

if TYPE_CHECKING:
    # ``pytest`` below is bound by __import__, which pyright treats as a
    # variable rather than a module, so it cannot carry type annotations.
    from pytest import MonkeyPatch

pytest = __import__("pytest")
pytest.importorskip("fastapi")

from unittest.mock import MagicMock, patch  # noqa: E402

from fastapi import Request  # noqa: E402  # pyright: ignore[reportMissingImports]
from fastapi.routing import APIRoute  # noqa: E402  # pyright: ignore[reportMissingImports]
from fastapi.testclient import TestClient  # noqa: E402  # pyright: ignore[reportMissingImports]

from studyloop.session_state import TopicEntry  # noqa: E402
from studyloop.web.app import create_app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    """TestClient for session endpoint testing."""
    app = create_app(study_dirs=[])
    return TestClient(app)


class TestSessionPage:
    def test_session_url_redirects_to_hash(self, client: TestClient) -> None:
        resp = client.get("/session", follow_redirects=False)
        assert resp.status_code == 307
        assert resp.headers["location"] == "/#study-session"

    def test_session_redirect_lands_on_index(self, client: TestClient) -> None:
        resp = client.get("/session")  # follows redirect by default
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "session-dashboard" in resp.text


class TestSessionStaticUI:
    def test_course_and_lesson_targets_require_specific_selection(self) -> None:
        """Course/lesson targets must not fall back to the vendor label."""
        # sessionTimer's resolvedTopic() moved out of index.html's inline script
        # into its own ES module, so this reads the module. The requirement is
        # unchanged; only the location is. There are now also direct unit tests for
        # resolvedTopic in packages/studyloop/tests/js/session-timer.test.js, which
        # assert the same behaviour by CALLING it rather than by matching source
        # text - a far better guarantee than this string comparison, which breaks on
        # a reformat that changes nothing.
        js = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "studyloop"
            / "web"
            / "static"
            / "js"
            / "components"
            / "session-timer.js"
        ).read_text()

        assert "if (this.targetKind === 'lesson') {\n          return '';" in js
        assert "if (this.targetKind === 'course') {\n          return '';" in js


class TestSessionStateAPI:
    def test_no_active_session(self, client: TestClient) -> None:
        with (
            patch("studyloop.web.routes.session.read_session_state", return_value={}),
            patch("studyloop.web.routes.session.parse_topics_file", return_value=[]),
            patch("studyloop.web.routes.session.parse_parking_file", return_value=[]),
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
                "studyloop.web.routes.session.read_session_state",
                return_value=mock_state,
            ),
            patch(
                "studyloop.web.routes.session.parse_topics_file",
                return_value=mock_topics,
            ),
            patch("studyloop.web.routes.session.parse_parking_file", return_value=[]),
        ):
            resp = client.get("/api/session/state")
            data = resp.json()
            assert data["study_session_id"] == "abc123"
            assert data["topic"] == "Spark Internals"
            assert len(data["topics"]) == 2
            assert data["topics"][0]["status"] == "win"
            assert data["topics"][1]["status"] == "struggling"

    def test_state_survives_session_files_vanishing_mid_request(
        self, client: TestClient, monkeypatch: MonkeyPatch
    ) -> None:
        """The endpoint returns 200, not 500, when IPC files vanish mid-read.

        Session release runs clear_session_files() on an executor thread, so a
        request in flight can lose session-topics.md between the exists() check
        and the read. That raced GET /api/session/state and returned HTTP 500.

        This drives the REAL parsers (only the file objects are replaced), so it
        exercises the guard rather than a mock of it.
        """

        class _VanishingFile:
            def exists(self) -> bool:
                return True

            def read_text(self, *args: object, **kwargs: object) -> str:
                raise FileNotFoundError(2, "No such file or directory")

        monkeypatch.setattr("studyloop.session_state.TOPICS_FILE", _VanishingFile())
        monkeypatch.setattr("studyloop.session_state.PARKING_FILE", _VanishingFile())

        resp = client.get("/api/session/state")

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["topics"] == []
        assert data["parking"] == []


class TestSessionSSE:
    """SSE format tests.

    The SSE generator runs in an infinite async loop, which makes it
    difficult to test via TestClient.stream() without hanging. Instead
    we test the rendering pipeline directly — the SSE endpoint is a thin
    wrapper that polls files and yields render output.
    """

    def test_sse_endpoint_accepts_request_injection(self, client: TestClient) -> None:
        """Regression: Request must be imported at runtime, or FastAPI returns 422."""
        from studyloop.web.routes.session._dashboard import session_stream

        hints = get_type_hints(session_stream)
        assert hints["request"] is Request

        app = cast("Any", client.app)
        route = next(
            route
            for route in app.routes
            if isinstance(route, APIRoute) and route.path == "/api/session/stream"
        )
        query_param_names = {param.name for param in route.dependant.query_params}
        assert "request" not in query_param_names

    def test_sse_render_produces_valid_sse_format(self) -> None:
        """Verify the render pipeline produces valid SSE event format."""
        from studyloop.web.routes.session import _render_update

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
        # The activity feed content is the inner HTML for the SSE swap target
        # (no wrapper div — the swap target element already has id="activity-feed")
        assert "activity-item" in sse_line
        assert "counter-wins" in sse_line
        assert "session-meta" in sse_line


class TestRenderFunctions:
    """Test the HTML rendering helper functions directly."""

    def test_render_activity_feed_empty(self) -> None:
        from studyloop.web.routes.session import _render_activity_feed

        html = _render_activity_feed({"topics": [], "parking": []})
        assert "activity-empty" in html
        assert "Waiting for session activity" in html

    def test_render_activity_feed_empty_live_session(self) -> None:
        """A live session shows an honest 'what populates this' message rather
        than the misleading 'Waiting for session activity...'."""
        from studyloop.web.routes.session import _render_activity_feed

        html = _render_activity_feed(
            {"topics": [], "parking": [], "study_session_id": "abc", "mode": "focus"}
        )
        assert "activity-empty" in html
        assert "Session live" in html
        assert "Waiting for session activity" not in html

    def test_render_activity_feed_with_topics(self) -> None:
        from studyloop.web.routes.session import _render_activity_feed

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
        from studyloop.web.routes.session import _render_activity_feed

        html = _render_activity_feed({"topics": [], "parking": [{"question": "GIL question"}]})
        assert "status-parked" in html
        assert "GIL question" in html
        assert "\u25cb" in html  # ○ shape

    def test_render_counters(self) -> None:
        from studyloop.web.routes.session import _render_counters

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
        from studyloop.web.routes.session import _render_summary

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
        from studyloop.web.routes.session import _render_update

        state = {
            "mode": "active",
            "topic": "Test",
            "energy": 5,
            "topics": [],
            "parking": [],
        }
        html = _render_update(state)
        # The activity feed content is the inner HTML for the SSE swap target
        # (no wrapper div — the swap target element already has id="activity-feed")
        assert "activity-empty" in html
        assert "counter-wins" in html
        assert "session-meta" in html

    def test_render_update_ended_session(self) -> None:
        from studyloop.web.routes.session import _render_update

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
        from studyloop.web.routes.session import _render_activity_feed

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


class TestTopicsAPI:
    """Tests for GET /api/session/topics."""

    def test_returns_topics_from_settings(self, client: TestClient) -> None:
        from unittest.mock import MagicMock

        from studyloop.settings import TopicConfig

        mock_topics = [
            TopicConfig(name="Python", slug="python", obsidian_path=Path(""), tags=["python"]),
            TopicConfig(name="Spark", slug="spark", obsidian_path=Path(""), tags=["data"]),
        ]
        settings = MagicMock()
        settings.topics = mock_topics
        with patch("studyloop.settings.load_settings", return_value=settings):
            resp = client.get("/api/session/topics")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["name"] == "Python"
        assert data[0]["slug"] == "python"
        assert data[1]["name"] == "Spark"

    def test_returns_empty_on_no_settings(self, client: TestClient) -> None:
        with patch(
            "studyloop.settings.load_settings",
            side_effect=FileNotFoundError,
        ):
            resp = client.get("/api/session/topics")
        assert resp.status_code == 200
        assert resp.json() == []


class TestEndSessionAPI:
    """Tests for POST /api/session/end."""

    def test_end_returns_404_when_no_session(self, client: TestClient) -> None:
        with patch("studyloop.web.routes.session.read_session_state", return_value={}):
            resp = client.post("/api/session/end")
        assert resp.status_code == 404
        assert "No active session" in resp.json()["error"]

    def test_end_calls_cleanup_and_returns_topic(self, client: TestClient) -> None:
        mock_state = {
            "study_session_id": "test-123",
            "topic": "Python Decorators",
            "tmux_session": "study-python-test",
        }
        with (
            patch(
                "studyloop.web.routes.session.read_session_state",
                return_value=mock_state,
            ),
            patch(
                "studyloop.session.cleanup.end_session_common",
                return_value="Python Decorators",
            ) as mock_end,
        ):
            resp = client.post("/api/session/end")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ended"] is True
        assert data["topic"] == "Python Decorators"
        mock_end.assert_called_once_with(mock_state)


class TestStartSessionAPI:
    """Tests for POST /api/session/start — validation and error paths.

    The happy path requires tmux, an agent binary, and a database, so it
    is tested via E2E in test_web_sidebar.py. These tests cover the guard
    clauses and error responses.
    """

    def test_start_rejects_active_session(self, client: TestClient) -> None:
        """Legacy-path 409 when a session is already live."""
        mock_backend = MagicMock()
        mock_backend.is_available.return_value = True
        with (
            patch("studyloop.multiplexer.get_backend", return_value=mock_backend),
            patch("studyloop.web.routes.session.is_session_active", return_value=True),
        ):
            resp = client.post(
                "/api/session/start",
                json={"topic": "Python", "energy": 5, "transport": "ttyd"},
            )
        assert resp.status_code == 409
        assert "already active" in resp.json()["error"]

    def test_start_rejects_no_tmux(self, client: TestClient) -> None:
        """transport=ttyd requires a multiplexer — 503 when unavailable.

        The default (pty) path no longer consults the multiplexer, so this
        assertion is specific to the legacy ttyd opt-in.
        """
        mock_backend = MagicMock()
        mock_backend.is_available.return_value = False
        with patch("studyloop.multiplexer.get_backend", return_value=mock_backend):
            resp = client.post(
                "/api/session/start",
                json={"topic": "Python", "energy": 5, "transport": "ttyd"},
            )
        assert resp.status_code == 503
        error_msg = resp.json()["error"]
        assert "multiplexer" in error_msg.lower() or "not available" in error_msg

    def test_start_rejects_unknown_agent(self, client: TestClient) -> None:
        mock_backend = MagicMock()
        mock_backend.is_available.return_value = True
        with (
            patch("studyloop.multiplexer.get_backend", return_value=mock_backend),
            patch("studyloop.web.routes.session.is_session_active", return_value=False),
        ):
            resp = client.post(
                "/api/session/start",
                json={"topic": "Python", "energy": 5, "agent": "nonexistent", "transport": "ttyd"},
            )
        assert resp.status_code == 400
        assert "Unknown agent" in resp.json()["error"]

    def test_start_rejects_agent_when_binary_missing(self, client: TestClient) -> None:
        """User picks pi but its binary is absent → 503, not a silent fallback.

        Locks in the Phase 0 decision that agent selection is always respected:
        no `null`-fallback substitution, no silent routing to the first detected
        binary. Matches docs/plans/2026-05-09-refactor-agent-session-transport-plan.md
        Phase 0 acceptance criteria.
        """
        mock_backend = MagicMock()
        mock_backend.is_available.return_value = True
        with (
            patch("studyloop.multiplexer.get_backend", return_value=mock_backend),
            patch("studyloop.web.routes.session.is_session_active", return_value=False),
            patch("shutil.which", return_value=None),
        ):
            resp = client.post(
                "/api/session/start",
                json={"topic": "Python", "energy": 5, "agent": "pi", "transport": "ttyd"},
            )
        assert resp.status_code == 503
        error = resp.json()["error"]
        assert "pi" in error
        assert "not found" in error

    def test_start_validates_energy_range(self, client: TestClient) -> None:
        resp = client.post(
            "/api/session/start",
            json={"topic": "Python", "energy": 15},
        )
        assert resp.status_code == 422  # Pydantic validation

    def test_start_requires_topic(self, client: TestClient) -> None:
        resp = client.post(
            "/api/session/start",
            json={"energy": 5},
        )
        assert resp.status_code == 422  # Pydantic validation
