"""Immutable observations, source dependencies and content-free retirement links."""

import sqlite3

STATEMENTS = (
    """CREATE TABLE context_observations (
        id TEXT PRIMARY KEY NOT NULL,
        kind TEXT NOT NULL,
        subject TEXT NOT NULL,
        payload TEXT NOT NULL CHECK(json_valid(payload)),
        producer TEXT NOT NULL,
        authority TEXT NOT NULL CHECK(authority IN ('reported','model_interpretation')),
        recorded_at TEXT NOT NULL,
        binding_sha256 TEXT NOT NULL,
        subject_sha256 TEXT NOT NULL
    )""",
    "CREATE INDEX context_observations_subject ON context_observations(kind,subject)",
    """CREATE TRIGGER context_observations_immutable BEFORE UPDATE ON context_observations
        BEGIN SELECT RAISE(ABORT, 'Observation versions are immutable'); END""",
    """CREATE TABLE context_observation_sources (
        observation_id TEXT NOT NULL REFERENCES context_observations(id) ON DELETE CASCADE,
        evidence_id TEXT NOT NULL REFERENCES context_evidence(id) ON DELETE CASCADE,
        PRIMARY KEY(observation_id,evidence_id)
    )""",
    "CREATE INDEX context_observation_source ON context_observation_sources(evidence_id)",
    """CREATE TRIGGER context_observation_sources_immutable BEFORE UPDATE
        ON context_observation_sources
        BEGIN SELECT RAISE(ABORT, 'Observation source bindings are immutable'); END""",
    """CREATE TABLE context_observation_owners (
        observation_id TEXT PRIMARY KEY NOT NULL
            REFERENCES context_observations(id) ON DELETE CASCADE,
        project_id TEXT REFERENCES context_projects(id),
        fixed_scope TEXT CHECK(fixed_scope IN ('personal','work','unclassified')),
        CHECK((project_id IS NOT NULL) != (fixed_scope IS NOT NULL))
    )""",
    # These links contain only IDs. Retain them after a successor is forgotten,
    # so deletion cannot turn an older superseded claim back into current advice.
    """CREATE TABLE context_observation_supersedes (
        observation_id TEXT NOT NULL,
        previous_id TEXT NOT NULL,
        PRIMARY KEY(observation_id,previous_id),
        CHECK(observation_id != previous_id)
    )""",
    "CREATE INDEX context_observation_previous ON context_observation_supersedes(previous_id)",
    """CREATE TRIGGER context_observation_supersedes_immutable BEFORE UPDATE
        ON context_observation_supersedes
        BEGIN SELECT RAISE(ABORT, 'Observation revision bindings are immutable'); END""",
    """CREATE TABLE context_observation_tombstones (
        observation_id TEXT PRIMARY KEY NOT NULL,
        deleted_at TEXT NOT NULL
    )""",
    """CREATE TABLE context_observation_retired_subjects (
        subject_sha256 TEXT PRIMARY KEY NOT NULL
    )""",
    """CREATE TRIGGER context_observation_retirement BEFORE DELETE ON context_observations
        BEGIN INSERT OR IGNORE INTO context_observation_tombstones VALUES
          (OLD.id,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
          INSERT OR IGNORE INTO context_observation_retired_subjects VALUES (OLD.subject_sha256);
        END""",
    """CREATE TRIGGER context_no_forgotten_observation BEFORE INSERT ON context_observations
        WHEN EXISTS (SELECT 1 FROM context_observation_tombstones
          WHERE observation_id=NEW.id)
        BEGIN SELECT RAISE(ABORT, 'Observation was forgotten'); END""",
    """CREATE TRIGGER context_remove_dependent_observations BEFORE DELETE ON context_evidence
        BEGIN DELETE FROM context_observations WHERE id IN
          (SELECT observation_id FROM context_observation_sources WHERE evidence_id=OLD.id); END""",
)


def install(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
