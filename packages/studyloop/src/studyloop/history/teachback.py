"""Teach-back scoring: record and query 5-dimension assessments."""

from __future__ import annotations

import json
import sqlite3
import uuid

from . import _connection


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

        # Update study_progress with latest teach-back score and angle
        total = sum(scores)
        progress_id = str(
            uuid.uuid5(uuid.NAMESPACE_DNS, f"{topic.lower().strip()}:{concept.lower().strip()}")
        )

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
            UPDATE study_progress
            SET last_teachback_score = ?,
                angles_used = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (total, json.dumps(angles), progress_id),
        )

        conn.commit()
        return True
    except sqlite3.OperationalError:
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
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
