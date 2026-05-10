"""Tests for the §1.10 agent-native parity MCP tools.

The web UI exposes a study-options picker and an end-session button;
these tests lock the matching MCP tools so an agent driving
studyloop via MCP has the same power the browser has.

Plan: docs/plans/2026-05-09-refactor-agent-session-transport-plan.md §1.10
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
                "studyloop.web.routes.session._topic_options",
                return_value=[],
            ),
            patch(
                "studyloop.web.routes.session._vendor_options",
                return_value=[],
            ),
            patch(
                "studyloop.web.routes.session._course_options",
                return_value=[],
            ),
            patch(
                "studyloop.web.routes.session._lesson_options",
                return_value=[],
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
