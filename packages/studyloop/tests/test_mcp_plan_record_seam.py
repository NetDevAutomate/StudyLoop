"""``record_plan_learning`` goes through the seam (T2.2, the one ``tools.py`` edit).

``tests/test_plan_record.py::TestMcpTool`` pins the tool's contract from
before the seam existed — created/number/retry/missing plan. This file pins
what the migration adds: the write is one ``RevisePlan(learning_record=…)``
applied through ``PlanApplication`` (so the resulting-document gate and the
store's single learning-record rule both apply), and every seam refusal is a
``ToolError`` — a not-ready refusal naming its blockers, so an agent can tell
the learner what to fix.
"""

from __future__ import annotations

import pytest

pytest.importorskip("mcp")

from mcp.server.fastmcp.exceptions import ToolError

from studyloop.planning import (
    Milestone,
    Mission,
    PlanApplication,
    PlanNotReady,
    ReadinessView,
    RevisePlan,
    StudyPlan,
    store,
)


@pytest.fixture(autouse=True)
def isolated_plans_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))


@pytest.fixture(autouse=True)
def isolated_checkpoint_db(tmp_path, monkeypatch):
    """``store.create_plan`` refreshes the derived index in the sessions
    database; keep that off any developer database (council review 2, F10)."""
    monkeypatch.setenv("STUDYLOOP_DB", str(tmp_path / "sessions.db"))


def _tool():
    from studyloop.mcp.server import mcp

    return mcp._tool_manager._tools["record_plan_learning"].fn


def _seed(plan_id: str = "decorators") -> StudyPlan:
    plan = StudyPlan(
        plan_id=plan_id,
        title="Python Decorators",
        status="active",
        topics=["python"],
        mission=Mission(why="They keep appearing in code review.", success=["Explain them."]),
        milestones=[Milestone(title="Trace a decorated call", concepts=["wrapper"])],
    )
    store.create_plan(plan)
    return plan


def test_tool_applies_one_revise_plan_with_the_record(monkeypatch) -> None:
    _seed()
    seen: list[object] = []
    real_apply = PlanApplication.apply

    def spying_apply(self, intent):
        seen.append(intent)
        return real_apply(self, intent)

    monkeypatch.setattr(PlanApplication, "apply", spying_apply)

    payload = _tool()("decorators", "MCP insight", body="prose", status="active")

    (intent,) = seen
    assert isinstance(intent, RevisePlan)
    assert intent.plan_id == "decorators"
    assert intent.learning_record is not None
    assert (intent.learning_record.title, intent.learning_record.body) == ("MCP insight", "prose")
    assert payload == {
        "plan_id": "decorators",
        "number": 1,
        "title": "MCP insight",
        "status": "active",
        "created": True,
    }
    assert store.load_plan("decorators").learning_records[0].body == "prose"


def test_retry_reports_created_false_through_the_seam(monkeypatch) -> None:
    _seed()
    _tool()("decorators", "Again", body="same")
    seen: list[object] = []
    real_apply = PlanApplication.apply

    def spying_apply(self, intent):
        seen.append(intent)
        return real_apply(self, intent)

    monkeypatch.setattr(PlanApplication, "apply", spying_apply)

    payload = _tool()("decorators", "Again", body="same")

    assert len(seen) == 1, "a retry is still one seam call, not a store call"
    assert payload["created"] is False
    assert payload["number"] == 1
    assert len(store.load_plan("decorators").learning_records) == 1


def test_created_is_the_mutations_outcome_not_a_prior_read(monkeypatch) -> None:
    """Council review 2, GPT Astra F4: the tool inspected, then applied, and
    reported ``created`` from the first read. A writer landing the same record
    between the two made a no-op report ``created: true``. With the writer
    modelled at the seam boundary the tool must say false — from the
    mutation's own outcome — and make no preliminary read."""
    _seed()
    real_apply = PlanApplication.apply
    inspections: list[str] = []
    real_inspect = PlanApplication.inspect

    def racing_apply(self, intent):
        store.record_learning("decorators", "Again", body="same")  # the other writer
        return real_apply(self, intent)

    def spying_inspect(self, plan_id, **kwargs):
        inspections.append(plan_id)
        return real_inspect(self, plan_id, **kwargs)

    monkeypatch.setattr(PlanApplication, "apply", racing_apply)
    monkeypatch.setattr(PlanApplication, "inspect", spying_inspect)

    payload = _tool()("decorators", "Again", body="same")

    assert payload["created"] is False, "the record existed when the mutation ran"
    assert payload["number"] == 1
    assert inspections == [], "one seam mutation decides persistence and `created`"
    assert len(store.load_plan("decorators").learning_records) == 1


def test_not_ready_refusal_is_a_tool_error_naming_the_blockers(monkeypatch) -> None:
    readiness = ReadinessView.from_plan(StudyPlan(plan_id="decorators", title="Decorators"))
    _seed()

    def refuse(self, intent):
        raise PlanNotReady(readiness)

    monkeypatch.setattr(PlanApplication, "apply", refuse)

    with pytest.raises(ToolError) as caught:
        _tool()("decorators", "Insight")

    message = str(caught.value)
    assert "not ready" in message
    for blocker in readiness.blockers:
        assert blocker in message


@pytest.mark.parametrize(
    ("title", "body", "fragment"),
    [
        ("   ", "", "title"),
        ("Trap", "fine\n### LR-0999 — fake", "###"),
    ],
    ids=["empty-title", "heading-in-body"],
)
def test_store_rule_refusals_are_tool_errors(title: str, body: str, fragment: str) -> None:
    _seed()
    with pytest.raises(ToolError, match=fragment):
        _tool()("decorators", title, body=body)
    assert store.load_plan("decorators").learning_records == []


def test_missing_plan_and_malformed_id_are_tool_errors() -> None:
    with pytest.raises(ToolError, match="no study plan"):
        _tool()("ghost", "Anything")
    with pytest.raises(ToolError, match="invalid plan id"):
        _tool()("../escape", "Anything")
