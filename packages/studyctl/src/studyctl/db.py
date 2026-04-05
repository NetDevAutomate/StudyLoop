"""Shared SQLite connection factory.

All write-path database access (parking, review_db, history) should use
``connect_db()`` to ensure consistent WAL mode, busy timeout, and
connection options.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


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
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn
