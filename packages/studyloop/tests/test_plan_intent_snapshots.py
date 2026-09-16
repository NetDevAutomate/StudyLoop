"""``CreatePlan.answers`` is a snapshot taken at construction (council review 3, F5).

Review 2 recorded the hazard and deferred it to #11: ``CreatePlan.answers`` was
a *live* mapping on a frozen intent, so a caller (or anything that queued or
replayed the intent) could change what the seam judged after the intent was
built. #11 shipped ``create_study_plan`` without the freeze because
``intents.py`` was outside its file set. This module pins the closure: the
intent deep-copies the answers it is given and exposes them read-only, so the
document the seam writes is the one the intent described when it was made.

The values keep their JSON types (lists stay lists, dicts stay dicts) because
``authoring.draft_plan`` reads them by type; immutability is at the intent's
boundary — the caller cannot reach the copy — not a recursive type change.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from studyloop.planning import CreatePlan, PlanApplication, store


@pytest.fixture(autouse=True)
def isolated_world(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))
    monkeypatch.setenv("STUDYLOOP_DB", str(tmp_path / "sessions.db"))


def _answers() -> dict[str, object]:
    return {
        "why": "Ship analytics queries without help",
        "success": ["Write a RANK() query unaided"],
        "topics": ["sql"],
        "milestones": [{"title": "OVER clause", "concepts": ["window function"]}],
    }


def test_create_plan_snapshots_nested_answers_at_construction() -> None:
    answers = _answers()
    intent = CreatePlan(title="SQL Windows", answers=answers)

    answers["why"] = "changed after the intent was built"
    answers["milestones"].append({"title": "Injected", "concepts": ["x"]})  # type: ignore[union-attr]
    answers["success"][0] = "rewritten"  # type: ignore[index]

    assert intent.answers["why"] == "Ship analytics queries without help"
    assert intent.answers["success"] == ["Write a RANK() query unaided"]
    assert len(intent.answers["milestones"]) == 1  # type: ignore[arg-type]
    assert intent.answers == _answers(), "the snapshot equals what the caller passed"
    assert isinstance(intent.answers, Mapping)


def test_create_plan_answers_are_read_only() -> None:
    intent = CreatePlan(title="SQL Windows", answers=_answers())

    with pytest.raises(TypeError):
        intent.answers["why"] = "no"  # type: ignore[index]
    with pytest.raises(TypeError):
        del intent.answers["topics"]  # type: ignore[attr-defined]


def test_create_plan_keeps_json_types_for_the_authoring_layer() -> None:
    intent = CreatePlan(title="SQL Windows", answers=_answers())

    assert isinstance(intent.answers["milestones"], list)
    assert isinstance(intent.answers["milestones"][0], dict)  # type: ignore[index]
    assert isinstance(intent.answers["topics"], list)


def test_replayed_create_uses_original_answer_snapshot() -> None:
    answers = _answers()
    intent = CreatePlan(title="SQL Windows", answers=answers, plan_id="sql-windows")
    answers["why"] = "a later edit the intent must not see"
    answers["milestones"].clear()  # type: ignore[union-attr]

    detail = PlanApplication().apply(intent)

    assert detail.mission.why == "Ship analytics queries without help"
    assert [m.title for m in detail.milestones] == ["OVER clause"]
    assert store.load_plan("sql-windows").mission.why == "Ship analytics queries without help"


def test_non_mapping_answers_still_reach_the_seams_boundary_check() -> None:
    """The snapshot must not pre-empt the seam's own refusal: a JSON array is
    left as it is and ``apply`` raises ``InvalidField`` as before (the
    accepted Phase-1 boundary test builds this intent at import time)."""
    from studyloop.planning import InvalidField

    intent = CreatePlan(title="X", answers=["nope"])  # type: ignore[arg-type]

    with pytest.raises(InvalidField):
        PlanApplication().apply(intent)
    assert store.list_plan_ids() == []


def test_mcp_create_captured_intent_isolated_from_caller_mutation(monkeypatch) -> None:
    """Over MCP the adapter builds the intent from the decoded ``answers`` and
    applies it at once; the snapshot means even a caller that keeps a handle
    to that object cannot alter what was judged."""
    pytest.importorskip("mcp")
    from studyloop.mcp.server import mcp

    captured: list[CreatePlan] = []
    real_apply = PlanApplication.apply

    def spy(self: PlanApplication, intent):
        captured.append(intent)
        return real_apply(self, intent)

    monkeypatch.setattr(PlanApplication, "apply", spy)
    answers = _answers()

    mcp._tool_manager._tools["create_study_plan"].fn("SQL Windows", answers, plan_id="sql-windows")
    answers["why"] = "mutated after the call"

    assert len(captured) == 1
    assert captured[0].answers["why"] == "Ship analytics queries without help"
    assert store.load_plan("sql-windows").mission.why == "Ship analytics queries without help"
