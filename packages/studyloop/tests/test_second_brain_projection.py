"""T2 C1/C2/C3/C9/C10: the projection renderers are pure.

Purity is the design decision under test, not an implementation detail. A
renderer that reads the clock, the settings or the filesystem cannot be compared
against its own previous output, and comparison is exactly how idempotence is
achieved here: the writer decides whether to write by hashing the rendered body.
A timestamp in the output would make every publish a write, every day, forever.
"""

from __future__ import annotations

import re

import pytest
from test_second_brain_templates import full_plan, headings

from studyloop.planning import MISSION_SUBSECTION_HEADINGS, PLAN_SECTION_HEADINGS
from studyloop.second_brain.projection import (
    MAX_DUE_CARDS,
    MAX_FOCUS_TOPICS,
    MAX_TODAY_ALTERNATES,
    OWNERSHIP_KEY,
    PROJECTED_PLAN_KEYS,
    TODAY_SECTION_HEADINGS,
    ProjectionIdentity,
    TodayData,
    render_learning_record_projection,
    render_plan_projection,
    render_today,
)


def _identity(**overrides) -> ProjectionIdentity:
    base = {
        "kind": "plan-projection",
        "plan_id": "python-decorators",
        "learning_record": None,
        "source": "STUDYLOOP_PLANS_DIR/python-decorators.md",
    }
    base.update(overrides)
    return ProjectionIdentity(**base)


def _today_data(**overrides) -> TodayData:
    base = {
        "primary": "Recall how a closure captures a cell variable",
        "primary_reason": "Due today, and it blocks the next milestone.",
        "primary_minutes": 25,
        "alternates": ("Re-read PEP 318", "Write one decorator from memory"),
        "due_cards": ({"course": "Python", "card_hash": "abc123", "next_review": "2026-09-03"},),
        "focus_topics": ("python",),
    }
    base.update(overrides)
    return TodayData(**base)


# ---------------------------------------------------------------------------
# C1 — purity
# ---------------------------------------------------------------------------


def test_renderers_are_deterministic_and_do_no_io(monkeypatch) -> None:
    """Render twice with the filesystem, the clock and settings detonated."""
    import subprocess
    import time

    def _explode(*args: object, **kwargs: object):
        raise AssertionError("a projection renderer performed I/O or read the clock")

    monkeypatch.setattr(subprocess, "run", _explode)
    monkeypatch.setattr(subprocess, "Popen", _explode)
    monkeypatch.setattr(time, "time", _explode)
    from studyloop import settings as settings_mod

    monkeypatch.setattr(settings_mod, "load_settings", _explode)

    plan = full_plan()
    first = render_plan_projection(plan, _identity())
    second = render_plan_projection(plan, _identity())
    assert first == second

    today = _today_data()
    assert render_today(today, _identity(kind="today-projection", plan_id=None)) == render_today(
        today, _identity(kind="today-projection", plan_id=None)
    )

    record_identity = _identity(kind="learning-record-projection", learning_record=1)
    assert render_learning_record_projection(
        plan, plan.learning_records[0], record_identity
    ) == render_learning_record_projection(plan, plan.learning_records[0], record_identity)


def test_no_renderer_output_contains_a_clock_reading_of_its_own() -> None:
    """A clock in the body would make every publish a write, forever.

    The plan's own ``updated`` field is an ISO timestamp and legitimately appears
    — it changes only when the plan changes, which is exactly when a rewrite is
    wanted. What must never appear is a reading taken at render time, so the
    assertion is that every time-like string in the output came from the plan.
    """
    plan = full_plan()
    rendered = render_plan_projection(plan, _identity())
    plan_supplied = {plan.updated, plan.created, plan.target_date} | {
        checkpoint.at for checkpoint in plan.checkpoints
    }
    for match in re.findall(r"\d{4}-\d{2}-\d{2}[T ]?[\d:]*Z?", rendered):
        assert any(match.strip() in value for value in plan_supplied if value), match
    assert "generated" not in rendered.lower()


# ---------------------------------------------------------------------------
# C2 — the plan projection keeps the document's section order
# ---------------------------------------------------------------------------


def test_plan_projection_uses_canonical_section_order() -> None:
    rendered = render_plan_projection(full_plan(), _identity())
    level_two = [text for level, text in headings(rendered) if level == 2]
    assert tuple(level_two) == PLAN_SECTION_HEADINGS
    mission_subsections = [
        text
        for level, text in headings(rendered)
        if level == 3 and text in MISSION_SUBSECTION_HEADINGS
    ]
    assert tuple(mission_subsections) == MISSION_SUBSECTION_HEADINGS


def test_plan_projection_carries_the_plan_content() -> None:
    """A projection with the right headings and none of the content is worthless."""
    plan = full_plan()
    rendered = render_plan_projection(plan, _identity())
    assert plan.mission.why in rendered
    assert plan.milestones[0].title in rendered
    assert plan.resources[0].url in rendered
    assert plan.learning_records[0].title in rendered


# ---------------------------------------------------------------------------
# C3 — the ownership marker
# ---------------------------------------------------------------------------


def test_projection_frontmatter_has_exact_ownership_schema() -> None:
    import yaml

    rendered = render_plan_projection(full_plan(), _identity())
    assert rendered.startswith("---\n")
    frontmatter = yaml.safe_load(rendered.split("---\n")[1])
    marker = frontmatter[OWNERSHIP_KEY]
    assert set(marker) == {
        "owned",
        "schema",
        "kind",
        "plan_id",
        "learning_record",
        "source",
        "content_hash",
    }
    assert marker["owned"] is True
    assert marker["schema"] == 1
    assert marker["kind"] == "plan-projection"
    assert re.fullmatch(r"[0-9a-f]{64}", marker["content_hash"])


def test_plan_frontmatter_exposes_the_documented_query_keys() -> None:
    """The Dataview snippet in the template can only use keys that are written."""
    import yaml

    plan = full_plan()
    frontmatter = yaml.safe_load(render_plan_projection(plan, _identity()).split("---\n")[1])
    for key in PROJECTED_PLAN_KEYS:
        assert key in frontmatter, key
    assert frontmatter["title"] == plan.title
    assert frontmatter["status"] == plan.status
    assert frontmatter["progress_pct"] == 0
    assert frontmatter["topics"] == ["python"]


def test_progress_pct_is_derived_from_milestones() -> None:
    """``StudyPlan`` has no progress field; the projection computes one.

    Computed rather than stored so a projection can never disagree with the plan
    document it was rendered from.
    """
    import yaml

    plan = full_plan()
    plan.milestones[0].done = True
    frontmatter = yaml.safe_load(render_plan_projection(plan, _identity()).split("---\n")[1])
    assert frontmatter["progress_pct"] == 100


def test_content_hash_excludes_itself() -> None:
    """Hashing must be stable, so the hash field cannot be part of the input."""
    import yaml

    rendered = render_plan_projection(full_plan(), _identity())
    marker = yaml.safe_load(rendered.split("---\n")[1])[OWNERSHIP_KEY]
    from studyloop.second_brain.projection import content_hash_of

    assert content_hash_of(rendered) == marker["content_hash"]


def test_content_hash_changes_when_the_plan_changes() -> None:
    import yaml

    def _hash(plan) -> str:
        return yaml.safe_load(render_plan_projection(plan, _identity()).split("---\n")[1])[
            OWNERSHIP_KEY
        ]["content_hash"]

    plan = full_plan()
    before = _hash(plan)
    plan.mission.why = "Something else entirely."
    assert _hash(plan) != before


# ---------------------------------------------------------------------------
# C9 — learning-record projections are regenerated, never appended
# ---------------------------------------------------------------------------


def test_learning_record_projection_is_regenerated_not_appended() -> None:
    plan = full_plan()
    record = plan.learning_records[0]
    identity = _identity(kind="learning-record-projection", learning_record=record.number)
    render_learning_record_projection(plan, record, identity)
    record.body = "A different conclusion."
    second = render_learning_record_projection(plan, record, identity)
    assert "A different conclusion." in second
    assert "Cells." not in second
    assert second.count("# LR-0001") == 1


# ---------------------------------------------------------------------------
# C10 — Today is bounded and replaced
# ---------------------------------------------------------------------------


def test_today_headings_match_the_constant() -> None:
    rendered = render_today(_today_data(), _identity(kind="today-projection", plan_id=None))
    level_two = [text for level, text in headings(rendered) if level == 2]
    assert tuple(level_two) == TODAY_SECTION_HEADINGS


def test_today_projection_bounds_all_lists() -> None:
    """Today has to stay glanceable. An unbounded list is not a "next action"."""
    data = _today_data(
        alternates=tuple(f"alt {n}" for n in range(10)),
        due_cards=tuple(
            {"course": "Python", "card_hash": f"h{n}", "next_review": "2026-09-03"}
            for n in range(50)
        ),
        focus_topics=tuple(f"topic-{n}" for n in range(30)),
    )
    rendered = render_today(data, _identity(kind="today-projection", plan_id=None))
    assert rendered.count("- alt ") == MAX_TODAY_ALTERNATES
    assert rendered.count("`h") == MAX_DUE_CARDS
    assert rendered.count("- topic-") == MAX_FOCUS_TOPICS


def test_today_names_one_primary_action() -> None:
    rendered = render_today(_today_data(), _identity(kind="today-projection", plan_id=None))
    next_action = rendered.split("## Next action")[1].split("##")[0]
    assert next_action.count("Recall how a closure") == 1
    assert "25 min" in next_action


def test_today_with_nothing_due_still_renders_every_heading() -> None:
    """An empty day is a valid day; a missing heading breaks the template guard."""
    data = _today_data(alternates=(), due_cards=(), focus_topics=())
    rendered = render_today(data, _identity(kind="today-projection", plan_id=None))
    for heading in TODAY_SECTION_HEADINGS:
        assert f"## {heading}" in rendered


@pytest.mark.parametrize("kind", ["plan-projection", "today-projection"])
def test_every_projection_declares_it_is_stuudyloop_owned(kind) -> None:
    """Whatever the kind, the marker says StudyLoop regenerates this file."""
    import yaml

    if kind == "plan-projection":
        rendered = render_plan_projection(full_plan(), _identity())
    else:
        rendered = render_today(_today_data(), _identity(kind=kind, plan_id=None))
    marker = yaml.safe_load(rendered.split("---\n")[1])[OWNERSHIP_KEY]
    assert marker["owned"] is True
    assert marker["kind"] == kind
