"""Card API routes — load cards/quizzes, record reviews."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from studyctl.review_loader import discover_directories
from studyctl.services.review import get_cards, record_review

router = APIRouter()


class ReviewRequest(BaseModel):
    """POST /api/review request body."""

    course: str
    card_hash: str
    correct: bool
    card_type: str = "flashcard"
    response_time_ms: int | None = None


@router.get("/cards/{course}")
def get_course_cards(request: Request, course: str, mode: str = "flashcards") -> list[dict]:
    """Load flashcards or quiz questions for a course."""
    courses = discover_directories(request.app.state.study_dirs)
    match = next(((n, p) for n, p in courses if n == course), None)
    if not match:
        raise HTTPException(status_code=404, detail=f"Course '{course}' not found")

    _, path = match
    flashcards, quizzes = get_cards(course, path)

    if mode == "flashcards" and flashcards:
        return [
            {
                "type": "flashcard",
                "front": c.front,
                "back": c.back,
                "hash": c.card_hash,
                "source": c.source,
            }
            for c in flashcards
        ]
    if mode == "quiz" and quizzes:
        return [
            {
                "type": "quiz",
                "question": q.question,
                "options": [
                    {
                        "text": o.text,
                        "is_correct": o.is_correct,
                        "rationale": o.rationale,
                    }
                    for o in q.options
                ],
                "hint": q.hint,
                "hash": q.card_hash,
                "source": q.source,
            }
            for q in quizzes
        ]

    raise HTTPException(status_code=404, detail=f"No {mode} content for {course}")


@router.post("/review")
def post_review(body: ReviewRequest) -> dict:
    """Record a single card review result."""
    record_review(
        course=body.course,
        card_type=body.card_type,
        card_hash=body.card_hash,
        correct=body.correct,
        response_time_ms=body.response_time_ms,
    )
    return {"ok": True}
