"""The three topic exercise formats, and the pipeline that reviews them.

Every generated topic carries exercises in three shapes:

1. **Blank slate** — requirements only; the learner writes the whole solution.
2. **Completion** — requirements plus a partial solution to finish.
3. **Multiple choice** — questions authored in Markdown form.

The two code formats are one feature, not two: they share
:func:`review_code`, and differ only in how much starting code is supplied
(:attr:`CodeExercise.starter_code`).  Criteria the starter code already
satisfies are recorded ``given`` and excluded from the score, so a completion
attempt is never credited with code the learner did not write.

Improvements are always surfaced as questions — see
:func:`studyloop.planning.exercises.review.scrub_leaks`, which removes any
reference-solution fragment from the mentoring path.
"""

from __future__ import annotations

from .authoring import (
    DEFAULT_REVEAL,
    derive_completion,
    draft_exercise_set,
    from_milestone,
    readiness,
)
from .markdown import (
    parse_criterion,
    parse_exercise_set,
    redacted_copy,
    render_criterion,
    render_exercise_set,
    render_for_learner,
    render_question,
)
from .models import (
    CODE_KINDS,
    CONFIDENCE_LEVELS,
    CRITERION_STATUSES,
    EXERCISE_KINDS,
    SCORE_BANDS,
    Choice,
    ChoiceResult,
    CodeExercise,
    Criterion,
    CriterionResult,
    ExerciseReview,
    ExerciseSet,
    MultipleChoiceQuestion,
    QuizReview,
    band_for,
    substantive_lines,
)
from .review import (
    authored_delta,
    record_review,
    review_code,
    review_quiz,
    review_submission,
    scrub_leaks,
)
from .store import (
    EXERCISES_DIR_ENV,
    ExerciseSetExistsError,
    ExerciseSetNotFoundError,
    InvalidSetIdError,
    create_set,
    delete_set,
    exercises_dir,
    list_set_ids,
    list_sets,
    load_set,
    load_set_text,
    save_set,
    set_path,
    unique_set_id,
)

__all__ = [
    "CODE_KINDS",
    "CONFIDENCE_LEVELS",
    "CRITERION_STATUSES",
    "DEFAULT_REVEAL",
    "EXERCISES_DIR_ENV",
    "EXERCISE_KINDS",
    "SCORE_BANDS",
    "Choice",
    "ChoiceResult",
    "CodeExercise",
    "Criterion",
    "CriterionResult",
    "ExerciseReview",
    "ExerciseSet",
    "ExerciseSetExistsError",
    "ExerciseSetNotFoundError",
    "InvalidSetIdError",
    "MultipleChoiceQuestion",
    "QuizReview",
    "authored_delta",
    "band_for",
    "create_set",
    "delete_set",
    "derive_completion",
    "draft_exercise_set",
    "exercises_dir",
    "from_milestone",
    "list_set_ids",
    "list_sets",
    "load_set",
    "load_set_text",
    "parse_criterion",
    "parse_exercise_set",
    "readiness",
    "record_review",
    "redacted_copy",
    "render_criterion",
    "render_exercise_set",
    "render_for_learner",
    "render_question",
    "review_code",
    "review_quiz",
    "review_submission",
    "save_set",
    "scrub_leaks",
    "set_path",
    "substantive_lines",
    "unique_set_id",
]
