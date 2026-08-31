"""Study progress tracking: record, query, and spaced repetition scheduling."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from . import _connection, search


def last_studied(topic_keywords: list[str]) -> str | None:
    """When was a topic last discussed? Returns ISO timestamp or None."""
    results = search.topic_frequency(topic_keywords, days=365)
    return results[0]["timestamp"] if results else None


REVIEW_INTERVALS: tuple[tuple[int, str], ...] = (
    (1, "5-min recall quiz"),
    (3, "10-min Socratic review"),
    (7, "15-min deep review"),
    (14, "Apply to new problem"),
    (30, "Teach-back session"),
)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _review_type_for(confidence: str | None, days_ago: int) -> str | None:
    if confidence == "struggling":
        return "Guided repair + tiny practice"

    review_type = None
    for interval, label in REVIEW_INTERVALS:
        if days_ago >= interval:
            review_type = label
    return review_type


def _study_progress_columns(conn: sqlite3.Connection) -> set[str]:
    return {row["name"] for row in conn.execute("PRAGMA table_info(study_progress)").fetchall()}


def _progress_review_due(now: datetime) -> tuple[list[dict], set[str]]:
    conn = _connection._connect()
    if not conn:
        return [], set()
    try:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "study_progress" not in tables:
            return [], set()

        columns = _study_progress_columns(conn)
        teachback_expr = (
            "last_teachback_score"
            if "last_teachback_score" in columns
            else "NULL AS last_teachback_score"
        )
        rows = conn.execute(
            f"""
            SELECT topic, concept, confidence, last_seen, session_count, {teachback_expr}
            FROM study_progress
            WHERE topic IS NOT NULL
              AND concept IS NOT NULL
            ORDER BY last_seen DESC
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return [], set()
    finally:
        conn.close()

    due = []
    topics_with_progress = set()
    for row in rows:
        if row["topic"]:
            topics_with_progress.add(row["topic"].lower())
        last_dt = _parse_timestamp(row["last_seen"])
        if last_dt is None:
            continue

        days_ago = max((now - last_dt).days, 0)
        review_type = _review_type_for(row["confidence"], days_ago)
        if not review_type:
            continue

        due.append(
            {
                "topic": row["topic"],
                "concept": row["concept"],
                "confidence": row["confidence"],
                "last_studied": row["last_seen"][:10],
                "days_ago": days_ago,
                "review_type": review_type,
                "evidence": "study_progress",
                "session_count": row["session_count"],
                "last_teachback_score": row["last_teachback_score"],
            }
        )

    priority = {"struggling": 0, "learning": 1, "confident": 2, "mastered": 3}

    def sort_key(item: dict) -> tuple[int, int]:
        confidence = str(item.get("confidence") or "")
        return (priority.get(confidence, 9), -(item.get("days_ago") or 0))

    return (
        sorted(
            due,
            key=sort_key,
        ),
        topics_with_progress,
    )


def spaced_repetition_due(topic_keywords_map: dict[str, list[str]]) -> list[dict]:
    """Check which concepts are due for spaced review.

    Args:
        topic_keywords_map: {"python": ["python", "pattern", "dataclass"], ...}

    Returns:
        List of {topic, concept, last_studied, days_ago, review_type}
    """
    now = datetime.now(UTC)

    progress_due, topics_with_progress = _progress_review_due(now)

    new_topics = []
    for topic in topic_keywords_map:
        if topic.lower() not in topics_with_progress:
            new_topics.append(
                {
                    "topic": topic,
                    "concept": None,
                    "confidence": None,
                    "last_studied": None,
                    "days_ago": None,
                    "review_type": "New topic -- start fresh",
                    "evidence": "configured_topic",
                }
            )

    if progress_due:
        return [*progress_due, *new_topics]

    # Fresh installs have no active-learning evidence yet, so new_topics is
    # the full configured list. Once a topic has progress evidence, it is only
    # shown when a concept is actually due.
    return new_topics


def _record_progress_on_connection(
    conn: sqlite3.Connection,
    topic: str,
    concept: str,
    confidence: str,
    notes: str | None = None,
    *,
    source_course: str | None = None,
    source_section: str | None = None,
    source_publisher: str | None = None,
    source_session_id: str | None = None,
    created_by: str = "agent",
) -> None:
    """Write one progress row on the caller's transaction without committing."""
    topic = topic.lower().strip()
    concept = concept.lower().strip()
    now = datetime.now(UTC).isoformat()
    progress_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{topic}:{concept}"))
    conn.execute(
        """
        INSERT INTO study_progress
            (id, topic, concept, confidence, first_seen, last_seen, session_count,
             notes, source_course, source_section, source_publisher,
             source_session_id, created_by)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            confidence = excluded.confidence,
            last_seen = excluded.last_seen,
            session_count = session_count + CASE
                WHEN excluded.source_session_id IS NOT NULL
                 AND excluded.source_session_id = source_session_id THEN 0
                ELSE 1
            END,
            notes = COALESCE(excluded.notes, notes),
            source_course = COALESCE(excluded.source_course, source_course),
            source_section = COALESCE(excluded.source_section, source_section),
            source_publisher = COALESCE(excluded.source_publisher, source_publisher),
            source_session_id = COALESCE(excluded.source_session_id, source_session_id),
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
            source_session_id,
            created_by,
        ),
    )


def record_progress(
    topic: str,
    concept: str,
    confidence: str,
    notes: str | None = None,
    *,
    source_course: str | None = None,
    source_section: str | None = None,
    source_publisher: str | None = None,
    source_session_id: str | None = None,
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
        _record_progress_on_connection(
            conn,
            topic,
            concept,
            confidence,
            notes,
            source_course=source_course,
            source_section=source_section,
            source_publisher=source_publisher,
            source_session_id=source_session_id,
            created_by=created_by,
        )
        conn.commit()
        return True
    except sqlite3.OperationalError:
        conn.rollback()
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

    def _merge(
        topic: str,
        concept_count: int,
        session_count: int,
        last_seen: str,
        *,
        concept: str | None = None,
        source_course: str | None = None,
        source_section: str | None = None,
        source_publisher: str | None = None,
    ) -> None:
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
                "source_course": source_course,
                "source_section": source_section,
                "source_publisher": source_publisher,
                "_concepts": {concept} if concept else set(),
            }
            return
        if concept:
            cur["_concepts"].add(concept)
            cur["concept_count"] = len(cur["_concepts"])
        else:
            cur["concept_count"] += concept_count
        cur["session_count"] += session_count
        if last_seen and last_seen > (cur["last_seen"] or ""):
            cur["last_seen"] = last_seen
        for field, value in (
            ("source_course", source_course),
            ("source_section", source_section),
            ("source_publisher", source_publisher),
        ):
            if not value:
                continue
            if cur.get(field) in (None, value):
                cur[field] = value
            else:
                # Multiple provenance values merged under one display topic:
                # keep the row useful, but avoid claiming a single exact source.
                cur[field] = None

    def _progress_columns() -> set[str]:
        try:
            return {r["name"] for r in conn.execute("PRAGMA table_info(study_progress)")}
        except sqlite3.OperationalError:
            return set()

    def _display_topic(topic: str, source_section: str | None) -> str:
        if source_section and source_section.strip():
            section_stem = Path(source_section).stem
            if section_stem:
                return section_stem
        return topic

    try:
        # Source 1: study_progress (authoritative).
        try:
            columns = _progress_columns()
            optional_source_cols = [
                col
                for col in ("source_course", "source_section", "source_publisher")
                if col in columns
            ]
            select_cols = ["topic", "concept", "session_count", "last_seen", *optional_source_cols]
            for r in conn.execute(
                f"""
                SELECT {", ".join(select_cols)}
                FROM study_progress
                WHERE confidence = 'struggling' AND last_seen > datetime('now', ?)
                ORDER BY last_seen DESC
                """,
                cutoff,
            ).fetchall():
                source_section = (
                    r["source_section"] if "source_section" in optional_source_cols else None
                )
                source_course = (
                    r["source_course"] if "source_course" in optional_source_cols else None
                )
                source_publisher = (
                    r["source_publisher"] if "source_publisher" in optional_source_cols else None
                )
                _merge(
                    _display_topic(r["topic"], source_section),
                    1,
                    r["session_count"] or 0,
                    r["last_seen"],
                    concept=r["concept"],
                    source_course=source_course,
                    source_section=source_section,
                    source_publisher=source_publisher,
                )
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

    results = []
    for item in merged.values():
        item.pop("_concepts", None)
        results.append(item)
    return sorted(results, key=lambda d: d["last_seen"] or "", reverse=True)


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
