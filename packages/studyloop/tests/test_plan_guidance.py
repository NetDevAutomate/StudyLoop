"""``PlanApplication.get_active_guidance`` — the plan-static read the ``now``
engine consumes (design §1, §3; decision D-5).

One ``ActivePlanGuidance`` per *active* plan, in a deterministic order, with
everything the ranker needs precomputed: the next unchecked milestone, the
normalised match keys (topics plus every milestone concept), the target-date
urgency bucket, the energy floor, and — for a plan whose every milestone is
ticked — a completion action instead of a study candidate. Malformed documents
become warnings, never exceptions: the ranker must always get an answer.

Several plans may be active at once (public doc, council review 1), so the
view is a collection and never an arbitrary singleton.

Phase 3 (#10) wires this into ``decision.py``; nothing consumes it yet.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, date, datetime, timedelta

import pytest

from studyloop.planning import store
from studyloop.planning.application import PlanApplication
from studyloop.planning.models import Milestone, Mission, StudyPlan
from studyloop.planning.views import (
    ActiveGuidance,  # pyright: ignore[reportAttributeAccessIssue]  # RED: lands in T2.2
    ActivePlanGuidance,  # pyright: ignore[reportAttributeAccessIssue]  # RED: lands in T2.2
    MilestoneView,
    PlanSummary,
    normalise_match_key,  # pyright: ignore[reportAttributeAccessIssue]  # RED: lands in T2.2
)

TODAY = date(2026, 9, 16)


@pytest.fixture(autouse=True)
def isolated_plans_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))
    return tmp_path / "study-plans"


@pytest.fixture(autouse=True)
def isolated_checkpoint_db(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDYLOOP_DB", str(tmp_path / "sessions.db"))


@pytest.fixture
def app() -> PlanApplication:
    return PlanApplication()


def _active(
    plan_id: str,
    *,
    topics: list[str] | None = None,
    milestones: list[Milestone] | None = None,
    target_date: str = "",
    energy_floor: int = 3,
    status: str = "active",
) -> StudyPlan:
    plan = StudyPlan(
        plan_id=plan_id,
        title=plan_id.replace("-", " ").title(),
        status=status,
        topics=topics if topics is not None else ["sql"],
        energy_floor=energy_floor,
        target_date=target_date,
        mission=Mission(why="Because", success=["Do a thing"]),
        milestones=(
            milestones
            if milestones is not None
            else [Milestone(title="Step one", concepts=["window function"])]
        ),
    )
    store.create_plan(plan)
    return plan


def _guidance(app: PlanApplication, *, today: date | None = TODAY) -> ActiveGuidance:
    return app.get_active_guidance(today=today)  # pyright: ignore[reportAttributeAccessIssue]  # RED: T2.2


# ---------------------------------------------------------------------------


def test_active_guidance_one_per_active_plan_with_match_keys_and_urgency(
    app: PlanApplication,
) -> None:
    _active(
        "sql-windows",
        topics=["SQL", "Data-Engineering"],
        milestones=[
            Milestone(title="OVER clause", done=True, concepts=["Window-Function"]),
            Milestone(title="Ranking", concepts=["RANK()", "dense rank"]),
            Milestone(title="Frames", concepts=["window frame"]),
        ],
        target_date=(TODAY + timedelta(days=30)).isoformat(),
        energy_floor=6,
    )
    _active("glue-etl", topics=["glue"], target_date=(TODAY - timedelta(days=2)).isoformat())
    _active("a-draft", status="draft")
    _active("paused-one", status="paused")

    guidance = _guidance(app)

    assert isinstance(guidance, ActiveGuidance)
    assert guidance.warnings == ()
    assert [g.plan.plan_id for g in guidance.plans] == ["glue-etl", "sql-windows"]
    assert all(isinstance(g, ActivePlanGuidance) for g in guidance.plans)

    sql = guidance.plans[1]
    assert isinstance(sql.plan, PlanSummary)
    assert sql.plan.status == "active"
    assert isinstance(sql.next_milestone, MilestoneView)
    assert (sql.next_milestone.index, sql.next_milestone.title) == (1, "Ranking")
    assert sql.next_milestone.concepts == ("RANK()", "dense rank")
    # Topics and every milestone's concepts — done or not — casefolded with
    # punctuation stripped, so a candidate topic "data-engineering" or a due
    # concept "Window Function" matches by equality, never by substring.
    assert sql.match_keys == frozenset(
        {"sql", "data engineering", "window function", "rank", "dense rank", "window frame"}
    )
    assert isinstance(sql.match_keys, frozenset)
    assert sql.target_urgency == "later"
    assert sql.energy_floor == 6
    assert sql.completion_action is None
    assert sql.warnings == ()

    glue = guidance.plans[0]
    assert glue.target_urgency == "overdue"
    assert glue.energy_floor == 3
    assert glue.match_keys == frozenset({"glue", "window function"})
    assert glue.next_milestone is not None and glue.next_milestone.index == 0


def test_active_guidance_orders_by_plan_id_and_skips_non_active(app: PlanApplication) -> None:
    # Store order is active-first then ``updated``; guidance order is the plan
    # id, so the ranker's output is stable across edits.
    _active("zeta", target_date="")
    _active("alpha")
    _active("mid")
    for status in ("draft", "paused", "complete", "abandoned"):
        _active(f"{status}-plan", status=status)

    guidance = _guidance(app)

    assert [g.plan.plan_id for g in guidance.plans] == ["alpha", "mid", "zeta"]
    assert guidance == _guidance(app), "repeat calls return equal views"
    assert all(g.plan.status == "active" for g in guidance.plans)


def test_active_guidance_empty_when_nothing_is_active(app: PlanApplication) -> None:
    _active("draft-only", status="draft")
    guidance = _guidance(app)
    assert guidance.plans == ()
    assert guidance.warnings == ()
    assert guidance.to_json_dict() == {"plans": [], "warnings": []}


def test_active_guidance_completion_action_when_all_done(app: PlanApplication) -> None:
    _active(
        "finished",
        milestones=[
            Milestone(title="One", done=True, concepts=["a"]),
            Milestone(title="Two", done=True, concepts=["b"]),
        ],
    )
    _active("in-flight")

    guidance = _guidance(app)
    finished, in_flight = guidance.plans

    assert finished.plan.plan_id == "finished"
    assert finished.next_milestone is None
    assert finished.completion_action is not None
    assert "Finished" in finished.completion_action
    assert finished.match_keys == frozenset({"sql", "a", "b"})
    assert in_flight.completion_action is None
    assert in_flight.next_milestone is not None


@pytest.mark.parametrize(
    ("target_offset_days", "expected"),
    [
        (-30, "overdue"),
        (-1, "overdue"),
        (0, "soon"),
        (1, "soon"),
        (7, "soon"),
        (8, "later"),
        (90, "later"),
        (None, "undated"),
    ],
    ids=["month-ago", "yesterday", "today", "tomorrow", "week", "eight-days", "quarter", "unset"],
)
def test_active_guidance_target_urgency_buckets(
    app: PlanApplication, target_offset_days: int | None, expected: str
) -> None:
    target = "" if target_offset_days is None else (TODAY + timedelta(days=target_offset_days))
    _active("dated", target_date=target.isoformat() if isinstance(target, date) else "")

    (only,) = _guidance(app).plans

    assert only.target_urgency == expected
    assert only.warnings == ()


def test_active_guidance_defaults_to_the_real_today(app: PlanApplication) -> None:
    real_today = datetime.now(UTC).date()
    _active("dated", target_date=(real_today + timedelta(days=60)).isoformat())
    (only,) = _guidance(app, today=None).plans
    assert only.target_urgency == "later"


def test_active_guidance_warns_on_malformed_documents(
    app: PlanApplication, isolated_plans_dir
) -> None:
    """A hand-edited active plan with no milestones, an unparseable target
    date, and an unparseable document beside it: the ranker still gets a
    view, and every defect is named rather than raised or silently dropped."""
    store.plans_dir()
    (isolated_plans_dir / "no-milestones.md").write_text(
        "---\nid: no-milestones\ntitle: No Milestones\nstatus: active\n"
        "target_date: someday\n---\n\n# No Milestones\n\n## Mission\n\n### Why\n\nBecause.\n",
        encoding="utf-8",
    )
    (isolated_plans_dir / "broken.md").write_text(
        "---\nthis: [is not: valid: yaml\n---\n# Broken\n", encoding="utf-8"
    )
    _active("healthy")

    guidance = _guidance(app)

    assert [g.plan.plan_id for g in guidance.plans] == ["healthy", "no-milestones"]
    assert any("broken" in warning for warning in guidance.warnings)

    degraded = guidance.plans[1]
    assert degraded.next_milestone is None
    assert degraded.completion_action is None, "nothing to complete when nothing was planned"
    assert degraded.target_urgency == "undated"
    assert any("milestone" in warning for warning in degraded.warnings)
    assert any("someday" in warning for warning in degraded.warnings)
    assert guidance.plans[0].warnings == ()


def test_active_guidance_views_are_frozen_and_json_fresh(app: PlanApplication) -> None:
    _active("demo", target_date=(TODAY + timedelta(days=3)).isoformat())
    guidance = _guidance(app)
    (only,) = guidance.plans

    for view in (guidance, only):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(view, "warnings", ("mutated",))  # noqa: B010
    assert isinstance(guidance.plans, tuple)
    assert isinstance(only.warnings, tuple)

    first = guidance.to_json_dict()
    second = guidance.to_json_dict()
    assert first == second
    assert first is not second
    assert first["plans"][0]["plan"]["plan_id"] == "demo"
    assert first["plans"][0]["next_milestone"]["index"] == 0
    assert sorted(first["plans"][0]["match_keys"]) == ["sql", "window function"]
    assert first["plans"][0]["target_urgency"] == "soon"
    assert first["plans"][0]["energy_floor"] == 3
    assert first["plans"][0]["completion_action"] is None
    first["plans"][0]["match_keys"].append("leaked")
    first["plans"][0]["plan"]["topics"].append("leaked")
    assert guidance.to_json_dict() == second
    json.dumps(first)


@pytest.mark.parametrize(
    ("raw", "key"),
    [
        ("SQL", "sql"),
        ("Data-Engineering", "data engineering"),
        ("Window-Function", "window function"),
        ("RANK()", "rank"),
        ("  dbt  ", "dbt"),
        ("Straße", "strasse"),
        ("a.b_c", "a b c"),
        ("!!!", ""),
    ],
)
def test_normalise_match_key(raw: str, key: str) -> None:
    """Casefold, replace punctuation with spaces, collapse whitespace. The
    ranker applies the same function to its candidates, so matching is
    equality on this key and never a substring test (design §3 step 4)."""
    assert normalise_match_key(raw) == key
