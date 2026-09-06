"""Study session CRUD: start, end, stats, energy, and session summaries."""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import UTC, datetime

from agent_session_tools.context import records
from agent_session_tools.context.legacy import legacy_global_visible
from agent_session_tools.context.scope import active_policy, visibility_sql

from . import _connection, observations, search

logger = logging.getLogger(__name__)


def start_study_session(
    topic: str,
    energy_level: str,
    session_id: str | None = None,
    *,
    topic_slug: str | None = None,
) -> str | None:
    """Start a tracked study session. Returns the study session ID."""
    conn = _connection._connect()
    if not conn:
        return None
    try:
        study_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        with _connection.owned_write(conn):
            conn.execute(
                """
                INSERT INTO study_sessions
                    (id, session_id, topic, energy_level, started_at, topic_slug)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (study_id, session_id, topic.lower().strip(), energy_level, now, topic_slug),
            )
            records.bind(conn, "study_sessions", study_id, session_id=session_id)
        return study_id
    except sqlite3.OperationalError as exc:
        if not _connection.is_missing_table_error(exc):
            logger.warning("start_study_session failed: %s", exc)
            raise
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
        clause, params = records.visible_sql(conn, "study_sessions")
        row = conn.execute(
            "SELECT notes FROM study_sessions r WHERE id=? AND " + clause,
            [study_id, *params],
        ).fetchone()
        return row["notes"] if row and row["notes"] else None
    except sqlite3.OperationalError as exc:
        if not _connection.is_missing_table_error(exc):
            raise
        return None
    finally:
        conn.close()


def update_persona_hash(study_id: str, persona_hash: str) -> bool:
    """Store the persona version hash for effectiveness tracking."""
    conn = _connection._connect()
    if not conn:
        return False
    try:
        with _connection.owned_write(conn):
            if not records.is_visible(conn, "study_sessions", study_id):
                return False
            conn.execute(
                "UPDATE study_sessions SET persona_hash = ? WHERE id = ?",
                (persona_hash, study_id),
            )
        return True
    except sqlite3.OperationalError as exc:
        if not _connection.is_missing_table_error(exc):
            logger.warning("update_persona_hash failed: %s", exc)
            raise
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
        with _connection.owned_write(conn):
            if not records.is_visible(conn, "study_sessions", study_id):
                return False
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
        return True
    except sqlite3.OperationalError as exc:
        if not _connection.is_missing_table_error(exc):
            logger.warning("end_study_session failed: %s", exc)
            raise
        return False
    finally:
        conn.close()


def abort_study_session(study_id: str, reason: str) -> bool:
    """Mark a study session as ended when startup fails before steady state."""
    conn = _connection._connect()
    if not conn:
        return False
    try:
        now = datetime.now(UTC).isoformat()
        with _connection.owned_write(conn):
            if not records.is_visible(conn, "study_sessions", study_id):
                return False
            conn.execute(
                """
                UPDATE study_sessions
                SET ended_at = COALESCE(ended_at, ?),
                    duration_minutes = COALESCE(duration_minutes, 0),
                    notes = CASE
                        WHEN notes IS NULL OR notes = '' THEN ?
                        ELSE notes || char(10) || ?
                    END
                WHERE id = ?
                """,
                (now, reason, reason, study_id),
            )
        return True
    except sqlite3.OperationalError as exc:
        if not _connection.is_missing_table_error(exc):
            logger.warning("abort_study_session failed: %s", exc)
            raise
        return False
    finally:
        conn.close()


def get_study_session_stats(days: int = 30) -> list[dict]:
    """Get study session stats grouped by course slug (or raw topic) for the given period."""
    conn = _connection._connect()
    if not conn:
        return []
    try:
        clause, params = records.visible_sql(conn, "study_sessions")
        rows = conn.execute(
            f"""
            SELECT COALESCE(topic_slug, topic) AS course,
                   COUNT(*) as sessions,
                   SUM(duration_minutes) as total_minutes,
                   AVG(duration_minutes) as avg_minutes,
                   SUM(win_count) as total_wins,
                   SUM(struggle_count) as total_struggles,
                   energy_level as most_common_energy
            FROM study_sessions r
            WHERE ({clause}) AND started_at > datetime('now', ?)
              AND duration_minutes IS NOT NULL
            GROUP BY course
            ORDER BY total_minutes DESC
            """,
            [*params, f"-{days} days"],
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError as exc:
        if not _connection.is_missing_table_error(exc):
            logger.warning("get_study_session_stats failed: %s", exc)
            raise
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
        clause, params = records.visible_sql(conn, "study_sessions")
        rows = conn.execute(
            f"""
            SELECT energy_level,
                   duration_minutes,
                   CAST(julianday('now') - julianday(started_at) AS INTEGER) as days_ago
            FROM study_sessions r
            WHERE ({clause}) AND started_at > datetime('now', ?)
              AND duration_minutes IS NOT NULL
              AND energy_level IS NOT NULL
            ORDER BY started_at ASC
            """,
            [*params, f"-{days} days"],
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError as exc:
        if not _connection.is_missing_table_error(exc):
            logger.warning("get_energy_session_data failed: %s", exc)
            raise
        return []
    finally:
        conn.close()


def get_last_study_session() -> dict | None:
    """Most recent study_sessions row, for the web "Resume: <topic>" shortcut.

    Distinct from ``get_last_session_summary`` (which reads the agent-session
    ``sessions`` table): this is the learner's last STUDY session — topic +
    energy — so the Today panel can offer start-again-same-topic.
    """
    conn = _connection._connect()
    if not conn:
        return None
    try:
        clause, params = records.visible_sql(conn, "study_sessions")
        row = conn.execute(
            f"""
            SELECT topic, topic_slug, energy_level, started_at, ended_at
            FROM study_sessions r
            WHERE {clause}
            ORDER BY started_at DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
        return dict(row) if row else None
    except sqlite3.OperationalError as exc:
        if not _connection.is_missing_table_error(exc):
            logger.warning("get_last_study_session failed: %s", exc)
            raise
        return None
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
        policy = active_policy()
        scope = policy.request_scope()
        visible, params = visibility_sql(conn, "s.id", policy=policy, scope=scope)
        # Find the most recent session
        session = conn.execute(
            f"""
            SELECT s.id, s.source, s.project_path, s.created_at, s.updated_at
            FROM sessions s
            WHERE {visible}
            ORDER BY COALESCE(s.updated_at, s.created_at) DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
        if not session:
            return None

        session_id = session["id"]

        # Get last few messages for context
        visible_messages, message_params = visibility_sql(
            conn, "m.session_id", policy=policy, scope=scope
        )
        messages = conn.execute(
            f"""
            SELECT m.role, m.content FROM messages m
            WHERE m.session_id = ? AND m.role IN ('user', 'assistant')
              AND {visible_messages}
            ORDER BY COALESCE(m.seq, m.rowid) DESC
            LIMIT 6
            """,
            (session_id, *message_params),
        ).fetchall()

        # Global progress rows can combine multiple conversations. A last-source
        # pointer cannot establish ownership of the whole merged record. Retain
        # legacy inspection only for an explicitly unclassified, unassigned DB.
        progress_visible = legacy_global_visible(conn)
        in_progress = sorted(
            (r for r in observations.rows(conn) if r["confidence"] in ("struggling", "learning")),
            key=lambda row: row["last_seen"],
            reverse=True,
        )[:5]

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
                {
                    "concept": r["concept"],
                    "topic": r["topic"],
                    "confidence": r["confidence"],
                    "confidence_status": r.get("confidence_status"),
                    "observation_ids": r.get("observation_ids", []),
                }
                for r in in_progress
            ],
            "concepts_scope_status": (
                "scoped_observations"
                if any(r.get("observation_ids") for r in in_progress)
                else "explicit_unclassified_legacy_inspection"
                if progress_visible
                else "withheld_missing_scope_lineage"
            ),
        }
    except sqlite3.OperationalError as exc:
        if not _connection.is_missing_table_error(exc):
            logger.warning("get_last_session_summary failed: %s", exc)
            raise
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
        clause, values = records.visible_sql(conn, "study_sessions")
        sql = f"""
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
            FROM study_sessions r
            WHERE ({clause}) AND persona_hash IS NOT NULL
              AND win_count IS NOT NULL
        """
        params: list = values
        if persona_hash:
            sql += " AND persona_hash = ?"
            params.append(persona_hash)
        sql += " GROUP BY persona_hash ORDER BY sessions DESC"

        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError as exc:
        if not _connection.is_missing_table_error(exc):
            logger.warning("get_persona_effectiveness failed: %s", exc)
            raise
        return []
    finally:
        conn.close()
