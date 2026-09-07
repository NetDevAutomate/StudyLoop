"""`init_db` must converge a legacy-shaped database, not abort on it.

A legacy sessions.db (tables created by old StudyLoop/exporter versions,
missing later columns like ``sessions.project_path`` or
``study_sessions.topic``) used to fail schema bootstrap on the first CREATE
INDEX that referenced a missing column. That failure was tolerated while
every feature lazily built only what it needed; the context-memory read
paths require the full schema, so init_db now reconciles the legacy shape
first (see ``_reconcile_legacy_base_tables``).
"""

import sqlite3

import pytest

pytestmark = []

LEGACY_SCHEMA = """
CREATE TABLE IF NOT EXISTS study_sessions (id TEXT PRIMARY KEY, started_at TEXT);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, source TEXT, created_at TEXT, updated_at TEXT
);
"""


@pytest.fixture
def legacy_db_path(tmp_path):
    db = tmp_path / "sessions.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(LEGACY_SCHEMA)
        conn.execute(
            "INSERT INTO sessions(id,source,created_at) VALUES ('legacy1','kiro','2024-01-01')"
        )
    return db


def test_init_db_converges_a_legacy_database(legacy_db_path):
    from agent_session_tools.export_sessions import init_db

    conn = init_db(str(legacy_db_path))
    try:
        sessions_cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
        assert "project_path" in sessions_cols  # schema.sql's index needs it
        study_cols = {r[1] for r in conn.execute("PRAGMA table_info(study_sessions)")}
        assert "topic" in study_cols  # migration v9's index needs it
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='messages'"
        ).fetchone(), "schema.sql tables must be created around the legacy ones"
        # Existing data is preserved, never rebuilt.
        assert conn.execute("SELECT id FROM sessions").fetchone()[0] == "legacy1"
    finally:
        conn.close()


def test_init_db_on_legacy_db_is_repeatable(legacy_db_path):
    """Second run must be a no-op, not a duplicate-column failure."""
    from agent_session_tools.export_sessions import init_db

    init_db(str(legacy_db_path)).close()
    conn = init_db(str(legacy_db_path))
    try:
        assert conn.execute("SELECT id FROM sessions").fetchone()[0] == "legacy1"
    finally:
        conn.close()
