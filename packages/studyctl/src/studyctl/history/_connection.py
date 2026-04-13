"""Shared database connection helpers for the history package.

Auto-creates the sessions DB and applies migrations on first use,
so ``studyctl study`` works on a fresh machine without ``studyctl doctor``
or any other bootstrap step.
"""

from __future__ import annotations

import logging

from ..db import connect_db
from ..settings import load_settings

logger = logging.getLogger(__name__)


def _get_db_path():
    """Return the configured sessions DB path (always a Path, never None)."""
    return load_settings().session_db


def _has_schema(conn) -> bool:
    """Check whether the study_sessions table exists."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='study_sessions'"
    ).fetchone()
    return row is not None


def _connect():
    """Open a connection to sessions.db, applying schema and migrations.

    On every connection: applies base schema if tables are missing, then
    runs any pending migrations.  Both operations are idempotent.
    Returns ``None`` only if agent-session-tools is not installed or
    schema setup fails.
    """
    db = _get_db_path()
    db.parent.mkdir(parents=True, exist_ok=True)

    conn = connect_db(db, row_factory=True)

    try:
        from agent_session_tools.export_sessions import SCHEMA_FILE
        from agent_session_tools.migrations import migrate
    except ImportError:
        # Without agent-session-tools we can still read an existing DB
        # but cannot create or upgrade one.
        if _has_schema(conn):
            return conn
        logger.warning("agent-session-tools not installed — cannot initialise sessions DB")
        conn.close()
        return None

    try:
        if not _has_schema(conn):
            with open(SCHEMA_FILE) as f:
                conn.executescript(f.read())
            logger.info("Created sessions DB at %s", db)

        # Always run pending migrations — safe on an up-to-date DB
        migrate(conn)
    except Exception:
        logger.exception("Failed to initialise/migrate sessions DB")
        conn.close()
        return None

    return conn
