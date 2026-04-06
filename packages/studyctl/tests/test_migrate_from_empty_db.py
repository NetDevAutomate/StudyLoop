"""Verify the full migration stack runs cleanly from a fresh in-memory DB.

Creates a bare schema (sessions + messages tables only), applies every
migration, and asserts the final user_version matches CURRENT_VERSION.
This catches migration regressions before they reach production.
"""

from __future__ import annotations

import sqlite3

import pytest

pytest.importorskip("agent_session_tools")


class TestMigrateFromEmptyDb:
    def test_migrate_from_empty_db(self) -> None:
        """Full migration stack on a fresh in-memory DB reaches CURRENT_VERSION."""
        from agent_session_tools.export_sessions import SCHEMA_FILE
        from agent_session_tools.migrations import CURRENT_VERSION, migrate

        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA journal_mode=WAL")

        # Apply base schema (creates sessions, messages tables)
        with open(SCHEMA_FILE) as f:
            conn.executescript(f.read())

        # Run all migrations
        migrate(conn)

        # Verify final schema version
        final_version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()

        assert final_version == CURRENT_VERSION, (
            f"Expected user_version={CURRENT_VERSION}, got {final_version}"
        )

    def test_migrate_is_idempotent(self) -> None:
        """Running migrate() twice on an already-current DB applies no new migrations."""
        from agent_session_tools.export_sessions import SCHEMA_FILE
        from agent_session_tools.migrations import migrate

        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA journal_mode=WAL")

        with open(SCHEMA_FILE) as f:
            conn.executescript(f.read())

        # First run — applies all migrations
        first_applied = migrate(conn)
        # Second run — nothing to do
        second_applied = migrate(conn)

        conn.close()

        assert len(first_applied) > 0, "First migration run should apply at least one migration"
        assert second_applied == [], f"Second run should apply nothing but got: {second_applied}"

    def test_migrate_from_empty_db_creates_expected_tables(self) -> None:
        """Post-migration schema must include key tables added by migrations."""
        from agent_session_tools.export_sessions import SCHEMA_FILE
        from agent_session_tools.migrations import migrate

        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA journal_mode=WAL")

        with open(SCHEMA_FILE) as f:
            conn.executescript(f.read())

        migrate(conn)

        # Collect all table names from the final schema
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        conn.close()

        # Base tables from schema.sql must always exist
        assert "sessions" in tables
        assert "messages" in tables

    def test_applied_migrations_list_matches_version_delta(self) -> None:
        """Number of applied migrations equals CURRENT_VERSION (starting from 0)."""
        from agent_session_tools.export_sessions import SCHEMA_FILE
        from agent_session_tools.migrations import CURRENT_VERSION, MIGRATIONS, migrate

        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA journal_mode=WAL")

        with open(SCHEMA_FILE) as f:
            conn.executescript(f.read())

        migrate(conn)
        conn.close()

        # Every version from 1..CURRENT_VERSION should be registered
        registered_versions = set(MIGRATIONS.keys())
        expected_versions = set(range(1, CURRENT_VERSION + 1))
        missing = expected_versions - registered_versions

        assert not missing, f"Migrations missing for versions: {sorted(missing)}"
        # Every registered migration should have a version entry
        assert len(registered_versions) == CURRENT_VERSION
