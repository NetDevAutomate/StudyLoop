"""Structured-Markdown contract for study plans.

The invariant these tests protect: the document on disk is the source of truth,
so ``render_plan(parse_plan(doc)) == doc`` must hold exactly. Any drift means a
save silently rewrites the learner's file.
"""

from __future__ import annotations

import pytest

from studyloop.planning.markdown import parse_plan, render_plan
from studyloop.planning.models import (
    Checkpoint,
    LearningRecord,
    Milestone,
    Mission,
    Resource,
    StudyPlan,
)


def _populated_plan() -> StudyPlan:
    return StudyPlan(
        plan_id="glue-etl",
        title="Ship a Glue ETL Job",
        status="active",
        created="2026-08-01T09:00:00+00:00",
        updated="2026-08-03T18:30:00+00:00",
        topics=["data-engineering", "python"],
        energy_floor=4,
        target_date="2026-09-30",
        review_cadence_days=5,
        mission=Mission(
            why="Own the nightly customer-events pipeline without pairing.",
            success=["Deploy a Glue job unaided", "Explain the job bookmark"],
            constraints=["4 evenings a week, 30 minutes each"],
            out_of_scope=["EMR tuning"],
        ),
        milestones=[
            Milestone(
                title="Understand Glue job anatomy",
                done=True,
                concepts=["glue job", "job bookmark"],
                notes="read the dev guide first",
            ),
            Milestone(title="Write the transform", concepts=["dynamicframe"]),
            Milestone(title="Schedule and monitor it"),
        ],
        learning_records=[
            LearningRecord(number=1, title="Bookmarks are per-job", body="Not per-run."),
            LearningRecord(number=2, title="Superseded idea", body="Old.", status="superseded"),
        ],
        resources=[
            Resource(
                label="Glue dev guide", url="https://docs.aws.amazon.com/glue/", note="primary"
            ),
            Resource(label="A book with no link"),
        ],
        checkpoints=[
            Checkpoint(
                phase="start",
                verdict="on-track",
                at="2026-08-03T18:00:00+00:00",
                summary="33% complete and moving.",
                study_id="abc-123",
            )
        ],
        notes="Prefers diagrams over prose.",
    )


def test_populated_plan_round_trips_byte_for_byte() -> None:
    plan = _populated_plan()
    doc = render_plan(plan)
    assert render_plan(parse_plan(doc, plan_id=plan.plan_id)) == doc


def test_empty_plan_round_trips_and_placeholders_read_back_as_absent() -> None:
    """The critical placeholder case.

    The renderer writes italic placeholders ('_No notes._') for empty sections so
    a gap is visible in the UI. If the parser read those back as content, an
    empty plan would look populated and ``readiness`` would report it ready.
    """
    plan = StudyPlan(plan_id="blank", title="Blank Plan")
    doc = render_plan(plan)
    parsed = parse_plan(doc, plan_id="blank")

    assert parsed.mission.why == ""
    assert parsed.mission.success == []
    assert parsed.mission.constraints == []
    assert parsed.mission.out_of_scope == []
    assert parsed.milestones == []
    assert parsed.learning_records == []
    assert parsed.resources == []
    assert parsed.notes == ""
    assert render_plan(parsed) == doc


def test_stable_across_two_generations() -> None:
    plan = _populated_plan()
    first = render_plan(plan)
    second = render_plan(parse_plan(first, plan_id=plan.plan_id))
    third = render_plan(parse_plan(second, plan_id=plan.plan_id))
    assert first == second == third


@pytest.mark.parametrize(
    ("line", "expect_done", "expect_title", "expect_concepts", "expect_notes"),
    [
        (
            "- [x] **Closures** `(concepts: closures, cells)`",
            True,
            "Closures",
            ["closures", "cells"],
            "",
        ),
        ("- [ ] **Basic decorator**", False, "Basic decorator", [], ""),
        ("- [ ] Plain title — some notes", False, "Plain title", [], "some notes"),
        (
            "- [X] **Both** — notes here `(concepts: a)`",
            True,
            "Both",
            ["a"],
            "notes here",
        ),
    ],
)
def test_milestone_line_parsing(
    line: str,
    expect_done: bool,
    expect_title: str,
    expect_concepts: list[str],
    expect_notes: str,
) -> None:
    doc = f"---\nid: m\ntitle: M\n---\n\n# M\n\n## Milestones\n\n{line}\n"
    parsed = parse_plan(doc, plan_id="m")
    assert len(parsed.milestones) == 1
    milestone = parsed.milestones[0]
    assert milestone.done is expect_done
    assert milestone.title == expect_title
    assert milestone.concepts == expect_concepts
    assert milestone.notes == expect_notes


def test_iso_timestamps_survive_yaml_coercion() -> None:
    """yaml.safe_load turns ISO datetimes into ``datetime`` objects.

    ``str()`` on those uses a space separator, which would silently rewrite
    every plan's frontmatter on the next save.
    """
    plan = _populated_plan()
    parsed = parse_plan(render_plan(plan), plan_id=plan.plan_id)
    assert parsed.created == "2026-08-01T09:00:00+00:00"
    assert parsed.updated == "2026-08-03T18:30:00+00:00"
    assert parsed.target_date == "2026-09-30"


def test_topics_parse_from_yaml_list() -> None:
    parsed = parse_plan(render_plan(_populated_plan()), plan_id="glue-etl")
    assert parsed.topics == ["data-engineering", "python"]
    assert parsed.energy_floor == 4
    assert parsed.review_cadence_days == 5


def test_unknown_section_is_preserved_into_notes() -> None:
    doc = "---\nid: keep\ntitle: Keep\n---\n\n# Keep\n\n## Some Custom Section\n\nDo not lose me.\n"
    parsed = parse_plan(doc, plan_id="keep")
    assert "Do not lose me." in parsed.notes
    assert "Some Custom Section" in parsed.notes


def test_checkpoint_rows_parse_back() -> None:
    parsed = parse_plan(render_plan(_populated_plan()), plan_id="glue-etl")
    assert len(parsed.checkpoints) == 1
    checkpoint = parsed.checkpoints[0]
    assert checkpoint.phase == "start"
    assert checkpoint.verdict == "on-track"
    assert checkpoint.study_id == "abc-123"


def test_checkpoint_summary_containing_pipe_does_not_break_the_table() -> None:
    """A literal '|' in a summary must survive, not shift the columns.

    Regression: the renderer escaped '|' but the parser split on a bare '|',
    tearing the cell in two and corrupting summary + study_id on the next save.
    """
    plan = StudyPlan(plan_id="pipe", title="Pipe")
    plan.checkpoints.append(
        Checkpoint(
            phase="end",
            verdict="at-risk",
            at="2026-08-03",
            summary="a | b | c",
            study_id="sess-7",
        )
    )
    doc = render_plan(plan)
    parsed = parse_plan(doc, plan_id="pipe")
    assert len(parsed.checkpoints) == 1
    checkpoint = parsed.checkpoints[0]
    assert checkpoint.phase == "end"
    assert checkpoint.verdict == "at-risk"
    assert checkpoint.summary == "a | b | c"
    assert checkpoint.study_id == "sess-7"
    assert render_plan(parsed) == doc


def test_checkpoint_summary_newlines_are_flattened_into_one_cell() -> None:
    """A table cell is single-line; a newline would end the row early."""
    plan = StudyPlan(plan_id="nl", title="NL")
    plan.checkpoints.append(
        Checkpoint(phase="mid", verdict="stalled", at="2026-08-03", summary="one\ntwo")
    )
    doc = render_plan(plan)
    parsed = parse_plan(doc, plan_id="nl")
    assert parsed.checkpoints[0].summary == "one two"
    assert parsed.checkpoints[0].verdict == "stalled"
    assert render_plan(parsed) == doc


def test_learning_records_parse_number_and_sort() -> None:
    doc = (
        "---\nid: lr\ntitle: LR\n---\n\n# LR\n\n## Learning Records\n\n"
        "### LR-0002 — Second\n\nBody two.\n\n"
        "### LR-0001 — First\n\nBody one.\n"
    )
    parsed = parse_plan(doc, plan_id="lr")
    assert [r.number for r in parsed.learning_records] == [1, 2]
    assert parsed.learning_records[0].title == "First"


def test_learning_record_status_is_read() -> None:
    parsed = parse_plan(render_plan(_populated_plan()), plan_id="glue-etl")
    statuses = {r.number: r.status for r in parsed.learning_records}
    assert statuses[2] == "superseded"


def test_resources_parse_link_label_and_note() -> None:
    parsed = parse_plan(render_plan(_populated_plan()), plan_id="glue-etl")
    linked = parsed.resources[0]
    assert linked.label == "Glue dev guide"
    assert linked.url == "https://docs.aws.amazon.com/glue/"
    assert linked.note == "primary"
    bare = parsed.resources[1]
    assert bare.label == "A book with no link"
    assert bare.url == ""


def test_missing_frontmatter_falls_back_to_body_title_and_given_id() -> None:
    parsed = parse_plan("# Hand Written Plan\n\n## Milestones\n\n- [ ] Step one\n", plan_id="hand")
    assert parsed.plan_id == "hand"
    assert parsed.title == "Hand Written Plan"
    assert len(parsed.milestones) == 1


def test_invalid_status_in_frontmatter_degrades_to_draft() -> None:
    doc = "---\nid: bad\ntitle: Bad\nstatus: banana\n---\n\n# Bad\n"
    assert parse_plan(doc, plan_id="bad").status == "draft"


def test_fenced_code_headings_are_not_treated_as_sections() -> None:
    """A '## ' inside a fenced block is code, not a section heading."""
    doc = (
        "---\nid: fence\ntitle: Fence\n---\n\n# Fence\n\n## Notes\n\n"
        "```python\n# Comment\n## Not a heading\n```\n"
    )
    parsed = parse_plan(doc, plan_id="fence")
    assert "## Not a heading" in parsed.notes
