"""Database connection helpers for session querying.

Provides lazy config initialisation and a factory for SQLite connections.
All higher-level query modules depend on this layer — nothing here imports
from other query_* modules, keeping the dependency graph acyclic.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from agent_session_tools.config_loader import get_db_path, load_config

logger = logging.getLogger(__name__)

# Lazy config cache — populated on first use so that importing this module has
# no side effects (no file I/O, no logging config, no directory creation).
_config: dict | None = None


def _get_config() -> dict:
    """Return the loaded config, initialising on first call."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def get_default_db_path() -> Path:
    """Return the default database path from config (lazy — no import-time I/O)."""
    return get_db_path(_get_config())


def get_connection(db: Path | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with row_factory set to sqlite3.Row.

    Args:
        db: Explicit path to the database file.  When *None* the default path
            from the loaded config is used.
    """
    db_path = db if db else get_default_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
