"""Shared database connection helpers for the history package.

Auto-creates the sessions DB and applies migrations on first use,
so ``studyloop study`` works on a fresh machine without ``studyloop doctor``
or any other bootstrap step.
"""

from __future__ import annotations

import logging
import uuid

from ..db import connect_db
from ..settings import load_settings

logger = logging.getLogger(__name__)


def progress_id_for(topic: str, concept: str) -> str:
    """Deterministic ``study_progress.id`` for a normalised (topic, concept) pair.

    Shared by ``history/teachback.py`` and ``history/progress.py`` -- both
    upsert the *same* ``study_progress`` row for a given (topic, concept), so
    they must derive the same id or one write silently orphans the other's row.

    R-21: a plain ``f"{topic}:{concept}"`` join is separator-unsafe --
    ``("a:b", "c")`` and ``("a", "b:c")`` both join to ``"a:b:c"`` and collide
    on the same id. Escaping a literal ``\\`` to ``\\\\`` and ``:`` to ``\\:``
    in each field before joining makes the join reversible (hence
    collision-free) while leaving the common case -- neither field contains
    ``:`` or ``\\`` -- byte-for-byte identical to the old join. Every existing
    id computed by the old formula therefore stays valid; nothing needs a data
    migration unless a topic or concept name has ever contained a literal
    colon or backslash, which no shipped topic/concept name does today.
    """

    def _escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace(":", "\\:")

    joined = f"{_escape(topic)}:{_escape(concept)}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, joined))


def is_missing_table_error(exc: BaseException) -> bool:
    """True when a caught ``sqlite3.OperationalError`` means "no such table".

    R-22: SQLite has no exception subtype for a missing table — both a
    genuinely absent table (an old schema, pre-migration) and a real fault
    (a lock timeout, a busy-DB error) raise the same
    ``sqlite3.OperationalError``, distinguishable only by matching its
    message. Only the first is safe to treat as "nothing to show"; a caller
    must log and re-raise anything else, or a lock collision reads back
    indistinguishably from "no struggling topics" / "no wins" / "no progress"
    — the exact defect ``e692510`` fixed for the explorer's FTS path.
    """
    return "no such table" in str(exc)


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
