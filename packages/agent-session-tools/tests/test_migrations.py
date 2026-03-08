"""Tests for database migration system."""

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

SCHEMA_PATH = (
    Path(__file__).parent.parent / "src" / "agent_session_tools" / "schema.sql"
)


@pytest.fixture
def fresh_db(tmp_path):
    """Create a fresh DB from schema.sql (simulates first-time setup)."""
    db_path = tmp_path / "sessions.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()
    yield conn
    conn.close()


class TestGetUserVersion:
    def test_returns_zero_for_fresh_db(self, fresh_db):
        assert get_user_version(fresh_db) == 0

    def test_returns_value_after_set(self, fresh_db):
        set_user_version(fresh_db, 5)
        assert get_user_version(fresh_db) == 5


class TestSetUserVersion:
    def test_updates_version(self, fresh_db):
        set_user_version(fresh_db, 3)
        assert get_user_version(fresh_db) == 3

    def test_overwrites_previous_version(self, fresh_db):
        set_user_version(fresh_db, 2)
        set_user_version(fresh_db, 7)
        assert get_user_version(fresh_db) == 7


class TestMigrate:
    def test_applies_pending_migrations(self, fresh_db):
        applied = migrate(fresh_db)
        assert len(applied) > 0
        assert get_user_version(fresh_db) == CURRENT_VERSION

    def test_already_migrated_returns_empty(self, fresh_db):
        migrate(fresh_db)
        second_run = migrate(fresh_db)
        assert second_run == []

    def test_all_versions_have_registered_migrations(self):
        for v in range(1, CURRENT_VERSION + 1):
            assert v in MIGRATIONS, f"Missing migration for version {v}"

    def test_key_tables_exist_after_migration(self, fresh_db):
        migrate(fresh_db)
        tables = {
            row[0]
            for row in fresh_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for expected in (
            "study_progress",
            "study_sessions",
            "session_tags",
            "session_notes",
        ):
            assert expected in tables, f"Table {expected} missing after migration"
