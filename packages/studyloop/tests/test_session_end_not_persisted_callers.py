"""A failed session save is reported, not thrown, by the CLI and MCP end paths.

Lane 2 of the 2026-10-21 review made ``end_session_common`` raise
``SessionNotPersistedError`` when the study_sessions row cannot be written,
instead of tearing the session down and deleting the only copy of its topics
and parking lot. The web End route catches it (503, session kept, retry). The
two other callers did not: ``studyloop study --end`` printed a traceback and
the MCP ``end_session`` tool surfaced a raw exception. Both must say what
happened -- the session is still running, its evidence was kept, end it again
-- and the CLI must exit non-zero.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from studyloop.session.cleanup import SessionNotPersistedError

_STATE = {"study_session_id": "s-1", "topic": "Window functions"}
_ERR = SessionNotPersistedError(
    "study session s-1 could not be saved; its topics and parking lot were kept "
    "so ending it again can retry"
)


class TestCliEnd:
    def test_failed_save_is_a_message_and_a_nonzero_exit_not_a_traceback(self) -> None:
        from studyloop.cli import cli as cli_main

        with (
            patch("studyloop.session_state.read_session_state", return_value=dict(_STATE)),
            patch("studyloop.session.cleanup.end_session_common", side_effect=_ERR),
        ):
            result = CliRunner().invoke(cli_main, ["study", "--end"])

        assert result.exit_code != 0
        leaked = result.exception is not None and not isinstance(result.exception, SystemExit)
        assert not leaked, f"the CLI leaked the exception: {result.exception!r}\n{result.output}"
        assert "could not be saved" in result.output
        assert "still running" in result.output
        assert "Traceback" not in result.output


class TestMcpEnd:
    def test_failed_save_is_a_tool_error_naming_the_retry(self) -> None:
        pytest.importorskip("mcp")
        from mcp.server.fastmcp.exceptions import ToolError

        from studyloop.mcp.server import mcp

        tool = mcp._tool_manager._tools["end_session"].fn
        with (
            patch("studyloop.web.routes.session.read_session_state", return_value=dict(_STATE)),
            patch("studyloop.session.cleanup.end_session_common", side_effect=_ERR),
            pytest.raises(ToolError) as excinfo,
        ):
            tool()

        message = str(excinfo.value)
        assert "could not be saved" in message
        assert "still running" in message
        assert "end it again" in message or "ending it again" in message
