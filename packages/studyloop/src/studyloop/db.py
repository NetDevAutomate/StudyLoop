"""Shared SQLite connection factory.

All write-path database access (parking, review_db, history) should use
``connect_db()`` to ensure consistent WAL mode, busy timeout, and
connection options.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


#: Serialises the *self-healing* schema CREATEs that several modules perform on
#: first write (see :func:`studyloop.notes._connect`).
#:
#: ``PRAGMA user_version`` can run ahead of the real schema when a migration
#: partially applies, so those modules check for their table directly and
#: CREATE it if absent. Uvicorn serves sync endpoints on a threadpool, so two
#: concurrent first-writers can reach that check together — one wins the
#: CREATE and the other raises. Holding this lock across check-and-create makes
#: the recovery path idempotent between threads.
#:
#: Guards schema repair only. Normal reads and writes rely on WAL plus
#: ``busy_timeout``, so this is not a global database mutex.
SCHEMA_LOCK = threading.Lock()


def _ensure_wal(conn: sqlite3.Connection) -> None:
    """Put the database in WAL mode, tolerating a concurrent converter.

    ``journal_mode`` is a *persistent, database-level* property: once any
    connection sets WAL it stays WAL, so this only ever has real work to do on a
    brand-new file. Changing it needs a lock that SQLite refuses **immediately**
    with ``SQLITE_BUSY`` instead of honouring ``busy_timeout`` -- so several
    connections opening a brand-new database at once collide, and all but one
    raise ``OperationalError: database is locked``.

    That is not hypothetical. The web SPA fires ``/api/now``, ``/api/backlog``,
    ``/api/session/last`` and ``/api/history`` in parallel on page load, each
    opening its own connection, and ``history/_connection.py`` calls this
    function *outside* its try block -- so on a first run the busy error escaped
    as an unhandled exception and the request became an HTTP 500.

    A connection that loses the race is still completely usable; it simply runs
    until the winner's conversion lands. So read the mode first, skip the write
    when it is already WAL, and treat a busy failure as benign.
    """
    try:
        row = conn.execute("PRAGMA journal_mode").fetchone()
    except sqlite3.OperationalError:  # pragma: no cover - defensive
        row = None
    if row is not None and str(row[0]).lower() == "wal":
        return
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError as exc:
        # Another connection is converting the same new file. Benign: it is a
        # database-level property and the winner's change applies to us too.
        logger.debug("journal_mode=WAL deferred to a concurrent connection: %s", exc)


def connect_db(db_path: Path | str, *, row_factory: bool = False) -> sqlite3.Connection:
    """Open a SQLite connection with WAL mode and busy timeout.

    Args:
        db_path: Path to the database file.
        row_factory: If True, set ``sqlite3.Row`` as the row factory
            so rows can be accessed by column name.

    Returns:
        Configured connection. Caller is responsible for closing it.
    """
    conn = sqlite3.connect(str(db_path), timeout=5)
    if row_factory:
        conn.row_factory = sqlite3.Row
    # busy_timeout first, so the pragmas that follow can actually wait.
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    _ensure_wal(conn)
    return conn
