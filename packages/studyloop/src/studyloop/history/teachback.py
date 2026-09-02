"""Teach-back scoring: record and query 5-dimension assessments."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime

from ..db import immediate
from . import _connection

logger = logging.getLogger(__name__)


def _confidence_from_teachback(total: int, review_type: str) -> str:
    if total < 9:
        return "struggling"
    if total <= 13:
        return "learning"
    if total <= 17:
        return "confident"
    return "mastered" if review_type == "full" else "confident"


def record_teachback(
    concept: str,
    topic: str,
    scores: tuple[int, int, int, int, int],
    review_type: str,
    angle: str | None = None,
    notes: str | None = None,
    session_id: str | None = None,
) -> bool:
    """Record a teach-back score for a concept.

    Args:
        concept: The concept being assessed.
        topic: Study topic (python, sql, etc.).
        scores: Tuple of (accuracy, own_words, structure, depth, transfer) each 1-4.
        review_type: One of micro, structured, transfer, full.
        angle: Question angle used (e.g. "bloom_apply", "network_analogy").
        notes: Optional notes about the assessment.
        session_id: Optional session ID to link to.
    """
    conn = _connection._connect()
    if not conn:
        return False
    try:
        # R-21 invariant, made explicit: this is NOT a lost-update race in
        # practice -- the INSERT into teach_back_scores below is the first DML
        # statement in this function, so Python's sqlite3 module opens the
        # write transaction there and holds SQLite's single writer lock across
        # the SELECT/upsert of study_progress that follows (a 150-thread probe
        # confirmed zero lost updates). But that safety previously depended on
        # statement order and the default isolation level -- nothing said so,
        # and a refactor that moved the SELECT earlier would silently reopen
        # the race. `db.immediate()` takes the write lock up front instead, so
        # the serialisation holds regardless of statement order.
        with immediate(conn):
            accuracy, own_words, structure, depth, transfer = scores
            conn.execute(
                """
                INSERT INTO teach_back_scores
                    (concept, topic, session_id, score_accuracy, score_own_words,
                     score_structure, score_depth, score_transfer,
                     review_type, question_angle, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    concept,
                    topic,
                    session_id,
                    accuracy,
                    own_words,
                    structure,
                    depth,
                    transfer,
                    review_type,
                    angle,
                    notes,
                ),
            )

            # Upsert study_progress so teach-back evidence feeds review
            # scheduling even when the concept was not explicitly recorded
            # beforehand.
            total = sum(scores)
            topic_key = topic.lower().strip()
            concept_key = concept.lower().strip()
            # R-21: shared with history/progress.py's _record_progress_on_connection
            # -- both must derive the same id for the same (topic, concept).
            progress_id = _connection.progress_id_for(topic_key, concept_key)
            now = datetime.now(UTC).isoformat()
            confidence = _confidence_from_teachback(total, review_type)

            # Get existing angles_used and append
            existing = conn.execute(
                "SELECT angles_used FROM study_progress WHERE id = ?",
                (progress_id,),
            ).fetchone()
            angles: list[str] = []
            if existing and existing["angles_used"]:
                angles = json.loads(existing["angles_used"])
            if angle and angle not in angles:
                angles.append(angle)

            conn.execute(
                """
                INSERT INTO study_progress
                    (id, topic, concept, confidence, first_seen, last_seen, session_count,
                     notes, last_teachback_score, angles_used)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    confidence = excluded.confidence,
                    last_seen = excluded.last_seen,
                    session_count = session_count + 1,
                    notes = COALESCE(excluded.notes, notes),
                    last_teachback_score = excluded.last_teachback_score,
                    angles_used = excluded.angles_used,
                    updated_at = datetime('now')
                """,
                (
                    progress_id,
                    topic_key,
                    concept_key,
                    confidence,
                    now,
                    now,
                    notes,
                    total,
                    json.dumps(angles),
                ),
            )

        return True
    except sqlite3.DatabaseError:
        # R-21: was `except sqlite3.OperationalError`, which does not catch
        # sqlite3.IntegrityError -- a CHECK-constraint violation (e.g. a score
        # outside teach_back_scores' `BETWEEN 1 AND 4` constraints) used to
        # raise straight through this best-effort, "return False" function.
        return False
    finally:
        conn.close()


def get_teachback_history(concept: str, topic: str | None = None) -> list[dict]:
    """Get teach-back score history for a concept."""
    conn = _connection._connect()
    if not conn:
        return []
    try:
        if topic:
            rows = conn.execute(
                """
                SELECT concept, topic, score_accuracy, score_own_words,
                       score_structure, score_depth, score_transfer,
                       total_score, review_type, question_angle, notes, created_at
                FROM teach_back_scores
                WHERE concept = ? AND topic = ?
                ORDER BY created_at DESC
                LIMIT 20
                """,
                (concept, topic),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT concept, topic, score_accuracy, score_own_words,
                       score_structure, score_depth, score_transfer,
                       total_score, review_type, question_angle, notes, created_at
                FROM teach_back_scores
                WHERE concept = ?
                ORDER BY created_at DESC
                LIMIT 20
                """,
                (concept,),
            ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError as exc:
        if not _connection.is_missing_table_error(exc):
            logger.warning("get_teachback_history failed: %s", exc)
            raise
        return []
    finally:
        conn.close()
