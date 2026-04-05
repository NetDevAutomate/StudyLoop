"""Parking lot persistence — store and manage tangential topics for future sessions.

During a study session, the AI agent parks tangential questions here.
At session start, unresolved parked topics are surfaced via ``studyctl resume``.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime

from studyctl.db import connect_db
from studyctl.settings import get_db_path

logger = logging.getLogger(__name__)


def _connect() -> sqlite3.Connection:
    """Get a connection to the session DB with WAL mode and busy timeout.

    Ensures the parked_topics table is present and up to date:
    1. Always run migrations (idempotent — skips already-applied versions)
    2. If that fails (version/schema drift), create the table directly

    The fallback handles a real-world failure mode: PRAGMA user_version
    can advance past the actual schema state if a migration partially
    succeeds. When that happens, the migration system skips the CREATE
    TABLE (thinks it already ran) and later migrations fail because the
    table doesn't exist. The direct CREATE is self-healing for this case.
    """
    conn = connect_db(get_db_path(), row_factory=True)

    # Always run migrations — they're idempotent (check user_version)
    # and handle both missing tables AND missing columns from newer versions.
    try:
        from agent_session_tools.migrations import migrate

        migrate(conn)
    except Exception:
        pass

    # If migrations didn't create the table, create it directly (self-healing)
    try:
        conn.execute("SELECT 1 FROM parked_topics LIMIT 0")
    except sqlite3.OperationalError:
        logger.info("Creating parked_topics table directly (migration drift recovery)")
        _create_parked_topics_table(conn)

    return conn


def _create_parked_topics_table(conn: sqlite3.Connection) -> None:
    """Create parked_topics with the full current schema.

    This is a last-resort fallback when the migration system can't
    self-heal. The schema matches the cumulative result of v14-v17:
    - v14: base table
    - v15: unique index (session_id, question)
    - v16: source, tech_area columns; index updated to include source
    - v17: priority column

    Uses IF NOT EXISTS / IF NOT EXISTS throughout so it's safe to call
    repeatedly — idempotency means no harm if the table already exists.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS parked_topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            study_session_id TEXT REFERENCES study_sessions(id) ON DELETE SET NULL,
            session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
            topic_tag TEXT,
            question TEXT NOT NULL,
            context TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'scheduled', 'resolved', 'dismissed')),
            scheduled_for TEXT,
            resolved_at TEXT,
            parked_at TEXT NOT NULL DEFAULT (datetime('now')),
            created_by TEXT DEFAULT 'agent',
            source TEXT NOT NULL DEFAULT 'parked',
            tech_area TEXT,
            priority INTEGER
        )
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uix_parked_topics_session_question
        ON parked_topics (study_session_id, question, source)
    """)
    conn.commit()


def park_topic(
    question: str,
    topic_tag: str | None = None,
    context: str | None = None,
    study_session_id: str | None = None,
    session_id: str | None = None,
    created_by: str = "agent",
    source: str = "parked",
    tech_area: str | None = None,
) -> int | None:
    """Park a tangential topic for later. Returns the row ID or None on failure.

    If the topic already exists for this session+source (INSERT OR IGNORE),
    the existing row's ID is returned instead of 0.

    Args:
        source: Origin of the entry — 'parked', 'struggled', or 'manual'.
        tech_area: Technology category (e.g. 'Python', 'SQL').
    """
    try:
        conn = _connect()
        try:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO parked_topics
                   (study_session_id, session_id, topic_tag, question,
                    context, created_by, source, tech_area)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    study_session_id,
                    session_id,
                    topic_tag,
                    question,
                    context,
                    created_by,
                    source,
                    tech_area,
                ),
            )
            conn.commit()
            if cursor.rowcount > 0:
                return cursor.lastrowid
            # Insert was ignored (duplicate) — fetch existing row ID
            row = conn.execute(
                """SELECT id FROM parked_topics
                   WHERE study_session_id IS ? AND question = ? AND source = ?""",
                (study_session_id, question, source),
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
    source: str | None = None,
    tech_area: str | None = None,
) -> list[dict]:
    """Get parked topics with optional filters.

    Args:
        study_session_id: Filter by specific study session.
        status: Filter by status (default 'pending').
        source: Filter by source ('parked', 'struggled', 'manual').
        tech_area: Filter by technology area.
    """
    conn = _connect()
    try:
        clauses = ["status = ?"]
        params: list[str] = [status]
        if study_session_id:
            clauses.append("study_session_id = ?")
            params.append(study_session_id)
        if source:
            clauses.append("source = ?")
            params.append(source)
        if tech_area:
            clauses.append("tech_area = ?")
            params.append(tech_area)
        where = " AND ".join(clauses)
        order = "parked_at" if study_session_id else "parked_at DESC"
        rows = conn.execute(
            f"SELECT * FROM parked_topics WHERE {where} ORDER BY {order}",
            params,
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


def get_topic_frequencies(status: str = "pending") -> dict[str, int]:
    """Count how many times each question appears in parked_topics.

    Returns a dict mapping question text to its frequency count.
    """
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT question, COUNT(*) as freq
               FROM parked_topics WHERE status = ?
               GROUP BY question ORDER BY freq DESC""",
            (status,),
        ).fetchall()
        return {row["question"]: row["freq"] for row in rows}
    finally:
        conn.close()


def update_topic_priority(parked_id: int, priority: int) -> bool:
    """Set the agent-assessed importance (1-5) on a backlog item."""
    conn = _connect()
    try:
        cursor = conn.execute(
            "UPDATE parked_topics SET priority = ? WHERE id = ?",
            (priority, parked_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
