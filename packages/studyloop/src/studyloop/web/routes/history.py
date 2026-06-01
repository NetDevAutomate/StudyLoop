"""History API routes — review sessions and session recording."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Query
from pydantic import BaseModel

from studyloop.history.progress import get_struggling_topics, record_progress
from studyloop.review_db import ensure_tables, record_session
from studyloop.settings import get_db_path

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


class StruggleRequest(BaseModel):
    """POST /api/history/struggling-topics request body."""

    course: str
    section: str
    publisher: str | None = None
    note: str | None = None


@router.post("/history/struggling-topics")
def post_struggling_topic(body: StruggleRequest) -> dict:
    """Flag a lesson section as a struggle topic.

    Writes a study_progress row with confidence='struggling' and full
    course/section provenance so the row surfaces in GET struggling-topics
    and drives deck generation without any extra plumbing.
    """
    ok = record_progress(
        topic=body.course,
        concept=body.section,
        confidence="struggling",
        notes=body.note,
        source_course=body.course,
        source_section=body.section,
        source_publisher=body.publisher,
        created_by="web",
    )
    return {"ok": ok}


@router.get("/history/struggling-topics")
def struggling_topics(days: int = Query(14, ge=1, le=90)) -> list[dict]:
    """Return distinct topics flagged 'struggling' in the lookback window.

    Drives the WebUI's topic-from-struggles dropdown when scope
    selection is "topic_struggles". Bounded 1..90 days at validation
    time so a stray ``?days=0`` or ``?days=99999`` is rejected with
    422 before the helper runs.
    """
    return get_struggling_topics(days=days)
