"""Parking lot persistence — store and manage tangential topics for future sessions.

During a study session, the AI agent parks tangential questions here.
At session start, unresolved parked topics are surfaced via ``studyctl resume``.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime

from studyctl.settings import get_db_path

logger = logging.getLogger(__name__)


def _connect() -> sqlite3.Connection:
    """Get a connection to the session DB with WAL mode and busy timeout.

    Ensures the parked_topics table exists by running agent-session-tools
    migrations on first connect.
    """
    conn = sqlite3.connect(str(get_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")

    # Ensure parked_topics table exists (migration v14)
    try:
        conn.execute("SELECT 1 FROM parked_topics LIMIT 0")
    except sqlite3.OperationalError:
        try:
            from agent_session_tools.migrations import migrate

            migrate(conn)
        except Exception:
            logger.warning("Could not run migrations — parked_topics table may be missing")
    return conn


def park_topic(
    question: str,
    topic_tag: str | None = None,
    context: str | None = None,
    study_session_id: str | None = None,
    session_id: str | None = None,
    created_by: str = "agent",
) -> int | None:
    """Park a tangential topic for later. Returns the row ID or None on failure.

    If the topic already exists for this session (INSERT OR IGNORE), the
    existing row's ID is returned instead of 0.
    """
    try:
        conn = _connect()
        try:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO parked_topics
                   (study_session_id, session_id, topic_tag, question, context, created_by)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (study_session_id, session_id, topic_tag, question, context, created_by),
            )
            conn.commit()
            if cursor.rowcount > 0:
                return cursor.lastrowid
            # Insert was ignored (duplicate) — fetch existing row ID
            row = conn.execute(
                """SELECT id FROM parked_topics
                   WHERE study_session_id IS ? AND question = ?""",
                (study_session_id, question),
            ).fetchone()
            return row["id"] if row else None
        finally:
            conn.close()
    except Exception:
        logger.exception("Failed to park topic: %s", question)
        return None


def get_parked_topics(
    study_session_id: str | None = None,
    status: str = "pending",
) -> list[dict]:
    """Get parked topics, optionally filtered by study session and/or status."""
    conn = _connect()
    try:
        if study_session_id:
            rows = conn.execute(
                """SELECT * FROM parked_topics
                   WHERE study_session_id = ? AND status = ?
                   ORDER BY parked_at""",
                (study_session_id, status),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM parked_topics
                   WHERE status = ?
                   ORDER BY parked_at DESC""",
                (status,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_unscheduled_parked_topics(
    topic_tag: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Get pending parked topics for surfacing at session start."""
    conn = _connect()
    try:
        if topic_tag:
            rows = conn.execute(
                """SELECT * FROM parked_topics
                   WHERE status = 'pending' AND topic_tag = ?
                   ORDER BY parked_at DESC LIMIT ?""",
                (topic_tag, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM parked_topics
                   WHERE status = 'pending'
                   ORDER BY parked_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def schedule_parked_topic(parked_id: int, scheduled_for: str) -> bool:
    """Set a date for a parked topic. scheduled_for is ISO date string (YYYY-MM-DD)."""
    conn = _connect()
    try:
        cursor = conn.execute(
            """UPDATE parked_topics
               SET status = 'scheduled', scheduled_for = ?
               WHERE id = ? AND status IN ('pending', 'scheduled')""",
            (scheduled_for, parked_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def resolve_parked_topic(parked_id: int) -> bool:
    """Mark a parked topic as resolved/covered."""
    conn = _connect()
    try:
        cursor = conn.execute(
            """UPDATE parked_topics
               SET status = 'resolved', resolved_at = ?
               WHERE id = ? AND status IN ('pending', 'scheduled')""",
            (datetime.now().isoformat(), parked_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def dismiss_parked_topic(parked_id: int) -> bool:
    """Mark a parked topic as dismissed (not worth scheduling)."""
    conn = _connect()
    try:
        cursor = conn.execute(
            """UPDATE parked_topics
               SET status = 'dismissed'
               WHERE id = ? AND status = 'pending'""",
            (parked_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
