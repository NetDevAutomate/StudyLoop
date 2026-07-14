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

# Schema ownership notes:
# - agent-session-tools owns the base sessions.db schema and forward migrations.
# - studyloop.history.progress consumes study_progress and must tolerate DBs
#   created before the v22 provenance-column migration.
# - explorer_fts.db is a derived web cache; it is rebuilt/refreshed by
#   StudyLoop web routes and is intentionally not migrated here.


@pytest.fixture
def fresh_db(tmp_path):
    """Create a fresh DB from schema.sql (simulates first-time setup)."""
    db_path = tmp_path / "sessions.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()
    yield conn
    conn.close()


def legacy_v0_connection(tmp_path: Path) -> sqlite3.Connection:
    """Create a minimal pre-migration DB with user data."""
    db_path = tmp_path / "legacy-v0.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            project_path TEXT,
            git_branch TEXT,
            created_at TEXT,
            updated_at TEXT,
            metadata JSON
        );

        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            parent_id TEXT,
            role TEXT NOT NULL,
            content TEXT,
            model TEXT,
            timestamp TEXT,
            metadata JSON
        );

        CREATE INDEX idx_messages_session ON messages(session_id);
        CREATE INDEX idx_messages_timestamp ON messages(timestamp);
        CREATE INDEX idx_sessions_source ON sessions(source);
        CREATE INDEX idx_sessions_project ON sessions(project_path);

        CREATE VIRTUAL TABLE messages_fts USING fts5(
            content,
            session_id UNINDEXED,
            role UNINDEXED,
            tokenize='porter unicode61'
        );

        CREATE TRIGGER messages_fts_insert AFTER INSERT ON messages
        WHEN NEW.content IS NOT NULL
        BEGIN
            INSERT INTO messages_fts(rowid, content, session_id, role)
            VALUES (NEW.rowid, NEW.content, NEW.session_id, NEW.role);
        END;

        INSERT INTO sessions (
            id, source, project_path, git_branch, created_at, updated_at, metadata
        ) VALUES (
            'legacy-session', 'claude_code', '/tmp/studyloop', 'main',
            '2026-01-01T00:00:00Z', '2026-01-01T00:01:00Z', '{}'
        );

        INSERT INTO messages (
            id, session_id, parent_id, role, content, model, timestamp, metadata
        ) VALUES (
            'legacy-message', 'legacy-session', NULL, 'user',
            'legacy migration smoke content', NULL,
            '2026-01-01T00:00:30Z', '{}'
        );
        """
    )
    conn.commit()
    return conn


def legacy_nullable_message_metadata_connection(tmp_path: Path) -> sqlite3.Connection:
    """Create a pre-migration DB with nullable message metadata columns."""
    db_path = tmp_path / "legacy-nullable-message-metadata.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            project_path TEXT,
            git_branch TEXT,
            created_at TEXT,
            updated_at TEXT,
            metadata JSON
        );

        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            session_id TEXT,
            parent_id TEXT,
            role TEXT,
            content TEXT,
            model TEXT,
            timestamp TEXT,
            metadata JSON
        );

        CREATE VIRTUAL TABLE messages_fts USING fts5(
            content,
            session_id UNINDEXED,
            role UNINDEXED,
            tokenize='porter unicode61'
        );

        CREATE TRIGGER messages_fts_insert AFTER INSERT ON messages
        WHEN NEW.content IS NOT NULL
        BEGIN
            INSERT INTO messages_fts(rowid, content, session_id, role)
            VALUES (NEW.rowid, NEW.content, NEW.session_id, NEW.role);
        END;

        INSERT INTO sessions (
            id, source, project_path, git_branch, created_at, updated_at, metadata
        ) VALUES (
            'session-1', 'claude_code', '/tmp/studyloop', 'main',
            '2026-01-01T00:00:00Z', '2026-01-01T00:01:00Z', '{}'
        );

        INSERT INTO messages (
            id, session_id, parent_id, role, content, model, timestamp, metadata
        ) VALUES
            (
                'null-role-message', 'session-1', NULL, NULL,
                'metadata transition role content', NULL,
                '2026-01-01T00:00:30Z', '{}'
            ),
            (
                'null-session-message', NULL, NULL, 'assistant',
                'metadata transition session content', NULL,
                '2026-01-01T00:00:40Z', '{}'
            );
        """
    )
    conn.commit()
    return conn


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

    def test_legacy_v0_database_migrates_to_current_version(self, tmp_path):
        conn = legacy_v0_connection(tmp_path)
        try:
            applied = migrate(conn)

            assert applied
            assert get_user_version(conn) == CURRENT_VERSION
            row = conn.execute(
                "SELECT content FROM messages WHERE id = 'legacy-message'"
            ).fetchone()
            assert row == ("legacy migration smoke content",)
        finally:
            conn.close()

    def test_legacy_v0_database_keeps_fts_readable_after_migration(self, tmp_path):
        conn = legacy_v0_connection(tmp_path)
        try:
            migrate(conn)

            rows = conn.execute(
                "SELECT content FROM messages_fts WHERE messages_fts MATCH 'legacy'"
            ).fetchall()
            assert rows == [("legacy migration smoke content",)]
        finally:
            conn.close()

    def test_legacy_v0_database_has_study_progress_provenance_after_migration(
        self, tmp_path
    ):
        conn = legacy_v0_connection(tmp_path)
        try:
            migrate(conn)

            cols = {
                r[1]
                for r in conn.execute("PRAGMA table_info(study_progress)").fetchall()
            }
            assert {
                "source_course",
                "source_section",
                "source_publisher",
                "created_by",
            } <= cols
        finally:
            conn.close()

    def test_legacy_v0_database_keeps_foreign_keys_enabled_after_migration(
        self, tmp_path
    ):
        conn = legacy_v0_connection(tmp_path)
        try:
            migrate(conn)

            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        finally:
            conn.close()

    def test_fts_update_indexes_null_to_text_transition(self, tmp_path):
        conn = legacy_v0_connection(tmp_path)
        try:
            migrate(conn)
            conn.execute(
                """
                INSERT INTO messages (
                    id, session_id, parent_id, role, content, model, timestamp, metadata
                ) VALUES (
                    'null-message', 'legacy-session', NULL, 'assistant',
                    NULL, NULL, '2026-01-01T00:00:40Z', '{}'
                )
                """
            )
            conn.execute(
                "UPDATE messages SET content = ? WHERE id = ?",
                ("late indexed content", "null-message"),
            )
            rows = conn.execute(
                "SELECT content FROM messages_fts WHERE messages_fts MATCH 'late'"
            ).fetchall()
            assert rows == [("late indexed content",)]
        finally:
            conn.close()

    def test_fts_update_removes_text_to_null_transition(self, tmp_path):
        conn = legacy_v0_connection(tmp_path)
        try:
            migrate(conn)
            conn.execute(
                "UPDATE messages SET content = NULL WHERE id = 'legacy-message'"
            )
            rows = conn.execute(
                "SELECT content FROM messages_fts WHERE messages_fts MATCH 'legacy'"
            ).fetchall()
            assert rows == []
        finally:
            conn.close()

    def test_fts_update_handles_role_null_to_value_transition(self, tmp_path):
        conn = legacy_nullable_message_metadata_connection(tmp_path)
        try:
            migrate(conn)

            conn.execute(
                "UPDATE messages SET role = ? WHERE id = ?",
                ("assistant", "null-role-message"),
            )
            row = conn.execute(
                """
                SELECT role
                FROM messages_fts
                WHERE messages_fts MATCH 'metadata'
                  AND rowid = (
                      SELECT rowid FROM messages WHERE id = 'null-role-message'
                  )
                """
            ).fetchone()
            assert row == ("assistant",)
        finally:
            conn.close()

    def test_fts_update_handles_session_id_null_to_value_transition(self, tmp_path):
        conn = legacy_nullable_message_metadata_connection(tmp_path)
        try:
            migrate(conn)

            conn.execute(
                "UPDATE messages SET session_id = ? WHERE id = ?",
                ("session-1", "null-session-message"),
            )
            row = conn.execute(
                """
                SELECT session_id
                FROM messages_fts
                WHERE messages_fts MATCH 'metadata'
                  AND rowid = (
                      SELECT rowid FROM messages WHERE id = 'null-session-message'
                  )
                """
            ).fetchone()
            assert row == ("session-1",)
        finally:
            conn.close()

    def test_legacy_v0_database_migration_is_idempotent(self, tmp_path):
        conn = legacy_v0_connection(tmp_path)
        try:
            migrate(conn)
            second = migrate(conn)

            assert second == []
            assert get_user_version(conn) == CURRENT_VERSION
        finally:
            conn.close()


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


class TestMigrationV16:
    """Test parked_topics source/tech_area migration idempotency."""

    def test_skips_existing_source_column_and_rebuilds_index(self, fresh_db):
        fresh_db.executescript(
            """
            CREATE TABLE parked_topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                study_session_id TEXT,
                session_id TEXT,
                topic_tag TEXT,
                question TEXT NOT NULL,
                context TEXT,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'scheduled', 'resolved', 'dismissed')),
                scheduled_for TEXT,
                resolved_at TEXT,
                parked_at TEXT NOT NULL DEFAULT (datetime('now')),
                created_by TEXT DEFAULT 'agent',
                source TEXT NOT NULL DEFAULT 'parked',
                tech_area TEXT
            );
            CREATE UNIQUE INDEX uix_parked_topics_session_question
            ON parked_topics (study_session_id, question);
            """
        )

        from agent_session_tools.migrations import migrate_v16

        migrate_v16(fresh_db)

        cols = {r[1] for r in fresh_db.execute("PRAGMA table_info(parked_topics)")}
        assert "source" in cols
        assert "tech_area" in cols

        index_cols = [
            r[2]
            for r in fresh_db.execute(
                "PRAGMA index_info(uix_parked_topics_session_question)"
            ).fetchall()
        ]
        assert index_cols == ["study_session_id", "question", "source"]


class TestMigrationV17:
    """Test parked_topics priority migration idempotency."""

    def test_skips_existing_priority_column(self, fresh_db):
        fresh_db.executescript(
            """
            CREATE TABLE parked_topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                study_session_id TEXT,
                session_id TEXT,
                topic_tag TEXT,
                question TEXT NOT NULL,
                context TEXT,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'scheduled', 'resolved', 'dismissed')),
                scheduled_for TEXT,
                resolved_at TEXT,
                parked_at TEXT NOT NULL DEFAULT (datetime('now')),
                created_by TEXT DEFAULT 'agent',
                source TEXT NOT NULL DEFAULT 'parked',
                tech_area TEXT,
                priority INTEGER
            );
            """
        )

        from agent_session_tools.migrations import migrate_v17

        migrate_v17(fresh_db)

        cols = {r[1] for r in fresh_db.execute("PRAGMA table_info(parked_topics)")}
        assert "priority" in cols

    def test_v16_and_v17_tolerate_already_extended_table(self, fresh_db):
        fresh_db.executescript(
            """
            CREATE TABLE parked_topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                study_session_id TEXT,
                session_id TEXT,
                topic_tag TEXT,
                question TEXT NOT NULL,
                context TEXT,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'scheduled', 'resolved', 'dismissed')),
                scheduled_for TEXT,
                resolved_at TEXT,
                parked_at TEXT NOT NULL DEFAULT (datetime('now')),
                created_by TEXT DEFAULT 'agent',
                source TEXT NOT NULL DEFAULT 'parked',
                tech_area TEXT,
                priority INTEGER
            );
            CREATE UNIQUE INDEX uix_parked_topics_session_question
            ON parked_topics (study_session_id, question);
            """
        )

        from agent_session_tools.migrations import migrate_v16, migrate_v17

        migrate_v16(fresh_db)
        migrate_v17(fresh_db)

        cols = {r[1] for r in fresh_db.execute("PRAGMA table_info(parked_topics)")}
        assert {"source", "tech_area", "priority"} <= cols

        index_cols = [
            r[2]
            for r in fresh_db.execute(
                "PRAGMA index_info(uix_parked_topics_session_question)"
            ).fetchall()
        ]
        assert index_cols == ["study_session_id", "question", "source"]


class TestMigrationV22:
    """Test course/section provenance columns added to study_progress."""

    def test_migrates_to_version_22(self, fresh_db):
        applied = migrate(fresh_db)
        assert get_user_version(fresh_db) == CURRENT_VERSION
        assert any("v22" in a for a in applied)

    def test_study_progress_has_provenance_columns(self, fresh_db):
        migrate(fresh_db)
        cols = {
            r[1]
            for r in fresh_db.execute("PRAGMA table_info(study_progress)").fetchall()
        }
        assert {
            "source_course",
            "source_section",
            "source_publisher",
            "created_by",
        } <= cols

    def test_created_by_defaults_to_agent(self, fresh_db):
        migrate(fresh_db)
        fresh_db.execute(
            "INSERT INTO study_progress "
            "(id, topic, concept, confidence, first_seen, last_seen, session_count) "
            "VALUES ('test-id', 'python', 'closures', 'struggling', datetime('now'), datetime('now'), 1)"
        )
        row = fresh_db.execute(
            "SELECT created_by FROM study_progress WHERE id='test-id'"
        ).fetchone()
        assert row[0] == "agent"

    def test_idempotent_run_twice(self, fresh_db):
        """Running migrate() twice must not raise (idempotent ALTER guards)."""
        migrate(fresh_db)
        second = migrate(fresh_db)
        assert second == []
        cols = {
            r[1]
            for r in fresh_db.execute("PRAGMA table_info(study_progress)").fetchall()
        }
        assert {
            "source_course",
            "source_section",
            "source_publisher",
            "created_by",
        } <= cols

    def test_provenance_columns_nullable(self, fresh_db):
        """source_course, source_section, source_publisher accept NULL."""
        migrate(fresh_db)
        fresh_db.execute(
            "INSERT INTO study_progress "
            "(id, topic, concept, confidence, first_seen, last_seen, session_count, "
            " source_course, source_section, source_publisher) "
            "VALUES ('null-test', 'sql', 'joins', 'struggling', datetime('now'), datetime('now'), 1, "
            " NULL, NULL, NULL)"
        )
        row = fresh_db.execute(
            "SELECT source_course, source_section, source_publisher "
            "FROM study_progress WHERE id='null-test'"
        ).fetchone()
        assert row[0] is None
        assert row[1] is None
        assert row[2] is None


class TestMigrationV24:
    """Test active-learning tables for practice attempts and mastery graph edges."""

    def test_creates_practice_attempts_table(self, fresh_db):
        migrate(fresh_db)
        tables = {
            r[0]
            for r in fresh_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "practice_attempts" in tables

    def test_creates_concept_dependencies_table(self, fresh_db):
        migrate(fresh_db)
        tables = {
            r[0]
            for r in fresh_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "concept_dependencies" in tables

    def test_concept_dependencies_unique_edge_constraint(self, fresh_db):
        migrate(fresh_db)
        fresh_db.execute(
            """
            INSERT INTO concept_dependencies
                (id, topic, source_concept, target_concept, relation_type)
            VALUES ('1', 'python', 'decorators', 'closures', 'prerequisite')
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            fresh_db.execute(
                """
                INSERT INTO concept_dependencies
                    (id, topic, source_concept, target_concept, relation_type)
                VALUES ('2', 'python', 'decorators', 'closures', 'prerequisite')
                """
            )


class TestV25CascadeOnMessageDelete:
    """v25: deleting a message must cascade to scrub_log + file_references."""

    def _seed(self, conn):
        migrate(conn)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("INSERT INTO sessions (id, source) VALUES ('s1', 'test')")
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, seq) "
            "VALUES ('m1', 's1', 'user', 'hi', 1)"
        )
        conn.execute(
            "INSERT INTO scrub_log (session_id, message_id, entity_type, placeholder) "
            "VALUES ('s1', 'm1', 'aws_secret_key', '<AWS_SECRET>')"
        )
        conn.execute(
            "INSERT INTO file_references "
            "(session_id, message_id, file_path, tool_name) "
            "VALUES ('s1', 'm1', '/x/y.py', 'read')"
        )
        conn.commit()

    def test_deleting_message_cascades_dependent_rows(self, fresh_db):
        self._seed(fresh_db)
        # The exporter update path does exactly this — must not raise even
        # when the message has scrub_log + file_references rows (the FK
        # violation the bare-except exporters used to swallow).
        fresh_db.execute("DELETE FROM messages WHERE session_id = 's1'")
        fresh_db.commit()
        assert fresh_db.execute("SELECT COUNT(*) FROM scrub_log").fetchone()[0] == 0
        assert (
            fresh_db.execute("SELECT COUNT(*) FROM file_references").fetchone()[0] == 0
        )
