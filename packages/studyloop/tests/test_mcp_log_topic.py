"""Tests for the log_topic MCP tool.

Accesses the tool via the FastMCP server registry, mirroring the pattern
used in test_mcp_tools.py.  append_topic and record_progress are
monkeypatched so the test never touches real filesystem or DB.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, call, patch

mcp_mod = __import__("pytest").importorskip("mcp")

import pytest  # noqa: E402

from studyloop.mcp.server import mcp  # noqa: E402

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helper — mirrors _get_tool() in test_mcp_tools.py
# ---------------------------------------------------------------------------


def _get_tool(name: str):
    tools = mcp._tool_manager._tools
    if name not in tools:
        raise KeyError(f"Tool {name!r} not found. Available: {list(tools.keys())}")
    return tools[name].fn


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect HOME and STUDYLOOP_SESSION_DIR so nothing writes to real files."""
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    # Override the module-level constants in session_state if they are set at
    # import time.  We patch the attributes used by append_topic directly.
    monkeypatch.setenv("STUDYLOOP_SESSION_DIR", str(session_dir))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLogTopicValidation:
    def test_invalid_status_raises_tool_error(self) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        tool = _get_tool("log_topic")
        with pytest.raises(ToolError, match="Invalid status"):
            tool("Python decorators", "unknown_status")

    def test_invalid_status_message_includes_allowed_set(self) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        tool = _get_tool("log_topic")
        with pytest.raises(ToolError) as exc_info:
            tool("generators", "bad")
        msg = str(exc_info.value)
        for allowed in ("learning", "struggling", "insight", "win", "parked"):
            assert allowed in msg


class TestLogTopicStruggling:
    """status='struggling' → both append_topic and record_progress are called."""

    def test_calls_append_topic_and_record_progress(self) -> None:
        tool = _get_tool("log_topic")

        with (
            patch("studyloop.mcp.tools.log_topic.__wrapped__") if False else patch(
                "studyloop.session_state.append_topic"
            ) as mock_append,
            patch("studyloop.history.record_progress") as mock_progress,
        ):
            # We need to patch at the import site used by the closure.
            # The closure does `from studyloop.session_state import append_topic`
            # at call time, so we patch the source module directly.
            pass

        # Re-patch at the module level the closure actually imports from
        with (
            patch(
                "studyloop.session_state.append_topic", autospec=True
            ) as mock_append,
            patch(
                "studyloop.history.record_progress", return_value=True
            ) as mock_progress,
        ):
            result = tool("async/await", "struggling", "confused about event loop")

        assert result == {"logged": "true", "topic": "async/await", "status": "struggling"}
        mock_append.assert_called_once()
        args = mock_append.call_args
        # args: (time_str, topic, status, note)
        assert args[0][1] == "async/await"
        assert args[0][2] == "struggling"
        assert args[0][3] == "confused about event loop"

        mock_progress.assert_called_once_with(
            topic="async/await",
            concept="async/await",
            confidence="struggling",
            notes="confused about event loop",
        )

    def test_time_format_is_hh_mm(self) -> None:
        tool = _get_tool("log_topic")
        captured_time: list[str] = []

        def capture_append(time: str, topic: str, status: str, note: str) -> None:
            captured_time.append(time)

        with (
            patch("studyloop.session_state.append_topic", side_effect=capture_append),
            patch("studyloop.history.record_progress", return_value=True),
        ):
            tool("closures", "struggling")

        assert len(captured_time) == 1
        import re
        assert re.fullmatch(r"\d{2}:\d{2}", captured_time[0]), (
            f"Expected HH:MM, got {captured_time[0]!r}"
        )


class TestLogTopicLearningAndWin:
    @pytest.mark.parametrize(
        ("status", "expected_confidence"),
        [
            ("learning", "learning"),
            ("win", "confident"),
            ("insight", "confident"),
        ],
    )
    def test_confidence_mapping(self, status: str, expected_confidence: str) -> None:
        tool = _get_tool("log_topic")

        with (
            patch("studyloop.session_state.append_topic"),
            patch(
                "studyloop.history.record_progress", return_value=True
            ) as mock_progress,
        ):
            result = tool("list comprehensions", status, "note text")

        assert result["status"] == status
        mock_progress.assert_called_once_with(
            topic="list comprehensions",
            concept="list comprehensions",
            confidence=expected_confidence,
            notes="note text",
        )


class TestLogTopicParked:
    """status='parked' → append_topic called, record_progress skipped."""

    def test_parked_skips_record_progress(self) -> None:
        tool = _get_tool("log_topic")

        with (
            patch("studyloop.session_state.append_topic") as mock_append,
            patch(
                "studyloop.history.record_progress", return_value=True
            ) as mock_progress,
        ):
            result = tool("metaclasses", "parked", "come back later")

        assert result == {"logged": "true", "topic": "metaclasses", "status": "parked"}
        mock_append.assert_called_once()
        mock_progress.assert_not_called()


class TestLogTopicEmptyNote:
    """note defaults to '' — record_progress should receive notes=None."""

    def test_empty_note_becomes_none_in_record_progress(self) -> None:
        tool = _get_tool("log_topic")

        with (
            patch("studyloop.session_state.append_topic"),
            patch(
                "studyloop.history.record_progress", return_value=True
            ) as mock_progress,
        ):
            tool("typing module", "learning")

        mock_progress.assert_called_once_with(
            topic="typing module",
            concept="typing module",
            confidence="learning",
            notes=None,
        )


class TestLogTopicDbFailureIsolation:
    """A DB failure in record_progress must not fail the whole tool."""

    def test_record_progress_exception_does_not_propagate(self) -> None:
        tool = _get_tool("log_topic")

        with (
            patch("studyloop.session_state.append_topic") as mock_append,
            patch(
                "studyloop.history.record_progress",
                side_effect=RuntimeError("DB exploded"),
            ),
        ):
            # Should NOT raise
            result = tool("generators", "struggling", "hard concept")

        assert result["logged"] == "true"
        mock_append.assert_called_once()
