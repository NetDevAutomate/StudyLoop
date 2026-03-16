"""History API routes — review sessions and session recording."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter
from pydantic import BaseModel

from studyctl.review_db import ensure_tables, record_session
from studyctl.settings import get_db_path

router = APIRouter()


class SessionRequest(BaseModel):
    """POST /api/session request body."""

    course: str
    mode: str = "flashcards"
    total: int
    correct: int
    duration_seconds: int | None = None


@router.get("/history")
def get_history() -> list[dict]:
    """Return recent review sessions for the history view."""
    db_path = get_db_path()
    if not db_path.exists():
        return []

    ensure_tables(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        rows = conn.execute(
            "SELECT course, mode, total, correct, duration_seconds, "
            "started_at, finished_at "
            "FROM review_sessions ORDER BY started_at DESC LIMIT 20"
        ).fetchall()
    finally:
        conn.close()

    return [
        {
            "course": r[0],
            "mode": r[1],
            "total": r[2],
            "correct": r[3],
            "duration": r[4],
            "date": r[5][:10] if r[5] else None,
        }
        for r in rows
    ]


@router.post("/session")
def post_session(body: SessionRequest) -> dict:
    """Record a complete review session."""
    record_session(
        course=body.course,
        mode=body.mode,
        total=body.total,
        correct=body.correct,
        duration_seconds=body.duration_seconds,
    )
    return {"ok": True}
