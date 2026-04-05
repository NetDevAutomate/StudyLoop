"""Study session CRUD: start, end, stats, energy, and session summaries."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime

from . import _connection, search


def start_study_session(
    topic: str,
    energy_level: str,
    session_id: str | None = None,
) -> str | None:
    """Start a tracked study session. Returns the study session ID."""
    conn = _connection._connect()
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


def get_session_notes(study_id: str) -> str | None:
    """Fetch the notes from a study session. Returns None if not found."""
    if not study_id:
        return None
    conn = _connection._connect()
    if not conn:
        return None
    try:
        row = conn.execute("SELECT notes FROM study_sessions WHERE id = ?", (study_id,)).fetchone()
        return row["notes"] if row and row["notes"] else None
    except Exception:
        return None
    finally:
        conn.close()


def update_persona_hash(study_id: str, persona_hash: str) -> bool:
    """Store the persona version hash for effectiveness tracking."""
    conn = _connection._connect()
    if not conn:
        return False
    try:
        conn.execute(
            "UPDATE study_sessions SET persona_hash = ? WHERE id = ?",
            (persona_hash, study_id),
        )
        conn.commit()
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


def end_study_session(
    study_id: str,
    notes: str | None = None,
    *,
    win_count: int | None = None,
    struggle_count: int | None = None,
) -> bool:
    """End a tracked study session, recording duration and outcome counts."""
    conn = _connection._connect()
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
                notes = COALESCE(?, notes),
                win_count = ?,
                struggle_count = ?
            WHERE id = ?
            """,
            (now, now, notes, win_count, struggle_count, study_id),
        )
        conn.commit()
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


def get_study_session_stats(days: int = 30) -> list[dict]:
    """Get study session stats grouped by topic for the given period."""
    conn = _connection._connect()
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


def get_energy_session_data(days: int = 30) -> list[dict]:
    """Get per-session energy and duration data for streak analysis.

    Returns a list of dicts with energy_level, duration_minutes, and
    days_ago -- the shape expected by streaks_logic.SessionSummary.
    """
    conn = _connection._connect()
    if not conn:
        return []
    try:
        rows = conn.execute(
            """
            SELECT energy_level,
                   duration_minutes,
                   CAST(julianday('now') - julianday(started_at) AS INTEGER) as days_ago
            FROM study_sessions
            WHERE started_at > datetime('now', ?)
              AND duration_minutes IS NOT NULL
              AND energy_level IS NOT NULL
            ORDER BY started_at ASC
            """,
            (f"-{days} days",),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def get_last_session_summary() -> dict | None:
    """Get a summary of the most recent study session for auto-resume.

    Returns {session_id, source, project_path, started, topics_covered,
             last_message_preview, concepts_in_progress} or None.
    """
    conn = _connection._connect()
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
        study_terms = search._get_study_terms()
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


def get_persona_effectiveness(persona_hash: str | None = None) -> list[dict]:
    """Get win rate and struggle count per persona version.

    When *persona_hash* is None, returns stats for all tracked versions.
    """
    conn = _connection._connect()
    if not conn:
        return []
    try:
        sql = """
            SELECT persona_hash,
                   COUNT(*)                    AS sessions,
                   AVG(win_count)              AS avg_wins,
                   AVG(struggle_count)         AS avg_struggles,
                   AVG(duration_minutes)       AS avg_duration,
                   CASE WHEN SUM(win_count + struggle_count) > 0
                        THEN ROUND(
                            CAST(SUM(win_count) AS REAL)
                            / SUM(win_count + struggle_count), 3)
                        ELSE NULL
                   END                         AS win_rate
            FROM study_sessions
            WHERE persona_hash IS NOT NULL
              AND win_count IS NOT NULL
        """
        params: tuple = ()
        if persona_hash:
            sql += " AND persona_hash = ?"
            params = (persona_hash,)
        sql += " GROUP BY persona_hash ORDER BY sessions DESC"

        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
