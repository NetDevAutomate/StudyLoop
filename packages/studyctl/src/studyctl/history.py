"""Query session history for study mentor intelligence."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from .settings import load_settings

if TYPE_CHECKING:
    from pathlib import Path


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
    db = load_settings().session_db
    return db if db.exists() else None


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


def get_last_session_summary() -> dict | None:
    """Get a summary of the most recent study session for auto-resume.

    Returns {session_id, source, project_path, started, topics_covered,
             last_message_preview, concepts_in_progress} or None.
    """
    conn = _connect()
    if not conn:
        return None
    try:
        # Find the most recent session
        session = conn.execute(
            """
            SELECT s.id, s.source, s.project_path, s.created_at, s.updated_at
            FROM sessions s
            ORDER BY COALESCE(s.updated_at, s.created_at) DESC
            LIMIT 1
            """
        ).fetchone()
        if not session:
            return None

        session_id = session["id"]

        # Get last few messages for context
        messages = conn.execute(
            """
            SELECT role, content FROM messages
            WHERE session_id = ? AND role IN ('user', 'assistant')
            ORDER BY COALESCE(seq, rowid) DESC
            LIMIT 6
            """,
            (session_id,),
        ).fetchall()

        # Get concepts currently in progress
        in_progress = conn.execute(
            """
            SELECT concept, topic, confidence FROM study_progress
            WHERE confidence IN ('struggling', 'learning')
            ORDER BY last_seen DESC
            LIMIT 5
            """
        ).fetchall()

        # Extract topic keywords from recent messages
        study_terms = _get_study_terms()
        topics_mentioned: set[str] = set()
        for msg in messages:
            content = (msg["content"] or "").lower()
            for term in study_terms:
                if term in content:
                    topics_mentioned.add(term)

        # Build preview from last assistant message
        preview = ""
        for msg in messages:
            if msg["role"] == "assistant" and msg["content"]:
                preview = msg["content"][:200].strip()
                break

        return {
            "session_id": session_id,
            "source": session["source"],
            "project_path": session["project_path"],
            "started": session["created_at"],
            "updated": session["updated_at"],
            "topics_covered": sorted(topics_mentioned)[:5],
            "last_message_preview": preview,
            "concepts_in_progress": [
                {"concept": r["concept"], "topic": r["topic"], "confidence": r["confidence"]}
                for r in in_progress
            ],
        }
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def get_study_streaks() -> dict:
    """Calculate study streak data from session history.

    Returns {current_streak, longest_streak, total_days, sessions_this_week,
             last_session_date, day_counts}.
    """
    conn = _connect()
    if not conn:
        return {
            "current_streak": 0,
            "longest_streak": 0,
            "total_days": 0,
            "sessions_this_week": 0,
            "last_session_date": None,
        }
    try:
        # Get distinct study days (dates only) from last 90 days
        rows = conn.execute(
            """
            SELECT DISTINCT DATE(COALESCE(s.updated_at, s.created_at)) as study_date
            FROM sessions s
            WHERE s.created_at > datetime('now', '-90 days')
            ORDER BY study_date DESC
            """
        ).fetchall()

        if not rows:
            return {
                "current_streak": 0,
                "longest_streak": 0,
                "total_days": 0,
                "sessions_this_week": 0,
                "last_session_date": None,
            }

        study_dates = [datetime.fromisoformat(r["study_date"]).date() for r in rows]
        today = datetime.now(UTC).date()

        # Calculate current streak (consecutive days ending today or yesterday)
        current_streak = 0
        check_date = today
        for d in study_dates:
            if d == check_date or d == check_date - timedelta(days=1):
                current_streak += 1
                check_date = d - timedelta(days=1)
            else:
                break

        # Calculate longest streak
        longest_streak = 1
        current_run = 1
        sorted_dates = sorted(study_dates)
        for i in range(1, len(sorted_dates)):
            if (sorted_dates[i] - sorted_dates[i - 1]).days == 1:
                current_run += 1
                longest_streak = max(longest_streak, current_run)
            else:
                current_run = 1

        # Sessions this week
        week_start = today - timedelta(days=today.weekday())
        sessions_this_week = conn.execute(
            """
            SELECT COUNT(*) as cnt FROM sessions
            WHERE DATE(COALESCE(updated_at, created_at)) >= ?
            """,
            (week_start.isoformat(),),
        ).fetchone()["cnt"]

        return {
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "total_days": len(study_dates),
            "sessions_this_week": sessions_this_week,
            "last_session_date": study_dates[0].isoformat() if study_dates else None,
        }
    except sqlite3.OperationalError:
        return {
            "current_streak": 0,
            "longest_streak": 0,
            "total_days": 0,
            "sessions_this_week": 0,
            "last_session_date": None,
        }
    finally:
        conn.close()


def check_medication_window(medication_config: dict) -> dict | None:
    """Check current time against medication schedule.

    Args:
        medication_config: {dose_time: "08:00", onset_minutes: 30,
                           peak_hours: 4, duration_hours: 8}

    Returns {phase, recommendation, minutes_remaining} or None if not configured.
    """
    if not medication_config or "dose_time" not in medication_config:
        return None

    now = datetime.now()
    dose_h, dose_m = medication_config["dose_time"].split(":")
    dose_time = now.replace(hour=int(dose_h), minute=int(dose_m), second=0, microsecond=0)

    # If dose time is in the future, assume yesterday's dose
    if dose_time > now:
        dose_time -= timedelta(days=1)

    minutes_since_dose = (now - dose_time).total_seconds() / 60
    onset = medication_config.get("onset_minutes", 30)
    peak_hours = medication_config.get("peak_hours", 4)
    duration_hours = medication_config.get("duration_hours", 8)

    if minutes_since_dose < onset:
        return {
            "phase": "onset",
            "recommendation": "Meds ramping up. Light review or body doubling is a good fit.",
            "minutes_remaining": int(onset - minutes_since_dose),
        }
    elif minutes_since_dose < (peak_hours * 60):
        return {
            "phase": "peak",
            "recommendation": "Peak window. Best time for new material or hard problems.",
            "minutes_remaining": int(peak_hours * 60 - minutes_since_dose),
        }
    elif minutes_since_dose < (duration_hours * 60):
        return {
            "phase": "tapering",
            "recommendation": "Meds tapering. Switch to review or lighter material.",
            "minutes_remaining": int(duration_hours * 60 - minutes_since_dose),
        }
    else:
        return {
            "phase": "worn_off",
            "recommendation": "Meds have worn off. Review-only or body doubling recommended.",
            "minutes_remaining": 0,
        }


def get_progress_for_map() -> list[dict]:
    """Get all study progress entries for rendering a progress map.

    Returns list of {topic, concept, confidence, session_count, first_seen, last_seen}.
    """
    conn = _connect()
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
    except sqlite3.OperationalError:
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
    except sqlite3.OperationalError:
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


# ── teach-back scoring ────────────────────────────────────────────────────────


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
    conn = _connect()
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
    conn = _connect()
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


# ── knowledge bridges ─────────────────────────────────────────────────────────


def record_bridge(
    source_concept: str,
    source_domain: str,
    target_concept: str,
    target_domain: str,
    structural_mapping: str | None = None,
    quality: str = "proposed",
    created_by: str = "agent",
) -> bool:
    """Record a knowledge bridge between two concepts."""
    conn = _connect()
    if not conn:
        return False
    try:
        conn.execute(
            """
            INSERT INTO knowledge_bridges
                (source_concept, source_domain, target_concept, target_domain,
                 structural_mapping, quality, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_concept,
                source_domain,
                target_concept,
                target_domain,
                structural_mapping,
                quality,
                created_by,
            ),
        )
        conn.commit()
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


def get_bridges(
    target_domain: str | None = None,
    source_domain: str | None = None,
    quality: str | None = None,
) -> list[dict]:
    """Get knowledge bridges, optionally filtered."""
    conn = _connect()
    if not conn:
        return []
    try:
        conditions = []
        params: list[str] = []
        if target_domain:
            conditions.append("target_domain = ?")
            params.append(target_domain)
        if source_domain:
            conditions.append("source_domain = ?")
            params.append(source_domain)
        if quality:
            conditions.append("quality = ?")
            params.append(quality)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = conn.execute(
            f"""
            SELECT id, source_concept, source_domain, target_concept, target_domain,
                   structural_mapping, quality, times_used, times_helpful,
                   created_by, created_at
            FROM knowledge_bridges
            {where}
            ORDER BY times_helpful DESC, created_at DESC
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def update_bridge_usage(bridge_id: int, helpful: bool) -> bool:
    """Record that a bridge was used, and whether it was helpful."""
    conn = _connect()
    if not conn:
        return False
    try:
        helpful_increment = 1 if helpful else 0
        conn.execute(
            """
            UPDATE knowledge_bridges
            SET times_used = times_used + 1,
                times_helpful = times_helpful + ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (helpful_increment, bridge_id),
        )
        conn.commit()
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


# ── study sessions ────────────────────────────────────────────────────────────


def start_study_session(
    topic: str,
    energy_level: str,
    session_id: str | None = None,
) -> str | None:
    """Start a tracked study session. Returns the study session ID."""
    conn = _connect()
    if not conn:
        return None
    try:
        study_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        conn.execute(
            """
            INSERT INTO study_sessions (id, session_id, topic, energy_level, started_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (study_id, session_id, topic.lower().strip(), energy_level, now),
        )
        conn.commit()
        return study_id
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def end_study_session(study_id: str, notes: str | None = None) -> bool:
    """End a tracked study session, recording duration."""
    conn = _connect()
    if not conn:
        return False
    try:
        now = datetime.now(UTC).isoformat()
        conn.execute(
            """
            UPDATE study_sessions
            SET ended_at = ?,
                duration_minutes = CAST(
                    (julianday(?) - julianday(started_at)) * 1440 AS INTEGER
                ),
                notes = COALESCE(?, notes)
            WHERE id = ?
            """,
            (now, now, notes, study_id),
        )
        conn.commit()
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


def get_study_session_stats(days: int = 30) -> list[dict]:
    """Get study session stats grouped by topic for the given period."""
    conn = _connect()
    if not conn:
        return []
    try:
        rows = conn.execute(
            """
            SELECT topic,
                   COUNT(*) as sessions,
                   SUM(duration_minutes) as total_minutes,
                   AVG(duration_minutes) as avg_minutes,
                   energy_level as most_common_energy
            FROM study_sessions
            WHERE started_at > datetime('now', ?)
              AND duration_minutes IS NOT NULL
            GROUP BY topic
            ORDER BY total_minutes DESC
            """,
            (f"-{days} days",),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
