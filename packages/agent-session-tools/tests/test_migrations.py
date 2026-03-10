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


class TestMigrationV12:
    """Test concept graph layer tables (concepts, aliases, relations)."""

    def test_creates_concepts_table(self, fresh_db):
        migrate(fresh_db)
        tables = {
            r[0]
            for r in fresh_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "concepts" in tables
        assert "concept_aliases" in tables
        assert "concept_relations" in tables

    def test_concepts_table_columns(self, fresh_db):
        migrate(fresh_db)
        cols = {
            r[1] for r in fresh_db.execute("PRAGMA table_info(concepts)").fetchall()
        }
        assert cols == {
            "id",
            "name",
            "domain",
            "description",
            "created_at",
            "updated_at",
        }

    def test_concept_aliases_table_columns(self, fresh_db):
        migrate(fresh_db)
        cols = {
            r[1]
            for r in fresh_db.execute("PRAGMA table_info(concept_aliases)").fetchall()
        }
        assert cols == {"alias", "concept_id"}

    def test_concept_relations_table_columns(self, fresh_db):
        migrate(fresh_db)
        cols = {
            r[1]
            for r in fresh_db.execute("PRAGMA table_info(concept_relations)").fetchall()
        }
        expected = {
            "id",
            "source_concept_id",
            "target_concept_id",
            "relation_type",
            "confidence",
            "evidence_session_id",
            "evidence_message_id",
            "created_by",
            "created_at",
            "updated_at",
        }
        assert cols == expected

    def test_concepts_unique_name_domain_index(self, fresh_db):
        migrate(fresh_db)
        # Insert a concept, then try a duplicate — should fail
        fresh_db.execute(
            "INSERT INTO concepts (id, name, domain) VALUES ('id1', 'closures', 'python')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            fresh_db.execute(
                "INSERT INTO concepts (id, name, domain) VALUES ('id2', 'closures', 'python')"
            )

    def test_concepts_same_name_different_domain_allowed(self, fresh_db):
        migrate(fresh_db)
        fresh_db.execute(
            "INSERT INTO concepts (id, name, domain) VALUES ('id1', 'partition', 'sql')"
        )
        fresh_db.execute(
            "INSERT INTO concepts (id, name, domain) VALUES ('id2', 'partition', 'spark')"
        )
        count = fresh_db.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]
        assert count == 2

    def test_concept_relations_unique_constraint(self, fresh_db):
        migrate(fresh_db)
        fresh_db.execute(
            "INSERT INTO concepts (id, name, domain) VALUES ('c1', 'a', 'python')"
        )
        fresh_db.execute(
            "INSERT INTO concepts (id, name, domain) VALUES ('c2', 'b', 'python')"
        )
        fresh_db.execute(
            "INSERT INTO concept_relations "
            "(source_concept_id, target_concept_id, relation_type) "
            "VALUES ('c1', 'c2', 'prerequisite')"
        )
        # Same edge again should fail
        with pytest.raises(sqlite3.IntegrityError):
            fresh_db.execute(
                "INSERT INTO concept_relations "
                "(source_concept_id, target_concept_id, relation_type) "
                "VALUES ('c1', 'c2', 'prerequisite')"
            )
        # Different relation_type should succeed
        fresh_db.execute(
            "INSERT INTO concept_relations "
            "(source_concept_id, target_concept_id, relation_type) "
            "VALUES ('c1', 'c2', 'confused_with')"
        )
        count = fresh_db.execute("SELECT COUNT(*) FROM concept_relations").fetchone()[0]
        assert count == 2

    def test_concept_relations_indexes_exist(self, fresh_db):
        migrate(fresh_db)
        indexes = {
            r[1]
            for r in fresh_db.execute(
                "SELECT * FROM sqlite_master WHERE type='index' "
                "AND tbl_name='concept_relations'"
            ).fetchall()
        }
        assert "idx_relations_source" in indexes
        assert "idx_relations_target" in indexes
        assert "idx_relations_type" in indexes


class TestMigrationV13:
    """Test message_concepts table and study_progress concept_id FK."""

    def test_creates_message_concepts_table(self, fresh_db):
        migrate(fresh_db)
        tables = {
            r[0]
            for r in fresh_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "message_concepts" in tables

    def test_message_concepts_columns(self, fresh_db):
        migrate(fresh_db)
        cols = {
            r[1]
            for r in fresh_db.execute("PRAGMA table_info(message_concepts)").fetchall()
        }
        assert cols == {"message_id", "concept_id", "confidence"}

    def test_study_progress_has_concept_id_column(self, fresh_db):
        migrate(fresh_db)
        cols = {
            r[1]
            for r in fresh_db.execute("PRAGMA table_info(study_progress)").fetchall()
        }
        assert "concept_id" in cols

    def test_message_concepts_index_exists(self, fresh_db):
        migrate(fresh_db)
        indexes = {
            r[1]
            for r in fresh_db.execute(
                "SELECT * FROM sqlite_master WHERE type='index' "
                "AND tbl_name='message_concepts'"
            ).fetchall()
        }
        assert "idx_msg_concepts_concept" in indexes
