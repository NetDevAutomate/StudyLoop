"""Crash-injection and deterministic journal recovery contracts."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from studyloop.planning.models import Goal, Milestone, Mission, StudyPlan
from studyloop.planning.repository import (
    MutationIntent,
    PlanningPaths,
    PlanningRef,
    PlanningRepository,
    RecoveryError,
)

if TYPE_CHECKING:
    from pathlib import Path

CRASH_POINTS = (
    "after_journal_intent",
    "after_temp_fsync",
    "after_replace",
    "after_directory_fsync",
    "after_commit_event",
)


class InjectedCrashError(RuntimeError):
    """Test-only abrupt stop after one durable commit step."""


def _paths(root: Path) -> PlanningPaths:
    return PlanningPaths.in_root(root)


def _intent() -> MutationIntent:
    plan = StudyPlan(
        plan_id="crash-plan",
        title="Crash plan",
        status="draft",
        created="2026-08-23T12:00:00+00:00",
        updated="2026-08-23T12:00:00+00:00",
        mission=Mission(why="Prove recovery.", success=["Classify every state"]),
        goals=[Goal("goal-crash", "Recover", "Needed", "Aligned")],
        milestones=[
            Milestone(
                "Inject crashes",
                milestone_id="milestone-crash",
                goal_id="goal-crash",
            )
        ],
    )
    return MutationIntent(
        intent_id="intent-crash",
        caller="pytest-crash",
        idempotency_key="key-crash",
        operation="create",
        plan=plan,
    )


def _inject_at(selected: str):
    def inject(point: str) -> None:
        if point == selected:
            raise InjectedCrashError(point)

    return inject


@pytest.mark.parametrize("crash_point", CRASH_POINTS)
def test_restart_classifies_each_crash_point_and_retry_is_idempotent(
    tmp_path: Path, crash_point: str
) -> None:
    paths = _paths(tmp_path)
    crashing = PlanningRepository(
        paths,
        crash_injector=_inject_at(crash_point),
        index_refresher=None,
    )

    with pytest.raises(InjectedCrashError, match=crash_point):
        crashing.commit(_intent())

    restarted = PlanningRepository(paths, index_refresher=None)
    report = restarted.recover()
    before_points = {"after_journal_intent", "after_temp_fsync"}
    after_points = {"after_replace", "after_directory_fsync"}
    if crash_point in before_points:
        assert [item.classification for item in report.recovered] == ["before"]
        assert not (paths.plans / "crash-plan.md").exists()
        assert restarted.commit(_intent()).status == "committed"
    elif crash_point in after_points:
        assert [item.classification for item in report.recovered] == ["after"]
        assert restarted.inspect(PlanningRef("crash-plan")).plan.title == "Crash plan"
        assert restarted.commit(_intent()).status == "replayed"
    else:
        assert report.recovered == ()
        assert restarted.inspect(PlanningRef("crash-plan")).plan.title == "Crash plan"
        assert restarted.commit(_intent()).status == "replayed"

    assert list(paths.plans.glob("*.tmp")) == []


def test_recovery_refuses_an_unclassifiable_third_state(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    crashing = PlanningRepository(
        paths,
        crash_injector=_inject_at("after_journal_intent"),
        index_refresher=None,
    )
    with pytest.raises(InjectedCrashError):
        crashing.commit(_intent())
    (paths.plans / "crash-plan.md").write_text("# Unjournalled third state\n", encoding="utf-8")

    restarted = PlanningRepository(paths, index_refresher=None)
    with pytest.raises(RecoveryError, match="neither its before nor after state"):
        restarted.recover()

    events = [json.loads(line) for line in paths.journal.read_text().splitlines()]
    assert [event["event"] for event in events] == ["intent"]
