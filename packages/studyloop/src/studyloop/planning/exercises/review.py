"""The shared review-and-score-then-mentor pipeline.

Both code exercise formats — blank slate and completion — run through
:func:`review_code`.  There is no per-format branch: the only thing that varies
is how much starting code was supplied, and that is read off
:attr:`CodeExercise.starter_code`.

Three invariants this module exists to hold:

1. **Supplied code earns nothing.**  A criterion the starter code already
   satisfies is recorded ``given`` and excluded from the score.  Otherwise a
   completion exercise would score highly for a solution the learner never
   wrote.
2. **Improvements are asked, never told.**  Every entry in
   :attr:`ExerciseReview.mentoring` is a question, and :func:`scrub_leaks`
   removes any fragment that would hand back the reference solution.  This is
   what makes the pipeline Socratic rather than a diff viewer.
3. **A score is evidence.**  :func:`record_review` writes the derived
   confidence into ``study_progress`` so an exercise result feeds spaced
   repetition instead of evaporating.
"""

from __future__ import annotations

import logging
import re

from .models import (
    ChoiceResult,
    CodeExercise,
    CriterionResult,
    ExerciseReview,
    ExerciseSet,
    MultipleChoiceQuestion,
    QuizReview,
    band_for,
    substantive_lines,
)

logger = logging.getLogger(__name__)

#: A reference-solution line shorter than this is too generic to be a leak
#: (``return x``, ``import re``), and redacting it would mangle useful prose.
_LEAK_MIN_LEN = 14

#: Stand-in for a redacted leak. Question-shaped, so the mentoring list keeps
#: its contract even when a fragment had to be removed.
_REDACTED = "[redacted — work it out from the requirement above]"


def scrub_leaks(text: str, reference: str) -> str:
    """Remove reference-solution fragments from mentoring ``text``.

    The reference solution is stored on the exercise so an *author* can review
    it, and so a future automated grader can diff against it.  It must never
    reach the learner through the mentoring path — that would convert guided
    discovery into an answer key.

    Only substantive lines of at least :data:`_LEAK_MIN_LEN` characters are
    considered, so a shared ``return total`` does not trigger a redaction.
    """
    cleaned = text or ""
    if not reference:
        return cleaned
    for line in substantive_lines(reference):
        if len(line) < _LEAK_MIN_LEN:
            continue
        if line.lower() in cleaned.lower():
            cleaned = re.sub(re.escape(line), _REDACTED, cleaned, flags=re.IGNORECASE)
    return cleaned


def _as_question(text: str) -> str:
    """Force a mentoring string into question shape."""
    stripped = (text or "").strip()
    if not stripped:
        return "What does the requirement ask for that your solution does not yet do?"
    return stripped if stripped.endswith("?") else f"{stripped}?"


def authored_delta(submission: str, starter: str) -> list[str]:
    """Substantive submission lines that were *not* handed over in ``starter``.

    This is the learner's actual contribution.  A completion attempt that
    returns the scaffold unchanged has an empty delta, which the scorer treats
    as "nothing attempted" rather than "everything already correct".
    """
    supplied = set(substantive_lines(starter))
    return [line for line in substantive_lines(submission) if line not in supplied]


def review_code(
    exercise: CodeExercise,
    submission: str,
    *,
    set_id: str = "",
    topic: str = "",
) -> ExerciseReview:
    """Score ``submission`` against ``exercise`` and produce Socratic follow-ups.

    Used for both ``blank_slate`` and ``completion``.  The scaffold level is a
    parameter of the exercise, not a different code path.
    """
    submission = submission or ""
    starter = exercise.starter_code or ""
    delta = authored_delta(submission, starter)

    results: list[CriterionResult] = []
    warnings: list[str] = []

    for criterion in exercise.rubric:
        # An unverifiable criterion is neither passed nor failed. Scoring it as
        # met would give an empty stub full marks — which is exactly what this
        # branch exists to prevent.
        if not criterion.is_scoreable():
            results.append(
                CriterionResult(
                    title=criterion.title,
                    status="unscoreable",
                    weight=criterion.weight,
                    question=criterion.question(),
                )
            )
            continue
        # Order matters: an anti-pattern in the learner's own code outranks a
        # positive match, otherwise a solution can be "met" and wrong at once.
        if criterion.is_violated(submission) and not criterion.is_violated(starter):
            results.append(
                CriterionResult(
                    title=criterion.title,
                    status="violated",
                    weight=criterion.weight,
                    question=criterion.question(),
                )
            )
            continue
        # Supplied by the scaffold → given: no credit, no blame.
        if starter.strip() and criterion.check and criterion.is_met(starter):
            results.append(
                CriterionResult(
                    title=criterion.title,
                    status="given",
                    weight=criterion.weight,
                )
            )
            continue
        met = criterion.is_met(submission)
        results.append(
            CriterionResult(
                title=criterion.title,
                status="met" if met else "unmet",
                weight=criterion.weight,
                question="" if met else criterion.question(),
            )
        )

    assessable = sum(r.weight for r in results if r.assessable)
    earned = sum(r.earned for r in results)
    unscoreable = [r for r in results if r.status == "unscoreable"]

    if unscoreable:
        titles = ", ".join(r.title for r in unscoreable[:3])
        warnings.append(
            f"{len(unscoreable)} rubric criterion(s) have no verifiable check and "
            f"were excluded rather than passed automatically: {titles}"
        )

    if not exercise.rubric:
        score = 0
        warnings.append(
            "This exercise has no rubric, so the score is not meaningful — "
            "author rubric criteria before scoring an attempt."
        )
    elif assessable == 0:
        score = 0
        # Distinguish the two ways there can be nothing to assess, because the
        # fix differs: author a real check, versus hide more of the solution.
        if unscoreable and len(unscoreable) == len(results):
            warnings.append(
                "No rubric criterion could be verified, so this attempt was not "
                "scored. Add a `check` pattern to each criterion."
            )
        else:
            warnings.append(
                "Every rubric criterion was already satisfied by the supplied "
                "starter code, so there was nothing left to assess. The completion "
                "exercise needs a criterion the learner must add."
            )
    elif not delta:
        score = 0
        warnings.append(
            "The submission adds nothing beyond the starter code, so nothing could be credited."
        )
    else:
        score = round(100 * earned / assessable)

    band, confidence = band_for(score)

    strengths = [r.title for r in results if r.status == "met"]
    mentoring: list[str] = []
    if not submission.strip():
        mentoring.append(
            "You submitted nothing yet — which single requirement feels like "
            "the smallest place to start?"
        )
    elif not delta and starter.strip():
        mentoring.append(
            "This is the starter code unchanged — what is the first behaviour "
            "the requirements ask for that it does not do yet?"
        )
    for result in results:
        # `unscoreable` is included: the machine cannot verify it, but the
        # question still belongs in the conversation — asking the learner to
        # justify it is exactly the Socratic move, and better than pretending
        # the criterion passed.
        if result.status in {"unmet", "violated", "unscoreable"} and result.question:
            asked = scrub_leaks(result.question, exercise.reference_solution)
            mentoring.append(_as_question(asked))

    if not mentoring and score >= 90:
        mentoring.append(
            "Every criterion held — where would this break if the input were ten times larger?"
        )

    return ExerciseReview(
        set_id=set_id,
        kind=exercise.kind,
        topic=topic,
        score=score,
        band=band,
        confidence=confidence,
        criteria=results,
        mentoring=mentoring,
        strengths=strengths,
        warnings=warnings,
        authored_line_count=len(delta),
        scaffold_ratio=exercise.scaffold_ratio,
    )


def _quiz_follow_up(question: MultipleChoiceQuestion, selected: list[int]) -> tuple[str, list[str]]:
    """Return ``(socratic_question, misconceptions)`` for a wrong answer.

    The follow-up is built from the *chosen distractor's* recorded misconception
    so the question lands on the learner's actual reasoning error — and it never
    names the correct option.
    """
    misconceptions = [
        question.choices[i].why.strip()
        for i in selected
        if 0 <= i < len(question.choices)
        and not question.choices[i].correct
        and question.choices[i].why.strip()
    ]
    if question.ask.strip():
        return _as_question(question.ask), misconceptions
    if misconceptions:
        return (
            _as_question(
                f"You picked the option that assumes {misconceptions[0]} — what would "
                "have to be true about the code for that to hold"
            ),
            misconceptions,
        )
    return (
        _as_question(f"What does “{question.prompt.strip()}” depend on that you can verify"),
        misconceptions,
    )


def review_quiz(
    questions: list[MultipleChoiceQuestion],
    answers: dict[int, list[int]],
    *,
    set_id: str = "",
    topic: str = "",
) -> QuizReview:
    """Grade multiple-choice ``answers`` (question index → selected indexes).

    Correctness is exact-set: a multi-select question is only right when every
    correct option is chosen and no distractor is.  Partial credit would let a
    learner shotgun every box and read it as understanding.
    """
    answerable = [(i, q) for i, q in enumerate(questions) if q.is_answerable()]
    warnings: list[str] = []
    skipped = len(questions) - len(answerable)
    if skipped:
        warnings.append(f"{skipped} question(s) were skipped: they have no correct answer marked.")

    results: list[ChoiceResult] = []
    mentoring: list[str] = []
    correct_count = 0

    for index, question in answerable:
        picked = answers.get(index, [])
        selected = sorted({int(i) for i in picked if 0 <= int(i) < len(question.choices)})
        expected = sorted(question.correct_indexes)
        is_correct = selected == expected
        if is_correct:
            correct_count += 1
            follow_up, misconceptions = "", []
        else:
            follow_up, misconceptions = _quiz_follow_up(question, selected)
            mentoring.append(follow_up)
        results.append(
            ChoiceResult(
                prompt=question.prompt,
                selected=selected,
                correct=expected,
                is_correct=is_correct,
                question=follow_up,
                misconceptions=misconceptions,
            )
        )

    total = len(answerable)
    score = round(100 * correct_count / total) if total else 0
    if not total:
        warnings.append("No answerable questions, so the score is not meaningful.")
    band, confidence = band_for(score)

    if not mentoring and total and correct_count == total:
        mentoring.append(
            "All correct — which of these would you struggle to explain to "
            "someone else without looking it up?"
        )

    return QuizReview(
        set_id=set_id,
        topic=topic,
        score=score,
        band=band,
        confidence=confidence,
        total=total,
        correct_count=correct_count,
        results=results,
        mentoring=mentoring,
        warnings=warnings,
    )


def review_submission(
    exercise_set: ExerciseSet,
    kind: str,
    *,
    submission: str = "",
    answers: dict[int, list[int]] | None = None,
) -> ExerciseReview | QuizReview:
    """Single entry point for all three formats.

    Dispatches on ``kind`` but keeps one contract: score, band, confidence,
    mentoring questions, warnings, and an agent-pasteable Markdown block.
    """
    if kind == "multiple_choice":
        return review_quiz(
            exercise_set.multiple_choice,
            answers or {},
            set_id=exercise_set.set_id,
            topic=exercise_set.topic,
        )
    exercise = exercise_set.code_exercise(kind)
    if exercise is None:
        msg = f"exercise set {exercise_set.set_id!r} has no {kind!r} exercise"
        raise LookupError(msg)
    return review_code(
        exercise,
        submission,
        set_id=exercise_set.set_id,
        topic=exercise_set.topic,
    )


def record_review(
    review: ExerciseReview | QuizReview,
    *,
    concepts: list[str] | None = None,
) -> bool:
    """Write the review's confidence signal into ``study_progress``.

    A score with no consequence is a score nobody acts on.  Recording it means a
    weak exercise result surfaces in ``studyloop review`` and ``studyloop now``
    without the learner having to remember to log it.

    Failures are swallowed (and logged): the review itself is still valid and
    must be shown even when the DB is unavailable.
    """
    targets = [c.strip() for c in (concepts or []) if c.strip()] or [review.topic]
    topic = (review.topic or "general").strip().lower()
    if not topic:
        return False
    try:
        from studyloop.history.progress import record_progress
    except Exception:  # pragma: no cover - import guard for slim installs
        logger.debug("progress recording unavailable", exc_info=True)
        return False

    note = f"exercise:{review.kind} score={review.score} band={review.band}"
    ok = False
    for concept in targets:
        try:
            ok = bool(record_progress(topic, concept, review.confidence, note)) or ok
        except Exception:
            logger.debug("record_progress failed for %s/%s", topic, concept, exc_info=True)
    return ok
