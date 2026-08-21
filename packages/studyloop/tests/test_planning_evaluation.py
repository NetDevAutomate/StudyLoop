"""Evaluation contract: verdicts, recommendations, and graceful degradation."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from studyloop.planning import evaluation as evaluation_module
from studyloop.planning.evaluation import evaluate_plan
from studyloop.planning.models import Milestone, Mission, StudyPlan


@pytest.fixture(autouse=True)
def isolated_plans_dir(tmp_path, monkeypatch):
    from studyloop.planning import store

    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    """Neutralise DB reads so verdicts are driven purely by plan shape.

    Evaluation is otherwise sensitive to whatever the developer's real
    sessions.db happens to contain, which would make these assertions flaky.
    """
    monkeypatch.setattr(
        evaluation_module,
        "_gather_concept_evidence",
        lambda plan, warnings: ([], [], []),
    )
    monkeypatch.setattr(evaluation_module, "_detect_drift", lambda plan, warnings: [])
    monkeypatch.setattr(evaluation_module, "_days_since", lambda value: None)


def _plan(**overrides) -> StudyPlan:
    defaults = {
        "plan_id": "demo",
        "title": "Demo Plan",
        "status": "active",
        "topics": ["python"],
        "mission": Mission(why="Because", success=["Do a thing"]),
        "milestones": [
            Milestone(title="One", concepts=["a"]),
            Milestone(title="Two", concepts=["b"]),
        ],
    }
    defaults.update(overrides)
    return StudyPlan(**defaults)


@pytest.mark.parametrize("phase", ["start", "mid", "end"])
def test_every_phase_produces_a_usable_evaluation(phase: str) -> None:
    result = evaluate_plan(_plan(), phase)
    assert result.phase == phase
    assert result.verdict in {"on-track", "at-risk", "stalled", "complete"}
    assert result.headline
    assert 1 <= len(result.recommendations) <= 4


def test_invalid_phase_is_rejected() -> None:
    with pytest.raises(ValueError, match="phase must be one of"):
        evaluate_plan(_plan(), "halfway")


def test_all_milestones_done_is_complete() -> None:
    plan = _plan(
        milestones=[
            Milestone(title="One", done=True, concepts=["a"]),
            Milestone(title="Two", done=True, concepts=["b"]),
        ]
    )
    assert evaluate_plan(plan, "end").verdict == "complete"


def test_plan_without_milestones_is_at_risk() -> None:
    result = evaluate_plan(_plan(milestones=[]), "start")
    assert result.verdict == "at-risk"
    assert "milestone" in result.headline.lower()


def _utc_today() -> date:
    """Today as the production code sees it.

    ``StudyPlan.days_until_target`` measures against
    ``datetime.now(timezone.utc).date()``. Building fixtures from
    ``date.today()`` (local) instead makes these tests fail for the hour each
    night when the local date is already ahead of UTC — which is exactly how
    this was first caught, at 00:03 BST.
    """
    return datetime.now(UTC).date()


def test_past_target_date_is_at_risk() -> None:
    yesterday = (_utc_today() - timedelta(days=3)).isoformat()
    result = evaluate_plan(_plan(target_date=yesterday), "start")
    assert result.verdict == "at-risk"
    assert "passed" in result.headline.lower()


def test_too_little_time_for_remaining_milestones_is_at_risk() -> None:
    """2 milestones left, 1 day to target — the plan cannot land."""
    tomorrow = (_utc_today() + timedelta(days=1)).isoformat()
    result = evaluate_plan(_plan(target_date=tomorrow), "start")
    assert result.verdict == "at-risk"


def test_comfortable_target_date_stays_on_track() -> None:
    far = (_utc_today() + timedelta(days=120)).isoformat()
    assert evaluate_plan(_plan(target_date=far), "start").verdict == "on-track"


def test_milestone_done_without_evidence_is_flagged() -> None:
    plan = _plan(
        milestones=[
            Milestone(title="Claimed", done=True, concepts=["never-studied"]),
            Milestone(title="Next", concepts=["b"]),
        ]
    )
    result = evaluate_plan(plan, "start")
    assert result.unverified_milestones == ["Claimed"]
    assert result.verdict == "at-risk"


def test_next_milestone_is_the_first_unchecked_one() -> None:
    plan = _plan(
        milestones=[
            Milestone(title="Done", done=True),
            Milestone(title="Current", concepts=["x"]),
            Milestone(title="Later"),
        ]
    )
    result = evaluate_plan(plan, "start")
    assert result.next_milestone == "Current"
    assert result.next_concepts == ["x"]


def test_as_markdown_carries_the_verdict_and_phase() -> None:
    result = evaluate_plan(_plan(), "mid")
    rendered = result.as_markdown()
    assert result.verdict in rendered
    assert "mid" in rendered
    assert result.plan_title in rendered


def test_to_dict_is_json_serialisable() -> None:
    payload = evaluate_plan(_plan(), "end").to_dict()
    assert json.loads(json.dumps(payload, default=str))["plan_id"] == "demo"


def test_to_checkpoint_matches_the_evaluation() -> None:
    result = evaluate_plan(_plan(), "end", study_id="sess-1")
    checkpoint = result.to_checkpoint()
    assert checkpoint.phase == "end"
    assert checkpoint.verdict == result.verdict
    assert checkpoint.study_id == "sess-1"


def test_recommendations_are_capped_for_working_memory() -> None:
    plan = _plan(milestones=[], mission=Mission())
    for phase in ("start", "mid", "end"):
        assert len(evaluate_plan(plan, phase).recommendations) <= 4


def test_missing_database_degrades_to_warnings_not_an_exception(monkeypatch) -> None:
    """A fresh install has no study tables; evaluation must still answer."""

    def _boom(plan, warnings):
        warnings.append("study_progress unavailable — evaluation is partial")
        return [], [], []

    monkeypatch.setattr(evaluation_module, "_gather_concept_evidence", _boom)
    result = evaluate_plan(_plan(), "start")
    assert result.warnings
    assert result.verdict in {"on-track", "at-risk", "stalled", "complete"}


def test_reader_exception_is_caught_by_the_safe_wrapper(monkeypatch) -> None:
    """_safe converts a raising reader into a warning."""
    warnings: list[str] = []

    def _raise():
        msg = "table missing"
        raise RuntimeError(msg)

    got = evaluation_module._safe("study_progress", _raise, [], warnings)
    assert got == []
    assert warnings and "study_progress" in warnings[0]
