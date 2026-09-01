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
CURRENT_VERSION = 27

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


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    """Return the column names currently present on a table."""
    cursor = conn.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}


def set_user_version(conn: sqlite3.Connection, version: int) -> None:
    """Set database schema version."""
    conn.execute(f"PRAGMA user_version = {version}")


def _install_messages_fts_update_trigger(conn: sqlite3.Connection) -> None:
    """Install the FTS update trigger with NULL transition handling."""
    conn.execute("DROP TRIGGER IF EXISTS messages_fts_update")
    conn.execute("""
        CREATE TRIGGER messages_fts_update AFTER UPDATE ON messages
        BEGIN
            DELETE FROM messages_fts WHERE rowid = OLD.rowid;
            INSERT INTO messages_fts(rowid, content, session_id, role)
            SELECT NEW.rowid, NEW.content, NEW.session_id, NEW.role
            WHERE NEW.content IS NOT NULL;
        END
    """)


#: Migrations whose entire body is connection/database-level ``PRAGMA`` work.
#:
#: SQLite makes both ``PRAGMA journal_mode`` and ``PRAGMA foreign_keys`` a
#: **silent no-op** while a transaction is open -- this file already documents
#: that for the v26 table rebuild. Now that :func:`migrate` runs the whole
#: sequence inside one ``BEGIN IMMEDIATE``, a pragma-only migration would
#: quietly stop having any effect, so these are re-applied after the commit.
#:
#: Safe precisely because they carry no DDL and no data change, so their
#: position relative to the transaction cannot alter the schema or its contents.
#: A migration added here that *does* touch schema or data would be a bug.
PRAGMA_ONLY_VERSIONS: frozenset[int] = frozenset({6})


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Run all pending migrations.

    Returns list of migration descriptions that were applied.

    Concurrency
    -----------
    The migrations are NOT idempotent -- they ``ALTER TABLE ... ADD COLUMN``,
    ``CREATE INDEX`` and ``CREATE TABLE`` without ``IF NOT EXISTS``. This
    function used to read ``user_version`` with no lock held and then
    ``commit()`` after *each* individual migration, which made two failures
    possible whenever two connections opened the same fresh database at once:

    * both read the same stale version and then applied the same DDL, producing
      ``duplicate column name: seq``, ``index ... already exists`` and
      ``table messages_fts already exists``;
    * the per-migration commit released the write lock mid-sequence, so a second
      migrator could enter partway through and start from a version that was
      only half-applied.

    That is not a theoretical race. The SPA fires ``/api/now``, ``/api/backlog``,
    ``/api/session/last`` and ``/api/history`` in parallel on page load, and each
    one reaches this function through its own lazily-opened connection -- so a
    first run on a new machine races its own schema setup.

    The sequence is now wrapped in a single ``BEGIN IMMEDIATE`` transaction: the
    write lock is taken up front, the version is re-read *under* that lock, and
    exactly one commit ends the whole run. A loser of the race blocks on the
    lock, re-reads the now-current version, and correctly does nothing.

    The initial read stays outside the lock on purpose. Every request calls this
    function, and taking a write lock unconditionally would serialise reads that
    have no migrating to do.
    """
    # Fast path, unlocked: the overwhelming majority of calls have nothing to do.
    # Safe because the version only ever increases, and a migration in flight is
    # not yet committed -- so this read either sees the old version (and we go on
    # to take the lock and block) or the final one (and we correctly skip).
    if get_user_version(conn) >= CURRENT_VERSION:
        logger.debug(
            "Database already at version %d, no migrations needed", CURRENT_VERSION
        )
        return []

    # Only manage the transaction if we opened it; a caller that already holds
    # one keeps ownership of its commit/rollback.
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.execute("BEGIN IMMEDIATE")

    try:
        # Re-read under the lock: another migrator may have finished the whole
        # sequence while we were waiting for it.
        current = get_user_version(conn)
        applied: list[str] = []

        if current >= CURRENT_VERSION:
            logger.debug(
                "Another migrator brought the database to version %d while we waited",
                current,
            )
            if owns_transaction:
                conn.commit()
            return applied

        logger.info(f"Migrating database from version {current} to {CURRENT_VERSION}")
        pragma_only_applied: list[int] = []

        for version in range(current + 1, CURRENT_VERSION + 1):
            if version not in MIGRATIONS:
                logger.warning(f"Missing migration for version {version}")
                continue

            description, migration_func = MIGRATIONS[version]
            logger.info(f"Applying migration v{version}: {description}")

            migration_func(conn)
            set_user_version(conn, version)
            applied.append(f"v{version}: {description}")
            if version in PRAGMA_ONLY_VERSIONS:
                pragma_only_applied.append(version)

        # One commit for the entire sequence, so the lock is never released
        # part-way through and no other migrator can observe a half-applied
        # schema.
        if owns_transaction:
            conn.commit()

            # Only now, with no transaction open, can the pragma-only
            # migrations actually take effect. See PRAGMA_ONLY_VERSIONS.
            for version in pragma_only_applied:
                MIGRATIONS[version][1](conn)

        return applied
    except Exception as e:
        logger.error(f"Migration failed, rolling back the whole sequence: {e}")
        if owns_transaction:
            conn.rollback()
        raise


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

    _install_messages_fts_update_trigger(conn)

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


@migration(14, "Add parked_topics table for parking lot persistence")
def migrate_v14(conn: sqlite3.Connection) -> None:
    """Add table for persisting parking lot questions across sessions."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS parked_topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            study_session_id TEXT REFERENCES study_sessions(id) ON DELETE SET NULL,
            session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
            topic_tag TEXT,
            question TEXT NOT NULL,
            context TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'scheduled', 'resolved', 'dismissed')),
            scheduled_for TEXT,
            resolved_at TEXT,
            parked_at TEXT NOT NULL DEFAULT (datetime('now')),
            created_by TEXT DEFAULT 'agent'
        )
    """)


@migration(15, "Add unique constraint to prevent parking lot duplication")
def migrate_v15(conn: sqlite3.Connection) -> None:
    """Prevent duplicate parked topics when session_end re-inserts entries
    already written by the park CLI command during the session."""
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uix_parked_topics_session_question
        ON parked_topics (study_session_id, question)
    """)


@migration(16, "Add source and tech_area columns to parked_topics for study backlog")
def migrate_v16(conn: sqlite3.Connection) -> None:
    """Extend parked_topics for study backlog: distinguish parked/struggled/manual
    entries and allow technology area categorization.

    - source: where the entry came from (parked, struggled, manual)
    - tech_area: technology category (Python, SQL, etc.)
    - Updated unique index to allow same question from different sources
    - FKs are already nullable (ON DELETE SET NULL) from v14
    """
    columns = _table_columns(conn, "parked_topics")

    if "source" not in columns:
        conn.execute("""
            ALTER TABLE parked_topics
            ADD COLUMN source TEXT NOT NULL DEFAULT 'parked'
            CHECK(source IN ('parked', 'struggled', 'manual'))
        """)
    if "tech_area" not in columns:
        conn.execute("""
            ALTER TABLE parked_topics
            ADD COLUMN tech_area TEXT
        """)

    # Rebuild unique index to include source — allows same question
    # from different sources (e.g. parked during session, then manually added)
    conn.execute("DROP INDEX IF EXISTS uix_parked_topics_session_question")
    conn.execute("""
        CREATE UNIQUE INDEX uix_parked_topics_session_question
        ON parked_topics (study_session_id, question, source)
    """)


@migration(17, "Add priority column to parked_topics for agent-assessed importance")
def migrate_v17(conn: sqlite3.Connection) -> None:
    """Add agent-assessed importance score to backlog items.

    Priority is set by the AI agent during study sessions to indicate
    how foundational a topic is in the learning path:
    - NULL = not yet assessed (defaults to 3 in scoring)
    - 1 = low importance (niche/optional)
    - 5 = critical/foundational (e.g. OOP basics, closures)
    """
    columns = _table_columns(conn, "parked_topics")
    if "priority" not in columns:
        conn.execute("""
            ALTER TABLE parked_topics ADD COLUMN priority INTEGER
        """)


@migration(18, "Add scrub_log table for PII redaction audit trail")
def migrate_v18(conn: sqlite3.Connection) -> None:
    """Create scrub_log table to record what was scrubbed (never stores original values)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scrub_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            message_id TEXT,
            entity_type TEXT NOT NULL,
            placeholder TEXT NOT NULL,
            scrubbed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id),
            FOREIGN KEY (message_id) REFERENCES messages(id)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_scrub_log_session
        ON scrub_log(session_id)
    """)


@migration(19, "Add file_references table for file hotspot tracking")
def migrate_v19(conn: sqlite3.Connection) -> None:
    """Track file paths referenced in tool calls for hotspot analysis."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS file_references (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            timestamp TEXT,
            UNIQUE(message_id, file_path, tool_name),
            FOREIGN KEY (session_id) REFERENCES sessions(id),
            FOREIGN KEY (message_id) REFERENCES messages(id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_file_refs_path ON file_references(file_path)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_file_refs_session "
        "ON file_references(session_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_file_refs_tool ON file_references(tool_name)"
    )


@migration(20, "Add persona effectiveness tracking to study_sessions")
def migrate_v20(conn: sqlite3.Connection) -> None:
    """Track persona version and structured outcome counts for effectiveness analysis.

    persona_hash: SHA-256[:16] of the injected persona content at session start.
    win_count / struggle_count: structured counts extracted from session-topics.md
    at session end (previously only stored as unstructured text in notes).
    """
    for col, typedef in [
        ("persona_hash", "TEXT"),
        ("win_count", "INTEGER"),
        ("struggle_count", "INTEGER"),
    ]:
        try:
            conn.execute(f"ALTER TABLE study_sessions ADD COLUMN {col} {typedef}")
        except sqlite3.OperationalError:
            pass  # Column already exists (idempotent)

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_study_sessions_persona "
        "ON study_sessions(persona_hash)"
    )


@migration(21, "Add topic_slug to study_sessions for course-level aggregation")
def migrate_v21(conn: sqlite3.Connection) -> None:
    """Store the resolved topic slug alongside the raw topic string.

    Enables grouping sessions by course (slug) rather than raw free-text topic.
    Example: "Python Decorators", "Python OOP", "python" all map to slug "python".
    """
    try:
        conn.execute("ALTER TABLE study_sessions ADD COLUMN topic_slug TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists (idempotent)

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_study_sessions_slug "
        "ON study_sessions(topic_slug)"
    )


@migration(
    22, "Add course/section provenance to study_progress for web-flagged struggles"
)
def migrate_v22(conn: sqlite3.Connection) -> None:
    """Add source_course, source_section, source_publisher, created_by to study_progress.

    These columns record where a struggle was flagged from (web UI, agent, etc.)
    and which course/section triggered the flag. All columns are nullable so
    existing rows remain valid; created_by defaults to 'agent' for back-compat.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(study_progress)")}
    for col in ("source_course", "source_section", "source_publisher", "created_by"):
        if col not in existing:
            default = " DEFAULT 'agent'" if col == "created_by" else ""
            conn.execute(f"ALTER TABLE study_progress ADD COLUMN {col} TEXT{default}")


@migration(23, "Fix messages FTS update trigger NULL transitions")
def migrate_v23(conn: sqlite3.Connection) -> None:
    """Ensure message content updates keep FTS in sync across NULL transitions."""
    _install_messages_fts_update_trigger(conn)


@migration(24, "Add practice attempts and explicit concept dependencies")
def migrate_v24(conn: sqlite3.Connection) -> None:
    """Add active-learning evidence tables for practice and mastery graph features."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS practice_attempts (
            id TEXT PRIMARY KEY,
            practice_path TEXT NOT NULL,
            task_index INTEGER NOT NULL,
            task_prompt TEXT NOT NULL,
            verification_kind TEXT NOT NULL,
            passed INTEGER NOT NULL CHECK(passed IN (0, 1)),
            notes TEXT,
            command TEXT,
            exit_code INTEGER,
            stdout TEXT,
            stderr TEXT,
            duration_seconds REAL,
            expected_artifacts TEXT,
            missing_artifacts TEXT,
            workdir TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_practice_attempts_path "
        "ON practice_attempts(practice_path, task_index)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_practice_attempts_created "
        "ON practice_attempts(created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_practice_attempts_passed "
        "ON practice_attempts(passed)"
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS concept_dependencies (
            id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            source_concept TEXT NOT NULL,
            target_concept TEXT NOT NULL,
            relation_type TEXT NOT NULL DEFAULT 'prerequisite',
            evidence TEXT,
            source_type TEXT NOT NULL DEFAULT 'explicit',
            confidence REAL NOT NULL DEFAULT 0.5,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(topic, source_concept, target_concept, relation_type)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_concept_dependencies_topic "
        "ON concept_dependencies(topic)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_concept_dependencies_source "
        "ON concept_dependencies(topic, source_concept)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_concept_dependencies_target "
        "ON concept_dependencies(topic, target_concept)"
    )


@migration(25, "Add ON DELETE CASCADE to scrub_log/file_references message_id FKs")
def migrate_v25(conn: sqlite3.Connection) -> None:
    """Rebuild scrub_log and file_references so deleting a message cascades.

    The v18 scrub_log and v19 file_references FKs on ``message_id`` (and
    scrub_log's ``session_id``) lacked ``ON DELETE CASCADE`` — every other FK
    in the schema has it. With ``PRAGMA foreign_keys=ON`` (set on the export
    path), an exporter's update-path ``DELETE FROM messages WHERE session_id``
    hit a FK violation once any message had a scrub_log/file_references row.
    Gemini's bare ``except`` swallowed it (aborting the rest of the export);
    kiro surfaced it as an error. Rebuild both tables with cascading FKs.

    SQLite cannot ALTER a constraint, so this is the create-new / copy /
    drop / rename dance. No FK toggle is needed: nothing REFERENCES these two
    tables, and their own outward FKs (to sessions/messages) aren't violated
    by copying existing rows. (A ``PRAGMA foreign_keys`` change is a no-op
    inside a transaction anyway, and migrate() runs inside one.)
    """
    # scrub_log — cascade on both session_id and message_id.
    conn.execute("""
        CREATE TABLE scrub_log_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            message_id TEXT,
            entity_type TEXT NOT NULL,
            placeholder TEXT NOT NULL,
            scrubbed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        INSERT INTO scrub_log_new
            (id, session_id, message_id, entity_type, placeholder, scrubbed_at)
        SELECT id, session_id, message_id, entity_type, placeholder, scrubbed_at
        FROM scrub_log
    """)
    conn.execute("DROP TABLE scrub_log")
    conn.execute("ALTER TABLE scrub_log_new RENAME TO scrub_log")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_scrub_log_session ON scrub_log(session_id)"
    )

    # file_references — cascade on both session_id and message_id.
    conn.execute("""
        CREATE TABLE file_references_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            timestamp TEXT,
            UNIQUE(message_id, file_path, tool_name),
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        INSERT INTO file_references_new
            (id, session_id, message_id, file_path, tool_name, timestamp)
        SELECT id, session_id, message_id, file_path, tool_name, timestamp
        FROM file_references
    """)
    conn.execute("DROP TABLE file_references")
    conn.execute("ALTER TABLE file_references_new RENAME TO file_references")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_file_refs_path ON file_references(file_path)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_file_refs_session ON file_references(session_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_file_refs_tool ON file_references(tool_name)"
    )


@migration(
    26,
    "Fix parked_topics deduplication: partial unique index on (question, source) WHERE pending",
)
def migrate_v26(conn: sqlite3.Connection) -> None:
    """Collapse duplicate pending parked_topics rows and fix uniqueness scope.

    Issue 0004: The old index scoped uniqueness to (study_session_id, question, source),
    so the same question parked from different sessions created duplicate rows. NULLs in
    study_session_id also bypassed deduplication entirely (SQLite NULL distinctness).

    This migration:
    1. Adds park_count column (default 1) to preserve re-park frequency signal
    2. Collapses duplicate pending rows per (question, source), keeping the earliest
       parked_at and dismissing the rest (no rows deleted)
    3. Drops the old broken index
    4. Creates a partial unique index on (question, source) WHERE status = 'pending'
    """
    columns = _table_columns(conn, "parked_topics")

    # Step 1: Add park_count column if missing
    if "park_count" not in columns:
        conn.execute(
            "ALTER TABLE parked_topics ADD COLUMN park_count INTEGER NOT NULL DEFAULT 1"
        )

    # Step 2: Collapse duplicate pending rows — keep the row with the earliest
    # parked_at per (question, source) group (tie-break on lowest id). Dismiss all
    # others. The keeper inherits the group's size as its park_count, so the
    # "this keeps coming up" signal survives the rows that carried it.
    # Strategy: find the single keeper per group (MIN parked_at, then MIN id for ties),
    # then dismiss every other pending row in that group.
    keeper_ids_sql = """
        SELECT MIN(sub.id)
        FROM parked_topics sub
        WHERE sub.status = 'pending'
          AND sub.parked_at = (
              SELECT MIN(sub2.parked_at)
              FROM parked_topics sub2
              WHERE sub2.question = sub.question
                AND sub2.source = sub.source
                AND sub2.status = 'pending'
          )
        GROUP BY sub.question, sub.source
    """

    # Backfill park_count on the keepers BEFORE dismissing the losers, while the
    # group is still countable. park_count is at least 1 for a singleton group.
    conn.execute(f"""
        UPDATE parked_topics
        SET park_count = MAX(park_count, (
            SELECT COUNT(*) FROM parked_topics grp
            WHERE grp.question = parked_topics.question
              AND grp.source = parked_topics.source
              AND grp.status = 'pending'
        ))
        WHERE id IN ({keeper_ids_sql})
    """)  # noqa: S608 - keeper_ids_sql is a module-local literal, no user input

    conn.execute(f"""
        UPDATE parked_topics
        SET status = 'dismissed'
        WHERE status = 'pending'
          AND id NOT IN ({keeper_ids_sql})
    """)  # noqa: S608 - keeper_ids_sql is a module-local literal, no user input

    # Step 3: Drop the old index
    conn.execute("DROP INDEX IF EXISTS uix_parked_topics_session_question")

    # Step 4: Create the partial unique index
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uix_parked_topics_question_source_pending
        ON parked_topics (question, source) WHERE status = 'pending'
    """)

    # Log the collapse for audit
    dismissed_count = conn.execute(
        "SELECT COUNT(*) FROM parked_topics WHERE status = 'dismissed'"
    ).fetchone()[0]
    logger.info(
        f"v26 dedup: partial index created, {dismissed_count} total dismissed rows"
    )


@migration(27, "Add source-session provenance to extracted study progress")
def migrate_v27(conn: sqlite3.Connection) -> None:
    """Add nullable source_session_id without inventing historical provenance."""
    columns = _table_columns(conn, "study_progress")
    if not columns:
        return
    if "source_session_id" not in columns:
        conn.execute("ALTER TABLE study_progress ADD COLUMN source_session_id TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_progress_source_session "
        "ON study_progress(source_session_id)"
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
