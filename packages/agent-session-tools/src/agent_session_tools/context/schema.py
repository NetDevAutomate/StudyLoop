"""Additive canonical evidence schema. The migration caller owns its transaction."""

import sqlite3


# Execute individual statements: sqlite3.executescript would commit an enclosing
# migration transaction before running, defeating atomic upgrade/rollback.
STATEMENTS = (
    """CREATE TABLE context_projects (
        id TEXT PRIMARY KEY NOT NULL,
        scope TEXT NOT NULL CHECK(scope IN ('personal','work','unclassified')),
        policy_id TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE context_session_projects (
        session_id TEXT PRIMARY KEY NOT NULL REFERENCES sessions(id),
        project_id TEXT NOT NULL REFERENCES context_projects(id)
    )""",
    """CREATE TABLE context_evidence (
        id TEXT PRIMARY KEY NOT NULL,
        source_key TEXT NOT NULL,
        session_id TEXT NOT NULL REFERENCES sessions(id),
        harness TEXT NOT NULL,
        native_kind TEXT NOT NULL,
        native_locator TEXT NOT NULL,
        parser_version TEXT NOT NULL,
        machine_id TEXT NOT NULL,
        recorded_at TEXT,
        first_captured_at TEXT NOT NULL,
        body TEXT NOT NULL,
        body_sha256 TEXT NOT NULL,
        origin TEXT NOT NULL CHECK(origin IN
          ('conversation_message','process_exit','tool_result','unknown')),
        call_id TEXT,
        target TEXT,
        revision TEXT,
        exit_code INTEGER,
        CHECK ((origin='process_exit' AND typeof(exit_code)='integer') OR
               (origin!='process_exit' AND exit_code IS NULL))
    )""",
    "CREATE INDEX context_evidence_session ON context_evidence(session_id)",
    "CREATE INDEX context_evidence_source ON context_evidence(source_key)",
    """CREATE TRIGGER context_evidence_immutable BEFORE UPDATE ON context_evidence
        BEGIN SELECT RAISE(ABORT, 'Evidence versions are immutable'); END""",
    """CREATE VIRTUAL TABLE context_evidence_fts USING fts5(
        body, content='context_evidence', content_rowid='rowid',
        tokenize='unicode61'
    )""",
    """CREATE TRIGGER context_evidence_fts_insert AFTER INSERT ON context_evidence
        BEGIN INSERT INTO context_evidence_fts(rowid, body)
        VALUES (new.rowid, new.body); END""",
    """CREATE TRIGGER context_evidence_fts_delete AFTER DELETE ON context_evidence
        BEGIN INSERT INTO context_evidence_fts(context_evidence_fts,rowid,body)
        VALUES ('delete',old.rowid,old.body); END""",
    """CREATE TABLE context_assertions (
        id TEXT PRIMARY KEY NOT NULL,
        statement TEXT NOT NULL,
        proposed_state TEXT NOT NULL CHECK(proposed_state IN
            ('planned','in_progress','completed','unknown')),
        proposed_target TEXT,
        generator TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TRIGGER context_assertions_immutable BEFORE UPDATE ON context_assertions
        BEGIN SELECT RAISE(ABORT, 'Assertion versions are immutable'); END""",
    """CREATE TABLE context_citations (
        assertion_id TEXT NOT NULL REFERENCES context_assertions(id) ON DELETE CASCADE,
        evidence_id TEXT NOT NULL REFERENCES context_evidence(id) ON DELETE CASCADE,
        start_offset INTEGER NOT NULL CHECK(start_offset >= 0),
        end_offset INTEGER NOT NULL CHECK(end_offset > start_offset),
        quote TEXT NOT NULL,
        PRIMARY KEY(assertion_id,evidence_id,start_offset,end_offset)
    )""",
    """CREATE TRIGGER context_citations_immutable BEFORE UPDATE ON context_citations
        BEGIN SELECT RAISE(ABORT, 'Citation bindings are immutable'); END""",
    "CREATE INDEX context_citations_evidence ON context_citations(evidence_id)",
    """CREATE TRIGGER context_remove_dependent_assertions BEFORE DELETE ON context_evidence
        BEGIN DELETE FROM context_assertions WHERE id IN
          (SELECT assertion_id FROM context_citations WHERE evidence_id=OLD.id); END""",
    """CREATE TABLE context_relations (
        id TEXT PRIMARY KEY NOT NULL,
        from_assertion TEXT NOT NULL REFERENCES context_assertions(id) ON DELETE CASCADE,
        to_assertion TEXT NOT NULL REFERENCES context_assertions(id) ON DELETE CASCADE,
        relation TEXT NOT NULL CHECK(relation IN ('supports','contradicts','corrects')),
        proposer TEXT NOT NULL,
        created_at TEXT NOT NULL,
        CHECK(from_assertion != to_assertion),
        UNIQUE(from_assertion,to_assertion,relation,proposer)
    )""",
    """CREATE TABLE context_tombstones (
        session_id TEXT PRIMARY KEY NOT NULL,
        deletion_id TEXT NOT NULL UNIQUE,
        deleted_at TEXT NOT NULL
    )""",
    # Suppression survives direct writes through older capture adapters. More
    # complicated derived/sync/restore paths still require explicit integration.
    """CREATE TRIGGER context_no_forgotten_session BEFORE INSERT ON sessions
        WHEN EXISTS (SELECT 1 FROM context_tombstones WHERE session_id=NEW.id)
        BEGIN SELECT RAISE(IGNORE); END""",
    """CREATE TRIGGER context_no_forgotten_message BEFORE INSERT ON messages
        WHEN EXISTS (SELECT 1 FROM context_tombstones WHERE session_id=NEW.session_id)
        BEGIN SELECT RAISE(IGNORE); END""",
    """CREATE TRIGGER context_no_forgotten_evidence BEFORE INSERT ON context_evidence
        WHEN EXISTS (SELECT 1 FROM context_tombstones WHERE session_id=NEW.session_id)
        BEGIN SELECT RAISE(ABORT, 'Source session was forgotten'); END""",
)


def install(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
