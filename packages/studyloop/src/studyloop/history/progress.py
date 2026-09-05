"""Study progress tracking: record, query, and spaced repetition scheduling."""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from . import _connection, observations, search

if TYPE_CHECKING:
    from agent_session_tools.context.legacy_sources import SessionInput

logger = logging.getLogger(__name__)


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

        rows = observations.rows(conn)
    except sqlite3.OperationalError as exc:
        # The "study_progress missing" case is already handled above (the
        # sqlite_master check at :63-64) -- anything reaching here is a real
        # fault (e.g. a lock timeout), not an expected schema gap.
        if not _connection.is_missing_table_error(exc):
            logger.warning("_progress_review_due failed: %s", exc)
            raise
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
                "last_teachback_score": row.get("last_teachback_score"),
                "confidence_status": row.get("confidence_status"),
                "observation_ids": row.get("observation_ids", []),
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
    evidence_ids: tuple[str, ...] | None = None,
    input_snapshot: SessionInput | None = None,
) -> None:
    """Write one progress row on the caller's transaction without committing."""
    if observations.available(conn):
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        observations.record(
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
            evidence_ids=evidence_ids,
            input_snapshot=input_snapshot,
        )
        return
    from agent_session_tools.context.legacy import legacy_global_visible
    from agent_session_tools.context.scope import ScopeError

    if not legacy_global_visible(conn):
        raise ScopeError("Migrate before writing classified progress")
    topic = topic.lower().strip()
    concept = concept.lower().strip()
    now = datetime.now(UTC).isoformat()
    # R-21: shared with history/teachback.py's record_teachback -- both must
    # derive the same id for the same (topic, concept) pair.
    progress_id = _connection.progress_id_for(topic, concept)
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

    On the current schema each report has its own ownership and provenance.
    Omitted notes are not inherited from an older report. Legacy databases keep
    their historical aggregate behavior until migration.
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
    except sqlite3.OperationalError as exc:
        conn.rollback()
        if not _connection.is_missing_table_error(exc):
            logger.warning("record_progress failed: %s", exc)
            raise
        return False
    finally:
        conn.close()


def get_wins(days: int = 30) -> list[dict]:
    """Find recent confident reports; these do not establish measured improvement."""
    conn = _connection._connect()
    if not conn:
        return []
    try:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        rows = [
            r
            for r in observations.rows(conn)
            if r["confidence"] in ("confident", "mastered")
            and (_parse_timestamp(r["last_seen"]) or datetime.min.replace(tzinfo=UTC)) > cutoff
        ]
        return sorted(rows, key=lambda row: row["last_seen"], reverse=True)
    except sqlite3.OperationalError as exc:
        if not _connection.is_missing_table_error(exc):
            logger.warning("get_wins failed: %s", exc)
            raise
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

    def _display_topic(topic: str, source_section: str | None) -> str:
        if source_section and source_section.strip():
            section_stem = Path(source_section).stem
            if section_stem:
                return section_stem
        return topic

    try:
        # Source 1: the projection includes only permitted observation bodies.
        cutoff_dt = datetime.now(UTC) - timedelta(days=days)
        for r in observations.rows(conn):
            seen = _parse_timestamp(r["last_seen"])
            if r["confidence"] != "struggling" or seen is None or seen <= cutoff_dt:
                continue
            source_section = r.get("source_section")
            _merge(
                _display_topic(r["topic"], source_section),
                1,
                r["session_count"] or 0,
                r["last_seen"],
                concept=r["concept"],
                source_course=r.get("source_course"),
                source_section=source_section,
                source_publisher=r.get("source_publisher"),
            )

        from agent_session_tools.context.legacy import legacy_global_visible

        if not legacy_global_visible(conn):
            for item in merged.values():
                item.pop("_concepts", None)
            return sorted(merged.values(), key=lambda row: row["last_seen"] or "", reverse=True)

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
        except sqlite3.OperationalError as exc:
            if not _connection.is_missing_table_error(exc):
                logger.warning("get_struggling_topics: study_sessions source failed: %s", exc)
                raise

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
        except sqlite3.OperationalError as exc:
            if not _connection.is_missing_table_error(exc):
                logger.warning("get_struggling_topics: parked_topics source failed: %s", exc)
                raise
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
        return observations.rows(conn)
    except sqlite3.OperationalError as exc:
        if not _connection.is_missing_table_error(exc):
            logger.warning("get_progress_for_map failed: %s", exc)
            raise
        return []
    finally:
        conn.close()


def get_progress_summary() -> dict:
    """Get overall progress summary across all concepts."""
    conn = _connection._connect()
    if not conn:
        return {}
    try:
        from collections import Counter

        rows = observations.rows(conn)
        summary = dict(Counter(r["confidence"] for r in rows))
        summary["total"] = len(rows)
        conflicts = sum(r.get("confidence_status") == "conflicting_reports" for r in rows)
        if conflicts:
            summary["conflicting_reports"] = conflicts
        return summary
    except sqlite3.OperationalError as exc:
        if not _connection.is_missing_table_error(exc):
            logger.warning("get_progress_summary failed: %s", exc)
            raise
        return {}
    finally:
        conn.close()
