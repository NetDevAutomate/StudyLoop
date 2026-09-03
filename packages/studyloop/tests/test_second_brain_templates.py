"""T3: one source of truth for plan headings, and the template that mirrors it.

Three artefacts describe the same shape — ``render_plan``'s output, the Obsidian
projection, and the vault template a learner writes notes from. Three copies of a
heading list drift, and the drift is invisible: a template whose sections no
longer match the plan document still looks fine on its own. So they derive from
one constant and this file is the guard.

The heading constants land first (clause C1); the templates and the rest of the
clauses follow in the same task.
"""

from __future__ import annotations

import re

from studyloop.planning import (
    MISSION_SUBSECTION_HEADINGS,
    PLAN_SECTION_HEADINGS,
    render_plan,
)
from studyloop.planning.models import (
    Checkpoint,
    LearningRecord,
    Milestone,
    Mission,
    Resource,
    StudyPlan,
)

_HEADING_RE = re.compile(r"^(#{2,3}) (.+?)\s*$", re.MULTILINE)


def headings(text: str) -> list[tuple[int, str]]:
    """``(level, text)`` for every ``##`` and ``###`` heading, in order."""
    return [(len(m.group(1)), m.group(2)) for m in _HEADING_RE.finditer(text)]


def full_plan() -> StudyPlan:
    """A plan with every section populated.

    Every section, deliberately: a plan with empty sections renders placeholder
    prose instead of some content, and a heading comparison against it would
    pass while the populated form drifted.
    """
    return StudyPlan(
        plan_id="python-decorators",
        title="Master Python Decorators",
        status="active",
        topics=["python"],
        target_date="2026-10-01",
        review_cadence_days=3,
        mission=Mission(
            why="Decorators keep showing up in code I have to read.",
            success=["Explain a decorator's closure unprompted"],
            constraints=["45 minutes a day"],
            out_of_scope=["Metaclasses"],
        ),
        milestones=[Milestone(title="Closures", concepts=["closures", "cell-vars"])],
        learning_records=[LearningRecord(number=1, title="Closures clicked", body="Cells.")],
        resources=[Resource(label="PEP 318", url="https://peps.python.org/pep-0318/")],
        checkpoints=[Checkpoint(phase="mid", verdict="on-track", at="2026-09-03", summary="Good")],
        notes="Nothing yet.",
    )


def test_render_plan_headings_equal_constants() -> None:
    """The renderer's ``##`` headings ARE the constant, in order."""
    level_two = [text for level, text in headings(render_plan(full_plan())) if level == 2]
    assert tuple(level_two) == PLAN_SECTION_HEADINGS


def test_mission_subsection_headings_equal_constants() -> None:
    rendered = headings(render_plan(full_plan()))
    mission_index = rendered.index((2, "Mission"))
    subsections = []
    for level, text in rendered[mission_index + 1 :]:
        if level == 2:
            break
        subsections.append(text)
    assert tuple(subsections) == MISSION_SUBSECTION_HEADINGS


def test_known_sections_is_derived_from_the_constant() -> None:
    """The parser and the renderer must not be able to disagree.

    A section the renderer emits but the parser does not recognise is silently
    swept into ``notes`` on the next round trip, which loses structure without
    any error.
    """
    from studyloop.planning.markdown import _KNOWN_SECTIONS

    assert {heading.lower() for heading in PLAN_SECTION_HEADINGS} == _KNOWN_SECTIONS


def test_constants_are_immutable_tuples() -> None:
    """A list would let a caller mutate the shared source of truth in place."""
    assert isinstance(PLAN_SECTION_HEADINGS, tuple)
    assert isinstance(MISSION_SUBSECTION_HEADINGS, tuple)
