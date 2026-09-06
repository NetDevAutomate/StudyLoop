"""Ownership for existing mutable application rows; no source-authority promotion."""

import sqlite3

TABLES = ("study_sessions", "teach_back_scores", "knowledge_bridges")


def install(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE context_record_owners (
        id TEXT PRIMARY KEY NOT NULL,
        table_name TEXT NOT NULL CHECK(table_name IN
            ('study_sessions','teach_back_scores','knowledge_bridges')),
        row_id TEXT NOT NULL,
        session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
        project_id TEXT REFERENCES context_projects(id) ON DELETE CASCADE,
        scope TEXT CHECK(scope IN ('personal','work','unclassified')),
        created_at TEXT NOT NULL,
        UNIQUE(table_name,row_id),
        CHECK((session_id IS NOT NULL)+(project_id IS NOT NULL)+(scope IS NOT NULL)=1)
    )""")
    conn.execute(
        "CREATE INDEX context_record_session ON context_record_owners(session_id)"
    )
    conn.execute(
        "CREATE INDEX context_record_project ON context_record_owners(project_id)"
    )
    conn.execute("""CREATE TRIGGER context_record_owners_immutable
        BEFORE UPDATE ON context_record_owners
        BEGIN SELECT RAISE(ABORT,'Record ownership is immutable'); END""")
    conn.execute("""CREATE TRIGGER context_record_forget_session
        AFTER INSERT ON context_tombstones
        BEGIN DELETE FROM context_record_owners WHERE session_id=NEW.session_id; END""")
    for table in TABLES:
        # Identifiers are the fixed registry above, never a user-provided table.
        conn.execute(f"""CREATE TRIGGER context_record_remove_{table}
            AFTER DELETE ON context_record_owners WHEN OLD.table_name='{table}'
            BEGIN DELETE FROM {table} WHERE id=OLD.row_id; END""")
        conn.execute(f"""CREATE TRIGGER context_record_cleanup_{table}
            AFTER DELETE ON {table}
            BEGIN DELETE FROM context_record_owners
            WHERE table_name='{table}' AND row_id=CAST(OLD.id AS TEXT); END""")
