"""Shared database connection helpers for the history package."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from ..settings import load_settings

if TYPE_CHECKING:
    from pathlib import Path


def _find_db() -> Path | None:
    db = load_settings().session_db
    return db if db.exists() else None


def _connect() -> sqlite3.Connection | None:
    db = _find_db()
    if not db:
        return None
    conn = sqlite3.connect(db, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn
