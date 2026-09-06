"""Typed review targets; review payloads reuse immutable source-linked observations."""

import sqlite3

STATEMENTS = (
    """CREATE TABLE context_review_targets (
        observation_id TEXT PRIMARY KEY NOT NULL
          REFERENCES context_observations(id) ON DELETE CASCADE,
        assertion_id TEXT REFERENCES context_assertions(id) ON DELETE CASCADE,
        relation_id TEXT REFERENCES context_relations(id) ON DELETE CASCADE,
        target_sha256 TEXT NOT NULL CHECK(length(target_sha256)=64),
        CHECK((assertion_id IS NOT NULL) != (relation_id IS NOT NULL))
    )""",
    "CREATE INDEX context_review_assertion ON context_review_targets(assertion_id)",
    "CREATE INDEX context_review_relation ON context_review_targets(relation_id)",
    "CREATE INDEX context_relations_incoming ON context_relations(to_assertion)",
    """CREATE TRIGGER context_review_targets_immutable BEFORE UPDATE ON context_review_targets
       BEGIN SELECT RAISE(ABORT, 'Review target bindings are immutable'); END""",
    """CREATE TRIGGER context_relations_immutable BEFORE UPDATE ON context_relations
       BEGIN SELECT RAISE(ABORT, 'Proposed relation versions are immutable'); END""",
    """CREATE TRIGGER context_remove_assertion_reviews BEFORE DELETE ON context_assertions
       BEGIN DELETE FROM context_observations WHERE id IN
         (SELECT observation_id FROM context_review_targets WHERE assertion_id=OLD.id); END""",
    """CREATE TRIGGER context_remove_relation_reviews BEFORE DELETE ON context_relations
       BEGIN DELETE FROM context_observations WHERE id IN
         (SELECT observation_id FROM context_review_targets WHERE relation_id=OLD.id); END""",
)


def install(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
