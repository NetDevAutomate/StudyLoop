"""The table-role registry for the hot -> full tier mirror (ADR-0016 amendment).

One explicit classification of every table a migrated session database holds.
``tiering.sync_to_full`` copies by it and ``tiering._archive_context_complete``
(the proof ``prune_hot`` relies on) checks by it, so the set that is copied and
the set that is required are the same set by construction (council pass 7, C2).

Roles:

- ``PAYLOAD_IMMUTABLE`` -- written once, never updated by any writer (most carry
  a ``BEFORE UPDATE ... RAISE(ABORT)`` trigger). Copied insert-if-absent by a
  primary-key anti-join; an overlapping key whose columns differ refuses.
- ``PAYLOAD_MUTABLE`` -- updated in place by a writer. Copied by
  ``INSERT ... ON CONFLICT(<key>) DO UPDATE ... WHERE`` columns differ.
  ``INSERT OR REPLACE`` is never used: it is DELETE+INSERT, which fires the
  lifecycle retirement triggers and, with foreign keys on, cascades.
- ``CHILDREN_REPLACE`` -- a session's messages and file references, replaced
  wholesale for a session whose children changed.
- ``CONTROL`` -- permanent lifecycle controls. Reconciled canonical-first by
  ``managed_history.reconcile_full_controls``; never copied by the body phase.
- ``LOCAL_ONLY`` -- this instance's own state (identity, generations, policy,
  capture runs, origin labels, the mirror binding). Never copied, never required.
- ``PEER_LEDGER`` -- structured-replication history. Must be empty in a hot
  database that is mirrored by SQL; a hot that has taken part in structured
  replication is not a plain canonical.
- ``DERIVED`` -- indexes and vectors rebuilt from payload. Never copied.

Every entry was checked against the migrated schema and its writers; the
reasons are recorded beside the entries. A table the registry does not know is
refused when its name starts with ``context_`` or when it declares a foreign key
into a registered payload table (eviction could cascade into it); any other
unknown table is an application table outside the tier contract (StudyLoop
keeps ``card_reviews``, ``study_plans`` and similar beside the session schema)
and is neither copied nor required.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    PAYLOAD_IMMUTABLE = "payload-immutable"
    PAYLOAD_MUTABLE = "payload-mutable"
    CHILDREN_REPLACE = "children-replace"
    CONTROL = "control"
    LOCAL_ONLY = "local-only"
    PEER_LEDGER = "peer-ledger"
    DERIVED = "derived"


PAYLOAD_ROLES = frozenset(
    {Role.PAYLOAD_IMMUTABLE, Role.PAYLOAD_MUTABLE, Role.CHILDREN_REPLACE}
)

#: The mirror's own binding/receipt table. It lives in the full tier only and is
#: created there by the copier (migrations are tier-agnostic: ``init_db`` runs the
#: same chain on hot and full). Deliberately not ``context_``-prefixed: the
#: legacy guard (``replication/legacy.py``) treats any populated ``context_*``
#: table as protected memory, and a binding row is not memory.
MIRROR_TABLE = "tiering_mirror_state"


@dataclass(frozen=True)
class TableRole:
    """One registered table: its role, primary key and copy order."""

    name: str
    role: Role
    key: tuple[str, ...]
    #: Position in the copy order; parents come before children so every insert
    #: satisfies its foreign keys with ``PRAGMA foreign_keys=ON``. 0 = not copied.
    order: int = 0


class UnclassifiedTable(ValueError):
    """A table the tier contract does not know; mirroring it would be a guess."""

    def __init__(self, name: str, why: str = "") -> None:
        self.table = name
        detail = f" ({why})" if why else ""
        super().__init__(f"unclassified tier table: {name}{detail}")


def _payload(order: int, name: str, role: Role, *key: str) -> TableRole:
    return TableRole(name, role, tuple(key), order)


_I, _M, _C = Role.PAYLOAD_IMMUTABLE, Role.PAYLOAD_MUTABLE, Role.CHILDREN_REPLACE

#: Copy order. Parents before children (foreign keys are enforced during copy).
PAYLOAD: tuple[TableRole, ...] = (
    # exporters/base.py:111-127 upserts sessions ON CONFLICT(id) DO UPDATE.
    _payload(1, "sessions", _M, "id"),
    # Replaced per changed session (tiering.sync_to_full), FK -> sessions.
    _payload(2, "messages", _C, "id"),
    _payload(3, "file_references", _C, "id"),
    # store.py:210-212 upserts; scope.py reclassifies.
    _payload(4, "context_projects", _M, "id"),
    # store.py:229-230 and capture.py:110-117 upsert or delete-and-reinsert.
    _payload(5, "context_session_projects", _M, "session_id"),
    # Concept graph: message_concepts and study_progress reference concepts(id)
    # with NO ACTION, so the full tier needs concepts before either can arrive.
    # Written by studyloop (history/concepts.py, bridges.py, progress.py,
    # learning/mastery.py) with INSERT/INSERT OR IGNORE/UPDATE.
    _payload(6, "concepts", _M, "id"),
    _payload(7, "concept_aliases", _M, "alias", "concept_id"),
    _payload(8, "concept_relations", _M, "id"),
    _payload(9, "concept_dependencies", _M, "id"),
    _payload(10, "study_progress", _M, "id"),
    # FK messages(id) NO ACTION: deleted explicitly before a message replacement.
    _payload(11, "message_concepts", _M, "message_id", "concept_id"),
    # FK messages(id)/sessions(id) ON DELETE CASCADE; AUTOINCREMENT id.
    _payload(12, "scrub_log", _M, "id"),
    _payload(13, "session_notes", _M, "session_id"),
    _payload(14, "session_tags", _M, "session_id", "tag"),
    _payload(15, "session_learning_metadata", _M, "session_id"),
    # learner_schema.TABLES (record_schema.TABLES + parked_topics, study_notes,
    # practice_attempts). AUTOINCREMENT integer keys are safe as upsert keys
    # only because the full tier is bound to one canonical instance
    # (MIRROR_TABLE); a rebuilt hot restarts them and is refused unbound.
    _payload(16, "study_sessions", _M, "id"),
    _payload(17, "teach_back_scores", _M, "id"),
    _payload(18, "knowledge_bridges", _M, "id"),
    _payload(19, "parked_topics", _M, "id"),
    _payload(20, "study_notes", _M, "id"),
    _payload(21, "practice_attempts", _M, "id"),
    # parking.py:51,465 insert, :501 deletes; renamed in place.
    _payload(22, "context_board_columns", _M, "scope", "key"),
    # schema.py: context_evidence_immutable / assertions_immutable /
    # citations_immutable; relations are insert-only (store.py:475).
    _payload(23, "context_evidence", _I, "id"),
    # capture.py:78 INSERT OR IGNORE only; FK messages(id) ON DELETE CASCADE,
    # restored from hot after a message replacement.
    _payload(24, "context_native_message_sources", _I, "message_id", "evidence_id"),
    _payload(25, "context_assertions", _I, "id"),
    _payload(
        26,
        "context_citations",
        _I,
        "assertion_id",
        "evidence_id",
        "start_offset",
        "end_offset",
    ),
    _payload(27, "context_relations", _I, "id"),
    # observation_schema.py immutable triggers on observations/sources/supersedes.
    _payload(28, "context_observations", _I, "id"),
    _payload(29, "context_observation_sources", _I, "observation_id", "evidence_id"),
    # observations.py:522 updates owners in place (council pass 7, A3).
    _payload(30, "context_observation_owners", _M, "observation_id"),
    # session_owner_schema.py: context_session_owner_immutable.
    _payload(31, "context_observation_session_owners", _I, "observation_id"),
    _payload(32, "context_observation_supersedes", _I, "observation_id", "previous_id"),
    # reviews.py:138 INSERT OR IGNORE only.
    _payload(33, "context_review_targets", _I, "observation_id"),
    # record_schema.py: context_record_owners_immutable; links insert-only
    # (records.py:231, :347).
    _payload(34, "context_record_owners", _I, "id"),
    _payload(35, "context_record_study_links", _I, "record_id"),
    _payload(36, "context_record_observations", _I, "record_id", "observation_id"),
)

#: managed_history.CONTROL_TABLES plus the annotation retirements
#: (session_owner_schema.py:7-17: permanent, ABORT on UPDATE/DELETE).
CONTROL: tuple[TableRole, ...] = (
    TableRole("context_tombstones", Role.CONTROL, ("session_id",)),
    TableRole("context_observation_tombstones", Role.CONTROL, ("observation_id",)),
    TableRole(
        "context_observation_retired_subjects", Role.CONTROL, ("subject_sha256",)
    ),
    TableRole("context_retirements", Role.CONTROL, ("kind", "object_id")),
    TableRole("context_annotation_retirements", Role.CONTROL, ("session_id", "kind")),
)

LOCAL_ONLY: tuple[TableRole, ...] = (
    # Instance identity and access generation (compact_database mints a new one).
    TableRole("context_access_state", Role.LOCAL_ONLY, ("id",)),
    # Body generation counter (migration 46); the receipt compares against it.
    TableRole("context_replica_content_state", Role.LOCAL_ONLY, ("id",)),
    TableRole("context_lifecycle_mode", Role.LOCAL_ONLY, ("id",)),
    TableRole("context_policy_state", Role.LOCAL_ONLY, ("id",)),
    # Per-machine capture bookkeeping (capture.py:146-198).
    TableRole("context_capture_runs", Role.LOCAL_ONLY, ("id",)),
    TableRole("context_erasure_pending", Role.LOCAL_ONLY, ("id",)),
    # Machine-local origin labels; a sender cannot export its own label
    # (retention_schema.py:15-17).
    TableRole(
        "context_retention_origins",
        Role.LOCAL_ONLY,
        (
            "table_name",
            "key_sha256",
            "row_sha256",
            "origin",
            "contributor",
            "receipt_id",
        ),
    ),
    # This instance's policy-application audit (scope.py:399), paired with
    # context_policy_state. Never deleted by eviction, so never lost from hot.
    TableRole("context_scope_audit", Role.LOCAL_ONLY, ("id",)),
    TableRole(MIRROR_TABLE, Role.LOCAL_ONLY, ("id",)),
)

PEER_LEDGER: tuple[TableRole, ...] = tuple(
    TableRole(name, Role.PEER_LEDGER, key)
    for name, key in (
        ("context_replica_peers", ("peer",)),
        ("context_replica_offers", ("id", "direction")),
        ("context_replica_objects", ("peer", "kind", "object_id", "scope")),
        ("context_replica_control_batches", ("id", "direction")),
        ("context_replica_permissions", ("peer", "direction", "scope")),
        ("context_replica_permission_batches", ("id", "direction")),
        ("context_replica_denials", ("peer", "scope", "kind", "object_id")),
        ("context_replica_superseded", ("offer_id",)),
        (
            "context_replica_row_bases",
            ("offer_id", "direction", "table_name", "key_sha256"),
        ),
        ("context_replica_basis_sets", ("sequence",)),
        ("context_quarantine_discards", ("id",)),
    )
)

DERIVED: tuple[TableRole, ...] = tuple(
    TableRole(name, Role.DERIVED, ())
    for name in (
        "messages_fts",
        "messages_fts_data",
        "messages_fts_idx",
        "messages_fts_content",
        "messages_fts_docsize",
        "messages_fts_config",
        "context_evidence_fts",
        "context_evidence_fts_data",
        "context_evidence_fts_idx",
        "context_evidence_fts_docsize",
        "context_evidence_fts_config",
        # Regenerated locally by `session-maint embed` (migration 48).
        "message_embeddings",
    )
)

REGISTRY: dict[str, TableRole] = {}
for _entry in (*PAYLOAD, *CONTROL, *LOCAL_ONLY, *PEER_LEDGER, *DERIVED):
    if _entry.name in REGISTRY:  # pragma: no cover - guarded by the registry pin
        raise RuntimeError(f"table classified twice: {_entry.name}")
    REGISTRY[_entry.name] = _entry
del _entry

CONTROL_TABLES = tuple(entry.name for entry in CONTROL)
PAYLOAD_TABLES = tuple(entry.name for entry in PAYLOAD)


def classify(name: str) -> TableRole:
    """The registered role of ``name``; an unknown table raises, naming it."""
    try:
        return REGISTRY[name]
    except KeyError:
        raise UnclassifiedTable(name) from None


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def database_tables(conn: sqlite3.Connection, schema: str = "main") -> list[str]:
    """Every user table in ``schema``: ordinary, virtual and FTS shadow tables."""
    return sorted(
        row[1]
        for row in conn.execute(f"PRAGMA {schema}.table_list")
        if row[0] == schema
        and row[2] in ("table", "virtual", "shadow")
        and not row[1].startswith("sqlite_")
    )


def classify_database(
    conn: sqlite3.Connection, schema: str = "main"
) -> tuple[dict[str, TableRole], list[str]]:
    """Classify every table in ``schema``; ``(registered, unmanaged)``.

    Raises :class:`UnclassifiedTable` for an unknown ``context_*`` table and for
    an unknown table holding a foreign key into a registered payload table:
    either could hold memory that eviction would delete without the full tier
    having it. Other unknown tables (application tables kept beside the
    session schema) are returned as ``unmanaged``: never copied, never required,
    never deleted by eviction.
    """
    registered: dict[str, TableRole] = {}
    unmanaged: list[str] = []
    payload = {entry.name.lower() for entry in PAYLOAD}
    kinds = {
        row[1]: row[2]
        for row in conn.execute(f"PRAGMA {schema}.table_list")
        if row[0] == schema
    }
    for name in database_tables(conn, schema):
        entry = REGISTRY.get(name)
        if entry is not None:
            registered[name] = entry
            continue
        if name.startswith("context_"):
            raise UnclassifiedTable(name)
        if kinds.get(name) == "shadow":
            # The internal storage of an unmanaged virtual table.
            unmanaged.append(name)
            continue
        parents = {
            str(row[2]).lower()
            for row in conn.execute(f"PRAGMA {schema}.foreign_key_list({_quote(name)})")
        }
        if parents & payload:
            raise UnclassifiedTable(
                name, "it references " + ", ".join(sorted(parents & payload))
            )
        unmanaged.append(name)
    return registered, unmanaged


def columns(conn: sqlite3.Connection, table: str, schema: str = "main") -> list[str]:
    """Insertable columns in declaration order (generated columns excluded)."""
    return [
        row[1]
        for row in conn.execute(f"PRAGMA {schema}.table_xinfo({_quote(table)})")
        if row[6] == 0
    ]


def primary_key(
    conn: sqlite3.Connection, table: str, schema: str = "main"
) -> tuple[str, ...]:
    """The declared primary key, in key order."""
    rows = [
        row
        for row in conn.execute(f"PRAGMA {schema}.table_info({_quote(table)})")
        if row[5]
    ]
    return tuple(row[1] for row in sorted(rows, key=lambda row: row[5]))
