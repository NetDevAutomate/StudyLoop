"""Deterministic and injection-safe learning-map source tests."""

from __future__ import annotations

import re

import pytest

from studyloop.planning.learning_map import render_learning_map
from studyloop.planning.models import Goal, Milestone, StudyPlan


def _diagram_source(rendered: str) -> str:
    return rendered.split("```mermaid\n", 1)[1].split("\n```", 1)[0]


def _node_ids(rendered: str) -> list[str]:
    source = _diagram_source(rendered)
    return re.findall(r"^    ([gm]_[0-9a-f]{16})\[", source, flags=re.MULTILINE)


def test_learning_map_uses_stable_ids_and_links_milestones_to_goals() -> None:
    plan = StudyPlan(
        plan_id="stable",
        title="Stable",
        goals=[Goal("goal-1", "First goal", "Needed", "Aligned")],
        milestones=[
            Milestone(
                "First milestone",
                milestone_id="milestone-1",
                goal_id="goal-1",
            )
        ],
    )

    first = render_learning_map(plan)
    plan.goals[0].title = "Renamed goal"
    plan.milestones[0].title = "Renamed milestone"
    second = render_learning_map(plan)

    assert first == render_learning_map(
        StudyPlan(
            plan_id="stable",
            title="Stable",
            goals=[Goal("goal-1", "First goal", "Needed", "Aligned")],
            milestones=[
                Milestone(
                    "First milestone",
                    milestone_id="milestone-1",
                    goal_id="goal-1",
                )
            ],
        )
    )
    assert _node_ids(first) == _node_ids(second)
    goal_node, milestone_node = _node_ids(first)
    assert f"    {goal_node} --> {milestone_node}" in _diagram_source(first)


@pytest.mark.parametrize(
    "hostile_label",
    [
        "slash/name",
        "pipe | value",
        'double " quote',
        "apostrophe's value",
        "back`tick",
        "[brackets]",
        "(parentheses)",
        "colon: value",
        "semi;colon",
        "line one\nline two",
        "arrow --> injected",
        "emoji 🚀",
        "",
        "duplicate",
        "long " + ("x" * 2_000),
    ],
)
def test_learning_map_encodes_hostile_labels_as_label_text(hostile_label: str) -> None:
    plan = StudyPlan(
        plan_id="hostile",
        title="Hostile",
        goals=[Goal("goal-safe", hostile_label, "reason", "alignment")],
        milestones=[
            Milestone(
                hostile_label,
                milestone_id="milestone-safe",
                goal_id="goal-safe",
            )
        ],
    )

    rendered = render_learning_map(plan)
    source = _diagram_source(rendered)
    node_lines = [line for line in source.splitlines() if '["' in line]
    edge_lines = [line for line in source.splitlines() if " --> " in line]

    assert source.startswith("flowchart TD\n")
    assert len(node_lines) == 2
    assert len(edge_lines) == 1
    assert "&" not in source
    assert all(
        re.fullmatch(r'    [gm]_[0-9a-f]{16}\["[A-Za-z0-9 _&#;-]+"\]', line) for line in node_lines
    )
    if hostile_label and not hostile_label.isalnum():
        assert hostile_label not in source


def test_duplicate_and_empty_names_have_distinct_nodes() -> None:
    plan = StudyPlan(
        plan_id="duplicates",
        title="Duplicates",
        goals=[
            Goal("goal-1", "duplicate", "reason", "alignment"),
            Goal("goal-2", "duplicate", "reason", "alignment"),
        ],
        milestones=[
            Milestone("", milestone_id="milestone-1", goal_id="goal-1"),
            Milestone("", milestone_id="milestone-2", goal_id="goal-2"),
        ],
    )

    rendered = render_learning_map(plan)

    assert len(_node_ids(rendered)) == 4
    assert len(set(_node_ids(rendered))) == 4
    assert "Untitled milestone" in rendered


def test_blank_ids_remain_distinct_and_blank_goal_links_are_unassigned() -> None:
    plan = StudyPlan(
        plan_id="blank-identities",
        title="Blank identities",
        goals=[
            Goal("", "Goal A", "reason", "alignment"),
            Goal("", "Goal B", "reason", "alignment"),
        ],
        milestones=[Milestone("Step 1"), Milestone("Step 2")],
    )

    rendered = render_learning_map(plan)
    source = _diagram_source(rendered)

    assert len(_node_ids(rendered)) == 4
    assert len(set(_node_ids(rendered))) == 4
    assert "- Goal: Goal A\n- Goal: Goal B\n- Unassigned milestones" in rendered
    assert " --> " not in source


def test_duplicate_non_empty_goal_ids_fail_closed() -> None:
    plan = StudyPlan(
        plan_id="duplicate-goals",
        title="Duplicate goals",
        goals=[
            Goal("goal-duplicate", "Goal A", "reason", "alignment"),
            Goal("goal-duplicate", "Goal B", "reason", "alignment"),
        ],
    )

    with pytest.raises(ValueError, match="duplicate goal_id: goal-duplicate"):
        render_learning_map(plan)


def test_duplicate_non_empty_milestone_ids_fail_closed() -> None:
    plan = StudyPlan(
        plan_id="duplicate-milestones",
        title="Duplicate milestones",
        milestones=[
            Milestone("Step 1", milestone_id="milestone-duplicate"),
            Milestone("Step 2", milestone_id="milestone-duplicate"),
        ],
    )

    with pytest.raises(ValueError, match="duplicate milestone_id: milestone-duplicate"):
        render_learning_map(plan)


def test_learning_map_includes_textual_hierarchy_before_the_diagram() -> None:
    plan = StudyPlan(
        plan_id="fallback",
        title="Fallback",
        goals=[Goal("goal-1", "Goal one", "reason", "alignment")],
        milestones=[Milestone("Step one", milestone_id="step-1", goal_id="goal-1")],
    )

    rendered = render_learning_map(plan)

    assert rendered.startswith("### Text learning map\n\n- Goal: Goal one\n  - Milestone: Step one")
    assert rendered.index("- Goal: Goal one") < rendered.index("```mermaid")


def test_empty_learning_map_has_an_explicit_text_fallback() -> None:
    rendered = render_learning_map(StudyPlan(plan_id="empty", title="Empty"))

    assert rendered == "### Text learning map\n\n_No goals or milestones yet._"
    assert "```mermaid" not in rendered
