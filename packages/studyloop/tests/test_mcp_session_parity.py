"""Tests for the §1.10 agent-native parity MCP tools.

The web UI exposes a study-options picker and an end-session button;
these tests lock the matching MCP tools so an agent driving
studyloop via MCP has the same power the browser has.

Plan: private-docs/2026-05-09-refactor-agent-session-transport-plan.md §1.10
"""

from __future__ import annotations

from unittest.mock import patch

__import__("pytest").importorskip("mcp")

from studyloop.mcp.server import mcp  # noqa: E402


def _get_tool(name: str):
    tools = mcp._tool_manager._tools
    if name not in tools:
        raise KeyError(f"Tool '{name}' not found. Available: {list(tools.keys())}")
    return tools[name].fn


# ---------------------------------------------------------------------------
# list_session_options — thin wrapper over GET /session/options builders
# ---------------------------------------------------------------------------


class TestListSessionOptions:
    def test_returns_same_shape_as_web_route(self) -> None:
        """The MCP tool must expose the same keys the frontend picker
        hydrates from ``GET /api/session/options`` — otherwise agents
        and users see different choice surfaces."""
        tool = _get_tool("list_session_options")
        with (
            patch(
                "studyloop.web.routes.session._options._get_indexed_target_options",
                return_value={
                    "session_types": [
                        {"label": "Study Session", "value": "study", "kind": "session_type"}
                    ],
                    "topics": [],
                    "vendors": [],
                    "courses": [],
                    "lessons": [],
                },
            ),
            patch(
                "studyloop.web.routes.session._agent_options",
                return_value=[{"label": "Claude", "value": "claude", "available": True}],
            ),
        ):
            result = tool()

        assert set(result.keys()) == {
            "session_types",
            "topics",
            "vendors",
            "courses",
            "lessons",
            "agents",
        }
        assert result["agents"] == [{"label": "Claude", "value": "claude", "available": True}]


# ---------------------------------------------------------------------------
# end_session — thin wrapper over end_session_common()
# ---------------------------------------------------------------------------


class TestEndSession:
    def test_ends_active_session(self) -> None:
        tool = _get_tool("end_session")
        mock_state = {"study_session_id": "s-1", "topic": "Python"}
        with (
            patch(
                "studyloop.web.routes.session.read_session_state",
                return_value=mock_state,
            ),
            patch(
                "studyloop.session.cleanup.end_session_common",
                return_value="Python",
            ) as mock_end,
        ):
            result = tool()

        assert result == {"ended": True, "topic": "Python"}
        mock_end.assert_called_once_with(mock_state)

    def test_returns_no_active_session_when_none(self) -> None:
        """No active study_session_id → tool reports no-op cleanly.

        Idempotent: an agent can call end_session() after a prior call
        and get a meaningful response, not an exception."""
        tool = _get_tool("end_session")
        with patch(
            "studyloop.web.routes.session.read_session_state",
            return_value={},
        ):
            result = tool()

        assert result == {"ended": False, "topic": None}


# ---------------------------------------------------------------------------
# Registration: ensure both tools land in the MCP server registry
# ---------------------------------------------------------------------------


class TestToolRegistration:
    def test_session_parity_tools_registered(self) -> None:
        names = set(mcp._tool_manager._tools.keys())
        assert "list_session_options" in names
        assert "end_session" in names
        assert "get_due_cards" in names
        assert "log_review_outcome" in names
        assert "get_next_action" in names
        assert "get_active_topics" in names
        assert "log_struggle" in names


# ---------------------------------------------------------------------------
# get_due_cards — thin wrapper over review.get_due / list_course_summaries
# ---------------------------------------------------------------------------


class TestGetDueCards:
    def test_single_course_serializes_card_progress_fields(self) -> None:
        from studyloop.review_db import CardProgress

        card = CardProgress(
            card_hash="abc123",
            last_correct=True,
            ease_factor=2.5,
            interval_days=6,
            next_review="2026-07-12",
            review_count=3,
        )
        tool = _get_tool("get_due_cards")
        with patch("studyloop.mcp.tools.get_due", return_value=[card]) as mock_get_due:
            result = tool(course="python-basics")

        mock_get_due.assert_called_once_with("python-basics")
        assert result["count"] == 1
        assert result["due_cards"] == [
            {
                "course": "python-basics",
                "card_hash": "abc123",
                "last_correct": True,
                "ease_factor": 2.5,
                "interval_days": 6,
                "next_review": "2026-07-12",
                "review_count": 3,
            }
        ]

    def test_aggregates_across_courses_when_no_course_given(self) -> None:
        from studyloop.review_db import CardProgress

        card_a = CardProgress("a1", True, 2.5, 1, "2026-07-12", 1)
        card_b = CardProgress("b1", False, 1.3, 1, "2026-07-12", 2)

        tool = _get_tool("get_due_cards")
        with (
            patch(
                "studyloop.services.review.list_course_summaries",
                return_value=[{"name": "course-a"}, {"name": "course-b"}],
            ),
            patch(
                "studyloop.settings.resolve_study_dirs",
                return_value=["/fake/dir"],
            ),
            patch(
                "studyloop.mcp.tools.get_due",
                side_effect=lambda c: [card_a] if c == "course-a" else [card_b],
            ),
        ):
            result = tool()

        assert result["count"] == 2
        assert {c["course"] for c in result["due_cards"]} == {"course-a", "course-b"}

    def test_respects_limit(self) -> None:
        from studyloop.review_db import CardProgress

        cards = [CardProgress(f"h{i}", True, 2.5, 1, "2026-07-12", 1) for i in range(5)]
        tool = _get_tool("get_due_cards")
        with patch("studyloop.mcp.tools.get_due", return_value=cards):
            result = tool(course="python-basics", limit=2)

        assert result["count"] == 2
        assert len(result["due_cards"]) == 2


# ---------------------------------------------------------------------------
# log_review_outcome — thin wrapper over review.record_review
# ---------------------------------------------------------------------------


class TestLogReviewOutcome:
    def test_logs_flashcard_outcome(self) -> None:
        tool = _get_tool("log_review_outcome")
        with patch("studyloop.mcp.tools.record_review") as mock_record:
            result = tool(
                course="python-basics",
                card_type="flashcard",
                card_hash="abc123",
                correct=True,
                response_time_ms=1500,
            )

        mock_record.assert_called_once_with(
            course="python-basics",
            card_type="flashcard",
            card_hash="abc123",
            correct=True,
            response_time_ms=1500,
        )
        assert result == {
            "status": "logged",
            "course": "python-basics",
            "card_hash": "abc123",
            "correct": True,
        }

    def test_rejects_invalid_card_type(self) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        tool = _get_tool("log_review_outcome")
        try:
            tool(course="c", card_type="essay", card_hash="h", correct=True)
        except ToolError:
            pass
        else:
            raise AssertionError("Expected ToolError for invalid card_type")


# ---------------------------------------------------------------------------
# get_next_action — thin wrapper over learning.decision.build_now_plan
# ---------------------------------------------------------------------------


class TestGetNextAction:
    def test_delegates_to_build_now_plan(self) -> None:
        fake_plan = type(
            "FakePlan",
            (),
            {"to_json_dict": lambda self: {"primary": {"concept": "closures"}}},
        )()
        tool = _get_tool("get_next_action")
        with patch(
            "studyloop.learning.decision.build_now_plan", return_value=fake_plan
        ) as mock_build:
            result = tool(energy="high", time_minutes=15, modality="hands-on")

        mock_build.assert_called_once_with(energy="high", time_minutes=15, modality="hands-on")
        assert result == {"primary": {"concept": "closures"}}

    def test_rejects_invalid_energy(self) -> None:
        """A typo'd energy must fail loudly, not flow into scoring unvalidated."""
        from mcp.server.fastmcp.exceptions import ToolError

        tool = _get_tool("get_next_action")
        with (
            patch(
                "studyloop.learning.decision.build_now_plan",
                side_effect=AssertionError("must not reach the engine"),
            ),
            __import__("pytest").raises(ToolError, match="Invalid energy"),
        ):
            tool(energy="LOW")

    def test_rejects_invalid_modality(self) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        tool = _get_tool("get_next_action")
        with (
            patch(
                "studyloop.learning.decision.build_now_plan",
                side_effect=AssertionError("must not reach the engine"),
            ),
            __import__("pytest").raises(ToolError, match="Invalid modality"),
        ):
            tool(modality="recal")


# ---------------------------------------------------------------------------
# get_active_topics — pending backlog capped at MAX_ACTIVE_TOPICS
# ---------------------------------------------------------------------------


class TestGetActiveTopics:
    def test_caps_active_at_max_active_topics(self) -> None:
        from studyloop.settings import MAX_ACTIVE_TOPICS

        pending = [{"id": i, "question": f"q{i}"} for i in range(MAX_ACTIVE_TOPICS + 2)]
        tool = _get_tool("get_active_topics")
        with patch("studyloop.parking.get_parked_topics", return_value=pending) as mock_get:
            result = tool()

        mock_get.assert_called_once_with(status="pending")
        assert result["active_count"] == MAX_ACTIVE_TOPICS
        assert len(result["active"]) == MAX_ACTIVE_TOPICS
        assert result["backlog_count"] == 2
        assert result["max_active"] == MAX_ACTIVE_TOPICS

    def test_no_backlog_when_under_limit(self) -> None:
        tool = _get_tool("get_active_topics")
        with patch("studyloop.parking.get_parked_topics", return_value=[{"id": 1}]):
            result = tool()

        assert result["active_count"] == 1
        assert result["backlog_count"] == 0


# ---------------------------------------------------------------------------
# log_struggle — thin wrapper over parking.park_topic(source="struggled")
# ---------------------------------------------------------------------------


class TestLogStruggle:
    def test_logs_struggle_with_struggled_source(self) -> None:
        tool = _get_tool("log_struggle")
        with patch("studyloop.parking.park_topic", return_value=42) as mock_park:
            result = tool(question="What is a closure?", topic_tag="python", context="ch3")

        mock_park.assert_called_once_with(
            "What is a closure?",
            topic_tag="python",
            context="ch3",
            source="struggled",
        )
        assert result == {"status": "logged", "id": 42}
