"""Spaced repetition tracking for flashcard and quiz reviews.

Stores per-card review results in the sessions.db SQLite database.
Uses a simplified SM-2 algorithm for scheduling next reviews.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .settings import get_db_path

# SM-2 simplified intervals: correct → double interval, wrong → reset to 1
MIN_EASE = 1.3
DEFAULT_EASE = 2.5


def _get_db() -> Path:
    """Get sessions.db path from studyctl config."""
    try:
        return get_db_path()
    except Exception:
        return Path.home() / ".config" / "studyctl" / "sessions.db"


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with WAL mode and busy timeout."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def ensure_tables(db_path: Path | None = None) -> None:
    """Create card_reviews and review_sessions tables if they don't exist."""
    path = db_path or _get_db()
    if not path.exists():
        return

    with _connect(path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS card_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course TEXT NOT NULL,
                card_type TEXT NOT NULL,
                card_hash TEXT NOT NULL,
                correct BOOLEAN NOT NULL,
                reviewed_at TEXT NOT NULL,
                ease_factor REAL DEFAULT 2.5,
                interval_days INTEGER DEFAULT 1,
                next_review TEXT,
                response_time_ms INTEGER
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_card_reviews_next
            ON card_reviews(course, next_review)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_card_reviews_hash
            ON card_reviews(card_hash)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS review_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course TEXT NOT NULL,
                mode TEXT NOT NULL,
                total INTEGER NOT NULL,
                correct INTEGER NOT NULL,
                duration_seconds INTEGER,
                started_at TEXT NOT NULL,
                finished_at TEXT
            )
        """)


def record_card_review(
    course: str,
    card_type: str,
    card_hash: str,
    correct: bool,
    response_time_ms: int | None = None,
    db_path: Path | None = None,
) -> None:
    """Record a single card review and update spaced repetition schedule."""
    path = db_path or _get_db()
    ensure_tables(path)

    with _connect(path) as conn:
        now = datetime.now(UTC).isoformat()

        # Get previous review for this card
        row = conn.execute(
            "SELECT ease_factor, interval_days FROM card_reviews "
            "WHERE card_hash = ? ORDER BY reviewed_at DESC LIMIT 1",
            (card_hash,),
        ).fetchone()

        if row:
            ease, interval = row
        else:
            ease, interval = DEFAULT_EASE, 1

        # SM-2 simplified update (interval capped at 365 days)
        if correct:
            interval = min(max(1, int(interval * ease)), 365)
            ease = min(ease + 0.1, 3.0)
        else:
            interval = 1
            ease = max(ease - 0.2, MIN_EASE)

        next_review = (datetime.now(UTC) + timedelta(days=interval)).strftime("%Y-%m-%d")

        conn.execute(
            "INSERT INTO card_reviews "
            "(course, card_type, card_hash, correct, reviewed_at, "
            "ease_factor, interval_days, next_review, response_time_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                course,
                card_type,
                card_hash,
                correct,
                now,
                ease,
                interval,
                next_review,
                response_time_ms,
            ),
        )


def record_session(
    course: str,
    mode: str,
    total: int,
    correct: int,
    duration_seconds: int | None = None,
    db_path: Path | None = None,
) -> None:
    """Record a complete review session."""
    path = db_path or _get_db()
    ensure_tables(path)

    with _connect(path) as conn:
        now = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT INTO review_sessions "
            "(course, mode, total, correct, duration_seconds, started_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (course, mode, total, correct, duration_seconds, now, now),
        )


@dataclass
class CardProgress:
    card_hash: str
    last_correct: bool
    ease_factor: float
    interval_days: int
    next_review: str
    review_count: int


def get_due_cards(course: str, db_path: Path | None = None) -> list[CardProgress]:
    """Get cards due for review (next_review <= today)."""
    path = db_path or _get_db()
    if not path.exists():
        return []

    ensure_tables(path)
    with _connect(path) as conn:
        today = datetime.now(UTC).strftime("%Y-%m-%d")

        rows = conn.execute(
            """
            WITH latest AS (
                SELECT card_hash, correct, ease_factor, interval_days, next_review,
                       COUNT(*) OVER (PARTITION BY card_hash) as review_count,
                       ROW_NUMBER() OVER (PARTITION BY card_hash ORDER BY reviewed_at DESC) as rn
                FROM card_reviews
                WHERE course = ?
            )
            SELECT card_hash, correct, ease_factor, interval_days, next_review, review_count
            FROM latest
            WHERE rn = 1 AND next_review <= ?
            ORDER BY next_review ASC
            """,
            (course, today),
        ).fetchall()

    return [
        CardProgress(
            card_hash=r[0],
            last_correct=bool(r[1]),
            ease_factor=r[2],
            interval_days=r[3],
            next_review=r[4],
            review_count=r[5],
        )
        for r in rows
    ]


def get_wrong_hashes(course: str, db_path: Path | None = None) -> set[str]:
    """Get card hashes that were incorrect in the most recent session."""
    path = db_path or _get_db()
    if not path.exists():
        return set()

    ensure_tables(path)
    with _connect(path) as conn:
        # Find the most recent session's reviewed_at range
        last_session = conn.execute(
            "SELECT started_at FROM review_sessions "
            "WHERE course = ? ORDER BY started_at DESC LIMIT 1",
            (course,),
        ).fetchone()

        if not last_session:
            return set()

        rows = conn.execute(
            "SELECT DISTINCT card_hash FROM card_reviews "
            "WHERE course = ? AND correct = 0 AND reviewed_at >= ?",
            (course, last_session[0]),
        ).fetchall()

    return {r[0] for r in rows}


def get_course_stats(course: str, db_path: Path | None = None) -> dict:
    """Get summary statistics for a course."""
    path = db_path or _get_db()
    if not path.exists():
        return {"total_reviews": 0, "unique_cards": 0, "due_today": 0, "mastered": 0}

    ensure_tables(path)
    with _connect(path) as conn:
        today = datetime.now(UTC).strftime("%Y-%m-%d")

        total = conn.execute(
            "SELECT COUNT(*) FROM card_reviews WHERE course = ?", (course,)
        ).fetchone()[0]

        unique = conn.execute(
            "SELECT COUNT(DISTINCT card_hash) FROM card_reviews WHERE course = ?", (course,)
        ).fetchone()[0]

        due = conn.execute(
            "SELECT COUNT(DISTINCT card_hash) FROM card_reviews "
            "WHERE course = ? AND next_review <= ?",
            (course, today),
        ).fetchone()[0]

        # Mastered = interval > 30 days
        mastered = conn.execute(
            """
            SELECT COUNT(DISTINCT card_hash) FROM card_reviews cr1
            WHERE course = ? AND interval_days > 30
            AND reviewed_at = (
                SELECT MAX(reviewed_at) FROM card_reviews cr2
                WHERE cr2.card_hash = cr1.card_hash
            )
            """,
            (course,),
        ).fetchone()[0]

    return {
        "total_reviews": total,
        "unique_cards": unique,
        "due_today": due,
        "mastered": mastered,
    }
