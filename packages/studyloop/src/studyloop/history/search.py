"""Topic frequency and struggle detection via FTS5 search."""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime, timedelta

from . import _connection

logger = logging.getLogger(__name__)


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
    if not topic_keywords:
        return []

    conn = _connection._connect()
    if not conn:
        return []

    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    # ONE qualified MATCH, with the keywords OR'd inside the FTS5 query
    # string (R-92). Two defects lived in the old
    # `" OR ".join("content MATCH ?" ...)` shape:
    #   * `content` is ambiguous — both messages_fts and messages carry the
    #     column, so SQLite raised "ambiguous column name: content" on every
    #     call through get_study_history, and R-22b (correctly) re-raised it;
    #   * FTS5 refuses more than one MATCH constraint per table in a WHERE
    #     ("unable to use function MATCH in the requested context"), so the
    #     multi-keyword path — the normal path — was broken either way.
    # Each keyword is double-quoted as an FTS5 phrase, because several study
    # terms carry spaces ("window functions", "lake formation") and unquoted
    # they would parse as separate AND'd terms.
    match_expr = " OR ".join('"' + kw.replace('"', '""') + '"' for kw in topic_keywords)
    query = """
        SELECT m.session_id, m.timestamp,
            snippet(messages_fts, 0, '>>>', '<<<', '...', 30) as snippet
        FROM messages_fts
        JOIN messages m ON messages_fts.rowid = m.rowid
        WHERE messages_fts.content MATCH ? AND m.timestamp > ?
        ORDER BY m.timestamp DESC
        LIMIT 50
    """
    try:
        rows = conn.execute(query, [match_expr, cutoff]).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError as exc:
        # R-22b: a bare `except sqlite3.OperationalError: return []` cannot
        # tell a genuinely missing table (an old schema, pre-migration --
        # safe to treat as "no matches") apart from a real lock/timeout
        # fault, which used to read back indistinguishably as "topic never
        # mentioned" instead of surfacing the failure.
        if not _connection.is_missing_table_error(exc):
            logger.warning("topic_frequency failed: %s", exc)
            raise
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
    except sqlite3.OperationalError as exc:
        # R-22b: see topic_frequency's comment above -- same reasoning.
        if not _connection.is_missing_table_error(exc):
            logger.warning("struggle_topics failed: %s", exc)
            raise
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
