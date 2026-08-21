"""Authoring the three exercise formats for a topic.

:func:`draft_exercise_set` is the entry point: given a topic (and optionally a
plan milestone's concepts), it produces a document with all three formats
scaffolded, and it refuses to invent content it was not given.

Why scaffolding rather than generation-by-LLM: a fabricated rubric scores the
learner against criteria nobody chose, and a fabricated "correct" answer teaches
the wrong thing with full confidence.  So the drafting path emits honest,
clearly-marked gaps and a readiness report saying what a human or an agent still
has to author.  The LLM path can then fill the gaps through the same API.

:func:`derive_completion` is the design note made executable: it turns an
authored blank-slate exercise into a completion exercise by revealing a
configurable fraction of the reference solution and blanking the rest with
``TODO`` markers.  One authoring effort, two formats, one scoring pipeline.
"""

from __future__ import annotations

import re

from ..models import slugify
from .models import (
    CODE_KINDS,
    CodeExercise,
    Criterion,
    ExerciseSet,
    MultipleChoiceQuestion,
)

#: Default share of the reference solution revealed in a completion exercise.
DEFAULT_REVEAL = 0.4

#: Lines that anchor a solution's shape. Revealing these first makes a completion
#: exercise a "finish the body" task rather than a "guess the signature" task.
_STRUCTURAL_RE = re.compile(
    r"^\s*(def |class |async def |@|import |from |return\s*$|if __name__)",
)

_TODO_MARKER = "# TODO: "


def _dedent_marker_indent(line: str) -> str:
    """The leading whitespace of ``line``, so a TODO lands at the right depth."""
    return line[: len(line) - len(line.lstrip())]


def derive_completion(
    blank_slate: CodeExercise,
    *,
    reveal: float = DEFAULT_REVEAL,
) -> CodeExercise:
    """Derive a completion exercise from a blank-slate one.

    ``reveal`` is the scaffold parameter from the design note: 0.0 gives back
    something equivalent to the blank slate, 1.0 would hand over the answer (and
    is therefore capped below 1.0 — a completion exercise with nothing left to
    complete is not an exercise).

    Structural lines (signatures, imports, decorators) are revealed before
    bodies, and every hidden run collapses into a single ``# TODO`` so the shape
    of the missing work is visible without the work being done.
    """
    if not blank_slate.reference_solution.strip():
        msg = "cannot derive a completion exercise without a reference solution"
        raise ValueError(msg)

    lines = blank_slate.reference_solution.splitlines()
    # Cap strictly below 1.0 so at least one substantive line stays hidden.
    ratio = max(0.0, min(0.85, float(reveal)))

    candidates = [i for i, line in enumerate(lines) if line.strip()]
    budget = round(len(candidates) * ratio)
    structural = [i for i in candidates if _STRUCTURAL_RE.match(lines[i])]
    revealed: set[int] = set(structural[:budget])
    for index in candidates:
        if len(revealed) >= budget:
            break
        revealed.add(index)

    out: list[str] = []
    pending_hidden = False
    for index, line in enumerate(lines):
        if not line.strip():
            out.append(line)
            continue
        if index in revealed:
            out.append(line)
            pending_hidden = False
            continue
        if not pending_hidden:
            out.append(f"{_dedent_marker_indent(line)}{_TODO_MARKER}complete this step")
            pending_hidden = True

    starter = "\n".join(out).strip("\n")
    if not starter.strip():
        # Degenerate reference (single line): still give the learner an anchor.
        starter = f"{_TODO_MARKER}write the whole implementation"

    return CodeExercise(
        kind="completion",
        title=f"{blank_slate.title} — finish the implementation",
        requirements=list(blank_slate.requirements),
        starter_code=starter,
        # Same rubric: the pipeline marks starter-satisfied criteria `given`, so
        # sharing it is what makes the two formats comparable rather than
        # accidentally easier.
        rubric=[
            Criterion(
                title=c.title,
                weight=c.weight,
                check=c.check,
                forbid=c.forbid,
                ask=c.ask,
            )
            for c in blank_slate.rubric
        ],
        reference_solution=blank_slate.reference_solution,
        language=blank_slate.language,
    )


def _criteria_from_requirements(requirements: list[str]) -> list[Criterion]:
    """Turn requirements into rubric criteria with no ``check`` invented.

    A criterion with an empty ``check`` is vacuously met — which would inflate
    every score — so these carry a ``forbid`` that can never match and are
    reported by :func:`readiness` as needing a real check.  The honest failure
    mode is "this exercise is not scoreable yet", not "everyone passes".
    """
    return [
        Criterion(
            title=requirement,
            weight=1,
            check="",
            ask=(
                f"Which part of your solution satisfies “{requirement}”, "
                "and how would you prove it?"
            ),
        )
        for requirement in requirements
    ]


def draft_exercise_set(
    topic: str,
    *,
    plan_id: str = "",
    set_id: str = "",
    concepts: list[str] | None = None,
    requirements: list[str] | None = None,
    rubric: list[Criterion] | None = None,
    reference_solution: str = "",
    language: str = "python",
    questions: list[MultipleChoiceQuestion] | None = None,
    reveal: float = DEFAULT_REVEAL,
    notes: str = "",
) -> ExerciseSet:
    """Draft an exercise set with all three formats for ``topic``.

    The completion exercise is derived from the blank slate whenever a reference
    solution exists, so an author writes the task once.
    """
    cleaned_topic = (topic or "").strip() or "untitled"
    reqs = [r.strip() for r in (requirements or []) if r.strip()]
    criteria = list(rubric) if rubric else _criteria_from_requirements(reqs)

    blank_slate = CodeExercise(
        kind="blank_slate",
        title=cleaned_topic,
        requirements=reqs,
        starter_code="",
        rubric=criteria,
        reference_solution=reference_solution.strip(),
        language=language,
    )

    completion: CodeExercise | None = None
    if reference_solution.strip():
        completion = derive_completion(blank_slate, reveal=reveal)
    elif reqs:
        # No reference solution to slice, but the format is still required — give
        # a genuine (if minimal) scaffold rather than omitting the format.
        completion = CodeExercise(
            kind="completion",
            title=f"{cleaned_topic} — finish the implementation",
            requirements=reqs,
            starter_code=(
                f"{_TODO_MARKER}{reqs[0]}\n" + "\n".join(f"{_TODO_MARKER}{r}" for r in reqs[1:])
            ),
            rubric=[
                Criterion(title=c.title, weight=c.weight, check=c.check, forbid=c.forbid, ask=c.ask)
                for c in criteria
            ],
            reference_solution="",
            language=language,
        )

    return ExerciseSet(
        set_id=set_id or slugify(f"{plan_id}--{cleaned_topic}" if plan_id else cleaned_topic),
        topic=cleaned_topic,
        title=cleaned_topic,
        plan_id=plan_id,
        concepts=[c.strip() for c in (concepts or []) if c.strip()],
        blank_slate=blank_slate,
        completion=completion,
        multiple_choice=list(questions or []),
        notes=notes,
    )


def from_milestone(plan_id: str, milestone_title: str, concepts: list[str]) -> ExerciseSet:
    """Draft an exercise set for one plan milestone.

    Requirements are seeded from the milestone's concepts, which is the join key
    the plan already uses against ``study_progress`` — so the exercise, the
    milestone, and the confidence evidence all name the same thing.
    """
    requirements = [
        f"Demonstrate {concept} in working code, without looking it up" for concept in concepts
    ] or [f"Demonstrate {milestone_title} in working code"]
    return draft_exercise_set(
        milestone_title,
        plan_id=plan_id,
        concepts=concepts,
        requirements=requirements,
    )


def readiness(exercise_set: ExerciseSet) -> dict:
    """What still blocks this set from being usable, and what would improve it.

    Same shape as :func:`studyloop.planning.authoring.readiness`: ``ready``,
    ``blockers``, ``nudges`` — so the UI and the CLI can render either without a
    special case.
    """
    blockers: list[str] = []
    nudges: list[str] = []

    for kind in CODE_KINDS:
        exercise = exercise_set.code_exercise(kind)
        label = kind.replace("_", " ")
        if exercise is None:
            blockers.append(f"No {label} exercise — all three formats are required.")
            continue
        if not exercise.requirements:
            blockers.append(f"The {label} exercise has no requirements to work from.")
        if not exercise.rubric:
            blockers.append(f"The {label} exercise has no rubric, so an attempt cannot be scored.")
        else:
            uncheckable = [c.title for c in exercise.rubric if not c.check]
            if uncheckable:
                blockers.append(
                    f"{len(uncheckable)} {label} criterion(s) have no `check` pattern, "
                    "so they would pass automatically: " + ", ".join(uncheckable[:3])
                )
        if not exercise.reference_solution:
            nudges.append(
                f"The {label} exercise has no reference solution — "
                "the review can score it, but nothing can diff against intent."
            )

    completion = exercise_set.completion
    if completion is not None and completion.starter_code.strip():
        if not any(_TODO_MARKER.strip() in line for line in completion.starter_code.splitlines()):
            nudges.append(
                "The completion starter code has no TODO markers, so it is not "
                "obvious what the learner is meant to add."
            )
        if completion.scaffold_ratio >= 0.85:
            blockers.append(
                "The completion starter code reveals almost the whole solution — "
                "there is nothing left to complete."
            )

    answerable = [q for q in exercise_set.multiple_choice if q.is_answerable()]
    if not exercise_set.multiple_choice:
        blockers.append("No multiple-choice questions — all three formats are required.")
    elif not answerable:
        blockers.append("No multiple-choice question has a correct answer marked.")
    else:
        thin = [q.prompt for q in answerable if len(q.choices) < 3]
        if thin:
            nudges.append(
                f"{len(thin)} question(s) offer fewer than three options — "
                "a coin flip is not evidence."
            )
        no_why = [
            q.prompt
            for q in answerable
            if not q.ask and not any(c.why for c in q.choices if not c.correct)
        ]
        if no_why:
            nudges.append(
                f"{len(no_why)} question(s) record no misconception on their "
                "distractors, so a wrong answer cannot be mentored."
            )

    return {
        "ready": not blockers,
        "blockers": blockers,
        "nudges": nudges,
        "missing_formats": exercise_set.missing_formats(),
    }
