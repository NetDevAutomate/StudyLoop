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
from pathlib import Path

import pytest

from agent_session_tools.migrations import (
    CURRENT_VERSION,
    MIGRATIONS,
    get_user_version,
    migrate,
    set_user_version,
)

pytestmark = []

SCHEMA_PATH = (
    Path(__file__).parent.parent / "src" / "agent_session_tools" / "schema.sql"
)

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


def _database_stopped_at(tmp_path: Path, version: int) -> Path:
    """A sessions.db exactly as a fresh install left it at schema ``version``.

    schema.sql plus migrations 1..version, with ``user_version`` recorded --
    the shape of a database last touched by an older release.
    """
    db = tmp_path / f"sessions-v{version}.db"
    conn = sqlite3.connect(db)
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        for v in range(1, version + 1):
            MIGRATIONS[v][1](conn)
            set_user_version(conn, v)
        conn.execute(
            "INSERT INTO sessions(id,source,created_at) VALUES ('kept','kiro','2024-01-01')"
        )
        conn.commit()
    finally:
        conn.close()
    return db


def _widen_to_final_shape(conn: sqlite3.Connection) -> None:
    """What ``_reconcile_legacy_base_tables`` did before the fix.

    It diffed every live table against the *final* schema and ADDed each
    missing column -- including columns a not-yet-applied migration was
    about to add itself. Those ALTERs auto-committed before ``migrate()``
    ran and then survived its rollback, so a database it touched once was
    left with the columns present and ``user_version`` unchanged.
    """
    pristine = sqlite3.connect(":memory:")
    try:
        pristine.executescript(SCHEMA_PATH.read_text())
        migrate(pristine)
        tables = [
            row[0]
            for row in pristine.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        ]
        for table in tables:
            live = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
            if not live:
                continue
            for _, name, ctype, _, default, pk in pristine.execute(
                f'PRAGMA table_info("{table}")'
            ).fetchall():
                if name in live or pk:
                    continue
                ddl = f'ALTER TABLE "{table}" ADD COLUMN "{name}" {ctype}'
                if default is not None and "(" not in str(default):
                    ddl += f" DEFAULT {default}"
                conn.execute(ddl)
        conn.commit()
    finally:
        pristine.close()


@pytest.mark.parametrize("version", range(CURRENT_VERSION))
def test_init_db_converges_a_database_stopped_at_any_version(tmp_path, version):
    """Every release's schema must migrate forward through ``init_db``.

    The legacy reconciliation runs *before* the migrations. If it adds a
    column a pending migration adds unguarded, that migration fails with
    ``duplicate column name`` and the whole sequence rolls back -- which is
    how a v30 database (practice_attempts from v24, ``topic`` added by v37)
    could never reach v48.
    """
    from agent_session_tools.export_sessions import init_db

    conn = init_db(str(_database_stopped_at(tmp_path, version)))
    try:
        assert get_user_version(conn) == CURRENT_VERSION
        assert conn.execute("SELECT id FROM sessions").fetchone()[0] == "kept"
    finally:
        conn.close()


@pytest.mark.parametrize("version", range(CURRENT_VERSION))
def test_migrate_recovers_a_database_the_old_reconciliation_already_widened(
    tmp_path, version
):
    """Databases the old reconciliation touched are stuck until migrations tolerate it.

    Such a database already carries every final-shape column while its
    ``user_version`` still says ``version``. ``session-maint embed`` calls
    ``migrate()`` directly on it (no reconciliation), so the pending
    migrations themselves must skip a column that is already there.
    """
    db = _database_stopped_at(tmp_path, version)
    conn = sqlite3.connect(db)
    try:
        _widen_to_final_shape(conn)
        assert get_user_version(conn) == version

        migrate(conn)

        assert get_user_version(conn) == CURRENT_VERSION
        assert conn.execute("SELECT id FROM sessions").fetchone()[0] == "kept"
    finally:
        conn.close()
