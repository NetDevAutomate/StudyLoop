"""Exact additive schema for immutable concepts and append-only lifecycle events.

Lifted unchanged from the SessionWeaver reference ``concept_schema.py``
(``SCHEMA_VERSION = 2``); migration v49 installs exactly this DDL, so
``SCHEMA_FINGERPRINT`` is byte-for-byte identical to the reference's and
``UPSTREAM_SCHEMA_VERSION`` is pinned to the migration number that installs
the sidecar (design.md "Migrations: v48 tier-1 ontology, v49 concept
sidecar"). The sidecar records and verifies its own schema identity so drift
between this module's DDL and the installed DDL is detected, never silently
tolerated.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import NamedTuple
from uuid import uuid4

SCHEMA_VERSION = 2
UPSTREAM_SCHEMA_VERSION = 50
_SQLITE_MAX_INTEGER = (1 << 63) - 1
_MAX_COUNTER = _SQLITE_MAX_INTEGER - 1


class _SchemaObject(NamedTuple):
    kind: str
    name: str
    sql: str


_PAYLOAD_OBJECTS = (
    _SchemaObject(
        "table",
        "context_concepts",
        """CREATE TABLE context_concepts (
            id TEXT PRIMARY KEY NOT NULL,
            assertion_id TEXT UNIQUE REFERENCES context_assertions(id) ON DELETE CASCADE,
            binding_state TEXT NOT NULL CHECK(binding_state IN ('bound','legacy-unbound')),
            origin TEXT NOT NULL CHECK(origin IN ('winddown','legacy-okf','legacy-bind')),
            kind TEXT NOT NULL CHECK(kind IN
                ('Decision','Finding','Problem','Preference','Procedure')),
            title TEXT NOT NULL CHECK(length(trim(title))>0),
            statement TEXT NOT NULL CHECK(length(trim(statement))>0),
            canonical_tags TEXT NOT NULL
                CHECK(json_valid(canonical_tags) AND json_type(canonical_tags)='array'),
            confidence REAL NOT NULL
                CHECK(typeof(confidence) IN ('real','integer') AND confidence BETWEEN 0.5 AND 1.0),
            source_session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
            source_uri TEXT NOT NULL CHECK(length(trim(source_uri))>0),
            producer TEXT NOT NULL CHECK(length(trim(producer))>0),
            created_at TEXT NOT NULL CHECK(length(trim(created_at))>0),
            legacy_file_sha256 TEXT
                CHECK(legacy_file_sha256 IS NULL OR length(legacy_file_sha256)=64),
            supersedes_concept_id TEXT REFERENCES context_concepts(id),
            FOREIGN KEY(id) REFERENCES context_concept_events(initial_concept_id)
              DEFERRABLE INITIALLY DEFERRED,
            CHECK(
              (origin='winddown' AND binding_state='bound' AND assertion_id=id
                AND id NOT LIKE 'legacy:%' AND legacy_file_sha256 IS NULL
                AND source_session_id IS NOT NULL
                AND supersedes_concept_id IS NULL)
              OR
              (origin='legacy-okf' AND binding_state='legacy-unbound' AND assertion_id IS NULL
                AND id='legacy:' || legacy_file_sha256 AND supersedes_concept_id IS NULL
                AND (source_session_id IS NOT NULL OR
                  (source_uri LIKE 'sessionweaver://session/%'
                    AND length(source_uri)>length('sessionweaver://session/'))))
              OR
              (origin='legacy-bind' AND binding_state='bound' AND assertion_id=id
                AND id NOT LIKE 'legacy:%' AND legacy_file_sha256 IS NOT NULL
                AND source_session_id IS NOT NULL
                AND supersedes_concept_id IS NOT NULL)
            )
        )""",
    ),
    _SchemaObject(
        "index",
        "context_concepts_source_session",
        "CREATE INDEX context_concepts_source_session ON context_concepts(source_session_id)",
    ),
    _SchemaObject(
        "index",
        "context_concepts_kind",
        "CREATE INDEX context_concepts_kind ON context_concepts(kind)",
    ),
    _SchemaObject(
        "index",
        "context_concepts_one_bound_successor",
        """CREATE UNIQUE INDEX context_concepts_one_bound_successor
           ON context_concepts(supersedes_concept_id)
           WHERE supersedes_concept_id IS NOT NULL""",
    ),
    _SchemaObject(
        "trigger",
        "context_concepts_canonical_tags",
        """CREATE TRIGGER context_concepts_canonical_tags BEFORE INSERT ON context_concepts
        WHEN json_array_length(NEW.canonical_tags) NOT BETWEEN 2 AND 5
          OR EXISTS (
            SELECT 1 FROM json_each(NEW.canonical_tags)
            WHERE type!='text' OR length(value) NOT BETWEEN 1 AND 64
              OR substr(CAST(value AS TEXT),1,1) NOT GLOB '[a-z0-9]'
              OR CAST(value AS TEXT) GLOB '*[^a-z0-9._/-]*'
          )
          OR (SELECT count(*) FROM json_each(NEW.canonical_tags)) !=
             (SELECT count(DISTINCT value) FROM json_each(NEW.canonical_tags))
          OR NEW.canonical_tags != (
            SELECT json_group_array(value) FROM (
              SELECT value FROM json_each(NEW.canonical_tags) ORDER BY value
            )
          )
        BEGIN SELECT RAISE(ABORT, 'Concept canonical tags are invalid'); END""",
    ),
    _SchemaObject(
        "trigger",
        "context_concepts_bound_proof",
        """CREATE TRIGGER context_concepts_bound_proof BEFORE INSERT ON context_concepts
        WHEN NEW.binding_state='bound' AND (
          NOT EXISTS (
            SELECT 1 FROM context_assertions a
            WHERE a.id=NEW.assertion_id AND a.statement=NEW.statement
              AND a.proposed_state='unknown' AND a.proposed_target IS NULL
          )
          OR NOT (SELECT count(*) FROM context_citations c
                  WHERE c.assertion_id=NEW.assertion_id) BETWEEN 1 AND 8
          OR EXISTS (
            SELECT 1 FROM context_citations c
            LEFT JOIN context_evidence e ON e.id=c.evidence_id
            WHERE c.assertion_id=NEW.assertion_id
              AND (e.id IS NULL OR e.session_id!=NEW.source_session_id
                OR typeof(c.start_offset)!='integer'
                OR typeof(c.end_offset)!='integer'
                OR typeof(c.quote)!='text'
                OR c.start_offset<0 OR c.end_offset<=c.start_offset
                OR c.end_offset>length(e.body)
                OR substr(e.body,c.start_offset+1,c.end_offset-c.start_offset)!=c.quote)
          )
        )
        BEGIN SELECT RAISE(ABORT, 'bound concept invariant failed'); END""",
    ),
    _SchemaObject(
        "trigger",
        "context_citations_bound_insert",
        """CREATE TRIGGER context_citations_bound_insert
        BEFORE INSERT ON context_citations
        WHEN EXISTS (
          SELECT 1 FROM context_concepts c
          WHERE c.binding_state='bound' AND c.assertion_id=NEW.assertion_id
        ) AND (
          (SELECT count(*) FROM context_citations c
           WHERE c.assertion_id=NEW.assertion_id)>=8
          OR typeof(NEW.start_offset)!='integer'
          OR typeof(NEW.end_offset)!='integer'
          OR typeof(NEW.quote)!='text'
          OR NEW.start_offset<0 OR NEW.end_offset<=NEW.start_offset
          OR NOT EXISTS (
            SELECT 1 FROM context_concepts c
            JOIN context_evidence e ON e.id=NEW.evidence_id
            WHERE c.binding_state='bound' AND c.assertion_id=NEW.assertion_id
              AND e.session_id=c.source_session_id
              AND NEW.end_offset<=length(e.body)
              AND substr(e.body,NEW.start_offset+1,
                         NEW.end_offset-NEW.start_offset)=NEW.quote
          )
        )
        BEGIN SELECT RAISE(ABORT, 'bound citation invariant failed'); END""",
    ),
    _SchemaObject(
        "trigger",
        "context_citations_bound_delete",
        """CREATE TRIGGER context_citations_bound_delete
        BEFORE DELETE ON context_citations
        WHEN EXISTS (
          SELECT 1 FROM context_concepts c
          WHERE c.binding_state='bound' AND c.assertion_id=OLD.assertion_id
        ) AND (SELECT count(*) FROM context_citations c
               WHERE c.assertion_id=OLD.assertion_id)=1
        BEGIN SELECT RAISE(ABORT, 'bound citation invariant failed'); END""",
    ),
    _SchemaObject(
        "trigger",
        "context_concepts_legacy_successor",
        """CREATE TRIGGER context_concepts_legacy_successor BEFORE INSERT ON context_concepts
        WHEN NEW.origin='legacy-bind' AND NOT EXISTS (
          SELECT 1 FROM context_concepts previous
          WHERE previous.id=NEW.supersedes_concept_id
            AND previous.binding_state='legacy-unbound'
            AND previous.kind=NEW.kind
            AND previous.title=NEW.title
            AND previous.statement=NEW.statement
            AND previous.canonical_tags=NEW.canonical_tags
            AND previous.confidence=NEW.confidence
            AND (
              (previous.source_session_id IS NOT NULL
                AND previous.source_session_id=NEW.source_session_id)
              OR
              (previous.source_session_id IS NULL
                AND previous.source_uri='sessionweaver://session/' || NEW.source_session_id)
            )
            AND previous.source_uri=NEW.source_uri
            AND previous.producer=NEW.producer
            AND previous.legacy_file_sha256=NEW.legacy_file_sha256
        )
        BEGIN SELECT RAISE(ABORT, 'legacy successor invariant failed'); END""",
    ),
    _SchemaObject(
        "trigger",
        "context_concepts_immutable",
        """CREATE TRIGGER context_concepts_immutable BEFORE UPDATE ON context_concepts
        BEGIN SELECT RAISE(ABORT, 'Concept roots are immutable'); END""",
    ),
    _SchemaObject(
        "table",
        "context_concept_events",
        f"""CREATE TABLE context_concept_events (
            id TEXT PRIMARY KEY NOT NULL CHECK(length(id)=64),
            concept_id TEXT NOT NULL REFERENCES context_concepts(id) ON DELETE CASCADE,
            initial_concept_id TEXT UNIQUE,
            parent_event_id TEXT,
            standing TEXT NOT NULL CHECK(standing IN ('proposed','accepted','retired')),
            actor TEXT NOT NULL CHECK(length(trim(actor))>0),
            reason TEXT NOT NULL CHECK(length(trim(reason))>0),
            display_timestamp TEXT NOT NULL CHECK(length(trim(display_timestamp))>0),
            origin_instance TEXT NOT NULL CHECK(length(trim(origin_instance))>0),
            origin_seq INTEGER NOT NULL
              CHECK(typeof(origin_seq)='integer'
                AND origin_seq BETWEEN 1 AND {_MAX_COUNTER}),
            logical_time INTEGER NOT NULL
              CHECK(typeof(logical_time)='integer'
                AND logical_time BETWEEN 1 AND {_MAX_COUNTER}),
            UNIQUE(id,concept_id),
            UNIQUE(origin_instance,origin_seq),
            FOREIGN KEY(parent_event_id,concept_id)
              REFERENCES context_concept_events(id,concept_id),
            CHECK(
              (parent_event_id IS NULL AND standing='proposed'
                AND initial_concept_id IS NOT NULL AND initial_concept_id=concept_id)
              OR
              (parent_event_id IS NOT NULL AND standing!='proposed'
                AND initial_concept_id IS NULL)
            )
        )""",
    ),
    _SchemaObject(
        "index",
        "context_concept_events_current",
        """CREATE INDEX context_concept_events_current
           ON context_concept_events(concept_id,logical_time DESC,origin_instance DESC,
                                     origin_seq DESC,id DESC)""",
    ),
    _SchemaObject(
        "index",
        "context_concept_events_one_initial",
        """CREATE UNIQUE INDEX context_concept_events_one_initial
           ON context_concept_events(concept_id) WHERE parent_event_id IS NULL""",
    ),
    _SchemaObject(
        "trigger",
        "context_concept_events_immutable",
        """CREATE TRIGGER context_concept_events_immutable
        BEFORE UPDATE ON context_concept_events
        BEGIN SELECT RAISE(ABORT, 'Concept events are immutable'); END""",
    ),
    _SchemaObject(
        "table",
        "context_concept_clock",
        f"""CREATE TABLE context_concept_clock (
            id INTEGER PRIMARY KEY CHECK(id=1),
            origin_instance TEXT NOT NULL UNIQUE,
            origin_seq INTEGER NOT NULL
              CHECK(typeof(origin_seq)='integer'
                AND origin_seq BETWEEN 0 AND {_MAX_COUNTER}),
            logical_time INTEGER NOT NULL
              CHECK(typeof(logical_time)='integer'
                AND logical_time BETWEEN 0 AND {_MAX_COUNTER})
        )""",
    ),
    _SchemaObject(
        "trigger",
        "context_concept_clock_identity",
        """CREATE TRIGGER context_concept_clock_identity BEFORE UPDATE ON context_concept_clock
        WHEN NEW.id!=OLD.id OR NEW.origin_instance!=OLD.origin_instance
          OR NEW.origin_seq<OLD.origin_seq OR NEW.logical_time<OLD.logical_time
        BEGIN SELECT RAISE(ABORT, 'Concept clock identity is immutable'); END""",
    ),
    _SchemaObject(
        "table",
        "context_concept_fts",
        """CREATE VIRTUAL TABLE context_concept_fts USING fts5(
            title, statement, tags, kind, concept_id UNINDEXED, tokenize='unicode61'
        )""",
    ),
    _SchemaObject(
        "trigger",
        "context_concept_fts_insert",
        """CREATE TRIGGER context_concept_fts_insert AFTER INSERT ON context_concepts
        BEGIN
          INSERT INTO context_concept_fts(rowid,title,statement,tags,kind,concept_id)
          VALUES (
            NEW.rowid,NEW.title,NEW.statement,
            COALESCE((SELECT group_concat(value,' ') FROM json_each(NEW.canonical_tags)),''),
            NEW.kind,NEW.id
          );
        END""",
    ),
    _SchemaObject(
        "trigger",
        "context_concept_fts_delete",
        """CREATE TRIGGER context_concept_fts_delete AFTER DELETE ON context_concepts
        BEGIN DELETE FROM context_concept_fts WHERE rowid=OLD.rowid; END""",
    ),
)

_METADATA_OBJECTS = (
    _SchemaObject(
        "table",
        "context_concept_schema",
        """CREATE TABLE context_concept_schema (
            id INTEGER PRIMARY KEY CHECK(id=1),
            schema_version INTEGER NOT NULL,
            schema_fingerprint TEXT NOT NULL CHECK(length(schema_fingerprint)=64)
        )""",
    ),
    _SchemaObject(
        "trigger",
        "context_concept_schema_immutable",
        """CREATE TRIGGER context_concept_schema_immutable
        BEFORE UPDATE ON context_concept_schema
        BEGIN SELECT RAISE(ABORT, 'Concept schema identity is immutable'); END""",
    ),
    _SchemaObject(
        "trigger",
        "context_concept_schema_required",
        """CREATE TRIGGER context_concept_schema_required
        BEFORE DELETE ON context_concept_schema
        BEGIN SELECT RAISE(ABORT, 'Concept schema identity is required'); END""",
    ),
)


def _normalize_sql(value: str) -> str:
    return " ".join(value.split())


def _schema_payload(objects: tuple[_SchemaObject, ...]) -> list[list[str]]:
    return [[item.kind, item.name, _normalize_sql(item.sql)] for item in objects]


SCHEMA_FINGERPRINT = hashlib.sha256(
    json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "objects": _schema_payload(_PAYLOAD_OBJECTS + _METADATA_OBJECTS),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()


@dataclass(frozen=True)
class _FtsConsistency:
    """Internal deterministic FTS consistency receipt."""

    consistent: bool
    row_count: int
    expected_count: int
    digest: str
    actual_digest: str


@contextmanager
def _atomic(conn: sqlite3.Connection) -> Iterator[None]:
    owned = not conn.in_transaction
    savepoint = "concept_schema_" + uuid4().hex
    conn.execute("BEGIN IMMEDIATE" if owned else f"SAVEPOINT {savepoint}")
    try:
        yield
        if owned:
            conn.commit()
        else:
            conn.execute(f"RELEASE {savepoint}")
    except Exception:
        if owned:
            conn.rollback()
        elif conn.in_transaction:
            conn.execute(f"ROLLBACK TO {savepoint}")
            conn.execute(f"RELEASE {savepoint}")
        raise


def _object_rows(
    conn: sqlite3.Connection, objects: tuple[_SchemaObject, ...]
) -> dict[str, tuple[str, str]]:
    names = [item.name for item in objects]
    placeholders = ",".join("?" for _ in names)
    return {
        row[1]: (row[0], _normalize_sql(row[2] or ""))
        for row in conn.execute(
            f"SELECT type,name,sql FROM sqlite_master WHERE name IN ({placeholders})",
            names,
        )
    }


def _objects_match(
    conn: sqlite3.Connection, objects: tuple[_SchemaObject, ...]
) -> tuple[bool, bool]:
    rows = _object_rows(conn, objects)
    if not rows:
        return False, False
    expected = {item.name: (item.kind, _normalize_sql(item.sql)) for item in objects}
    return len(rows) == len(expected), rows == expected


def _verify_objects(conn: sqlite3.Connection) -> None:
    complete, exact = _objects_match(conn, _PAYLOAD_OBJECTS + _METADATA_OBJECTS)
    if not complete or not exact:
        raise RuntimeError("Concept schema is incomplete or has fingerprint drift")


def _create_objects(
    conn: sqlite3.Connection, objects: tuple[_SchemaObject, ...]
) -> None:
    for item in objects:
        conn.execute(item.sql)


def _verify_clock(conn: sqlite3.Connection) -> None:
    expected = conn.execute(
        "SELECT instance FROM context_access_state WHERE id=1"
    ).fetchone()
    actual = conn.execute(
        "SELECT origin_instance,origin_seq,logical_time FROM context_concept_clock WHERE id=1"
    ).fetchone()
    if expected is None or actual is None or actual[0] != expected[0]:
        raise RuntimeError(
            "Concept clock is missing or not pinned to this store instance"
        )
    if (
        type(actual[1]) is not int
        or type(actual[2]) is not int
        or not 0 <= actual[1] <= _MAX_COUNTER
        or not 0 <= actual[2] <= _MAX_COUNTER
    ):
        raise RuntimeError("Concept clock counters are invalid")


def _verify_installed_objects(conn: sqlite3.Connection) -> None:
    """Verify installed objects, marker, and clock without a version gate."""
    _verify_objects(conn)
    marker = conn.execute(
        "SELECT schema_version,schema_fingerprint FROM context_concept_schema WHERE id=1"
    ).fetchone()
    if marker is None or tuple(marker) != (SCHEMA_VERSION, SCHEMA_FINGERPRINT):
        raise RuntimeError("Concept schema version/fingerprint mismatch")
    _verify_clock(conn)


def verify_installed_schema(conn: sqlite3.Connection) -> None:
    """Verify an already-installed sidecar schema is exact, read-only, no mutation.

    Shared by ``_ensure_schema``'s existing-table branch and by projection's
    read-only callers so both agree on exactly one verification sequence.
    """
    upstream = conn.execute("PRAGMA user_version").fetchone()[0]
    if upstream != UPSTREAM_SCHEMA_VERSION:
        raise RuntimeError(
            f"Unsupported upstream schema v{upstream}; expected v{UPSTREAM_SCHEMA_VERSION}"
        )
    _verify_installed_objects(conn)


def install_schema(conn: sqlite3.Connection) -> None:
    """Install or exactly adopt the sidecar from ``migrate_v49``.

    Additive only -- no existing table, column, index, or trigger is altered;
    ``context_assertions`` in particular keeps its execution-state
    ``proposed_state`` vocabulary untouched (``EXECUTION-ERRATA.md`` decision
    #3). The version gate lives with the migration runner, which is mid-flight
    when this is called, so only the object/marker/clock identity is checked
    here. A byte-identical pre-existing sidecar (a database the SessionWeaver
    PoC already prepared) is adopted; a drifted one fails closed, because
    sidecar rows are authored data, not derived state.

    Downgrade (v49 -> v48): drop exactly these five objects and nothing else
    -- ``context_concepts``, ``context_concept_events``,
    ``context_concept_clock``, ``context_concept_fts``,
    ``context_concept_schema`` (their indexes and triggers drop implicitly
    with the tables). ``context_concepts`` carries an FK *to*
    ``context_assertions``, never the reverse, so the drop is unconditionally
    safe.
    """
    _install(conn)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Install, exactly adopt, or verify the sidecar without changing user_version."""
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise RuntimeError("Concept schema requires foreign_keys=ON")
    upstream = conn.execute("PRAGMA user_version").fetchone()[0]
    if upstream != UPSTREAM_SCHEMA_VERSION:
        raise RuntimeError(
            f"Unsupported upstream schema v{upstream}; expected v{UPSTREAM_SCHEMA_VERSION}"
        )
    _install(conn)


def _install(conn: sqlite3.Connection) -> None:
    required = {
        "context_assertions",
        "context_citations",
        "context_evidence",
        "context_access_state",
    }
    present = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'context_%'"
        )
    }
    if not required <= present:
        raise RuntimeError("Pinned context schema is incomplete")
    with _atomic(conn):
        metadata_present = (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='context_concept_schema'"
            ).fetchone()
            is not None
        )
        payload_complete, payload_exact = _objects_match(conn, _PAYLOAD_OBJECTS)
        payload_present = bool(_object_rows(conn, _PAYLOAD_OBJECTS))
        if metadata_present:
            _verify_installed_objects(conn)
            return
        if payload_complete and payload_exact:
            _create_objects(conn, _METADATA_OBJECTS)
            conn.execute(
                "INSERT INTO context_concept_schema VALUES (1,?,?)",
                (SCHEMA_VERSION, SCHEMA_FINGERPRINT),
            )
            _verify_objects(conn)
            _verify_clock(conn)
            return
        if payload_present:
            raise RuntimeError("Concept schema is incomplete or has fingerprint drift")
        _create_objects(conn, _PAYLOAD_OBJECTS)
        instance = conn.execute(
            "SELECT instance FROM context_access_state WHERE id=1"
        ).fetchone()
        if instance is None:
            raise RuntimeError("Pinned context instance identity is missing")
        conn.execute(
            "INSERT INTO context_concept_clock VALUES (1,?,0,0)", (instance[0],)
        )
        _create_objects(conn, _METADATA_OBJECTS)
        conn.execute(
            "INSERT INTO context_concept_schema VALUES (1,?,?)",
            (SCHEMA_VERSION, SCHEMA_FINGERPRINT),
        )
        _verify_objects(conn)
        _verify_clock(conn)


def _canonical_rows(rows: list[tuple[object, ...]]) -> str:
    return json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=False,
        separators=(",", ":"),
    )


def _digest(rows: list[tuple[object, ...]]) -> str:
    return hashlib.sha256(_canonical_rows(rows).encode("utf-8")).hexdigest()


def _inspect_fts_consistency(conn: sqlite3.Connection) -> _FtsConsistency:
    """Return a read-only FTS receipt after the caller verifies the sidecar schema."""
    expected = [
        tuple(row)
        for row in conn.execute(
            """SELECT id,title,statement,
               COALESCE((SELECT group_concat(value,' ') FROM json_each(canonical_tags)),''),
               kind FROM context_concepts ORDER BY 1,2,3,4,5"""
        )
    ]
    actual = [
        tuple(row)
        for row in conn.execute(
            """SELECT concept_id,title,statement,tags,kind
               FROM context_concept_fts ORDER BY 1,2,3,4,5"""
        )
    ]
    expected_digest = _digest(expected)
    actual_digest = _digest(actual)
    return _FtsConsistency(
        consistent=expected == actual,
        row_count=len(actual),
        expected_count=len(expected),
        digest=expected_digest,
        actual_digest=actual_digest,
    )


def _fts_consistency(conn: sqlite3.Connection) -> _FtsConsistency:
    """Return a stable, rowid-independent receipt, installing the sidecar if needed."""
    _ensure_schema(conn)
    return _inspect_fts_consistency(conn)


def _rebuild_fts(conn: sqlite3.Connection) -> _FtsConsistency:
    """Deterministically rebuild derived FTS content inside the caller transaction."""
    _ensure_schema(conn)
    with _atomic(conn):
        conn.execute("DELETE FROM context_concept_fts")
        conn.execute(
            """INSERT INTO context_concept_fts(rowid,title,statement,tags,kind,concept_id)
               SELECT rowid,title,statement,
                 COALESCE((SELECT group_concat(value,' ') FROM json_each(canonical_tags)),''),
                 kind,id FROM context_concepts ORDER BY id"""
        )
    return _fts_consistency(conn)
