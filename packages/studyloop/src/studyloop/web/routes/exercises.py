"""Exercise API routes — the three topic formats and their review pipeline.

Read paths serve both the parsed structure (for the interactive attempt UI) and
the raw Markdown (rendered through the same ``marked → DOMPurify → hljs`` pipeline
the Course Explorer and plan reader use).

The submit path is deliberately one endpoint for all three formats:
``POST /api/exercises/{set_id}/review`` with a ``kind``.  That mirrors the
domain — one review-and-score-then-mentor pipeline, parameterised by how much
starting code was supplied — rather than growing a second endpoint per format.

The reference solution is never returned to the client by the attempt or review
paths. It is available only on the explicit ``?include_reference=true`` read, so
the browser cannot accidentally hand the learner the answer while they work.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import PlainTextResponse

from studyloop.planning.exercises import (
    CODE_KINDS,
    EXERCISE_KINDS,
    Criterion,
    ExerciseSet,
    create_set,
    draft_exercise_set,
    from_milestone,
    list_sets,
    load_set,
    parse_exercise_set,
    readiness,
    record_review,
    render_exercise_set,
    render_for_learner,
    review_submission,
    save_set,
    unique_set_id,
)
from studyloop.planning.exercises.models import Choice, MultipleChoiceQuestion
from studyloop.planning.exercises.store import (
    ExerciseSetExistsError,
    ExerciseSetNotFoundError,
    InvalidSetIdError,
    delete_set,
)

logger = logging.getLogger(__name__)

router = APIRouter()

#: A replacement document must carry at least one of these headings. Cheap
#: sanity check against a caller PATCHing an unrelated body over a real set.
_REQUIRED_SECTION_HINTS = ("blank slate", "completion", "multiple choice")


def _load_or_404(set_id: str) -> ExerciseSet:
    try:
        return load_set(set_id)
    except ExerciseSetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidSetIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _code_payload(exercise, *, include_reference: bool) -> dict | None:
    """Serialise a code exercise for the attempt UI.

    ``reference_solution`` is withheld unless explicitly requested: the point of
    a blank-slate exercise evaporates if the answer ships with the requirements.
    """
    if exercise is None:
        return None
    payload = {
        "kind": exercise.kind,
        "title": exercise.title,
        "language": exercise.language,
        "requirements": list(exercise.requirements),
        "starter_code": exercise.starter_code,
        "scaffold_ratio": exercise.scaffold_ratio,
        "total_weight": exercise.total_weight,
        "ready": exercise.is_ready(),
        # Titles and weights only — a `check` regex is a partial answer key.
        "rubric": [{"title": c.title, "weight": c.weight} for c in exercise.rubric],
    }
    if include_reference:
        payload["reference_solution"] = exercise.reference_solution
    return payload


def _questions_payload(
    questions: list[MultipleChoiceQuestion],
    *,
    include_answers: bool,
) -> list[dict]:
    """Serialise multiple-choice questions, withholding which option is correct."""
    out = []
    for index, question in enumerate(questions):
        item: dict = {
            "index": index,
            "prompt": question.prompt,
            "multi_select": question.is_multi_select,
            "answerable": question.is_answerable(),
            "choices": [
                {"index": i, "label": question.label(i), "text": choice.text}
                for i, choice in enumerate(question.choices)
            ],
        }
        if include_answers:
            item["correct"] = question.correct_indexes
            item["ask"] = question.ask
            for i, choice in enumerate(question.choices):
                item["choices"][i]["correct"] = choice.correct
                item["choices"][i]["why"] = choice.why
        out.append(item)
    return out


def _require_markdown(value) -> str:
    """Validate a Markdown payload before it can replace a document.

    Two guards, both learned from the same failure mode: a non-string body
    (``None``, a number) stringifies into something the tolerant parser happily
    reads as an *empty* exercise set, which would silently wipe a real document
    on PATCH. And a string with none of the known section headings is almost
    certainly the wrong body, so it is rejected rather than persisted as a set
    with all three formats missing.
    """
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=400, detail="markdown must be a non-empty string")
    lowered = value.lower()
    if not any(f"## {section}" in lowered for section in _REQUIRED_SECTION_HINTS):
        raise HTTPException(
            status_code=400,
            detail=(
                "markdown has none of the expected sections "
                f"({', '.join(_REQUIRED_SECTION_HINTS)}) — refusing to replace a "
                "document with an empty one"
            ),
        )
    return value


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


@router.get("/exercises")
def get_exercise_sets(
    plan_id: str = Query("", max_length=160),
    topic: str = Query("", max_length=200),
) -> dict:
    """List exercise sets, optionally scoped to a plan and/or topic."""
    sets = list_sets(plan_id=plan_id.strip(), topic=topic.strip())
    return {
        "sets": [item.summary() for item in sets],
        "count": len(sets),
        "kinds": list(EXERCISE_KINDS),
    }


@router.get("/exercises/{set_id}")
def get_exercise_set(
    set_id: str,
    include_reference: bool = Query(False),
) -> dict:
    """One exercise set: all three formats, plus readiness.

    Correct answers and reference solutions are withheld by default so the
    attempt UI physically cannot show them.
    """
    item = _load_or_404(set_id)
    return {
        "set": item.summary(),
        # The authored document contains the reference solution and the marked
        # correct choices, so the learner-facing view is a redacted render.
        # Asserted at the network boundary by the E2E journey (phase 11).
        "markdown": render_exercise_set(item) if include_reference else render_for_learner(item),
        "blank_slate": _code_payload(item.blank_slate, include_reference=include_reference),
        "completion": _code_payload(item.completion, include_reference=include_reference),
        "multiple_choice": _questions_payload(
            item.multiple_choice, include_answers=include_reference
        ),
        "readiness": readiness(item),
    }


@router.get("/exercises/{set_id}/markdown", response_class=PlainTextResponse)
def get_exercise_markdown(
    set_id: str,
    include_reference: bool = Query(False),
) -> str:
    """The exercise document as Markdown — redacted unless answers are requested.

    Default is the learner-safe render so the "view raw Markdown" link in the UI
    (and a copy-to-agent paste) cannot hand over the answer key by accident.
    Authors and grading agents pass ``include_reference=true``.
    """
    item = _load_or_404(set_id)
    return render_exercise_set(item) if include_reference else render_for_learner(item)


# ---------------------------------------------------------------------------
# Review — one endpoint, all three formats
# ---------------------------------------------------------------------------


@router.post("/exercises/{set_id}/review", status_code=200)
def post_review(set_id: str, payload: Annotated[dict, Body()]) -> dict:
    """Score an attempt and return Socratic follow-up questions.

    ``kind`` selects the format; ``submission`` carries code for the two code
    formats, ``answers`` carries ``{question_index: [choice_index, …]}`` for
    multiple choice.  Set ``record`` to write the derived confidence into
    ``study_progress`` so a weak result surfaces in spaced repetition.
    """
    item = _load_or_404(set_id)
    kind = str(payload.get("kind", "")).strip()
    if kind not in EXERCISE_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {EXERCISE_KINDS}")

    answers: dict[int, list[int]] = {}
    if kind == "multiple_choice":
        raw = payload.get("answers") or {}
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="answers must be an object")
        for key, value in raw.items():
            try:
                index = int(key)
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=400, detail=f"answer key {key!r} is not a question index"
                ) from exc
            selected = value if isinstance(value, list) else [value]
            try:
                answers[index] = [int(v) for v in selected]
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=400, detail=f"answers[{index}] must be choice indexes"
                ) from exc

    try:
        review = review_submission(
            item,
            kind,
            submission=str(payload.get("submission", "")),
            answers=answers,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    recorded = False
    if payload.get("record"):
        recorded = record_review(review, concepts=item.concepts)

    return {
        "review": review.to_dict(),
        "markdown": review.as_markdown(),
        "recorded": recorded,
    }


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def _criteria_from_payload(items) -> list[Criterion]:
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="rubric must be a list")
    return [
        Criterion(
            title=str(entry.get("title", "")).strip() or "Unnamed criterion",
            weight=int(entry.get("weight", 1) or 1),
            check=str(entry.get("check", "")).strip(),
            forbid=str(entry.get("forbid", "")).strip(),
            ask=str(entry.get("ask", "")).strip(),
        )
        for entry in items
        if isinstance(entry, dict)
    ]


def _questions_from_payload(items) -> list[MultipleChoiceQuestion]:
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="questions must be a list")
    out: list[MultipleChoiceQuestion] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        choices = [
            Choice(
                text=str(choice.get("text", "")).strip(),
                correct=bool(choice.get("correct", False)),
                why=str(choice.get("why", "")).strip(),
            )
            for choice in (entry.get("choices") or [])
            if isinstance(choice, dict) and str(choice.get("text", "")).strip()
        ]
        out.append(
            MultipleChoiceQuestion(
                prompt=str(entry.get("prompt", "")).strip(),
                choices=choices,
                ask=str(entry.get("ask", "")).strip(),
            )
        )
    return out


@router.post("/exercises", status_code=201)
def post_exercise_set(payload: Annotated[dict, Body()]) -> dict:
    """Create an exercise set.

    Three input shapes, all landing on the same document:

    * ``{"markdown": "..."}`` — import a hand-authored document (validated by
      re-parsing).
    * ``{"plan_id", "milestone", "concepts"}`` — draft from a plan milestone.
    * ``{"topic", "requirements", "rubric", "reference_solution", "questions"}``
      — draft from an explicit task; the completion format is derived from the
      blank slate rather than authored twice.
    """
    raw_markdown = payload.get("markdown")
    if raw_markdown is not None:
        document = _require_markdown(raw_markdown)
        try:
            item = parse_exercise_set(document)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"unparseable markdown: {exc}") from exc
        if not item.set_id:
            item.set_id = unique_set_id(item.plan_id, item.topic)
    elif payload.get("milestone"):
        plan_id = str(payload.get("plan_id", "")).strip()
        concepts = [str(c).strip() for c in (payload.get("concepts") or []) if str(c).strip()]
        item = from_milestone(plan_id, str(payload["milestone"]).strip(), concepts)
        item.set_id = unique_set_id(plan_id, item.topic)
    else:
        topic = str(payload.get("topic", "")).strip()
        if not topic:
            raise HTTPException(status_code=400, detail="topic is required")
        plan_id = str(payload.get("plan_id", "")).strip()
        try:
            item = draft_exercise_set(
                topic,
                plan_id=plan_id,
                set_id=unique_set_id(plan_id, topic),
                concepts=[
                    str(c).strip() for c in (payload.get("concepts") or []) if str(c).strip()
                ],
                requirements=[
                    str(r).strip() for r in (payload.get("requirements") or []) if str(r).strip()
                ],
                rubric=_criteria_from_payload(payload.get("rubric") or []) or None,
                reference_solution=str(payload.get("reference_solution", "")),
                language=str(payload.get("language", "python")).strip() or "python",
                questions=_questions_from_payload(payload.get("questions") or []),
                reveal=float(payload.get("reveal", 0.4) or 0.4),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        create_set(item, overwrite=bool(payload.get("overwrite", False)))
    except ExerciseSetExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidSetIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"created": True, "set": item.summary(), "readiness": readiness(item)}


def _refuse_redacted_overwrite(current: ExerciseSet, replacement: ExerciseSet) -> None:
    """Refuse a PATCH that would silently delete the answer key.

    ``GET /markdown`` now returns the *redacted* document by default. The
    obvious author workflow — fetch, edit, PATCH back — would therefore strip
    every reference solution and unmark every correct choice, without a single
    error. That is unrecoverable data loss disguised as a successful save, so it
    is refused unless the caller opts in explicitly.
    """
    losses: list[str] = []
    for kind in CODE_KINDS:
        before = current.code_exercise(kind)
        after = replacement.code_exercise(kind)
        if before and before.reference_solution and (not after or not after.reference_solution):
            losses.append(f"the {kind.replace('_', ' ')} reference solution")
    had_answers = any(q.correct_indexes for q in current.multiple_choice)
    has_answers = any(q.correct_indexes for q in replacement.multiple_choice)
    if had_answers and not has_answers:
        losses.append("every marked multiple-choice answer")

    if losses:
        raise HTTPException(
            status_code=409,
            detail=(
                f"this replacement would remove {', and '.join(losses)}. That is what "
                "the redacted GET /markdown returns — fetch it with "
                "?include_reference=true to edit the authored document, or pass "
                '"allow_answer_loss": true if the removal is intended.'
            ),
        )


@router.patch("/exercises/{set_id}")
def patch_exercise_set(set_id: str, payload: Annotated[dict, Body()]) -> dict:
    """Update a set. Accepts ``markdown`` (whole document), ``notes``, ``concepts``."""
    item = _load_or_404(set_id)

    if "markdown" in payload:
        document = _require_markdown(payload["markdown"])
        try:
            replacement = parse_exercise_set(document, set_id=item.set_id)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"unparseable markdown: {exc}") from exc
        replacement.set_id = item.set_id
        replacement.created = item.created
        if not payload.get("allow_answer_loss"):
            _refuse_redacted_overwrite(item, replacement)
        save_set(replacement)
        return {
            "updated": True,
            "set": replacement.summary(),
            "readiness": readiness(replacement),
        }

    if "notes" in payload:
        item.notes = str(payload["notes"])
    if "concepts" in payload:
        item.concepts = [str(c).strip() for c in payload["concepts"] if str(c).strip()]
    if "questions" in payload:
        item.multiple_choice = _questions_from_payload(payload["questions"])
    for kind in CODE_KINDS:
        if kind in payload and isinstance(payload[kind], dict):
            exercise = item.code_exercise(kind)
            if exercise is None:
                continue
            block = payload[kind]
            if "requirements" in block:
                exercise.requirements = [
                    str(r).strip() for r in block["requirements"] if str(r).strip()
                ]
            if "rubric" in block:
                exercise.rubric = _criteria_from_payload(block["rubric"])
            if "reference_solution" in block:
                exercise.reference_solution = str(block["reference_solution"])

    save_set(item)
    return {"updated": True, "set": item.summary(), "readiness": readiness(item)}


@router.delete("/exercises/{set_id}")
def remove_exercise_set(set_id: str) -> dict:
    """Delete an exercise set document."""
    try:
        deleted = delete_set(set_id)
    except InvalidSetIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"no exercise set with id {set_id!r}")
    return {"deleted": True, "set_id": set_id}
