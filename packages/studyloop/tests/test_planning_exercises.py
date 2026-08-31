"""Tests for the three topic exercise formats and the shared review pipeline.

The assertions that matter most are the design invariants:

* the two code formats run through *one* pipeline, parameterised by scaffold;
* starter code earns no credit;
* mentoring is question-shaped and never leaks the reference solution.
"""

from __future__ import annotations

import pytest

from studyloop.planning.exercises import (
    Choice,
    CodeExercise,
    Criterion,
    ExerciseSet,
    MultipleChoiceQuestion,
    authored_delta,
    band_for,
    derive_completion,
    draft_exercise_set,
    from_milestone,
    parse_exercise_set,
    readiness,
    redacted_copy,
    render_exercise_set,
    render_for_learner,
    review_code,
    review_quiz,
    review_submission,
    scrub_leaks,
    substantive_lines,
)

REFERENCE = """def make_counter():
    count = 0

    def increment():
        nonlocal count
        count += 1
        return count

    return increment
"""

RUBRIC = [
    Criterion(
        title="Defines the factory function",
        weight=1,
        check=r"def\s+make_counter",
        ask="What has to exist before anything can be returned",
    ),
    Criterion(
        title="Keeps state in the enclosing scope",
        weight=3,
        check=r"nonlocal\s+\w+",
        ask="Where does the count have to live to survive between calls",
    ),
    Criterion(
        title="Avoids module-level global state",
        weight=2,
        check=r"return\s+increment",
        forbid=r"^global\s+\w+",
        ask="What breaks if two counters share one name",
    ),
]

REQUIREMENTS = [
    "`make_counter()` returns a callable",
    "Each returned callable counts its own calls independently",
]


def make_blank_slate() -> CodeExercise:
    return CodeExercise(
        kind="blank_slate",
        title="Closures",
        requirements=list(REQUIREMENTS),
        rubric=[
            Criterion(title=c.title, weight=c.weight, check=c.check, forbid=c.forbid, ask=c.ask)
            for c in RUBRIC
        ],
        reference_solution=REFERENCE,
    )


def make_set() -> ExerciseSet:
    blank = make_blank_slate()
    return ExerciseSet(
        set_id="python--closures",
        topic="closures",
        title="Closures",
        plan_id="python",
        concepts=["closures", "cell variables"],
        blank_slate=blank,
        completion=derive_completion(blank, reveal=0.4),
        multiple_choice=[
            MultipleChoiceQuestion(
                prompt="What keeps a closure's variable alive?",
                choices=[
                    Choice(
                        text="The global namespace",
                        why="globals are shared, so two counters would collide",
                    ),
                    Choice(text="A cell object referenced by the function", correct=True),
                    Choice(
                        text="Nothing — it is copied by value",
                        why="values are rebound, not copied",
                    ),
                ],
            )
        ],
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_blank_slate_cannot_carry_starter_code() -> None:
    """The format's definition is enforced, not just documented."""
    with pytest.raises(ValueError, match="cannot supply starter code"):
        CodeExercise(kind="blank_slate", title="x", starter_code="def f(): ...")


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="kind must be one of"):
        CodeExercise(kind="essay", title="x")


def test_substantive_lines_drops_noise() -> None:
    code = "\n".join(["", "# a comment", "def f():", "    pass", "    return 1", "}"])
    assert substantive_lines(code) == ["def f():", "return 1"]


def test_score_bands_map_to_progress_confidence() -> None:
    assert band_for(100) == ("strong", "mastered")
    assert band_for(75) == ("solid", "confident")
    assert band_for(50) == ("developing", "learning")
    assert band_for(0) == ("struggling", "struggling")


def test_missing_formats_names_all_three() -> None:
    empty = ExerciseSet(set_id="s", topic="t")
    assert set(empty.missing_formats()) == {"blank_slate", "completion", "multiple_choice"}
    assert not empty.is_complete
    assert make_set().is_complete


# ---------------------------------------------------------------------------
# Scaffold parameterisation (the design note)
# ---------------------------------------------------------------------------


def test_blank_slate_has_no_scaffold_and_completion_does() -> None:
    """One task authored once yields both formats, differing only by scaffold."""
    blank = make_blank_slate()
    completion = derive_completion(blank, reveal=0.4)

    assert blank.scaffold_ratio == 0.0
    assert 0.0 < completion.scaffold_ratio < 1.0
    assert completion.kind == "completion"
    # Same requirements and same rubric — that is what makes them comparable.
    assert completion.requirements == blank.requirements
    assert [c.title for c in completion.rubric] == [c.title for c in blank.rubric]


def test_completion_starter_marks_the_missing_work() -> None:
    completion = derive_completion(make_blank_slate(), reveal=0.4)
    assert "TODO" in completion.starter_code
    # The signature is revealed; the stateful body is not.
    assert "def make_counter" in completion.starter_code
    assert "nonlocal count" not in completion.starter_code


def test_reveal_is_capped_below_everything() -> None:
    """A completion exercise must always leave something to complete."""
    completion = derive_completion(make_blank_slate(), reveal=1.0)
    assert completion.scaffold_ratio < 1.0
    assert "TODO" in completion.starter_code


def test_derive_completion_requires_a_reference() -> None:
    bare = CodeExercise(kind="blank_slate", title="x", requirements=["do a thing"])
    with pytest.raises(ValueError, match="without a reference solution"):
        derive_completion(bare)


# ---------------------------------------------------------------------------
# The shared review pipeline
# ---------------------------------------------------------------------------


def test_authored_delta_excludes_supplied_lines() -> None:
    starter = "def f():\n    # TODO: body\n"
    submission = "def f():\n    return 42\n"
    assert authored_delta(submission, starter) == ["return 42"]


def test_full_solution_scores_strong_on_blank_slate() -> None:
    review = review_code(make_blank_slate(), REFERENCE, topic="closures")
    assert review.score == 100
    assert review.band == "strong"
    assert review.confidence == "mastered"
    assert review.kind == "blank_slate"
    assert not review.outstanding


def test_partial_solution_scores_by_weight_and_asks_questions() -> None:
    """Missing the heavily-weighted criterion costs the most, and raises a question."""
    partial = "def make_counter():\n    return increment\n"
    review = review_code(make_blank_slate(), partial, topic="closures")

    assert 0 < review.score < 100
    statuses = {c.title: c.status for c in review.criteria}
    assert statuses["Keeps state in the enclosing scope"] == "unmet"
    assert statuses["Defines the factory function"] == "met"
    # 1 + 2 of 6 weight = 50%.
    assert review.score == 50
    assert review.mentoring, "an unmet criterion must produce a mentoring question"
    assert all(q.endswith("?") for q in review.mentoring)


def test_starter_code_earns_no_credit() -> None:
    """The invariant that keeps completion scores honest.

    Submitting the starter code unchanged must not inherit its criteria as
    passes — the learner gets neither credit nor blame for supplied code, and a
    zero-delta submission scores nothing.
    """
    completion = derive_completion(make_blank_slate(), reveal=0.4)
    review = review_code(completion, completion.starter_code, topic="closures")

    assert review.score == 0
    assert review.authored_line_count == 0
    assert any("starter code" in w for w in review.warnings)
    given = {c.title for c in review.given}
    assert "Defines the factory function" in given, given
    assert all(c.earned == 0 for c in review.given)


def test_completion_credits_only_the_learners_delta() -> None:
    """A finished completion scores on what the learner added, not what was given."""
    completion = derive_completion(make_blank_slate(), reveal=0.4)
    review = review_code(completion, REFERENCE, topic="closures")

    assert review.score == 100
    assert review.authored_line_count > 0
    # The signature came from the scaffold, so it is `given`, not `met`.
    assert "Defines the factory function" in {c.title for c in review.given}
    assert all(c.status != "met" for c in review.given)


def test_both_code_formats_use_the_same_entry_point() -> None:
    """One pipeline, two formats — dispatch is data, not a separate feature."""
    exercise_set = make_set()
    blank_review = review_submission(exercise_set, "blank_slate", submission=REFERENCE)
    completion_review = review_submission(exercise_set, "completion", submission=REFERENCE)

    assert blank_review.kind == "blank_slate"
    assert completion_review.kind == "completion"
    assert blank_review.score == completion_review.score == 100
    assert type(blank_review) is type(completion_review)


def test_forbidden_pattern_beats_a_positive_match() -> None:
    submission = "global count\ndef make_counter():\n    nonlocal count\n    return increment\n"
    review = review_code(make_blank_slate(), submission, topic="closures")
    violated = [c for c in review.criteria if c.status == "violated"]
    assert violated, [c.to_dict() for c in review.criteria]
    assert violated[0].question.endswith("?")


def test_empty_submission_is_scored_zero_with_a_starting_question() -> None:
    review = review_code(make_blank_slate(), "", topic="closures")
    assert review.score == 0
    assert "smallest place to start" in " ".join(review.mentoring)


def test_rubric_without_checks_is_reported_not_silently_passed() -> None:
    """An uncheckable rubric must not award marks for nothing."""
    exercise = CodeExercise(
        kind="blank_slate",
        title="x",
        requirements=["do a thing"],
        rubric=[Criterion(title="does the thing")],
    )
    check = readiness(ExerciseSet(set_id="s", topic="t", blank_slate=exercise))
    assert any("no `check` pattern" in b for b in check["blockers"])


def test_unverifiable_criterion_scores_nothing_rather_than_everything() -> None:
    """The flattery bug: an empty stub must not score 100 on an unauthored rubric.

    A criterion with no ``check`` cannot be verified. Treating it as met would
    hand full marks to ``def f(): pass``; treating it as unmet would blame the
    learner for the author's gap. So it is excluded, and the gap is reported.
    """
    exercise = CodeExercise(
        kind="blank_slate",
        title="x",
        requirements=["make_counter() returns a callable"],
        rubric=[Criterion(title="make_counter() returns a callable")],
    )
    review = review_code(exercise, "def make_counter():\n    pass\n")

    assert review.score == 0, "an unverifiable rubric awarded marks"
    assert [c.status for c in review.criteria] == ["unscoreable"]
    assert not review.strengths
    assert any("no verifiable check" in w for w in review.warnings)
    assert any("not scored" in w for w in review.warnings)
    # The question still belongs in the conversation.
    assert review.mentoring and review.mentoring[0].endswith("?")


def test_partly_verifiable_rubric_scores_on_what_can_be_checked() -> None:
    exercise = CodeExercise(
        kind="blank_slate",
        title="x",
        requirements=["r"],
        rubric=[
            Criterion(title="uses a generator", weight=1, check="yield"),
            Criterion(title="is elegant", weight=9),
        ],
    )
    review = review_code(exercise, "def f():\n    yield 1\n")
    # The unscoreable weight-9 criterion is out of the denominator entirely.
    assert review.score == 100
    statuses = {c.title: c.status for c in review.criteria}
    assert statuses == {"uses a generator": "met", "is elegant": "unscoreable"}
    assert any("no verifiable check" in w for w in review.warnings)


def test_forbid_only_criterion_is_scoreable() -> None:
    """Nothing required, one thing banned — still verifiable, so still scored."""
    exercise = CodeExercise(
        kind="blank_slate",
        title="x",
        requirements=["r"],
        rubric=[Criterion(title="no bare except", forbid=r"except\s*:")],
    )
    assert review_code(exercise, "try:\n    f()\nexcept ValueError:\n    pass\n").score == 100
    bad = review_code(exercise, "try:\n    f()\nexcept:\n    pass\n")
    assert bad.score == 0
    assert [c.status for c in bad.criteria] == ["violated"]


def test_no_rubric_scores_zero_with_a_warning() -> None:
    exercise = CodeExercise(kind="blank_slate", title="x", requirements=["r"])
    review = review_code(exercise, "def f(): pass")
    assert review.score == 0
    assert any("no rubric" in w for w in review.warnings)


# ---------------------------------------------------------------------------
# Socratic guarantee — improvements are asked, never handed over
# ---------------------------------------------------------------------------


def test_review_never_leaks_the_reference_solution() -> None:
    """The whole point of the mentoring path: guide, do not answer."""
    review = review_code(make_blank_slate(), "def make_counter():\n    pass\n", topic="closures")
    blob = " ".join(review.mentoring) + review.as_markdown()
    for line in substantive_lines(REFERENCE):
        if len(line) >= 14:
            assert line not in blob, f"reference solution leaked: {line!r}"


def test_scrub_leaks_redacts_substantive_lines_only() -> None:
    reference = "def make_counter():\n    nonlocal count\n    return count\n"
    leaky = "You need to write `def make_counter():` at the top."
    assert "def make_counter():" not in scrub_leaks(leaky, reference)
    # Short, generic lines are not redacted — that would mangle useful prose.
    assert "return count" in scrub_leaks("What does return count give you?", reference)


def test_mentoring_is_always_question_shaped() -> None:
    exercise = CodeExercise(
        kind="blank_slate",
        title="x",
        requirements=["r"],
        rubric=[Criterion(title="uses a generator", check="yield", ask="Consider laziness")],
    )
    review = review_code(exercise, "def f(): return [1]")
    assert review.mentoring == ["Consider laziness?"]


def test_criterion_without_ask_still_produces_a_question() -> None:
    exercise = CodeExercise(
        kind="blank_slate",
        title="x",
        requirements=["r"],
        rubric=[Criterion(title="uses a generator", check="yield")],
    )
    review = review_code(exercise, "def f(): return [1]")
    assert len(review.mentoring) == 1
    assert review.mentoring[0].endswith("?")
    assert "uses a generator" in review.mentoring[0]


# ---------------------------------------------------------------------------
# Multiple choice
# ---------------------------------------------------------------------------


def test_correct_answer_scores_and_asks_a_transfer_question() -> None:
    exercise_set = make_set()
    review = review_quiz(exercise_set.multiple_choice, {0: [1]}, topic="closures")
    assert review.score == 100
    assert review.correct_count == 1
    assert review.results[0].is_correct
    assert review.mentoring, "even a perfect score should push understanding"


def test_wrong_answer_mentors_from_the_chosen_misconception() -> None:
    """The follow-up lands on the learner's reasoning, without naming the answer."""
    exercise_set = make_set()
    review = review_quiz(exercise_set.multiple_choice, {0: [0]}, topic="closures")

    assert review.score == 0
    result = review.results[0]
    assert not result.is_correct
    assert result.misconceptions == ["globals are shared, so two counters would collide"]
    assert result.question.endswith("?")
    # The correct choice's text must not be handed over.
    assert "A cell object referenced by the function" not in result.question


def test_multi_select_requires_the_exact_set() -> None:
    question = MultipleChoiceQuestion(
        prompt="Which are true?",
        choices=[
            Choice(text="a", correct=True),
            Choice(text="b", correct=True),
            Choice(text="c", why="c is a distractor"),
        ],
    )
    assert question.is_multi_select
    assert review_quiz([question], {0: [0, 1]}).score == 100
    # Shotgunning every box is not understanding.
    assert review_quiz([question], {0: [0, 1, 2]}).score == 0
    assert review_quiz([question], {0: [0]}).score == 0


def test_question_without_a_correct_answer_is_skipped_with_a_warning() -> None:
    broken = MultipleChoiceQuestion(prompt="?", choices=[Choice(text="a"), Choice(text="b")])
    review = review_quiz([broken], {0: [0]})
    assert review.total == 0
    assert any("no correct answer" in w for w in review.warnings)


def test_out_of_range_selections_are_ignored() -> None:
    exercise_set = make_set()
    review = review_quiz(exercise_set.multiple_choice, {0: [1, 99, -3]}, topic="closures")
    assert review.results[0].selected == [1]
    assert review.score == 100


def test_review_submission_dispatches_multiple_choice() -> None:
    review = review_submission(make_set(), "multiple_choice", answers={0: [1]})
    assert review.kind == "multiple_choice"
    assert review.score == 100


def test_review_submission_rejects_a_missing_format() -> None:
    bare = ExerciseSet(set_id="s", topic="t")
    with pytest.raises(LookupError, match="no 'blank_slate' exercise"):
        review_submission(bare, "blank_slate", submission="x")


# ---------------------------------------------------------------------------
# Markdown round trip
# ---------------------------------------------------------------------------


def test_markdown_round_trip_preserves_all_three_formats() -> None:
    original = make_set()
    reparsed = parse_exercise_set(render_exercise_set(original), set_id=original.set_id)

    assert reparsed.set_id == original.set_id
    assert reparsed.topic == original.topic
    assert reparsed.plan_id == original.plan_id
    assert reparsed.concepts == original.concepts
    assert reparsed.created == original.created

    assert reparsed.blank_slate is not None
    assert original.blank_slate is not None
    reparsed_blank_slate = reparsed.blank_slate
    original_blank_slate = original.blank_slate
    assert reparsed_blank_slate.kind == "blank_slate"
    assert reparsed_blank_slate.requirements == original_blank_slate.requirements
    assert reparsed_blank_slate.reference_solution == original_blank_slate.reference_solution
    assert reparsed_blank_slate.starter_code == ""

    assert reparsed.completion is not None
    assert original.completion is not None
    reparsed_completion = reparsed.completion
    original_completion = original.completion
    assert reparsed_completion.kind == "completion"
    assert reparsed_completion.starter_code == original_completion.starter_code

    for parsed_c, original_c in zip(
        reparsed_blank_slate.rubric, original_blank_slate.rubric, strict=True
    ):
        assert parsed_c.title == original_c.title
        assert parsed_c.weight == original_c.weight
        assert parsed_c.check == original_c.check
        assert parsed_c.forbid == original_c.forbid
        assert parsed_c.ask == original_c.ask

    assert len(reparsed.multiple_choice) == 1
    question = reparsed.multiple_choice[0]
    assert question.prompt == "What keeps a closure's variable alive?"
    assert question.correct_indexes == [1]
    assert question.choices[0].why == "globals are shared, so two counters would collide"
    assert reparsed.is_complete


def test_round_trip_is_stable_across_two_renders() -> None:
    once = render_exercise_set(make_set())
    twice = render_exercise_set(parse_exercise_set(once, set_id="python--closures"))
    assert once == twice


def test_hand_authored_markdown_parses() -> None:
    """A learner writes a quiz in a text editor; no tooling required."""
    document = """---
id: sql--windows
plan_id: sql
topic: window functions
---

# Window functions

## Blank Slate

### Requirements

- Rank rows within each partition

### Rubric

- [2] Uses a window function `(check: over\\s*\\()` `(ask: What does the partition scope)`

## Multiple Choice

### Q1 — What does PARTITION BY change?

- [ ] The number of returned rows `(why: it confuses windows with GROUP BY)`
- [x] The frame each row's function sees

`(ask: How many rows come back either way?)`
"""
    parsed = parse_exercise_set(document)
    assert parsed.set_id == "sql--windows"
    assert parsed.topic == "window functions"
    assert parsed.blank_slate is not None
    assert parsed.blank_slate.rubric[0].weight == 2
    assert parsed.blank_slate.rubric[0].check == r"over\s*\("
    assert parsed.blank_slate.rubric[0].title == "Uses a window function"
    question = parsed.multiple_choice[0]
    assert question.prompt == "What does PARTITION BY change?"
    assert question.correct_indexes == [1]
    assert question.ask == "How many rows come back either way?"


def test_starter_code_in_a_blank_slate_section_is_read_as_completion() -> None:
    """Honour the document's intent rather than raising on a hand-edit."""
    document = """---
id: x
topic: t
---

# T

## Blank Slate

### Requirements

- do it

### Starter Code

```python
def f():
    # TODO: body
```
"""
    parsed = parse_exercise_set(document)
    assert parsed.blank_slate is not None
    assert parsed.blank_slate.kind == "completion"


def test_unknown_sections_are_preserved_in_notes() -> None:
    document = """---
id: x
topic: t
---

# T

## Somebody's Custom Section

Keep me.
"""
    assert "Keep me." in parse_exercise_set(document).notes


# ---------------------------------------------------------------------------
# Authoring
# ---------------------------------------------------------------------------


def test_draft_produces_all_three_formats_from_one_task() -> None:
    drafted = draft_exercise_set(
        "closures",
        plan_id="python",
        concepts=["closures"],
        requirements=REQUIREMENTS,
        rubric=RUBRIC,
        reference_solution=REFERENCE,
        questions=make_set().multiple_choice,
    )
    assert drafted.blank_slate is not None
    assert drafted.completion is not None
    assert drafted.multiple_choice
    assert drafted.is_complete
    assert drafted.set_id == "python-closures"


def test_draft_without_a_reference_still_supplies_a_completion_scaffold() -> None:
    """All three formats are required, so none may silently vanish."""
    drafted = draft_exercise_set("closures", requirements=REQUIREMENTS)
    assert drafted.completion is not None
    assert "TODO" in drafted.completion.starter_code
    assert "multiple_choice" in drafted.missing_formats()


def test_drafted_rubric_without_checks_is_not_ready() -> None:
    """Drafting invents no answers, and says so instead of scoring vacuously."""
    drafted = draft_exercise_set("closures", requirements=REQUIREMENTS)
    check = readiness(drafted)
    assert not check["ready"]
    assert any("no `check` pattern" in b for b in check["blockers"])


def test_from_milestone_seeds_requirements_from_concepts() -> None:
    drafted = from_milestone("python", "Closures", ["closures", "cell variables"])
    assert drafted.plan_id == "python"
    assert drafted.concepts == ["closures", "cell variables"]
    assert drafted.blank_slate is not None
    assert any("cell variables" in r for r in drafted.blank_slate.requirements)


def test_readiness_is_clean_for_a_complete_set() -> None:
    check = readiness(make_set())
    assert check["ready"], check["blockers"]
    assert check["missing_formats"] == []


# ---------------------------------------------------------------------------
# Redaction — the learner-facing document must not be an answer key
# ---------------------------------------------------------------------------


def test_redacted_copy_strips_every_answer_channel() -> None:
    """Redaction by construction: anything not copied is provably absent."""
    redacted = redacted_copy(make_set())
    original_reference = make_set()

    assert redacted.blank_slate is not None
    assert redacted.completion is not None
    assert original_reference.blank_slate is not None
    redacted_blank_slate = redacted.blank_slate
    original_blank_slate = original_reference.blank_slate
    assert redacted_blank_slate.reference_solution == ""
    assert redacted.completion.reference_solution == ""
    # A `check` regex recognises a correct solution, so it is a partial answer.
    assert all(not c.check and not c.forbid for c in redacted_blank_slate.rubric)
    # …but the brief survives: titles and weights are what the learner is told.
    assert [c.title for c in redacted_blank_slate.rubric] == [
        c.title for c in original_blank_slate.rubric
    ]
    assert [c.weight for c in redacted_blank_slate.rubric] == [1, 3, 2]

    question = redacted.multiple_choice[0]
    assert question.correct_indexes == []
    assert all(not c.why for c in question.choices)
    assert question.ask == ""
    # The options themselves must remain, or there is nothing to answer.
    assert [c.text for c in question.choices] == [
        c.text for c in make_set().multiple_choice[0].choices
    ]


def test_redacted_copy_keeps_the_completion_scaffold() -> None:
    """The scaffold is the exercise, not the answer — it must survive redaction."""
    redacted = redacted_copy(make_set())
    assert redacted.completion is not None
    redacted_completion = redacted.completion
    assert "TODO" in redacted_completion.starter_code
    assert "def make_counter" in redacted_completion.starter_code
    assert "nonlocal count" not in redacted_completion.starter_code


def test_learner_render_contains_no_reference_solution() -> None:
    """No *hidden* solution line may appear in the learner-facing document.

    Lines the completion scaffold deliberately reveals are excluded: they are
    the exercise, not a leak. What must never appear is the work the learner is
    being asked to do.
    """
    original = make_set()
    document = render_for_learner(original)
    assert original.completion is not None
    supplied = set(substantive_lines(original.completion.starter_code))
    hidden = [
        line for line in substantive_lines(REFERENCE) if len(line) >= 14 and line not in supplied
    ]
    assert hidden, "test is vacuous — the scaffold revealed everything"
    for line in hidden:
        assert line not in document, f"leaked into learner document: {line!r}"

    assert "- [x]" not in document, "a correct answer was still marked"
    assert "(why:" not in document
    assert "(check:" not in document
    # The Reference Solution section must be empty, not merely trimmed.
    assert "_No reference solution recorded._" in document


def test_learner_render_still_carries_the_brief() -> None:
    """Redaction must not hollow the document out."""
    document = render_for_learner(make_set())
    assert "## Blank Slate" in document
    assert "## Completion" in document
    assert "## Multiple Choice" in document
    assert "`make_counter()` returns a callable" in document
    assert "What keeps a closure's variable alive?" in document
    assert "Keeps state in the enclosing scope" in document


def test_redaction_does_not_mutate_the_original() -> None:
    original = make_set()
    redacted_copy(original)
    assert original.blank_slate is not None
    original_blank_slate = original.blank_slate
    assert original_blank_slate.reference_solution == REFERENCE.strip("\n")
    assert original.multiple_choice[0].correct_indexes == [1]
    assert original_blank_slate.rubric[1].check == r"nonlocal\s+\w+"
