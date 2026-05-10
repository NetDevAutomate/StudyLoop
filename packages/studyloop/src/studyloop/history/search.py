"""Topic frequency and struggle detection via FTS5 search."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from . import _connection


def _get_study_terms() -> list[str]:
    """Build study terms from configured topics, falling back to defaults."""
    try:
        from ..topics import get_topics

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


def topic_frequency(topic_keywords: list[str], days: int = 30) -> list[dict]:
    """How often a topic appears in recent sessions.

    Returns list of {date, session_id, snippet} for sessions mentioning the topic.
    """
    conn = _connection._connect()
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


def struggle_topics(days: int = 30, min_sessions: int = 3) -> list[dict]:
    """Find topics that keep coming up -- potential struggle areas.

    Returns topics mentioned in 3+ sessions (user asking, not assistant explaining).
    """
    conn = _connection._connect()
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
