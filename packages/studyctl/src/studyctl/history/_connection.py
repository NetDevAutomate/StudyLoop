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


def _connect():
    """Open a connection to sessions.db, creating it if necessary.

    On first use the file and all tables are created via the
    agent-session-tools migration chain.  Returns ``None`` only if
    the migration import is unavailable (agent-session-tools not
    installed).
    """
    db = _get_db_path()
    db.parent.mkdir(parents=True, exist_ok=True)

    is_new = not db.exists()
    conn = connect_db(db, row_factory=True)

    if is_new:
        try:
            from agent_session_tools.export_sessions import SCHEMA_FILE
            from agent_session_tools.migrations import migrate

            # Apply base schema first — migrations assume tables exist
            with open(SCHEMA_FILE) as f:
                conn.executescript(f.read())

            migrate(conn)
            logger.info("Created sessions DB at %s", db)
        except ImportError:
            logger.debug("agent-session-tools not installed — skipping migrations")
        except Exception:
            logger.exception("Failed to initialise sessions DB")
            conn.close()
            return None

    return conn
