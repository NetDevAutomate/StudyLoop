"""The learning-record writer (R-93): store function, CLI, and MCP tool.

Before this writer existed, ``LearningRecord`` was constructed in exactly one
place — the Markdown parser — so a record existed only if the learner typed it
into the plan document by hand, and an xTiles wind-down's learning record lived
only in xTiles, inverting ADR-0010. These tests pin the ruled design: parse →
append → ``save_plan`` (never raw Markdown), ``max(existing) + 1`` numbering,
and byte-level idempotence on a same-title-same-body re-run.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from studyloop.cli import cli
from studyloop.planning import (
    LearningRecord,
    Mission,
    StudyPlan,
    create_plan,
    load_plan,
    record_learning,
    store,
)
from studyloop.planning.store import PlanNotFoundError, plan_path


@pytest.fixture(autouse=True)
def isolated_plans_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))
    return tmp_path / "study-plans"


def _seed(plan_id: str = "decorators", records: list[LearningRecord] | None = None) -> StudyPlan:
    plan = StudyPlan(
        plan_id=plan_id,
        title="Python Decorators",
        status="active",
        topics=["python"],
        mission=Mission(why="They keep appearing in code review."),
        learning_records=records or [],
    )
    create_plan(plan)
    return plan


class TestRecordLearning:
    def test_first_record_is_lr_0001_and_round_trips(self) -> None:
        _seed()

        record, created = record_learning(
            "decorators", "Closures carry state", body="The wrapper closes over its cell."
        )

        assert created is True
        assert record.number == 1
        # Through the real renderer, in the renderer's format — never our own.
        text = plan_path("decorators").read_text(encoding="utf-8")
        assert "### LR-0001 — Closures carry state" in text
        reloaded = load_plan("decorators")
        assert [r.title for r in reloaded.learning_records] == ["Closures carry state"]
        assert reloaded.learning_records[0].body == "The wrapper closes over its cell."

    def test_numbering_is_max_plus_one_not_count(self) -> None:
        """A superseded LR keeps its number; gaps must not be reused."""
        _seed(records=[LearningRecord(number=3, title="Old insight", body="kept")])

        record, _ = record_learning("decorators", "New insight")

        assert record.number == 4

    def test_rerun_with_same_title_and_body_is_a_byte_level_noop(self) -> None:
        _seed()
        record_learning("decorators", "Once", body="only")
        before = plan_path("decorators").read_bytes()

        record, created = record_learning("decorators", "Once", body="only")

        assert created is False
        assert record.number == 1
        assert plan_path("decorators").read_bytes() == before

    def test_same_title_different_body_is_a_new_record(self) -> None:
        _seed()
        record_learning("decorators", "Insight", body="first take")

        record, created = record_learning("decorators", "Insight", body="second take")

        assert created is True
        assert record.number == 2

    def test_non_active_status_renders_and_round_trips(self) -> None:
        _seed()

        record_learning("decorators", "Was wrong", body="see LR-0002", status="superseded")

        text = plan_path("decorators").read_text(encoding="utf-8")
        assert "Status: superseded" in text
        assert load_plan("decorators").learning_records[0].status == "superseded"

    def test_empty_title_is_refused(self) -> None:
        _seed()
        with pytest.raises(ValueError, match="title"):
            record_learning("decorators", "   ")

    def test_missing_plan_raises(self) -> None:
        with pytest.raises(PlanNotFoundError):
            record_learning("nope", "Anything")

    def test_heading_lines_in_the_body_are_refused_not_mangled(self) -> None:
        """H1-H3 in a body would be re-parsed as sections/records on reload
        (_subsection_items splits on '### ' and ignores code fences), silently
        corrupting the document. H4+ is safe prose and stays allowed."""
        _seed()

        with pytest.raises(ValueError, match="###"):
            record_learning("decorators", "Trap", body="fine\n### LR-0999 — fake\nmore")

        _record, created = record_learning("decorators", "Fine", body="#### a sub-note\nprose")
        assert created is True
        assert load_plan("decorators").learning_records[0].body.startswith("#### a sub-note")


class TestPlanRecordCli:
    def _run(self, *args: str):
        return CliRunner().invoke(cli, ["plan", "record", *args])

    def test_json_shape(self) -> None:
        _seed()

        result = self._run("decorators", "--title", "CLI insight", "--body", "prose", "--json")

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload == {
            "plan_id": "decorators",
            "number": 1,
            "title": "CLI insight",
            "status": "active",
            "created": True,
        }

    def test_rerun_reports_created_false(self) -> None:
        _seed()
        self._run("decorators", "--title", "Same", "--body", "same", "--json")

        result = self._run("decorators", "--title", "Same", "--body", "same", "--json")

        assert result.exit_code == 0
        assert json.loads(result.output)["created"] is False

    def test_body_file(self, tmp_path) -> None:
        _seed()
        body = tmp_path / "body.md"
        body.write_text("From a file.", encoding="utf-8")

        result = self._run("decorators", "--title", "Filed", "--body-file", str(body), "--json")

        assert result.exit_code == 0
        assert load_plan("decorators").learning_records[0].body == "From a file."

    def test_body_and_body_file_together_fail(self, tmp_path) -> None:
        _seed()
        body = tmp_path / "body.md"
        body.write_text("x", encoding="utf-8")

        result = self._run(
            "decorators", "--title", "T", "--body", "inline", "--body-file", str(body)
        )

        assert result.exit_code == 1
        assert "not both" in result.output

    def test_missing_plan_names_the_fix(self) -> None:
        result = self._run("ghost", "--title", "T")

        assert result.exit_code == 1
        assert "studyloop plan list" in result.output


class TestMcpTool:
    @pytest.fixture(autouse=True)
    def _requires_mcp(self):
        pytest.importorskip("mcp")

    def _tool(self):
        from studyloop.mcp.server import mcp

        return mcp._tool_manager._tools["record_plan_learning"].fn

    def test_records_and_reports(self) -> None:
        _seed()

        payload = self._tool()("decorators", "MCP insight", body="prose")

        assert payload["created"] is True
        assert payload["number"] == 1
        assert load_plan("decorators").learning_records[0].title == "MCP insight"

    def test_retry_is_safe(self) -> None:
        _seed()
        self._tool()("decorators", "Again", body="same")

        payload = self._tool()("decorators", "Again", body="same")

        assert payload["created"] is False

    def test_missing_plan_is_a_tool_error(self) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        with pytest.raises(ToolError):
            self._tool()("ghost", "Anything")
