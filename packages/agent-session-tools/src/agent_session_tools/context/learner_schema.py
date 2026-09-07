"""Schema37: application records, typed study dependencies and scoped board names."""

import sqlite3

from .record_schema import TABLES as V36_TABLES

TABLES = (*V36_TABLES, "parked_topics", "study_notes", "practice_attempts")

NOTES_DDL = """CREATE TABLE IF NOT EXISTS study_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    study_session_id TEXT REFERENCES study_sessions(id) ON DELETE SET NULL,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', topic TEXT,
    kind TEXT NOT NULL DEFAULT 'note'
        CHECK(kind IN ('note','question','plan','assessment','win','struggle')),
    confidence INTEGER, origin TEXT NOT NULL DEFAULT 'body-double',
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','dismissed')),
    created_by TEXT NOT NULL DEFAULT 'web',
    created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT
)"""


def install(conn: sqlite3.Connection) -> None:
    conn.execute(NOTES_DDL)
    conn.execute("ALTER TABLE practice_attempts ADD COLUMN topic TEXT")
    conn.execute("ALTER TABLE practice_attempts ADD COLUMN concept TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_study_notes_status ON study_notes(status,created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_study_notes_topic ON study_notes(topic)"
    )
    # Drop only this component's known triggers before rebuilding its CHECK allowlist.
    for name in ["context_record_owners_immutable", "context_record_forget_session"]:
        conn.execute(f"DROP TRIGGER {name}")
    for table in V36_TABLES:
        conn.execute(f"DROP TRIGGER context_record_remove_{table}")
        conn.execute(f"DROP TRIGGER context_record_cleanup_{table}")
    names = ",".join("'" + table + "'" for table in TABLES)
    conn.execute(f"""CREATE TABLE context_record_owners_next (
        id TEXT PRIMARY KEY NOT NULL,
        table_name TEXT NOT NULL CHECK(table_name IN ({names})),
        row_id TEXT NOT NULL,
        session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
        project_id TEXT REFERENCES context_projects(id) ON DELETE CASCADE,
        scope TEXT CHECK(scope IN ('personal','work','unclassified')),
        created_at TEXT NOT NULL, UNIQUE(table_name,row_id),
        CHECK((session_id IS NOT NULL)+(project_id IS NOT NULL)+(scope IS NOT NULL)=1)
    )""")
    conn.execute(
        "INSERT INTO context_record_owners_next SELECT * FROM context_record_owners"
    )
    conn.execute("DROP TABLE context_record_owners")
    conn.execute(
        "ALTER TABLE context_record_owners_next RENAME TO context_record_owners"
    )
    conn.execute(
        "CREATE INDEX context_record_session ON context_record_owners(session_id)"
    )
    conn.execute(
        "CREATE INDEX context_record_project ON context_record_owners(project_id)"
    )
    conn.execute("""CREATE TRIGGER context_record_owners_immutable BEFORE UPDATE ON context_record_owners
        BEGIN SELECT RAISE(ABORT,'Record ownership is immutable'); END""")
    conn.execute("""CREATE TRIGGER context_record_forget_session AFTER INSERT ON context_tombstones
        BEGIN DELETE FROM context_record_owners WHERE session_id=NEW.session_id; END""")
    for table in TABLES:
        conn.execute(f"""CREATE TRIGGER context_record_remove_{table}
            AFTER DELETE ON context_record_owners WHEN OLD.table_name='{table}'
            BEGIN DELETE FROM {table} WHERE id=OLD.row_id; END""")
        conn.execute(f"""CREATE TRIGGER context_record_cleanup_{table} AFTER DELETE ON {table}
            BEGIN DELETE FROM context_record_owners
            WHERE table_name='{table}' AND row_id=CAST(OLD.id AS TEXT); END""")
    conn.execute("""CREATE TABLE context_record_study_links (
        record_id TEXT PRIMARY KEY REFERENCES context_record_owners(id) ON DELETE CASCADE,
        study_session_id TEXT NOT NULL REFERENCES study_sessions(id) ON DELETE CASCADE
    )""")
    conn.execute(
        "CREATE INDEX context_record_study_parent ON context_record_study_links(study_session_id)"
    )
    conn.execute("""CREATE TRIGGER context_record_study_link_kind BEFORE INSERT ON context_record_study_links
        WHEN NOT EXISTS (SELECT 1 FROM context_record_owners WHERE id=NEW.record_id
            AND table_name IN ('parked_topics','study_notes'))
        BEGIN SELECT RAISE(ABORT,'Unsupported study-record dependency'); END""")
    conn.execute("""CREATE TRIGGER context_record_study_link_immutable BEFORE UPDATE ON context_record_study_links
        BEGIN SELECT RAISE(ABORT,'Record dependency is immutable'); END""")
    conn.execute("""CREATE TRIGGER context_record_study_link_purge AFTER DELETE ON context_record_study_links
        BEGIN DELETE FROM context_record_owners WHERE id=OLD.record_id; END""")
    conn.execute("""CREATE TABLE context_record_observations (
        record_id TEXT NOT NULL REFERENCES context_record_owners(id) ON DELETE CASCADE,
        observation_id TEXT NOT NULL REFERENCES context_observations(id) ON DELETE CASCADE,
        PRIMARY KEY(record_id,observation_id)
    )""")
    conn.execute(
        "CREATE INDEX context_record_observation ON context_record_observations(observation_id)"
    )
    conn.execute("""CREATE TRIGGER context_record_observations_immutable BEFORE UPDATE ON context_record_observations
        BEGIN SELECT RAISE(ABORT,'Record observation dependency is immutable'); END""")
    conn.execute("""CREATE TRIGGER context_record_purge_observations BEFORE DELETE ON context_record_owners
        BEGIN DELETE FROM context_observations WHERE id IN
            (SELECT observation_id FROM context_record_observations WHERE record_id=OLD.id); END""")

    columns = {r[1] for r in conn.execute("PRAGMA table_info(parked_topics)")}
    for name, kind in [
        ("notes", "TEXT"),
        ("board_column", "TEXT"),
        ("board_order", "INTEGER"),
        ("updated_at", "TEXT"),
    ]:
        if name not in columns:
            conn.execute(f"ALTER TABLE parked_topics ADD COLUMN {name} {kind}")
    # Guarded like the columns above: init_db's legacy reconciliation may have
    # already converged parked_topics to the final shape before install runs.
    if "owner_key" not in columns:
        conn.execute(
            "ALTER TABLE parked_topics ADD COLUMN owner_key TEXT NOT NULL DEFAULT 'legacy'"
        )
    conn.execute("DROP INDEX IF EXISTS uix_parked_topics_question_source_pending")
    conn.execute("""CREATE UNIQUE INDEX uix_parked_topics_owned_pending
        ON parked_topics(question,source,owner_key) WHERE status='pending'""")
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='board_columns'"
    ).fetchone()
    conn.execute("""CREATE TABLE context_board_columns (
        scope TEXT NOT NULL CHECK(scope IN ('personal','work','unclassified')),
        key TEXT NOT NULL, name TEXT NOT NULL, position INTEGER NOT NULL,
        PRIMARY KEY(scope,key)
    )""")
    if exists:
        # Preserve old names in their explicit unknown boundary, never infer a scope.
        conn.execute(
            "INSERT INTO context_board_columns SELECT 'unclassified',key,name,position FROM board_columns"
        )
        conn.execute("DROP TABLE board_columns")
