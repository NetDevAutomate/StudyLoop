"""Shared SQLite connection factory.

All write-path database access (parking, review_db, history) should use
``connect_db()`` to ensure consistent WAL mode, busy timeout, and
connection options.
"""

from __future__ import annotations

import sqlite3
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


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
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn
