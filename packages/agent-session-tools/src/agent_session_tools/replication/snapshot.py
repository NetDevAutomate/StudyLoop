"""Scoped content projection for the structured protocol's data plane.

This module does not perform sync or claim deletion reconciliation. The protocol
coordinator must reconcile lifecycle controls before accepting a content snapshot.
The existing SQL transport is never used here.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import sqlite3

from ..context import records
from ..context.observations import ObservationStore
from ..context.provenance import Scope
from ..context.scope import visibility_sql
from ..context.store import Access, ContextStore, _hash, _json
from .policy import PeerPolicy, ReplicaError, check_plan, hello, open_read

MAX_ROWS = 100_000
MAX_BYTES = 32 * 1024 * 1024

NATIVE = (
    "sessions",
    "messages",
    "session_notes",
    "session_tags",
    "session_learning_metadata",
    "file_references",
)
CONTEXT = (
    "context_session_projects",
    "context_evidence",
    "context_native_message_sources",
    "context_assertions",
    "context_citations",
    "context_relations",
    "context_observations",
    "context_observation_sources",
    "context_observation_owners",
    "context_observation_session_owners",
    "context_observation_supersedes",
    "context_review_targets",
    "context_record_owners",
    "context_record_study_links",
    "context_record_observations",
    "context_annotation_retirements",
    "context_observation_retired_subjects",
)
TABLES = (*NATIVE, *records.TABLES, *CONTEXT)


@dataclass
class Projection:
    conn: sqlite3.Connection
    rows: int = 0
    raw_bytes: int = 0

    def selected(self, name, query, values=()):
        if name not in {
            "sessions",
            "messages",
            "evidence",
            "assertions",
            "relations",
            "owners",
            "observations",
        }:
            raise ReplicaError("Unsupported internal selection")
        self.conn.execute(
            f"CREATE TEMP TABLE replica_{name}(id TEXT PRIMARY KEY) WITHOUT ROWID"
        )
        self.conn.execute(f"INSERT INTO replica_{name} {query}", values)

    def read(self, table, where="1", values=()):
        if table not in TABLES:
            raise ReplicaError("Unsupported snapshot table")
        columns = [r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")]
        quoted = ['"' + c.replace('"', '""') + '"' for c in columns]
        sizes = "+".join(f"coalesce(length(CAST(r.{c} AS BLOB)),0)" for c in quoted)
        n, byte_count = self.conn.execute(
            f"SELECT count(*),coalesce(sum({sizes}),0) FROM {table} r WHERE {where}",
            values,
        ).fetchone()
        self.rows += n
        self.raw_bytes += byte_count
        if self.rows > MAX_ROWS or self.raw_bytes > MAX_BYTES:
            raise ReplicaError(
                "Snapshot exceeds transfer limits; no truncated snapshot returned"
            )
        return [
            dict(row)
            for row in self.conn.execute(
                "SELECT "
                + ",".join("r." + c for c in quoted)
                + f" FROM {table} r WHERE {where}",
                values,
            )
        ]


def _select(conn, policy, scope):
    from ..context.withdrawal_gate import predicate

    selection = Projection(conn)
    visible, values = visibility_sql(conn, "s.id", policy=policy, scope=scope)
    selection.selected(
        "sessions", "SELECT s.id FROM sessions s WHERE " + visible, values
    )
    selection.selected(
        "messages",
        "SELECT id FROM messages WHERE session_id IN (SELECT id FROM replica_sessions)",
    )
    selection.selected(
        "evidence",
        "SELECT e.id FROM context_evidence e WHERE session_id IN (SELECT id FROM replica_sessions) AND "
        + predicate(conn, "evidence", "e.id"),
    )
    selection.selected(
        "assertions",
        """SELECT a.id FROM context_assertions a
        WHERE EXISTS (SELECT 1 FROM context_citations c WHERE c.assertion_id=a.id)
        AND NOT EXISTS (SELECT 1 FROM context_citations c WHERE c.assertion_id=a.id
          AND c.evidence_id NOT IN (SELECT id FROM replica_evidence)) AND """
        + predicate(conn, "assertion", "a.id"),
    )
    selection.selected(
        "relations",
        """SELECT r.id FROM context_relations r
        WHERE from_assertion IN (SELECT id FROM replica_assertions)
          AND to_assertion IN (SELECT id FROM replica_assertions) AND """
        + predicate(conn, "relation", "r.id"),
    )
    owner_queries, owner_values = [], []
    for table in records.TABLES:
        clause, params = records._visible_sql(conn, table, "r.id", policy, scope=scope)
        if table in (
            "study_sessions",
            "teach_back_scores",
            "parked_topics",
            "study_notes",
        ):
            clause += " AND (r.session_id IS NULL OR r.session_id IN (SELECT id FROM replica_sessions))"
        if table in ("parked_topics", "study_notes"):
            parent, parent_values = records._visible_sql(
                conn, "study_sessions", "parent.id", policy, scope=scope
            )
            clause += (
                " AND (r.study_session_id IS NULL OR EXISTS (SELECT 1 FROM study_sessions parent "
                "WHERE parent.id=r.study_session_id AND (parent.session_id IS NULL OR "
                "parent.session_id IN (SELECT id FROM replica_sessions)) AND "
                + parent
                + "))"
            )
            params = [*params, *parent_values]
        owner_queries.append(
            f"SELECT own.id FROM {table} r JOIN context_record_owners own "
            f"ON own.table_name=? AND own.row_id=CAST(r.id AS TEXT) WHERE {clause}"
        )
        owner_values.extend([table, *params])
    selection.selected("owners", " UNION ".join(owner_queries), owner_values)
    clause, values = ObservationStore(conn)._visible(policy, scope)
    selection.selected(
        "observations",
        "SELECT o.id FROM context_observations o WHERE "
        + clause
        + """
        AND NOT EXISTS (SELECT 1 FROM context_record_observations link WHERE link.observation_id=o.id
          AND link.record_id NOT IN (SELECT id FROM replica_owners))
        AND NOT EXISTS (SELECT 1 FROM context_review_targets target WHERE target.observation_id=o.id
          AND ((target.assertion_id IS NOT NULL AND target.assertion_id NOT IN (SELECT id FROM replica_assertions))
            OR (target.relation_id IS NOT NULL AND target.relation_id NOT IN (SELECT id FROM replica_relations))))""",
        values,
    )
    invalid_review = conn.execute("""SELECT o.id FROM context_observations o
        JOIN context_review_targets target ON target.observation_id=o.id
        LEFT JOIN context_relations rel ON rel.id=target.relation_id
        WHERE o.id IN (SELECT id FROM replica_observations) AND (
          json_type(o.payload,'$.citations') IS NOT 'array'
          OR EXISTS (SELECT 1 FROM json_each(o.payload,'$.citations') item
            WHERE NOT EXISTS (SELECT 1 FROM context_observation_sources dep
              WHERE dep.observation_id=o.id
                AND dep.evidence_id=json_extract(item.value,'$.evidence_id')))
          OR EXISTS (SELECT 1 FROM context_citations c
            WHERE c.assertion_id IN (target.assertion_id,rel.from_assertion,rel.to_assertion)
              AND NOT EXISTS (SELECT 1 FROM context_observation_sources dep
                WHERE dep.observation_id=o.id AND dep.evidence_id=c.evidence_id))) LIMIT 1""").fetchone()
    if invalid_review:
        raise ReplicaError(
            "Selected review has undeclared captured inputs; no bodies selected"
        )
    return selection


def collect(conn, policy, scope):
    """Select native and owned derivative closure before materializing payloads."""
    scope = Scope(scope)
    p = _select(conn, policy, scope)
    rows = {}
    for table in NATIVE:
        key = "id" if table == "sessions" else "session_id"
        predicate = f"r.{key} IN (SELECT id FROM replica_sessions)"
        if table == "file_references":
            # The session and message are both dependencies; malformed cross-scope
            # references must not expose even a filename from the excluded side.
            predicate += " AND (r.message_id IS NULL OR r.message_id IN (SELECT id FROM replica_messages))"
        rows[table] = p.read(table, predicate)
    rows["context_session_projects"] = p.read(
        "context_session_projects", "r.session_id IN (SELECT id FROM replica_sessions)"
    )
    rows["context_native_message_sources"] = p.read(
        "context_native_message_sources",
        "r.message_id IN (SELECT id FROM replica_messages) AND r.evidence_id IN (SELECT id FROM replica_evidence)",
    )
    for table, selection in (
        ("context_evidence", "evidence"),
        ("context_assertions", "assertions"),
        ("context_relations", "relations"),
        ("context_observations", "observations"),
        ("context_record_owners", "owners"),
    ):
        rows[table] = p.read(table, f"r.id IN (SELECT id FROM replica_{selection})")
    rows["context_citations"] = p.read(
        "context_citations", "r.assertion_id IN (SELECT id FROM replica_assertions)"
    )
    for table in (
        "context_observation_sources",
        "context_observation_owners",
        "context_observation_session_owners",
        "context_review_targets",
        "context_record_observations",
    ):
        rows[table] = p.read(
            table, "r.observation_id IN (SELECT id FROM replica_observations)"
        )
    rows["context_record_study_links"] = p.read(
        "context_record_study_links", "r.record_id IN (SELECT id FROM replica_owners)"
    )
    rows["context_observation_supersedes"] = p.read(
        "context_observation_supersedes",
        """
        r.observation_id IN (SELECT id FROM replica_observations)
        OR r.previous_id IN (SELECT id FROM replica_observations)""",
    )
    rows["context_annotation_retirements"] = p.read(
        "context_annotation_retirements",
        "r.session_id IN (SELECT id FROM replica_sessions)",
    )
    rows["context_observation_retired_subjects"] = p.read(
        "context_observation_retired_subjects",
        """
        r.subject_sha256 IN (SELECT subject_sha256 FROM context_observations
          WHERE id IN (SELECT id FROM replica_observations))""",
    )
    for table in records.TABLES:
        rows[table] = p.read(
            table,
            """CAST(r.id AS TEXT) IN
            (SELECT own.row_id FROM context_record_owners own
             WHERE own.table_name=? AND own.id IN (SELECT id FROM replica_owners))""",
            (table,),
        )
    # Administrative content projection records excluded classes explicitly. The
    # final coordinator must refuse claiming full sync until lifecycle and legacy
    # state are reconciled. No payload from these tables is read here.
    legacy_counts = {}
    for table in records.TABLES:
        clause, values = records._visible_sql(conn, table, "r.id", policy, scope=scope)
        count = conn.execute(
            f"SELECT count(*) FROM {table} r WHERE {clause} AND NOT EXISTS "
            "(SELECT 1 FROM context_record_owners own WHERE own.table_name=? AND own.row_id=CAST(r.id AS TEXT))",
            [*values, table],
        ).fetchone()[0]
        if count:
            legacy_counts[table] = count
    access = Access(
        scope=scope,
        projects=frozenset(p.id for p in policy.projects if p.scope == scope),
        include_unassigned=scope == Scope.UNCLASSIFIED,
    )
    store = ContextStore(conn)
    for row in rows["context_evidence"]:
        store.source(row["id"], access)
    for row in rows["context_assertions"]:
        store.assertion(row["id"], access)
    observations = ObservationStore(conn)
    clause = observations._visible(policy, scope)
    for row in rows["context_observations"]:
        observations._checked(row, policy, scope, visible_snapshot=clause)
    from .content import _closure, _review_bindings

    _closure(rows, policy, scope.value)
    _review_bindings(conn, rows, access)
    return rows, legacy_counts


def export_snapshot(path, config, plan, scope):
    """Prepare a content snapshot; the lifecycle/SSH coordinator is a separate gate."""
    check_plan(plan, scope=scope)
    peer = PeerPolicy.from_config(config, plan["receiver"]["node"])
    conn = open_read(path)
    try:
        from .permissions import current

        if current(conn, peer.peer, scope, "out")[1] != "granted":
            raise ReplicaError("Outgoing scope permission is withdrawn")
        if hello(conn, peer) != plan["sender"]:
            raise ReplicaError("Sender state changed after negotiation")
        rows, legacy = collect(conn, peer.policy, scope)
        result = {
            "contract": "session-replica-content/v1",
            "plan": plan,
            "scope": scope,
            "tables": rows,
            "legacy_owned_table_gaps": legacy,
            "lifecycle_reconciled": False,
        }
        if len(_json(result).encode()) > MAX_BYTES:
            raise ReplicaError(
                "Encoded snapshot exceeds transfer limit; no content returned"
            )
        result["sha256"] = _hash(_json(result))
        if len(_json(result).encode()) > MAX_BYTES:
            raise ReplicaError(
                "Encoded snapshot exceeds transfer limit; no content returned"
            )
        if PeerPolicy.from_config(config, peer.peer) != peer:
            raise ReplicaError("Sender configuration changed during snapshot selection")
        # A separate fresh connection can observe reclassification during the read.
        with closing(open_read(path)) as monitor:
            if hello(monitor, peer) != plan["sender"]:
                raise ReplicaError("Sender access changed during snapshot selection")
        return result
    finally:
        conn.close()
