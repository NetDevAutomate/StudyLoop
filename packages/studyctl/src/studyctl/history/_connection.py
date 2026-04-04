"""Shared database connection helpers for the history package.

Auto-creates the sessions DB and applies migrations on first use,
so ``studyctl study`` works on a fresh machine without ``studyctl doctor``
or any other bootstrap step.
"""

from __future__ import annotations

import logging
import sqlite3

from ..settings import load_settings

logger = logging.getLogger(__name__)


def _get_db_path():
    """Return the configured sessions DB path (always a Path, never None)."""
    return load_settings().session_db


def _connect() -> sqlite3.Connection | None:
    """Open a connection to sessions.db, creating it if necessary.

    On first use the file and all tables are created via the
    agent-session-tools migration chain.  Returns ``None`` only if
    the migration import is unavailable (agent-session-tools not
    installed).
    """
    db = _get_db_path()
    db.parent.mkdir(parents=True, exist_ok=True)

    is_new = not db.exists()
    conn = sqlite3.connect(db, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")

    if is_new:
        try:
            from agent_session_tools.migrations import migrate

            migrate(conn)
            logger.info("Created sessions DB at %s", db)
        except ImportError:
            logger.debug("agent-session-tools not installed — skipping migrations")
        except Exception:
            logger.exception("Failed to initialise sessions DB")
            conn.close()
            return None

    return conn
