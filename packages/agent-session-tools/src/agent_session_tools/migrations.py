#!/usr/bin/env python3
"""Database migration system using PRAGMA user_version.

Provides forward-only migrations for schema evolution without data loss.
Each migration is idempotent and can be safely re-run.
"""

import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

# Current schema version - increment when adding new migrations
CURRENT_VERSION = 13

# Migration functions: version -> (description, migration_func)
MIGRATIONS: dict[int, tuple[str, Callable[[sqlite3.Connection], None]]] = {}


def migration(version: int, description: str):
    """Decorator to register a migration function."""

    def decorator(func: Callable[[sqlite3.Connection], None]):
        MIGRATIONS[version] = (description, func)
        return func

    return decorator


def get_user_version(conn: sqlite3.Connection) -> int:
    """Get current database schema version."""
    result = conn.execute("PRAGMA user_version").fetchone()
    return result[0] if result else 0


def set_user_version(conn: sqlite3.Connection, version: int) -> None:
    """Set database schema version."""
    conn.execute(f"PRAGMA user_version = {version}")


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Run all pending migrations.

    Returns list of migration descriptions that were applied.
    """
    current = get_user_version(conn)
    applied = []

    if current >= CURRENT_VERSION:
        logger.debug(f"Database at version {current}, no migrations needed")
        return applied

    logger.info(f"Migrating database from version {current} to {CURRENT_VERSION}")

    for version in range(current + 1, CURRENT_VERSION + 1):
        if version not in MIGRATIONS:
            logger.warning(f"Missing migration for version {version}")
            continue

        description, migration_func = MIGRATIONS[version]
        logger.info(f"Applying migration v{version}: {description}")

        try:
            migration_func(conn)
            set_user_version(conn, version)
            conn.commit()
            applied.append(f"v{version}: {description}")
        except Exception as e:
            logger.error(f"Migration v{version} failed: {e}")
            conn.rollback()
            raise

    return applied


# ============================================================================
# MIGRATIONS
# ============================================================================


@migration(1, "Add content_hash and import_fingerprint for change detection")
def migrate_v1(conn: sqlite3.Connection) -> None:
    """Add columns for incremental export support."""
    # Check if columns exist before adding
    cursor = conn.execute("PRAGMA table_info(sessions)")
    columns = {row[1] for row in cursor.fetchall()}

    if "content_hash" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN content_hash TEXT")

    if "import_fingerprint" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN import_fingerprint TEXT")

    cursor = conn.execute("PRAGMA table_info(messages)")
    columns = {row[1] for row in cursor.fetchall()}

    if "content_hash" not in columns:
        conn.execute("ALTER TABLE messages ADD COLUMN content_hash TEXT")

    # Add index for faster lookups
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_content_hash ON sessions(content_hash)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_fingerprint ON sessions(import_fingerprint)"
    )


@migration(2, "Add message sequence number for ordering without timestamps")
def migrate_v2(conn: sqlite3.Connection) -> None:
    """Add seq column for reliable message ordering."""
    cursor = conn.execute("PRAGMA table_info(messages)")
    columns = {row[1] for row in cursor.fetchall()}

    if "seq" not in columns:
        conn.execute("ALTER TABLE messages ADD COLUMN seq INTEGER")

    # Create index for ordering
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_session_seq ON messages(session_id, seq)"
    )

    # Backfill seq values for existing messages using rowid order
    conn.execute(
        """
        UPDATE messages SET seq = (
            SELECT COUNT(*) FROM messages m2
            WHERE m2.session_id = messages.session_id
            AND m2.rowid <= messages.rowid
        ) WHERE seq IS NULL
    """
    )


@migration(3, "Add session tags and notes tables for annotation")
def migrate_v3(conn: sqlite3.Connection) -> None:
    """Add tables for session tagging and notes."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS session_tags (
            session_id TEXT NOT NULL,
            tag TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (session_id, tag),
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        )
    """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS session_notes (
            session_id TEXT PRIMARY KEY,
            notes TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        )
    """
    )

    conn.execute("CREATE INDEX IF NOT EXISTS idx_session_tags_tag ON session_tags(tag)")


@migration(4, "Add critical performance indexes for 10K+ session scale")
def migrate_v4(conn: sqlite3.Connection) -> None:
    """Add indexes for common query patterns at scale."""

    # Session listing optimization
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_source ON sessions(source)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_updated_source ON sessions(updated_at DESC, source)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_project_updated ON sessions(project_path, updated_at DESC)"
    )

    # Message querying optimization
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_session_role ON messages(session_id, role)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp DESC)"
    )

    # Covering index for list operations (most common query)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sessions_list_covering
        ON sessions(updated_at DESC, source, project_path, id)
    """)

    # Tag operations optimization (uses tables from migration v3)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_session_tags_tag ON session_tags(tag)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_tags_session ON session_tags(session_id)"
    )


@migration(5, "Optimize FTS5 with porter stemming and metadata columns")
def migrate_v5(conn: sqlite3.Connection) -> None:
    """Rebuild FTS5 table with porter stemming for better search quality."""

    # Drop triggers FIRST (they reference the FTS table)
    conn.execute("DROP TRIGGER IF EXISTS messages_fts_insert")
    conn.execute("DROP TRIGGER IF EXISTS messages_fts_update")
    conn.execute("DROP TRIGGER IF EXISTS messages_fts_delete")

    # Now safe to drop the FTS table
    conn.execute("DROP TABLE IF EXISTS messages_fts")

    # Create optimized FTS table with porter stemming and unindexed metadata
    conn.execute("""
        CREATE VIRTUAL TABLE messages_fts USING fts5(
            content,
            session_id UNINDEXED,
            role UNINDEXED,
            tokenize='porter unicode61'
        )
    """)

    # Populate with existing messages
    conn.execute("""
        INSERT INTO messages_fts(rowid, content, session_id, role)
        SELECT m.rowid, m.content, m.session_id, m.role
        FROM messages m
        WHERE m.content IS NOT NULL
    """)

    # Create triggers for automatic FTS updates
    conn.execute("""
        CREATE TRIGGER messages_fts_insert AFTER INSERT ON messages
        WHEN NEW.content IS NOT NULL
        BEGIN
            INSERT INTO messages_fts(rowid, content, session_id, role)
            VALUES (NEW.rowid, NEW.content, NEW.session_id, NEW.role);
        END
    """)

    conn.execute("""
        CREATE TRIGGER messages_fts_update AFTER UPDATE ON messages
        WHEN NEW.content IS NOT NULL
        BEGIN
            UPDATE messages_fts SET
                content = NEW.content,
                session_id = NEW.session_id,
                role = NEW.role
            WHERE rowid = NEW.rowid;
        END
    """)

    conn.execute("""
        CREATE TRIGGER messages_fts_delete AFTER DELETE ON messages
        BEGIN
            DELETE FROM messages_fts WHERE rowid = OLD.rowid;
        END
    """)


@migration(6, "Enable WAL mode for concurrent batch processing")
def migrate_v6(conn: sqlite3.Connection) -> None:
    """Set journal_mode=WAL and foreign_keys=ON."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")


@migration(7, "Add embeddings tables and session metadata for semantic search")
def migrate_v7(conn: sqlite3.Connection) -> None:
    """Add infrastructure for semantic search and tutoring/learning tracking.

    This migration supports both:
    1. Session memory - finding relevant historical context for current work
    2. Tutoring/learning - tracking progress and identifying gaps over time
    """
    # Message-level embeddings for semantic search
    conn.execute("""
        CREATE TABLE IF NOT EXISTS message_embeddings (
            message_id TEXT PRIMARY KEY,
            embedding BLOB NOT NULL,
            model TEXT DEFAULT 'all-MiniLM-L6-v2',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
        )
    """)

    # Session-level embeddings (aggregate representation of session)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_embeddings (
            session_id TEXT PRIMARY KEY,
            embedding BLOB NOT NULL,
            model TEXT DEFAULT 'all-MiniLM-L6-v2',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        )
    """)

    # Add session_type for differentiating use cases (work, learning, debugging, etc.)
    cursor = conn.execute("PRAGMA table_info(sessions)")
    columns = {row[1] for row in cursor.fetchall()}

    if "session_type" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN session_type TEXT DEFAULT 'work'")

    # Learning/tutoring metadata for sessions
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_learning_metadata (
            session_id TEXT PRIMARY KEY,
            topics JSON,
            concepts_practiced JSON,
            skill_gaps JSON,
            assessment_score REAL,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        )
    """)

    # Indexes for efficient querying
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sessions_type
        ON sessions(session_type)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sessions_type_updated
        ON sessions(session_type, updated_at DESC)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_learning_metadata_score
        ON session_learning_metadata(assessment_score)
    """)


@migration(8, "Remove conflicting legacy FTS triggers")
def migrate_v8(conn: sqlite3.Connection) -> None:
    """Drop old messages_ai/ad/au triggers that conflict with v5 FTS triggers."""
    conn.execute("DROP TRIGGER IF EXISTS messages_ai")
    conn.execute("DROP TRIGGER IF EXISTS messages_ad")
    conn.execute("DROP TRIGGER IF EXISTS messages_au")


@migration(9, "Add study_progress and study_sessions tables for win tracking")
def migrate_v9(conn: sqlite3.Connection) -> None:
    """Add tables for tracking learning progress and study sessions."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_progress (
            id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            concept TEXT NOT NULL,
            confidence TEXT NOT NULL DEFAULT 'struggling',
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            session_count INTEGER NOT NULL DEFAULT 1,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_progress_topic ON study_progress(topic)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_progress_confidence ON study_progress(confidence)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_progress_updated ON study_progress(updated_at DESC)"
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_sessions (
            id TEXT PRIMARY KEY,
            session_id TEXT REFERENCES sessions(id),
            topic TEXT,
            energy_level TEXT,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            duration_minutes INTEGER,
            pomodoro_cycles INTEGER DEFAULT 0,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_study_sessions_topic ON study_sessions(topic)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_study_sessions_energy ON study_sessions(energy_level)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_study_sessions_started ON study_sessions(started_at DESC)"
    )


@migration(10, "Add teach-back scoring and study progress extensions")
def migrate_v10(conn: sqlite3.Connection) -> None:
    """Add teach_back_scores table and extend study_progress for teach-back tracking."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS teach_back_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            concept TEXT NOT NULL,
            topic TEXT NOT NULL,
            session_id TEXT REFERENCES sessions(id),
            score_accuracy INTEGER CHECK(score_accuracy BETWEEN 1 AND 4),
            score_own_words INTEGER CHECK(score_own_words BETWEEN 1 AND 4),
            score_structure INTEGER CHECK(score_structure BETWEEN 1 AND 4),
            score_depth INTEGER CHECK(score_depth BETWEEN 1 AND 4),
            score_transfer INTEGER CHECK(score_transfer BETWEEN 1 AND 4),
            total_score INTEGER GENERATED ALWAYS AS (
                COALESCE(score_accuracy, 0) + COALESCE(score_own_words, 0)
                + COALESCE(score_structure, 0) + COALESCE(score_depth, 0)
                + COALESCE(score_transfer, 0)
            ) STORED,
            review_type TEXT NOT NULL,
            question_angle TEXT,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_teachback_concept "
        "ON teach_back_scores(concept, topic)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_teachback_date "
        "ON teach_back_scores(created_at DESC)"
    )

    # Extend study_progress with teach-back tracking columns
    cursor = conn.execute("PRAGMA table_info(study_progress)")
    columns = {row[1] for row in cursor.fetchall()}

    if "last_teachback_score" not in columns:
        conn.execute(
            "ALTER TABLE study_progress ADD COLUMN last_teachback_score INTEGER"
        )
    if "angles_used" not in columns:
        conn.execute("ALTER TABLE study_progress ADD COLUMN angles_used TEXT")
    if "mastery_signals" not in columns:
        conn.execute("ALTER TABLE study_progress ADD COLUMN mastery_signals TEXT")


@migration(11, "Add knowledge bridges table for configurable domain analogies")
def migrate_v11(conn: sqlite3.Connection) -> None:
    """Add knowledge_bridges table for dynamic concept bridging."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_bridges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_concept TEXT NOT NULL,
            source_domain TEXT NOT NULL,
            target_concept TEXT NOT NULL,
            target_domain TEXT NOT NULL,
            structural_mapping TEXT,
            quality TEXT DEFAULT 'proposed',
            times_used INTEGER DEFAULT 0,
            times_helpful INTEGER DEFAULT 0,
            created_by TEXT DEFAULT 'agent',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bridge_target "
        "ON knowledge_bridges(target_concept, target_domain)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bridge_source "
        "ON knowledge_bridges(source_domain)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bridge_quality ON knowledge_bridges(quality)"
    )


@migration(12, "Add concept graph layer — concepts, aliases, and relations")
def migrate_v12(conn: sqlite3.Connection) -> None:
    """Add concept graph tables for tracking concept relationships."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS concepts (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            domain TEXT NOT NULL,
            description TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_concepts_name_domain "
        "ON concepts(name, domain)"
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS concept_aliases (
            alias TEXT NOT NULL,
            concept_id TEXT NOT NULL REFERENCES concepts(id),
            PRIMARY KEY (alias, concept_id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_aliases_alias ON concept_aliases(alias)"
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS concept_relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_concept_id TEXT NOT NULL REFERENCES concepts(id),
            target_concept_id TEXT NOT NULL REFERENCES concepts(id),
            relation_type TEXT NOT NULL,
            confidence REAL DEFAULT 0.5,
            evidence_session_id TEXT,
            evidence_message_id TEXT,
            created_by TEXT DEFAULT 'agent',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(source_concept_id, target_concept_id, relation_type)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_relations_source "
        "ON concept_relations(source_concept_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_relations_target "
        "ON concept_relations(target_concept_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_relations_type "
        "ON concept_relations(relation_type)"
    )


@migration(13, "Add message_concepts table and concept_id to study_progress")
def migrate_v13(conn: sqlite3.Connection) -> None:
    """Add message-concept linking and concept FK on study_progress."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS message_concepts (
            message_id TEXT NOT NULL REFERENCES messages(id),
            concept_id TEXT NOT NULL REFERENCES concepts(id),
            confidence REAL DEFAULT 0.5,
            PRIMARY KEY (message_id, concept_id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_msg_concepts_concept "
        "ON message_concepts(concept_id)"
    )

    # Add concept_id FK to study_progress
    cursor = conn.execute("PRAGMA table_info(study_progress)")
    columns = {row[1] for row in cursor.fetchall()}
    if "concept_id" not in columns:
        conn.execute(
            "ALTER TABLE study_progress ADD COLUMN concept_id TEXT "
            "REFERENCES concepts(id)"
        )


def check_migration_status(db_path: Path) -> dict:
    """Check migration status without modifying database.

    Returns dict with current_version, target_version, and pending migrations.
    """
    conn = sqlite3.connect(db_path)
    try:
        current = get_user_version(conn)
        pending = []

        for version in range(current + 1, CURRENT_VERSION + 1):
            if version in MIGRATIONS:
                desc, _ = MIGRATIONS[version]
                pending.append(f"v{version}: {desc}")

        return {
            "current_version": current,
            "target_version": CURRENT_VERSION,
            "pending_migrations": pending,
            "up_to_date": current >= CURRENT_VERSION,
        }
    finally:
        conn.close()
