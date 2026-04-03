"""Study progress tracking: record, query, and spaced repetition scheduling."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime

from . import _connection, search


def last_studied(topic_keywords: list[str]) -> str | None:
    """When was a topic last discussed? Returns ISO timestamp or None."""
    results = search.topic_frequency(topic_keywords, days=365)
    return results[0]["timestamp"] if results else None


def spaced_repetition_due(topic_keywords_map: dict[str, list[str]]) -> list[dict]:
    """Check which topics are due for spaced review.

    Args:
        topic_keywords_map: {"python": ["python", "pattern", "dataclass"], ...}

    Returns:
        List of {topic, last_studied, days_ago, review_type}
    """
    due = []
    now = datetime.now(UTC)
    intervals = [
        (1, "5-min recall quiz"),
        (3, "10-min Socratic review"),
        (7, "15-min deep review"),
        (14, "Apply to new problem"),
        (30, "Teach-back session"),
    ]

    for topic, keywords in topic_keywords_map.items():
        last = last_studied(keywords)
        if not last:
            due.append(
                {
                    "topic": topic,
                    "last_studied": None,
                    "days_ago": None,
                    "review_type": "New topic -- start fresh",
                }
            )
            continue

        try:
            last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue

        days_ago = (now - last_dt).days
        review_type = None
        for interval, rtype in intervals:
            if days_ago >= interval:
                review_type = rtype

        if review_type:
            due.append(
                {
                    "topic": topic,
                    "last_studied": last[:10],
                    "days_ago": days_ago,
                    "review_type": review_type,
                }
            )

    return sorted(due, key=lambda x: x.get("days_ago") or 999, reverse=True)


def record_progress(
    topic: str,
    concept: str,
    confidence: str,
    notes: str | None = None,
) -> bool:
    """Record or update progress on a concept."""
    conn = _connection._connect()
    if not conn:
        return False
    try:
        # Normalise to avoid case-sensitive duplicates (e.g. "Python" vs "python")
        topic = topic.lower().strip()
        concept = concept.lower().strip()
        now = datetime.now(UTC).isoformat()
        progress_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{topic}:{concept}"))
        conn.execute(
            """
            INSERT INTO study_progress
                (id, topic, concept, confidence, first_seen, last_seen, session_count, notes)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(id) DO UPDATE SET
                confidence = excluded.confidence,
                last_seen = excluded.last_seen,
                session_count = session_count + 1,
                notes = COALESCE(excluded.notes, notes),
                updated_at = datetime('now')
            """,
            (progress_id, topic, concept, confidence, now, now, notes),
        )
        conn.commit()
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


def get_wins(days: int = 30) -> list[dict]:
    """Find concepts that improved in confidence over the given period."""
    conn = _connection._connect()
    if not conn:
        return []
    try:
        rows = conn.execute(
            """
            SELECT topic, concept, confidence, first_seen, last_seen, session_count
            FROM study_progress
            WHERE confidence IN ('confident', 'mastered')
              AND last_seen > datetime('now', ?)
            ORDER BY last_seen DESC
            """,
            (f"-{days} days",),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def get_progress_for_map() -> list[dict]:
    """Get all study progress entries for rendering a progress map.

    Returns list of {topic, concept, confidence, session_count, first_seen, last_seen}.
    """
    conn = _connection._connect()
    if not conn:
        return []
    try:
        rows = conn.execute(
            """
            SELECT topic, concept, confidence, session_count, first_seen, last_seen
            FROM study_progress
            ORDER BY topic, confidence DESC, concept
            """
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def get_progress_summary() -> dict:
    """Get overall progress summary across all concepts."""
    conn = _connection._connect()
    if not conn:
        return {}
    try:
        rows = conn.execute(
            "SELECT confidence, COUNT(*) as count FROM study_progress GROUP BY confidence"
        ).fetchall()
        summary = {r["confidence"]: r["count"] for r in rows}
        summary["total"] = sum(summary.values())
        return summary
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()
