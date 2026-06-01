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
    *,
    source_course: str | None = None,
    source_section: str | None = None,
    source_publisher: str | None = None,
    created_by: str = "agent",
) -> bool:
    """Record or update progress on a concept.

    The optional keyword-only arguments (source_course, source_section,
    source_publisher, created_by) capture provenance when the struggle is
    flagged from a specific course lesson in the web UI (Phase 5).  Existing
    callers that omit them continue to work: new columns default to None /
    'agent'.

    The ON CONFLICT COALESCE pattern means a later call without provenance
    will not overwrite provenance written by an earlier web-flagged row.
    """
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
                (id, topic, concept, confidence, first_seen, last_seen, session_count,
                 notes, source_course, source_section, source_publisher, created_by)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                confidence = excluded.confidence,
                last_seen = excluded.last_seen,
                session_count = session_count + 1,
                notes = COALESCE(excluded.notes, notes),
                source_course = COALESCE(excluded.source_course, source_course),
                source_section = COALESCE(excluded.source_section, source_section),
                source_publisher = COALESCE(excluded.source_publisher, source_publisher),
                created_by = COALESCE(excluded.created_by, created_by),
                updated_at = datetime('now')
            """,
            (
                progress_id,
                topic,
                concept,
                confidence,
                now,
                now,
                notes,
                source_course,
                source_section,
                source_publisher,
                created_by,
            ),
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


def get_struggling_topics(days: int = 14) -> list[dict]:
    """Return distinct struggling topics within the last ``days``.

    The session DB is the single source of truth, but struggle signal lands
    in three places, so this unions all of them by topic:

    1. ``study_progress`` (confidence='struggling') — the authoritative,
       per-concept store written at session end and by ``studyloop review``.
    2. ``study_sessions`` with ``struggle_count > 0`` — a session the user
       flagged as a struggle even if no per-concept row was written.
    3. ``parked_topics`` with ``source='struggled'`` — topics auto-parked
       from a struggle.

    Unioning means the dropdown is useful from existing data (1,900+ study
    sessions) even before per-concept rows accumulate. Each source is
    optional/guarded so a missing table never breaks the others.

    Drives the WebUI's topic-from-struggles dropdown (U10) and the scope
    resolver when ``scope.kind='topic_struggles'``.

    Returns:
        List of ``{"topic", "concept_count", "session_count", "last_seen"}``
        sorted by ``last_seen`` descending.
    """
    conn = _connection._connect()
    if not conn:
        return []
    cutoff = (f"-{days} days",)
    # topic -> aggregated dict, merged across sources (case-insensitive key).
    merged: dict[str, dict] = {}

    def _merge(topic: str, concept_count: int, session_count: int, last_seen: str) -> None:
        if not topic or not topic.strip():
            return
        key = topic.strip().lower()
        cur = merged.get(key)
        if cur is None:
            merged[key] = {
                "topic": topic.strip(),
                "concept_count": concept_count,
                "session_count": session_count,
                "last_seen": last_seen,
            }
            return
        cur["concept_count"] += concept_count
        cur["session_count"] += session_count
        if last_seen and last_seen > (cur["last_seen"] or ""):
            cur["last_seen"] = last_seen

    try:
        # Source 1: study_progress (authoritative).
        try:
            for r in conn.execute(
                """
                SELECT topic,
                       COUNT(DISTINCT concept) AS concept_count,
                       SUM(session_count)      AS session_count,
                       MAX(last_seen)          AS last_seen
                FROM study_progress
                WHERE confidence = 'struggling' AND last_seen > datetime('now', ?)
                GROUP BY topic
                """,
                cutoff,
            ).fetchall():
                _merge(r["topic"], r["concept_count"] or 0, r["session_count"] or 0, r["last_seen"])
        except sqlite3.OperationalError:
            pass

        # Source 2: study_sessions flagged as a struggle.
        try:
            for r in conn.execute(
                """
                SELECT topic,
                       COUNT(*)         AS session_count,
                       MAX(started_at)  AS last_seen
                FROM study_sessions
                WHERE struggle_count > 0
                  AND topic IS NOT NULL
                  AND started_at > datetime('now', ?)
                GROUP BY topic
                """,
                cutoff,
            ).fetchall():
                _merge(r["topic"], 0, r["session_count"] or 0, r["last_seen"])
        except sqlite3.OperationalError:
            pass

        # Source 3: parked topics whose source is a struggle.
        try:
            for r in conn.execute(
                """
                SELECT topic_tag      AS topic,
                       COUNT(*)       AS session_count,
                       MAX(parked_at) AS last_seen
                FROM parked_topics
                WHERE source = 'struggled'
                  AND topic_tag IS NOT NULL
                  AND parked_at > datetime('now', ?)
                GROUP BY topic_tag
                """,
                cutoff,
            ).fetchall():
                _merge(r["topic"], 0, r["session_count"] or 0, r["last_seen"])
        except sqlite3.OperationalError:
            pass
    finally:
        conn.close()

    return sorted(merged.values(), key=lambda d: d["last_seen"] or "", reverse=True)


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
