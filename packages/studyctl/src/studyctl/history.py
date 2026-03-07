"""Query session history for study mentor intelligence."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .settings import load_settings


def _get_study_terms() -> list[str]:
    """Build study terms from configured topics, falling back to defaults."""
    try:
        from .config import get_topics

        topics = get_topics()
        if topics:
            terms: set[str] = set()
            for t in topics:
                terms.add(t.name.lower())
                terms.update(tag.lower() for tag in t.tags)
            return sorted(terms)
    except Exception:
        pass
    # Fallback defaults
    return [
        "spark",
        "glue",
        "athena",
        "redshift",
        "sql",
        "python",
        "pattern",
        "strategy",
        "bridge",
        "template",
        "factory",
        "pipeline",
        "etl",
        "partition",
        "dag",
        "airflow",
        "dbt",
        "dataclass",
        "protocol",
        "abc",
        "decorator",
        "generator",
        "async",
        "type hint",
        "testing",
        "pytest",
        "sagemaker",
        "lake formation",
        "iceberg",
        "delta",
    ]


def _find_db() -> Path | None:
    candidates = [
        load_settings().session_db,
        Path.home() / ".local" / "share" / "agent-session-tools" / "sessions.db",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _connect() -> sqlite3.Connection | None:
    db = _find_db()
    if not db:
        return None
    conn = sqlite3.connect(db, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def topic_frequency(topic_keywords: list[str], days: int = 30) -> list[dict]:
    """How often a topic appears in recent sessions.

    Returns list of {date, session_id, snippet} for sessions mentioning the topic.
    """
    conn = _connect()
    if not conn:
        return []

    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    placeholders = " OR ".join("content MATCH ?" for _ in topic_keywords)
    query = f"""
        SELECT m.session_id, m.timestamp,
            snippet(messages_fts, 0, '>>>', '<<<', '...', 30) as snippet
        FROM messages_fts
        JOIN messages m ON messages_fts.rowid = m.rowid
        WHERE ({placeholders}) AND m.timestamp > ?
        ORDER BY m.timestamp DESC
        LIMIT 50
    """
    try:
        rows = conn.execute(query, [*topic_keywords, cutoff]).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def last_studied(topic_keywords: list[str]) -> str | None:
    """When was a topic last discussed? Returns ISO timestamp or None."""
    results = topic_frequency(topic_keywords, days=365)
    return results[0]["timestamp"] if results else None


def struggle_topics(days: int = 30, min_sessions: int = 3) -> list[dict]:
    """Find topics that keep coming up — potential struggle areas.

    Returns topics mentioned in 3+ sessions (user asking, not assistant explaining).
    """
    conn = _connect()
    if not conn:
        return []

    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    # Look for user questions (role='user') with question marks
    try:
        rows = conn.execute(
            """
            SELECT m.content, m.session_id, m.timestamp
            FROM messages m
            WHERE m.role = 'user' AND m.content LIKE '%?%' AND m.timestamp > ?
            ORDER BY m.timestamp DESC
            LIMIT 200
        """,
            [cutoff],
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()

    # Simple keyword extraction from questions
    from collections import Counter

    keywords = Counter()
    study_terms = _get_study_terms()
    for row in rows:
        content = row["content"].lower()
        for term in study_terms:
            if term in content:
                keywords[term] += 1

    return [{"topic": k, "mentions": v} for k, v in keywords.most_common(10) if v >= min_sessions]


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
                    "review_type": "New topic — start fresh",
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


def get_wins(days: int = 30) -> list[dict]:
    """Find concepts that improved in confidence over the given period."""
    conn = _connect()
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
    except Exception:
        return []
    finally:
        conn.close()


def get_progress_summary() -> dict:
    """Get overall progress summary across all concepts."""
    conn = _connect()
    if not conn:
        return {}
    try:
        rows = conn.execute(
            "SELECT confidence, COUNT(*) as count FROM study_progress GROUP BY confidence"
        ).fetchall()
        summary = {r["confidence"]: r["count"] for r in rows}
        summary["total"] = sum(summary.values())
        return summary
    except Exception:
        return {}
    finally:
        conn.close()


def record_progress(
    topic: str,
    concept: str,
    confidence: str,
    notes: str | None = None,
) -> bool:
    """Record or update progress on a concept."""
    conn = _connect()
    if not conn:
        return False
    try:
        now = datetime.now(UTC).isoformat()
        progress_id = str(
            uuid.uuid5(uuid.NAMESPACE_DNS, f"{topic.lower().strip()}:{concept.lower().strip()}")
        )
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
    except Exception:
        return False
    finally:
        conn.close()
