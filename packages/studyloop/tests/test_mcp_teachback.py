"""RED for the ``record_teachback`` MCP tool (learning tier, item 1, stage S1-RED).

The learning tier is unfed because the mentor has no MCP writer for a teach-back
score: the only writer is the CLI (``studyloop teachback``), which an agent
session never calls. Plan §5 (``docs/architecture/learning-tier/plan-2026-09-19.md``)
and the S1-0 receipt pin the contract this file tests:

* the tool exists beside the other ``W_auto`` writers;
* it validates exactly as ``cli/_teachback.py`` does -- five scores, integers,
  each 1-4, ``review_type`` in ``TEACHBACK_TYPES`` -- and lands **no row** when
  validation fails;
* a valid call lands **one row** in ``teach_back_scores`` through the real
  migrated schema, whose CHECK constraints are what "honouring CHECK" means;
* the live study session id is reported in the reply and never taken from
  the caller; it is not stored as the row's ``session_id`` (finding N1: the
  ownership layer reserves that column for native harness sessions);
* a repeated call is two rows -- teach-backs are events, not state;
* a missing connection is a ``ToolError``, never a silent success.

Accesses the tool via the FastMCP registry, mirroring ``test_mcp_log_topic.py``.
The scratch database comes from ``STUDYLOOP_DB`` (read at call time), so the
schema is the one ``_connection._connect`` migrates, not a hand-rolled table.
"""

from __future__ import annotations

import inspect
import sqlite3
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("mcp")

from mcp.server.fastmcp.exceptions import ToolError

from studyloop.mcp.server import mcp

if TYPE_CHECKING:
    from pathlib import Path

W_AUTO = ("log_topic", "log_struggle", "record_teachback", "record_plan_learning")
VALID_SCORES = [3, 3, 4, 3, 2]


def _get_tool(name: str):
    tools = mcp._tool_manager._tools
    if name not in tools:
        raise KeyError(f"Tool {name!r} not found. Available: {sorted(tools)}")
    return tools[name].fn


def _rows(db: Path) -> list[tuple]:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT concept, topic, session_id, score_accuracy, score_own_words, "
            "score_structure, score_depth, score_transfer FROM teach_back_scores ORDER BY id"
        ).fetchall()
    except sqlite3.OperationalError as exc:  # table absent: nothing was ever written
        if "no such table" in str(exc):
            return []
        raise
    finally:
        conn.close()


@pytest.fixture()
def scratch_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A per-test sessions.db that the real connection resolver migrates."""
    db = tmp_path / "sessions.db"
    monkeypatch.setenv("STUDYLOOP_DB", str(db))
    return db


@pytest.fixture()
def session_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect the session-state files into tmp_path and return the writer."""
    from studyloop import session_state as ss

    monkeypatch.setattr(ss, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(ss, "STATE_FILE", tmp_path / "session-state.json")
    monkeypatch.setattr(ss, "TOPICS_FILE", tmp_path / "session-topics.md")
    monkeypatch.setattr(ss, "PARKING_FILE", tmp_path / "session-parking.md")
    return ss.write_session_state


class TestTheToolExists:
    def test_record_teachback_is_registered_beside_the_other_writers(self) -> None:
        registered = set(mcp._tool_manager._tools)
        missing = [name for name in W_AUTO if name not in registered]
        assert missing == [], f"W_auto writers absent from the MCP registry: {missing}"

    def test_the_caller_cannot_supply_a_session_id(self) -> None:
        params = inspect.signature(_get_tool("record_teachback")).parameters
        assert "session_id" not in params, "session_id is bound from session state, not the caller"


class TestValidationMirrorsTheCli:
    """Every rejection is a ToolError and leaves the table untouched."""

    @pytest.mark.parametrize(
        ("scores", "fragment"),
        [
            ([3, 3, 4, 3], "five"),
            ([3, 3, 4, 3, 2, 1], "five"),
            ([0, 3, 4, 3, 2], "1 and 4"),
            ([3, 3, 4, 3, 5], "1 and 4"),
        ],
    )
    def test_score_shape_and_range(self, scratch_db: Path, scores: list, fragment: str) -> None:
        tool = _get_tool("record_teachback")
        with pytest.raises(ToolError, match=fragment):
            tool(concept="window frame", topic="sql", scores=scores, review_type="micro")
        assert _rows(scratch_db) == []

    def test_non_integer_scores_are_rejected(self, scratch_db: Path) -> None:
        tool = _get_tool("record_teachback")
        with pytest.raises(ToolError, match="integer"):
            tool(
                concept="window frame", topic="sql", scores=["3", "x", 4, 3, 2], review_type="micro"
            )
        assert _rows(scratch_db) == []

    def test_unknown_review_type_is_rejected_naming_the_allowed_set(self, scratch_db: Path) -> None:
        from studyloop.cli._teachback import TEACHBACK_TYPES

        tool = _get_tool("record_teachback")
        with pytest.raises(ToolError) as excinfo:
            tool(concept="window frame", topic="sql", scores=VALID_SCORES, review_type="vibes")
        for allowed in TEACHBACK_TYPES:
            assert allowed in str(excinfo.value)
        assert _rows(scratch_db) == []


class TestARowLands:
    def test_a_valid_call_lands_exactly_one_row_through_the_real_schema(
        self, scratch_db: Path, session_state
    ) -> None:
        session_state({"study_session_id": "study-42"})
        tool = _get_tool("record_teachback")

        result = tool(
            concept="window frame",
            topic="sql",
            scores=VALID_SCORES,
            review_type="structured",
            angle="apply_network_analogy",
            notes="explained ROWS vs RANGE unprompted",
        )

        assert result["recorded"] is True
        assert result["total"] == sum(VALID_SCORES)
        rows = _rows(scratch_db)
        assert rows == [("window frame", "sql", None, 3, 3, 4, 3, 2)]
        # The schema is the migrated one: its CHECK constraints are present.
        conn = sqlite3.connect(scratch_db)
        try:
            ddl = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='teach_back_scores'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert "BETWEEN 1 AND 4" in ddl

    def test_the_study_session_is_reported_not_stored_as_the_rows_session_id(
        self, scratch_db: Path, session_state
    ) -> None:
        """Finding N1 (S1-GREEN, corrected from the RED as first written).

        The RED assumed the live study session id would land in the row's
        ``session_id``. The ownership layer forbids it: ``records.bind`` treats
        ``session_id`` as a *native* harness session (it must exist in
        ``sessions`` and be visible in scope) and links study sessions only for
        ``parked_topics`` and ``study_notes`` -- the write failed and the tool
        reported "not recorded". So the row is owned by scope, as the CLI's
        rows are, and the study session id travels in the tool's reply.
        """
        session_state({"study_session_id": "study-7"})
        result = _get_tool("record_teachback")(
            concept="decorators", topic="python", scores=VALID_SCORES, review_type="micro"
        )
        assert result["study_session_id"] == "study-7"
        assert [row[2] for row in _rows(scratch_db)] == [None]

    def test_no_live_session_reports_none_and_still_records(
        self, scratch_db: Path, session_state
    ) -> None:
        result = _get_tool("record_teachback")(
            concept="decorators", topic="python", scores=VALID_SCORES, review_type="micro"
        )
        assert result["study_session_id"] is None
        assert len(_rows(scratch_db)) == 1

    def test_a_repeated_call_is_two_rows_because_teachbacks_are_events(
        self, scratch_db: Path, session_state
    ) -> None:
        tool = _get_tool("record_teachback")
        for _ in range(2):
            tool(concept="decorators", topic="python", scores=VALID_SCORES, review_type="micro")
        assert len(_rows(scratch_db)) == 2


class TestFailureIsLoud:
    def test_no_connection_is_a_tool_error_not_a_silent_success(
        self, scratch_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import studyloop.history._connection as _conn

        monkeypatch.setattr(_conn, "_connect", lambda: None)
        with pytest.raises(ToolError, match="not recorded"):
            _get_tool("record_teachback")(
                concept="decorators", topic="python", scores=VALID_SCORES, review_type="micro"
            )
        assert _rows(scratch_db) == []
