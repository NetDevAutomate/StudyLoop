"""Deterministic Tier-1 ontology extraction, rebuild, and health contracts.

Lifted from SessionWeaver's reference implementation
(``session_weaver.ontology``, extraction version ``tier1-v2-canonical-messages``)
per the phase-2 retrofit design (``openspec/changes/sessionweaver-phase2-retrofit
/design.md``, "Migrations" and A2's canonical-ontology-baseline ruling). The
extraction version string and the logical-hash algorithm are byte-for-byte
identical to the reference so upstream's A2 baseline
(``docs/data/ontology-tier1-baseline.json``) is directly comparable to this
package's own baseline.

Every row in ``ontology_structural``, ``ontology_individual`` and
``ontology_relation`` is derived from ``sessions``/``messages`` and is
byte-for-byte reproducible by a full rebuild -- nothing here is user-authored
or carries independent provenance. That is why the ontology is *derived,
never synced* (``sync.SYNC_TABLES`` / ``sync.GLOBAL_SYNC_TABLES`` never list
these tables) and why a rebuild is always safe to re-run.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from collections.abc import Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

logger = logging.getLogger(__name__)

EXTRACTION_VERSION = "tier1-v2-canonical-messages"
_LOGICAL_FORMAT = "sessionweaver-ontology-logical-v1"
_BUSY_TIMEOUT_MS = 5_000

ONTOLOGY_TABLES: frozenset[str] = frozenset(
    {
        "ontology_class",
        "ontology_property",
        "ontology_individual",
        "ontology_relation",
        "ontology_structural",
        "ontology_build_state",
    }
)
ONTOLOGY_INDEXES: Mapping[str, tuple[str, ...]] = {
    "idx_ontology_structural_session_type": ("session_id", "type"),
    "idx_ontology_individual_class_label": ("class", "label"),
    "idx_ontology_relation_subject_predicate_object": (
        "subject",
        "predicate",
        "object",
    ),
    "idx_ontology_relation_predicate_subject_object": (
        "predicate",
        "subject",
        "object",
    ),
    "idx_ontology_relation_object_predicate_subject": (
        "object",
        "predicate",
        "subject",
    ),
}

_TBOX_CLASSES = (
    ("Project", None, "A codebase/topic identified by its filesystem root"),
    ("Harness", None, "A coding-agent tool that conducts sessions"),
    ("Session", None, "One recorded conversation between the user and an agent"),
    ("SubagentSession", "Session", "A session spawned by another session"),
    ("Artifact", None, "A file touched or referenced during work"),
    ("Command", None, "A shell command class, keyed by its binary"),
    ("TestRun", None, "A recorded test-suite execution with its verbatim summary"),
)
_TBOX_PROPERTIES = (
    ("ranIn", "Session", "Project", "The project a session worked in"),
    ("conductedBy", "Session", "Harness", "The harness that produced the session"),
    ("childOf", "SubagentSession", "Session", "The parent session of a subagent"),
    ("touched", "Session", "Artifact", "The session referenced this file"),
    ("executed", "Session", "Command", "The session ran this command binary"),
    ("produced", "Session", "TestRun", "The session produced this test result"),
)

# Frozen PoC expressions. Extraction version 2 deliberately does not widen these.
_RE_TESTRUN = re.compile(
    r"(\d+ passed(?:, \d+ (?:skipped|xfailed|failed|deselected|xpassed))*"
    r"[^\n]{0,40}in [\d.]+s)"
)
_RE_PATH = re.compile(
    r"(?<![\w.])(/Users/[a-z]+/[\w./~-]{8,140}\.[A-Za-z0-9]{1,8})(?![\w/])"
)
_RE_CMD = re.compile(
    r"(?:^\$ |^```(?:bash|zsh|sh)\n)([a-z][\w.-]+(?: [^\n`]{2,120})?)",
    re.M,
)
_RE_TEST_NUMS = re.compile(r"(\d+) passed(?:, (\d+) skipped)?(?:, (\d+) deselected)?")
_RE_PARENT = re.compile(r"/([0-9a-f]{8}-[0-9a-f-]{27})/subagents/")
_SUFFIX = re.compile(r"_[A-Za-z0-9_]+")

_LIVE_TO_STAGING = {table: f"__{table}_next" for table in ONTOLOGY_TABLES}
_LIVE_IDENTITY = {table: table for table in ONTOLOGY_TABLES}
_GRAPH_TABLE_ORDER = (
    (
        "class",
        "ontology_class",
        ("name", "parent", "description"),
        ("name",),
    ),
    (
        "property",
        "ontology_property",
        ("name", "domain", "range", "description"),
        ("name",),
    ),
    (
        "structural",
        "ontology_structural",
        ("id", "session_id", "type", "key", "value", "ts", "extraction_version"),
        ("id",),
    ),
    (
        "individual",
        "ontology_individual",
        ("id", "class", "label", "attrs"),
        ("id",),
    ),
    (
        "relation",
        "ontology_relation",
        ("subject", "predicate", "object"),
        ("subject", "predicate", "object"),
    ),
)


_EXPECTED_COLUMNS: Mapping[str, tuple[str, ...]] = {
    "ontology_class": ("name", "parent", "description"),
    "ontology_property": ("name", "domain", "range", "description"),
    "ontology_structural": (
        "id",
        "session_id",
        "type",
        "key",
        "value",
        "ts",
        "extraction_version",
    ),
    "ontology_individual": ("id", "class", "label", "attrs"),
    "ontology_relation": ("subject", "predicate", "object"),
    "ontology_build_state": (
        "singleton",
        "extraction_version",
        "logical_hash",
        "completed_at",
        "mode",
        "source_session_count",
        "source_message_count",
        "candidate_session_count",
        "counts",
    ),
}


class OntologyError(RuntimeError):
    """Base class for maintained ontology failures."""


class OntologyValidationError(OntologyError):
    """Raised when extracted rows cannot form one valid deterministic graph."""


@dataclass(frozen=True, slots=True)
class CanonicalMessage:
    """One normalized conversation message in deterministic extraction order."""

    id: str
    session_id: str
    role: str
    content: str
    timestamp: str | None
    seq: int | None


@dataclass(frozen=True, slots=True)
class OntologyCounts:
    """Stable graph and source counts returned to later CLI/doctor consumers."""

    classes: int
    properties: int
    structural: int
    individuals: int
    relations: int
    source_sessions: int
    source_messages: int


@dataclass(frozen=True, slots=True)
class OntologyBuildResult:
    """The committed result of one full or incremental ontology rebuild."""

    extraction_version: str
    logical_hash: str
    completed_at: str
    mode: Literal["full", "incremental"]
    fallback_reason: str | None
    candidate_sessions: int
    counts: OntologyCounts


@dataclass(frozen=True, slots=True)
class OntologyStatus:
    """Read-only ontology health dimensions and deterministic diagnostics."""

    healthy: bool
    extraction_version: str | None
    extraction_version_matches: bool
    recorded_logical_hash: str | None
    recomputed_logical_hash: str | None
    hash_matches: bool
    completed_at: str | None
    completed_at_valid: bool
    newest_session_updated_at: str | None
    fresh: bool
    source_sessions: int
    source_messages: int
    recorded_source_sessions: int | None
    recorded_source_messages: int | None
    source_counts_match: bool
    covered_sessions: int
    missing_sessions: int
    coverage_ratio: float
    orphan_session_individuals: int
    orphan_structural_rows: int
    foreign_key_violations: int
    domain_range_violations: int
    missing_tables: tuple[str, ...]
    missing_indexes: tuple[str, ...]
    schema_errors: tuple[str, ...]
    malformed_timestamps: tuple[str, ...]
    diagnostics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Session:
    id: str
    source: str
    project_path: str | None
    git_branch: str | None
    created_at: str | None
    updated_at: str | None
    metadata: str | None


@dataclass(frozen=True, slots=True)
class _Structural:
    id: str
    session_id: str
    type: str
    key: str
    value: str
    ts: str | None
    extraction_version: str = EXTRACTION_VERSION

    def values(self) -> tuple[object, ...]:
        return (
            self.id,
            self.session_id,
            self.type,
            self.key,
            self.value,
            self.ts,
            self.extraction_version,
        )


@dataclass(frozen=True, slots=True)
class _Individual:
    id: str
    class_name: str
    label: str
    attrs: str

    def values(self) -> tuple[str, str, str, str]:
        return (self.id, self.class_name, self.label, self.attrs)


@dataclass(frozen=True, slots=True)
class _Graph:
    individuals: tuple[_Individual, ...]
    relations: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True, slots=True)
class _BuildState:
    logical_hash: str
    completed_at: str
    source_session_count: int
    source_message_count: int


@dataclass(frozen=True, slots=True)
class _ExtractionPlan:
    mode: Literal["full", "incremental"]
    fallback_reason: str | None
    candidate_ids: frozenset[str]
    structural: tuple[_Structural, ...]


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _timestamp_text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _parse_timestamp(timestamp: object) -> datetime | None:
    timestamp_text = _timestamp_text(timestamp)
    if timestamp_text is None:
        return None
    normalized = timestamp_text.removesuffix("Z")
    if timestamp_text.endswith("Z"):
        normalized += "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parsed_timestamp_key(timestamp: str | None) -> tuple[int, str, str]:
    """Return a total-order key with parseable timestamps before raw text."""
    raw = timestamp or ""
    parsed = _parse_timestamp(timestamp)
    if parsed is None:
        return (1, "", raw)
    return (0, parsed.isoformat(timespec="microseconds"), raw)


def _canonical_message_key(message: CanonicalMessage) -> tuple[object, ...]:
    return (
        message.seq is None,
        message.seq if message.seq is not None else 0,
        *_parsed_timestamp_key(message.timestamp),
        message.id,
    )


def canonical_messages(
    conn: sqlite3.Connection,
    session_ids: Collection[str] | None = None,
) -> Iterator[CanonicalMessage]:
    """Yield normalized, per-session deduplicated messages in a total order."""
    parameters: tuple[str, ...] = ()
    restriction = ""
    if session_ids is not None:
        selected = tuple(sorted(set(session_ids)))
        if not selected:
            return
        placeholders = ", ".join("?" for _ in selected)
        restriction = f" AND session_id IN ({placeholders})"
        parameters = selected

    rows: list[CanonicalMessage] = []
    query = (
        "SELECT id, session_id, role, content, timestamp, seq "
        "FROM messages WHERE role IN ('user', 'assistant')" + restriction
    )
    for message_id, session_id, role, content, timestamp, seq in conn.execute(
        query, parameters
    ):
        if content is None:
            continue
        text = content.strip()
        if not text:
            continue
        # SQLite LIKE is ASCII-case-insensitive by default; preserve that measured filter.
        if len(text) < 120 and text.lower().startswith("[tool:"):
            continue
        rows.append(
            CanonicalMessage(
                id=message_id,
                session_id=session_id,
                role=role,
                content=text,
                timestamp=timestamp,
                seq=seq,
            )
        )

    rows.sort(
        key=lambda message: (message.session_id, *_canonical_message_key(message))
    )
    seen: dict[str, set[str]] = {}
    for message in rows:
        session_seen = seen.setdefault(message.session_id, set())
        if message.content in session_seen:
            continue
        session_seen.add(message.content)
        yield message


def _read_sessions(conn: sqlite3.Connection) -> tuple[_Session, ...]:
    rows = conn.execute(
        """
        SELECT id, source, project_path, git_branch, created_at, updated_at, metadata
        FROM sessions
        ORDER BY id
        """
    )
    return tuple(_Session(*row) for row in rows)


def _message_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        session_id: count
        for session_id, count in conn.execute(
            "SELECT session_id, COUNT(*) FROM messages GROUP BY session_id ORDER BY session_id"
        )
    }


def _make_structural(
    session_id: str,
    entity_type: str,
    key: str,
    value: str,
    timestamp: str | None,
) -> _Structural:
    identity = {"key": key, "session_id": session_id, "type": entity_type}
    return _Structural(
        id=_sha256_json(identity),
        session_id=session_id,
        type=entity_type,
        key=key,
        value=value,
        ts=timestamp,
    )


def _add_structural(
    rows: dict[tuple[str, str, str], _Structural],
    row: _Structural,
) -> None:
    identity = (row.session_id, row.type, row.key)
    previous = rows.get(identity)
    if previous is None:
        rows[identity] = row


def _extract_structural(
    conn: sqlite3.Connection,
    sessions: Sequence[_Session],
    session_ids: Collection[str] | None = None,
) -> tuple[_Structural, ...]:
    selected = {session.id for session in sessions}
    if session_ids is not None:
        selected.intersection_update(session_ids)
    rows: dict[tuple[str, str, str], _Structural] = {}

    for session in sessions:
        if session.id not in selected:
            continue
        path = session.project_path or "unknown"
        _add_structural(
            rows,
            _make_structural(
                session.id,
                "project",
                path,
                session.git_branch or "",
                session.updated_at,
            ),
        )

    for message in canonical_messages(conn, selected):
        for match in _RE_TESTRUN.finditer(message.content):
            summary = match.group(1)
            _add_structural(
                rows,
                _make_structural(
                    message.session_id,
                    "testrun",
                    summary,
                    summary,
                    message.timestamp,
                ),
            )
        for match in _RE_PATH.finditer(message.content):
            path = match.group(1)
            _add_structural(
                rows,
                _make_structural(
                    message.session_id,
                    "artifact",
                    path,
                    path,
                    message.timestamp,
                ),
            )
        for match in _RE_CMD.finditer(message.content):
            command = match.group(1).strip()
            binary = command.split()[0]
            _add_structural(
                rows,
                _make_structural(
                    message.session_id,
                    "command",
                    binary,
                    command,
                    message.timestamp,
                ),
            )

    return tuple(
        sorted(rows.values(), key=lambda row: (row.session_id, row.type, row.key))
    )


def _add_individual(
    rows: dict[str, _Individual],
    individual_id: str,
    class_name: str,
    label: str,
    attrs: object,
) -> str:
    candidate = _Individual(
        id=individual_id,
        class_name=class_name,
        label=label[:200],
        attrs=_canonical_json(attrs),
    )
    previous = rows.get(individual_id)
    if previous is not None and previous != candidate:
        raise OntologyValidationError(f"conflicting individual id: {individual_id}")
    rows.setdefault(individual_id, candidate)
    return individual_id


def _test_run_id(session_id: str, summary: str) -> str:
    digest = hashlib.sha256(summary.encode("utf-8")).hexdigest()
    return f"testrun:{session_id}:{digest}"


def _build_graph(
    sessions: Sequence[_Session],
    structural: Sequence[_Structural],
    message_counts: Mapping[str, int],
) -> _Graph:
    individuals: dict[str, _Individual] = {}
    relations: set[tuple[str, str, str]] = set()
    known_session_ids = {session.id for session in sessions}
    project_rows = {row.session_id: row for row in structural if row.type == "project"}

    for session in sessions:
        project = project_rows.get(session.id)
        if project is None:
            raise OntologyValidationError(
                f"session has no structural project: {session.id}"
            )
        harness_id = _add_individual(
            individuals,
            f"harness:{session.source}",
            "Harness",
            session.source,
            {},
        )
        project_id = _add_individual(
            individuals,
            f"project:{project.key}",
            "Project",
            project.key,
            {"path": None if project.key == "unknown" else project.key},
        )
        parent_match = _RE_PARENT.search(session.metadata or "")
        parent_id = parent_match.group(1) if parent_match is not None else None
        class_name = (
            "SubagentSession"
            if session.id.startswith("agent-") or parent_match is not None
            else "Session"
        )
        session_individual_id = _add_individual(
            individuals,
            f"session:{session.id}",
            class_name,
            session.id[:24],
            {
                "branch": session.git_branch,
                "created": session.created_at,
                "messages": message_counts.get(session.id, 0),
                "updated": session.updated_at,
            },
        )
        relations.add((session_individual_id, "ranIn", project_id))
        relations.add((session_individual_id, "conductedBy", harness_id))
        if parent_id in known_session_ids:
            relations.add((session_individual_id, "childOf", f"session:{parent_id}"))

    for row in structural:
        if row.type == "project":
            continue
        session_id = f"session:{row.session_id}"
        if session_id not in individuals:
            raise OntologyValidationError(
                f"structural row references absent session: {row.session_id}"
            )
        if row.type == "artifact":
            object_id = _add_individual(
                individuals,
                f"artifact:{row.value}",
                "Artifact",
                row.value,
                {"ext": row.value.rsplit(".", 1)[-1], "path": row.value},
            )
            relations.add((session_id, "touched", object_id))
        elif row.type == "command":
            object_id = _add_individual(
                individuals,
                f"command:{row.key}",
                "Command",
                row.key,
                {"binary": row.key},
            )
            relations.add((session_id, "executed", object_id))
        elif row.type == "testrun":
            parsed = _RE_TEST_NUMS.search(row.value)
            attrs: dict[str, object] = {"summary": row.value}
            if parsed is not None:
                attrs.update(
                    passed=int(parsed.group(1)),
                    skipped=int(parsed.group(2) or 0),
                    deselected=int(parsed.group(3) or 0),
                )
            object_id = _add_individual(
                individuals,
                _test_run_id(row.session_id, row.value),
                "TestRun",
                row.value[:60],
                attrs,
            )
            relations.add((session_id, "produced", object_id))
        else:
            raise OntologyValidationError(f"unknown structural type: {row.type}")

    return _Graph(
        individuals=tuple(sorted(individuals.values(), key=lambda row: row.id)),
        relations=tuple(sorted(relations)),
    )


def _drop_tables(conn: sqlite3.Connection, *, staging: bool) -> None:
    names = _LIVE_TO_STAGING if staging else _LIVE_IDENTITY
    for table in (
        "ontology_relation",
        "ontology_individual",
        "ontology_property",
        "ontology_class",
        "ontology_structural",
        "ontology_build_state",
    ):
        conn.execute(f'DROP TABLE IF EXISTS "{names[table]}"')


def _table_ddl_statements(
    names: Mapping[str, str],
    *,
    if_not_exists: bool = False,
) -> tuple[str, ...]:
    """DDL for the six ontology schema objects under an arbitrary name mapping.

    ``names`` maps each of :data:`ONTOLOGY_TABLES` to the physical table name
    to create. Used both for staging tables (rebuild's atomic swap) and for
    the live tables directly (migration v48's fresh install), so the two can
    never drift apart.

    ``if_not_exists`` is for the migration path only: a database that ran
    ontology extraction ad hoc before migrations existed for it (or one
    already mid-upgrade from a retried migration) may already have some of
    these tables, in whatever shape that earlier code left them in.
    Migration v48 must still converge rather than crash -- the first
    rebuild's staging swap (:func:`_swap_staging`) unconditionally drops and
    replaces every one of these six tables regardless of their prior shape,
    so tolerating a pre-existing table here costs nothing: it is corrected
    the moment anything calls :func:`rebuild_ontology`.
    """
    clause = "IF NOT EXISTS " if if_not_exists else ""
    return (
        f"""
        CREATE TABLE {clause}{names["ontology_class"]}(
            name TEXT PRIMARY KEY CHECK(length(name) > 0),
            parent TEXT REFERENCES {names["ontology_class"]}(name)
                DEFERRABLE INITIALLY DEFERRED,
            description TEXT NOT NULL CHECK(length(description) > 0)
        )
        """,
        f"""
        CREATE TABLE {clause}{names["ontology_property"]}(
            name TEXT PRIMARY KEY CHECK(length(name) > 0),
            domain TEXT NOT NULL REFERENCES {names["ontology_class"]}(name),
            range TEXT NOT NULL REFERENCES {names["ontology_class"]}(name),
            description TEXT NOT NULL CHECK(length(description) > 0)
        )
        """,
        f"""
        CREATE TABLE {clause}{names["ontology_structural"]}(
            id TEXT PRIMARY KEY CHECK(length(id) = 64),
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            type TEXT NOT NULL CHECK(type IN ('project', 'testrun', 'artifact', 'command')),
            key TEXT NOT NULL CHECK(length(key) > 0),
            value TEXT NOT NULL,
            ts TEXT,
            extraction_version TEXT NOT NULL,
            UNIQUE(session_id, type, key)
        )
        """,
        f"""
        CREATE TABLE {clause}{names["ontology_individual"]}(
            id TEXT PRIMARY KEY CHECK(length(id) > 0),
            class TEXT NOT NULL REFERENCES {names["ontology_class"]}(name),
            label TEXT NOT NULL CHECK(length(label) <= 200),
            attrs TEXT NOT NULL CHECK(json_valid(attrs))
        )
        """,
        f"""
        CREATE TABLE {clause}{names["ontology_relation"]}(
            subject TEXT NOT NULL REFERENCES {names["ontology_individual"]}(id),
            predicate TEXT NOT NULL REFERENCES {names["ontology_property"]}(name),
            object TEXT NOT NULL REFERENCES {names["ontology_individual"]}(id),
            PRIMARY KEY(subject, predicate, object)
        ) WITHOUT ROWID
        """,
        f"""
        CREATE TABLE {clause}{names["ontology_build_state"]}(
            singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
            extraction_version TEXT NOT NULL,
            logical_hash TEXT NOT NULL CHECK(length(logical_hash) = 64),
            completed_at TEXT NOT NULL,
            mode TEXT NOT NULL CHECK(mode IN ('full', 'incremental')),
            source_session_count INTEGER NOT NULL CHECK(source_session_count >= 0),
            source_message_count INTEGER NOT NULL CHECK(source_message_count >= 0),
            candidate_session_count INTEGER NOT NULL CHECK(candidate_session_count >= 0),
            counts TEXT NOT NULL CHECK(json_valid(counts))
        )
        """,
    )


def _create_staging_tables(conn: sqlite3.Connection) -> None:
    for statement in _table_ddl_statements(_LIVE_TO_STAGING):
        conn.execute(statement)


def install_schema(conn: sqlite3.Connection) -> None:
    """Create the six live ontology schema objects, empty, with their indexes.

    This is exactly what migration v48 needs: the tables and indexes
    ``ontology.py`` defines, present but unpopulated (the first rebuild --
    triggered by the next export or ``session-maint ontology-rebuild`` --
    populates them). Shares its DDL with the staging-table path used by
    :func:`rebuild_ontology`, so a migrated-fresh schema and a rebuilt-live
    schema can never drift apart.

    Uses ``IF NOT EXISTS`` (see :func:`_table_ddl_statements`): a database
    that already carries ad hoc ontology tables from before this migration
    existed converges on the next rebuild rather than failing the migration.
    """
    for statement in _table_ddl_statements(_LIVE_IDENTITY, if_not_exists=True):
        conn.execute(statement)
    _create_live_indexes(conn)


def _populate_staging(
    conn: sqlite3.Connection,
    structural: Sequence[_Structural],
    graph: _Graph,
) -> None:
    class_rows = sorted(_TBOX_CLASSES, key=lambda row: (row[1] is not None, row[0]))
    conn.executemany("INSERT INTO __ontology_class_next VALUES (?, ?, ?)", class_rows)
    conn.executemany(
        "INSERT INTO __ontology_property_next VALUES (?, ?, ?, ?)",
        sorted(_TBOX_PROPERTIES),
    )
    conn.executemany(
        "INSERT INTO __ontology_structural_next VALUES (?, ?, ?, ?, ?, ?, ?)",
        (row.values() for row in sorted(structural, key=lambda item: item.id)),
    )
    conn.executemany(
        "INSERT INTO __ontology_individual_next VALUES (?, ?, ?, ?)",
        (row.values() for row in graph.individuals),
    )
    conn.executemany(
        "INSERT INTO __ontology_relation_next VALUES (?, ?, ?)",
        graph.relations,
    )


def _table_for_suffix(table: str, suffix: str) -> str:
    if not suffix:
        return table
    if _SUFFIX.fullmatch(suffix) is None:
        raise ValueError(f"invalid ontology table suffix: {suffix!r}")
    return f"__{table}{suffix}"


def ontology_logical_hash(conn: sqlite3.Connection, *, suffix: str = "") -> str:
    """Hash canonical logical rows, excluding storage layout and build metadata."""
    digest = hashlib.sha256()

    def add_line(value: object) -> None:
        digest.update(_canonical_json(value).encode("utf-8"))
        digest.update(b"\n")

    add_line({"extraction_version": EXTRACTION_VERSION, "format": _LOGICAL_FORMAT})
    for logical_name, base_table, columns, primary_key in _GRAPH_TABLE_ORDER:
        table = _table_for_suffix(base_table, suffix)
        selected = ", ".join(f'"{column}"' for column in columns)
        ordered = ", ".join(f'"{column}"' for column in primary_key)
        query = f'SELECT {selected} FROM "{table}" ORDER BY {ordered}'
        for raw_row in conn.execute(query):
            row = list(raw_row)
            if logical_name == "individual":
                try:
                    row[3] = json.loads(row[3])
                except (TypeError, json.JSONDecodeError) as error:
                    raise OntologyValidationError(
                        f"individual attrs are not canonical JSON: {row[0]}"
                    ) from error
            add_line({"columns": columns, "row": row, "table": logical_name})
    return digest.hexdigest()


def _domain_range_violations(conn: sqlite3.Connection, *, suffix: str) -> int:
    classes = _table_for_suffix("ontology_class", suffix)
    properties = _table_for_suffix("ontology_property", suffix)
    individuals = _table_for_suffix("ontology_individual", suffix)
    relations = _table_for_suffix("ontology_relation", suffix)
    query = f"""
        WITH RECURSIVE ancestors(class, ancestor) AS (
            SELECT name, name FROM "{classes}"
            UNION
            SELECT ancestors.class, parent.parent
            FROM ancestors
            JOIN "{classes}" AS parent ON parent.name = ancestors.ancestor
            WHERE parent.parent IS NOT NULL
        )
        SELECT COUNT(*)
        FROM "{relations}" AS relation
        JOIN "{individuals}" AS subject ON subject.id = relation.subject
        JOIN "{individuals}" AS object ON object.id = relation.object
        JOIN "{properties}" AS property ON property.name = relation.predicate
        WHERE NOT EXISTS (
            SELECT 1 FROM ancestors
            WHERE ancestors.class = subject.class
              AND ancestors.ancestor = property.domain
        ) OR NOT EXISTS (
            SELECT 1 FROM ancestors
            WHERE ancestors.class = object.class
              AND ancestors.ancestor = property.range
        )
    """
    return int(conn.execute(query).fetchone()[0])


def _validate_staging(conn: sqlite3.Connection, source_session_count: int) -> None:
    foreign_key_errors: list[tuple[object, ...]] = []
    for table in _LIVE_TO_STAGING.values():
        foreign_key_errors.extend(conn.execute(f'PRAGMA foreign_key_check("{table}")'))
    if foreign_key_errors:
        raise OntologyValidationError(
            f"staging foreign-key violations: {len(foreign_key_errors)}"
        )

    missing_projects = conn.execute(
        """
        SELECT COUNT(*)
        FROM sessions AS source
        LEFT JOIN __ontology_structural_next AS structural
          ON structural.session_id = source.id AND structural.type = 'project'
        GROUP BY source.id
        HAVING COUNT(structural.id) != 1
        """
    ).fetchall()
    if (
        missing_projects
        or conn.execute(
            "SELECT COUNT(*) FROM __ontology_structural_next WHERE type = 'project'"
        ).fetchone()[0]
        != source_session_count
    ):
        raise OntologyValidationError(
            "staging does not contain one project per session"
        )

    versions = {
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT extraction_version FROM __ontology_structural_next"
        )
    }
    if versions and versions != {EXTRACTION_VERSION}:
        raise OntologyValidationError(
            f"unexpected staging extraction versions: {versions!r}"
        )
    domain_range = _domain_range_violations(conn, suffix="_next")
    if domain_range:
        raise OntologyValidationError(
            f"staging domain/range violations: {domain_range}"
        )


def _graph_counts(
    conn: sqlite3.Connection,
    *,
    suffix: str,
    source_session_count: int,
    source_message_count: int,
) -> OntologyCounts:
    return OntologyCounts(
        classes=int(
            conn.execute(
                f'SELECT COUNT(*) FROM "{_table_for_suffix("ontology_class", suffix)}"'
            ).fetchone()[0]
        ),
        properties=int(
            conn.execute(
                f'SELECT COUNT(*) FROM "{_table_for_suffix("ontology_property", suffix)}"'
            ).fetchone()[0]
        ),
        structural=int(
            conn.execute(
                f'SELECT COUNT(*) FROM "{_table_for_suffix("ontology_structural", suffix)}"'
            ).fetchone()[0]
        ),
        individuals=int(
            conn.execute(
                f'SELECT COUNT(*) FROM "{_table_for_suffix("ontology_individual", suffix)}"'
            ).fetchone()[0]
        ),
        relations=int(
            conn.execute(
                f'SELECT COUNT(*) FROM "{_table_for_suffix("ontology_relation", suffix)}"'
            ).fetchone()[0]
        ),
        source_sessions=source_session_count,
        source_messages=source_message_count,
    )


def _create_live_indexes(conn: sqlite3.Connection) -> None:
    # IF NOT EXISTS: harmless after a fresh staging swap (nothing to collide
    # with) and required for migration v48's install path, which may find a
    # pre-existing ad hoc ontology schema with none of these named indexes.
    for index, columns in ONTOLOGY_INDEXES.items():
        table = (
            "ontology_structural"
            if index.startswith("idx_ontology_structural")
            else "ontology_individual"
            if index.startswith("idx_ontology_individual")
            else "ontology_relation"
        )
        column_sql = ", ".join(f'"{column}"' for column in columns)
        conn.execute(f'CREATE INDEX IF NOT EXISTS "{index}" ON "{table}"({column_sql})')


def _swap_staging(conn: sqlite3.Connection) -> None:
    _drop_tables(conn, staging=False)
    for table in (
        "ontology_class",
        "ontology_property",
        "ontology_structural",
        "ontology_individual",
        "ontology_relation",
        "ontology_build_state",
    ):
        staging = _LIVE_TO_STAGING[table]
        conn.execute(f'ALTER TABLE "{staging}" RENAME TO "{table}"')
    _create_live_indexes(conn)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        is not None
    )


def _read_build_state(
    conn: sqlite3.Connection,
) -> tuple[_BuildState | None, str | None]:
    if not _table_exists(conn, "ontology_build_state"):
        return (None, "missing-build-state")
    try:
        rows = conn.execute(
            """
            SELECT singleton, extraction_version, logical_hash, completed_at,
                   source_session_count, source_message_count, counts
            FROM ontology_build_state
            """
        ).fetchall()
    except sqlite3.DatabaseError:
        return (None, "invalid-build-state")
    if len(rows) != 1 or rows[0][0] != 1:
        return (None, "invalid-build-state")
    (
        _singleton,
        extraction_version,
        logical_hash,
        completed_at,
        source_session_count,
        source_message_count,
        counts_json,
    ) = rows[0]
    if extraction_version != EXTRACTION_VERSION:
        return (None, "extraction-version-mismatch")
    try:
        counts = json.loads(counts_json)
    except (TypeError, json.JSONDecodeError):
        return (None, "invalid-build-state")
    if (
        not isinstance(counts, dict)
        or re.fullmatch(r"[0-9a-f]{64}", logical_hash or "") is None
        or _parse_timestamp(completed_at) is None
        or type(source_session_count) is not int
        or source_session_count < 0
        or type(source_message_count) is not int
        or source_message_count < 0
    ):
        return (None, "invalid-build-state")
    graph_tables = {table for _, table, _, _ in _GRAPH_TABLE_ORDER}
    if not all(_table_exists(conn, table) for table in graph_tables):
        return (None, "invalid-build-state")
    try:
        if ontology_logical_hash(conn) != logical_hash:
            return (None, "invalid-build-state")
    except (OntologyError, sqlite3.DatabaseError):
        return (None, "invalid-build-state")
    versions = {
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT extraction_version FROM ontology_structural"
        )
    }
    if versions and versions != {EXTRACTION_VERSION}:
        return (None, "extraction-version-mismatch")
    return (
        _BuildState(
            logical_hash=logical_hash,
            completed_at=completed_at,
            source_session_count=source_session_count,
            source_message_count=source_message_count,
        ),
        None,
    )


def _previous_message_counts(conn: sqlite3.Connection) -> dict[str, int] | None:
    counts: dict[str, int] = {}
    try:
        rows = conn.execute(
            """
            SELECT id, attrs
            FROM ontology_individual
            WHERE id LIKE 'session:%' AND class IN ('Session', 'SubagentSession')
            """
        )
        for individual_id, attrs_json in rows:
            attrs = json.loads(attrs_json)
            count = attrs.get("messages") if isinstance(attrs, dict) else None
            if type(count) is not int or count < 0:
                return None
            counts[individual_id.removeprefix("session:")] = count
    except (sqlite3.DatabaseError, TypeError, json.JSONDecodeError):
        return None
    return counts


def _incremental_candidates(
    conn: sqlite3.Connection,
    sessions: Sequence[_Session],
    message_counts: Mapping[str, int],
    state: _BuildState,
) -> tuple[frozenset[str] | None, str | None]:
    completed_at = _parse_timestamp(state.completed_at)
    if completed_at is None:
        return (None, "invalid-build-state")
    project_sessions = {
        row[0]
        for row in conn.execute(
            "SELECT session_id FROM ontology_structural WHERE type = 'project'"
        )
    }
    candidates: set[str] = set()
    for session in sessions:
        if session.id not in project_sessions:
            candidates.add(session.id)
        if session.updated_at is None:
            continue
        updated_at = _parse_timestamp(session.updated_at)
        if updated_at is None:
            return (None, "unparseable-source-timestamp")
        if updated_at > completed_at:
            candidates.add(session.id)

    previous_counts = _previous_message_counts(conn)
    if (
        previous_counts is None
        or len(previous_counts) != state.source_session_count
        or sum(previous_counts.values()) != state.source_message_count
    ):
        return (None, "invalid-build-state")
    current_ids = {session.id for session in sessions}
    if any(
        previous_counts.get(session_id) != message_counts.get(session_id, 0)
        for session_id in current_ids - candidates
    ):
        return (None, "unexplained-source-count-change")
    return (frozenset(candidates), None)


def _copied_structural(
    conn: sqlite3.Connection,
    current_ids: Collection[str],
    candidate_ids: Collection[str],
) -> tuple[_Structural, ...] | None:
    reusable_ids = set(current_ids) - set(candidate_ids)
    copied: list[_Structural] = []
    rows = conn.execute(
        """
        SELECT id, session_id, type, key, value, ts, extraction_version
        FROM ontology_structural
        ORDER BY session_id, type, key
        """
    )
    for raw_row in rows:
        row = _Structural(*raw_row)
        if row.session_id not in reusable_ids:
            continue
        expected = _make_structural(
            row.session_id, row.type, row.key, row.value, row.ts
        )
        if row.extraction_version != EXTRACTION_VERSION or row.id != expected.id:
            return None
        copied.append(row)
    return tuple(copied)


def _plan_extraction(
    conn: sqlite3.Connection,
    sessions: Sequence[_Session],
    message_counts: Mapping[str, int],
    *,
    incremental: bool,
) -> _ExtractionPlan:
    all_ids = frozenset(session.id for session in sessions)
    if not incremental:
        return _ExtractionPlan(
            mode="full",
            fallback_reason=None,
            candidate_ids=all_ids,
            structural=_extract_structural(conn, sessions),
        )

    state, fallback_reason = _read_build_state(conn)
    if state is None:
        return _ExtractionPlan(
            mode="full",
            fallback_reason=fallback_reason,
            candidate_ids=all_ids,
            structural=_extract_structural(conn, sessions),
        )
    candidates, fallback_reason = _incremental_candidates(
        conn, sessions, message_counts, state
    )
    if candidates is None:
        return _ExtractionPlan(
            mode="full",
            fallback_reason=fallback_reason,
            candidate_ids=all_ids,
            structural=_extract_structural(conn, sessions),
        )
    copied = _copied_structural(conn, all_ids, candidates)
    if copied is None:
        return _ExtractionPlan(
            mode="full",
            fallback_reason="invalid-build-state",
            candidate_ids=all_ids,
            structural=_extract_structural(conn, sessions),
        )

    combined: dict[tuple[str, str, str], _Structural] = {}
    for row in copied:
        _add_structural(combined, row)
    for row in _extract_structural(conn, sessions, candidates):
        _add_structural(combined, row)
    return _ExtractionPlan(
        mode="incremental",
        fallback_reason=None,
        candidate_ids=candidates,
        structural=tuple(
            sorted(
                combined.values(), key=lambda row: (row.session_id, row.type, row.key)
            )
        ),
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _before_swap(_conn: sqlite3.Connection) -> None:
    """Injectable test seam immediately before the atomic live-table swap."""


def rebuild_ontology(
    conn: sqlite3.Connection,
    *,
    incremental: bool = False,
) -> OntologyBuildResult:
    """Build and atomically commit a deterministic complete Tier-1 graph."""
    if conn.in_transaction:
        raise OntologyError(
            "rebuild_ontology requires a connection outside a transaction"
        )
    conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise OntologyError("SQLite foreign-key enforcement could not be enabled")

    try:
        conn.execute("BEGIN IMMEDIATE")
        sessions = _read_sessions(conn)
        message_counts = _message_counts(conn)
        source_message_count = sum(message_counts.values())
        plan = _plan_extraction(
            conn,
            sessions,
            message_counts,
            incremental=incremental,
        )
        if incremental and plan.mode == "full":
            logger.info(
                "ontology incremental rebuild fell back to full: %s",
                plan.fallback_reason,
            )
        graph = _build_graph(sessions, plan.structural, message_counts)

        _drop_tables(conn, staging=True)
        _create_staging_tables(conn)
        _populate_staging(conn, plan.structural, graph)
        _validate_staging(conn, len(sessions))
        logical_hash = ontology_logical_hash(conn, suffix="_next")
        completed_at = _utc_now()
        counts = _graph_counts(
            conn,
            suffix="_next",
            source_session_count=len(sessions),
            source_message_count=source_message_count,
        )
        conn.execute(
            """
            INSERT INTO __ontology_build_state_next(
                singleton, extraction_version, logical_hash, completed_at, mode,
                source_session_count, source_message_count, candidate_session_count, counts
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                EXTRACTION_VERSION,
                logical_hash,
                completed_at,
                plan.mode,
                len(sessions),
                source_message_count,
                len(plan.candidate_ids),
                _canonical_json(
                    {
                        "classes": counts.classes,
                        "individuals": counts.individuals,
                        "properties": counts.properties,
                        "relations": counts.relations,
                        "structural": counts.structural,
                    }
                ),
            ),
        )
        _before_swap(conn)
        _swap_staging(conn)
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise OntologyValidationError(
                "live graph has foreign-key violations after swap"
            )
        conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise

    logger.info(
        "ontology rebuild complete: mode=%s sessions=%d individuals=%d relations=%d hash=%s",
        plan.mode,
        counts.source_sessions,
        counts.individuals,
        counts.relations,
        logical_hash[:12],
    )
    return OntologyBuildResult(
        extraction_version=EXTRACTION_VERSION,
        logical_hash=logical_hash,
        completed_at=completed_at,
        mode=plan.mode,
        fallback_reason=plan.fallback_reason,
        candidate_sessions=len(plan.candidate_ids),
        counts=counts,
    )


def _required_index_table(index: str) -> str:
    if index.startswith("idx_ontology_structural"):
        return "ontology_structural"
    if index.startswith("idx_ontology_individual"):
        return "ontology_individual"
    return "ontology_relation"


def ontology_status(conn: sqlite3.Connection) -> OntologyStatus:
    """Inspect ontology health without creating, repairing, or mutating anything."""
    diagnostics: list[str] = []
    schema_errors: list[str] = []
    present_tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    missing_tables = tuple(sorted(ONTOLOGY_TABLES - present_tables))
    for table in missing_tables:
        diagnostics.append(f"missing ontology table: {table}")

    for table in sorted(ONTOLOGY_TABLES & present_tables):
        actual_columns = tuple(
            row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')
        )
        expected_columns = _EXPECTED_COLUMNS[table]
        if actual_columns != expected_columns:
            schema_errors.append(
                f"{table} columns {actual_columns!r} != {expected_columns!r}"
            )

    index_rows = {
        name: table
        for name, table in conn.execute(
            "SELECT name, tbl_name FROM sqlite_master WHERE type = 'index'"
        )
    }
    missing_indexes = tuple(sorted(set(ONTOLOGY_INDEXES) - set(index_rows)))
    for index in missing_indexes:
        diagnostics.append(f"missing ontology index: {index}")
    for index, expected_columns in ONTOLOGY_INDEXES.items():
        if index not in index_rows:
            continue
        expected_table = _required_index_table(index)
        index_metadata = next(
            (
                row
                for row in conn.execute(f'PRAGMA index_list("{expected_table}")')
                if row[1] == index
            ),
            None,
        )
        metadata = (
            None
            if index_metadata is None
            else (
                bool(index_metadata[2]),
                index_metadata[3],
                bool(index_metadata[4]),
            )
        )
        key_definition = tuple(
            (row[2], bool(row[3]), row[4])
            for row in conn.execute(f'PRAGMA index_xinfo("{index}")')
            if row[5]
        )
        actual_definition = (index_rows[index], metadata, key_definition)
        expected_definition = (
            expected_table,
            (False, "c", False),
            tuple((column, False, "BINARY") for column in expected_columns),
        )
        if actual_definition != expected_definition:
            schema_errors.append(
                f"{index} definition {actual_definition!r} != {expected_definition!r}"
            )
    diagnostics.extend(f"schema error: {error}" for error in schema_errors)

    source_rows = conn.execute(
        "SELECT id, updated_at FROM sessions ORDER BY id"
    ).fetchall()
    source_ids = {row[0] for row in source_rows}
    source_sessions = len(source_rows)
    source_messages = int(conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0])

    extraction_version: str | None = None
    recorded_hash: str | None = None
    completed_at: str | None = None
    recorded_source_sessions: int | None = None
    recorded_source_messages: int | None = None
    if "ontology_build_state" in present_tables and not any(
        error.startswith("ontology_build_state columns") for error in schema_errors
    ):
        try:
            state_rows = conn.execute(
                """
                SELECT extraction_version, logical_hash, completed_at,
                       source_session_count, source_message_count
                FROM ontology_build_state
                WHERE singleton = 1
                """
            ).fetchall()
        except sqlite3.DatabaseError:
            state_rows = []
        if len(state_rows) == 1:
            (
                extraction_version,
                recorded_hash,
                raw_completed_at,
                recorded_source_sessions,
                recorded_source_messages,
            ) = state_rows[0]
            completed_at = _timestamp_text(raw_completed_at)
        else:
            diagnostics.append("ontology build state is missing or not singular")

    structural_versions: set[str] = set()
    if "ontology_structural" in present_tables:
        try:
            structural_versions = {
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT extraction_version FROM ontology_structural"
                )
            }
        except sqlite3.DatabaseError:
            structural_versions = set()
    extraction_version_matches = extraction_version == EXTRACTION_VERSION and (
        not structural_versions or structural_versions == {EXTRACTION_VERSION}
    )
    if not extraction_version_matches:
        diagnostics.append(
            "extraction version mismatch: "
            f"state={extraction_version!r}, structural={sorted(structural_versions)!r}, "
            f"expected={EXTRACTION_VERSION!r}"
        )

    ontology_session_ids: set[str] = set()
    if "ontology_individual" in present_tables:
        try:
            ontology_session_ids = {
                individual_id.removeprefix("session:")
                for (individual_id,) in conn.execute(
                    """
                    SELECT id FROM ontology_individual
                    WHERE id LIKE 'session:%'
                      AND class IN ('Session', 'SubagentSession')
                    """
                )
            }
        except sqlite3.DatabaseError:
            ontology_session_ids = set()
    covered_sessions = len(source_ids & ontology_session_ids)
    missing_sessions = len(source_ids - ontology_session_ids)
    coverage_ratio = covered_sessions / source_sessions if source_sessions else 1.0
    if coverage_ratio < 0.99:
        diagnostics.append(f"session coverage {coverage_ratio:.2%} is below 99.00%")
    orphan_session_individuals = len(ontology_session_ids - source_ids)
    if orphan_session_individuals:
        diagnostics.append(
            f"ontology session individuals absent from source: {orphan_session_individuals}"
        )

    orphan_structural_rows = 0
    if "ontology_structural" in present_tables:
        try:
            orphan_structural_rows = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM ontology_structural AS structural
                    LEFT JOIN sessions AS source ON source.id = structural.session_id
                    WHERE source.id IS NULL
                    """
                ).fetchone()[0]
            )
        except sqlite3.DatabaseError:
            orphan_structural_rows = 0
    if orphan_structural_rows:
        diagnostics.append(
            f"structural rows reference absent sessions: {orphan_structural_rows}"
        )

    try:
        foreign_key_violations = len(
            conn.execute("PRAGMA foreign_key_check").fetchall()
        )
    except sqlite3.DatabaseError:
        foreign_key_violations = 1
    if foreign_key_violations:
        diagnostics.append(f"foreign-key violations: {foreign_key_violations}")

    domain_range_violations = 0
    domain_tables = {
        "ontology_class",
        "ontology_property",
        "ontology_individual",
        "ontology_relation",
    }
    if domain_tables <= present_tables:
        try:
            domain_range_violations = _domain_range_violations(conn, suffix="")
        except sqlite3.DatabaseError:
            domain_range_violations = 1
    if domain_range_violations:
        diagnostics.append(f"domain/range violations: {domain_range_violations}")

    malformed_timestamps: list[str] = []
    parsed_timestamps: list[tuple[datetime, str, str]] = []
    for session_id, updated_at in source_rows:
        if updated_at is None:
            continue
        parsed = _parse_timestamp(updated_at)
        if parsed is None:
            malformed_timestamps.append(session_id)
        else:
            parsed_timestamps.append((parsed, updated_at, session_id))
    malformed = tuple(sorted(malformed_timestamps))
    if malformed:
        diagnostics.append(
            "malformed non-null session updated_at values: " + ", ".join(malformed)
        )
    newest_parsed: datetime | None = None
    newest_session_updated_at: str | None = None
    if parsed_timestamps:
        newest_parsed, newest_session_updated_at, _session_id = max(parsed_timestamps)

    completed_parsed = _parse_timestamp(completed_at)
    completed_at_valid = completed_parsed is not None
    if not completed_at_valid:
        diagnostics.append("completed-at is missing or malformed")
    source_counts_match = (
        recorded_source_sessions == source_sessions
        and recorded_source_messages == source_messages
    )
    if not source_counts_match:
        diagnostics.append(
            "source counts changed: "
            f"sessions={recorded_source_sessions!r}->{source_sessions}, "
            f"messages={recorded_source_messages!r}->{source_messages}"
        )
    source_not_newer = completed_parsed is not None and (
        newest_parsed is None or newest_parsed <= completed_parsed
    )
    if completed_parsed is not None and not source_not_newer:
        diagnostics.append(
            "ontology is stale: newest source updated_at "
            f"{newest_session_updated_at!r} is newer than completed-at {completed_at!r}"
        )
    fresh = (
        completed_at_valid
        and not malformed
        and source_not_newer
        and source_counts_match
    )

    recomputed_hash: str | None = None
    graph_tables = {table for _, table, _, _ in _GRAPH_TABLE_ORDER}
    if graph_tables <= present_tables:
        try:
            recomputed_hash = ontology_logical_hash(conn)
        except (OntologyError, sqlite3.DatabaseError):
            recomputed_hash = None
    hash_matches = (
        recorded_hash is not None
        and recomputed_hash is not None
        and recorded_hash == recomputed_hash
    )
    if not hash_matches:
        diagnostics.append(
            f"logical hash mismatch: recorded={recorded_hash!r}, recomputed={recomputed_hash!r}"
        )

    return OntologyStatus(
        healthy=not diagnostics,
        extraction_version=extraction_version,
        extraction_version_matches=extraction_version_matches,
        recorded_logical_hash=recorded_hash,
        recomputed_logical_hash=recomputed_hash,
        hash_matches=hash_matches,
        completed_at=completed_at,
        completed_at_valid=completed_at_valid,
        newest_session_updated_at=newest_session_updated_at,
        fresh=fresh,
        source_sessions=source_sessions,
        source_messages=source_messages,
        recorded_source_sessions=recorded_source_sessions,
        recorded_source_messages=recorded_source_messages,
        source_counts_match=source_counts_match,
        covered_sessions=covered_sessions,
        missing_sessions=missing_sessions,
        coverage_ratio=coverage_ratio,
        orphan_session_individuals=orphan_session_individuals,
        orphan_structural_rows=orphan_structural_rows,
        foreign_key_violations=foreign_key_violations,
        domain_range_violations=domain_range_violations,
        missing_tables=missing_tables,
        missing_indexes=missing_indexes,
        schema_errors=tuple(schema_errors),
        malformed_timestamps=malformed,
        diagnostics=tuple(diagnostics),
    )
