"""Transactional application of scoped content, below lifecycle reconciliation.

This is the content phase of replication, not a complete sync operation. Refusing
divergent rows preserves the originals and does not claim convergence.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..context import annotations, records
from ..context.observations import ObservationStore
from ..context.provenance import Scope
from ..context.store import Access, ContextStore, _hash, _json
from .policy import PeerPolicy, ReplicaError, check_plan, hello
from .snapshot import MAX_BYTES, MAX_ROWS, TABLES


class ReplicaConflict(ReplicaError):
    """Both replicas retain their pre-transfer state for explicit reconciliation."""


def _unique(rows, key="id"):
    from .staging import StagedRows

    if isinstance(rows, StagedRows):
        return rows.indexed(key)
    result = {}
    for row in rows:
        value = row.get(key)
        if value is None or value in result:
            raise ReplicaError("Missing or duplicate object identity")
        result[value] = row
    return result


def _closure(tables, policy, scope):
    """Check ownership and dependencies in memory before writing any received body."""
    sessions = _unique(tables["sessions"])
    assignments = _unique(tables["context_session_projects"], "session_id")
    projects = {p.id for p in policy.projects if p.scope.value == scope}
    if set(assignments) - set(sessions):
        raise ReplicaError("Assignment lacks its source session")
    for sid in sessions:
        assigned = assignments.get(sid)
        if (assigned and assigned["project_id"] not in projects) or (
            not assigned and scope != "unclassified"
        ):
            raise ReplicaError("Incoming session is outside the negotiated scope")
    messages = _unique(tables["messages"])
    evidence = _unique(tables["context_evidence"])
    for row in tables["context_native_message_sources"]:
        message = messages.get(row["message_id"])
        source = evidence.get(row["evidence_id"])
        if (
            message is None
            or source is None
            or message["session_id"] != source["session_id"]
            or _hash(message["content"] or "") != row["rendered_body_sha256"]
        ):
            raise ReplicaError(
                "Native rendering link lacks its exact included message/source binding"
            )
    for table in (
        "messages",
        "context_evidence",
        "session_notes",
        "session_tags",
        "session_learning_metadata",
        "file_references",
        "context_annotation_retirements",
    ):
        for row in tables[table]:
            if row["session_id"] not in sessions:
                raise ReplicaError("Native child lacks its included session")
            if (
                table == "file_references"
                and row["message_id"] is not None
                and row["message_id"] not in messages
            ):
                raise ReplicaError("File reference lacks its included message")
    assertions = _unique(tables["context_assertions"])
    cited = set()
    for row in tables["context_citations"]:
        if row["assertion_id"] not in assertions or row["evidence_id"] not in evidence:
            raise ReplicaError("Citation dependency is absent")
        cited.add(row["assertion_id"])
        start, end = row["start_offset"], row["end_offset"]
        body = evidence[row["evidence_id"]]["body"]
        if (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= len(body)
            or body[start:end] != row["quote"]
        ):
            raise ReplicaError("Citation does not match its exact source")
    if cited != set(assertions):
        raise ReplicaError("Assertion has no included citations")
    relations = _unique(tables["context_relations"])
    for row in relations.values():
        if (
            row["from_assertion"] not in assertions
            or row["to_assertion"] not in assertions
        ):
            raise ReplicaError("Relation endpoint is absent")

    def owned(row, scope_column):
        native, project, fixed = (
            row.get("session_id"),
            row.get("project_id"),
            row.get(scope_column),
        )
        if sum(v is not None for v in (native, project, fixed)) != 1:
            raise ReplicaError("Incoming ownership must have exactly one kind")
        if (
            (native is not None and native not in sessions)
            or (project is not None and project not in projects)
            or (fixed is not None and fixed != scope)
        ):
            raise ReplicaError("Incoming owner is outside the negotiated scope")

    owners = _unique(tables["context_record_owners"])
    app_rows = {t: _unique(tables[t]) for t in records.TABLES}
    app_keys = {t: {str(key) for key in rows} for t, rows in app_rows.items()}
    paired = set()
    for row in owners.values():
        owned(row, "scope")
        table, local = row["table_name"], row["row_id"]
        if table not in app_rows or (table, local) in paired:
            raise ReplicaError("Duplicate or unsupported learner ownership")
        paired.add((table, local))
        if local not in app_keys[table]:
            raise ReplicaError("Learner owner lacks its included record")
    if sum(len(v) for v in app_rows.values()) != len(paired):
        raise ReplicaError("Learner body lacks explicit ownership")
    for rows in app_rows.values():
        for row in rows.values():
            if row.get("session_id") is not None and row["session_id"] not in sessions:
                raise ReplicaError("Learner native dependency is absent")
            if (
                row.get("study_session_id") is not None
                and row["study_session_id"] not in app_rows["study_sessions"]
            ):
                raise ReplicaError("Learner study dependency is absent")
    for row in tables["context_record_study_links"]:
        if (
            row["record_id"] not in owners
            or row["study_session_id"] not in app_rows["study_sessions"]
        ):
            raise ReplicaError("Learner study link is incomplete")
    observations = _unique(tables["context_observations"])
    roots = {k: set() for k in observations}
    for row in tables["context_observation_sources"]:
        if (
            row["observation_id"] not in observations
            or row["evidence_id"] not in evidence
        ):
            raise ReplicaError("Observation source is absent")
        roots[row["observation_id"]].add("source")
    for row in tables["context_observation_owners"]:
        if row["observation_id"] not in observations:
            raise ReplicaError("Observation owner has no report")
        owned(row, "fixed_scope")
        roots[row["observation_id"]].add("explicit")
    for row in tables["context_observation_session_owners"]:
        if (
            row["observation_id"] not in observations
            or row["session_id"] not in sessions
        ):
            raise ReplicaError("Observation session owner is absent")
        roots[row["observation_id"]].add("session")
    if any(len(value) != 1 for value in roots.values()):
        raise ReplicaError("Observation ownership is missing or ambiguous")
    native_owners = {
        r["observation_id"]: r["session_id"]
        for r in tables["context_observation_session_owners"]
    }
    for oid, row in observations.items():
        payload = json.loads(row["payload"])
        if not isinstance(payload, dict):
            raise ReplicaError("Observation payload must be an object")
        if row["authority"] == "model_interpretation" and roots[oid] != {"source"}:
            raise ReplicaError("Model interpretation lacks captured inputs")
        if row["kind"] in annotations.KINDS.values():
            if (
                native_owners.get(oid) != row["subject"]
                or row["authority"] != "reported"
            ):
                raise ReplicaError(
                    "Session annotation ownership or authority is invalid"
                )
    for row in tables["context_record_observations"]:
        if row["record_id"] not in owners or row["observation_id"] not in observations:
            raise ReplicaError("Observation learner dependency is absent")
    for row in tables["context_review_targets"]:
        if row["observation_id"] not in observations:
            raise ReplicaError("Review has no observation")
        if row["assertion_id"] is not None:
            if row["relation_id"] is not None or row["assertion_id"] not in assertions:
                raise ReplicaError("Review assertion is absent")
        elif row["relation_id"] not in relations:
            raise ReplicaError("Review relation is absent")
        payload = json.loads(observations[row["observation_id"]]["payload"])
        citations = payload.get("citations")
        if not isinstance(citations, list) or not citations:
            raise ReplicaError("Review citations are missing")
        refs = {
            r["evidence_id"]
            for r in tables["context_observation_sources"]
            if r["observation_id"] == row["observation_id"]
        }
        for citation in citations:
            if (
                not isinstance(citation, dict)
                or set(citation) != {"evidence_id", "start", "end", "quote"}
                or citation["evidence_id"] not in refs
            ):
                raise ReplicaError("Review citation is not a declared captured input")
        target_ids = (
            {row["assertion_id"]}
            if row["assertion_id"] is not None
            else {
                relations[row["relation_id"]]["from_assertion"],
                relations[row["relation_id"]]["to_assertion"],
            }
        )
        target_refs = {
            r["evidence_id"]
            for r in tables["context_citations"]
            if r["assertion_id"] in target_ids
        }
        if not target_refs <= refs:
            raise ReplicaError("Review target sources are not declared captured inputs")


def _row(conn, table, row, *, ignore=(), contribution=None):
    """Insert identical-or-new rows only; divergence is an explicit transaction failure."""
    info = list(conn.execute(f"PRAGMA table_info({table})"))
    keys = [r[1] for r in sorted(info, key=lambda r: r[5]) if r[5]]
    if not keys:
        raise ReplicaError("Table has no supported identity")
    existing = conn.execute(
        f"SELECT * FROM {table} WHERE " + " AND ".join(f'"{k}"=?' for k in keys),
        [row[k] for k in keys],
    ).fetchone()
    if existing is not None:
        if any(existing[k] != value for k, value in row.items() if k not in ignore):
            raise ReplicaConflict(
                f"Divergent {table} identity; no content phase committed"
            )
        if contribution is not None:
            contribution.record(conn, table, dict(existing), existed=True)
        return False
    columns = list(row)
    conn.execute(
        f"INSERT INTO {table} ("
        + ",".join('"' + c + '"' for c in columns)
        + ") VALUES ("
        + ",".join("?" for _ in columns)
        + ")",
        [row[c] for c in columns],
    )
    if contribution is not None:
        contribution.record(conn, table, row, existed=False)
    return True


def _review_bindings(conn, tables, access):
    from ..context.reviews import KIND, VERDICTS

    store = ContextStore(conn)
    observations = _unique(tables["context_observations"])

    def assertion(identity):
        row = store.assertion(identity, access)
        if row is None:
            raise ReplicaError("Review assertion is unavailable")
        row["citations"].sort(
            key=lambda c: (c["evidence_id"], c["start_offset"], c["end_offset"])
        )
        return row

    for link in tables["context_review_targets"]:
        observation = observations[link["observation_id"]]
        payload = json.loads(observation["payload"])
        if link["assertion_id"] is not None:
            kind, identity = "assertion", link["assertion_id"]
            target = assertion(identity)
        else:
            kind, identity = "relation", link["relation_id"]
            edge = dict(
                conn.execute(
                    "SELECT * FROM context_relations WHERE id=?", (identity,)
                ).fetchone()
            )
            target = {
                "relation": edge,
                "from": assertion(edge["from_assertion"]),
                "to": assertion(edge["to_assertion"]),
            }
        if (
            observation["kind"] != KIND
            or observation["authority"] != "model_interpretation"
            or payload.get("target_kind") != kind
            or payload.get("target_id") != identity
            or payload.get("target_sha256") != link["target_sha256"]
            or _hash(_json(target)) != link["target_sha256"]
            or payload.get("verdict") not in VERDICTS
        ):
            raise ReplicaError("Review target binding failed")
        citations = payload.get("citations")
        if not isinstance(citations, list) or not citations:
            raise ReplicaError("Review citations are missing")
        for citation in citations:
            source = store.source(citation["evidence_id"], access)
            start, end = citation["start"], citation["end"]
            if (
                source is None
                or type(start) is not int
                or type(end) is not int
                or not 0 <= start < end <= len(source["body"])
                or source["body"][start:end] != citation["quote"]
            ):
                raise ReplicaError("Review citation binding failed")


def _learner(conn, tables, contribution=None):
    owners = {
        (r["table_name"], r["row_id"]): r for r in tables["context_record_owners"]
    }
    for table in records.TABLES:
        integer = table not in ("study_sessions", "practice_attempts")
        for incoming in tables[table]:
            row = dict(incoming)
            owner = dict(owners[(table, str(row["id"]))])
            old_owner = conn.execute(
                "SELECT * FROM context_record_owners WHERE id=?", (owner["id"],)
            ).fetchone()
            if old_owner is not None:
                if old_owner["table_name"] != table:
                    raise ReplicaConflict("Learner owner identity changed table")
                row["id"] = int(old_owner["row_id"]) if integer else old_owner["row_id"]
                _row(conn, table, row, contribution=contribution)
            else:
                if (
                    row.get("sync_key")
                    and conn.execute(
                        f"SELECT 1 FROM {table} WHERE sync_key=?", (row["sync_key"],)
                    ).fetchone()
                ):
                    raise ReplicaConflict(
                        "Stable learner row has independent ownership; reconcile identities before import"
                    )
                if integer:
                    row.pop("id")
                    columns = list(row)
                    cur = conn.execute(
                        f"INSERT INTO {table} ("
                        + ",".join('"' + c + '"' for c in columns)
                        + ") VALUES ("
                        + ",".join("?" for _ in columns)
                        + ")",
                        [row[c] for c in columns],
                    )
                    row["id"] = cur.lastrowid
                    if contribution is not None:
                        contribution.record(conn, table, row, existed=False)
                else:
                    if conn.execute(
                        f"SELECT 1 FROM {table} WHERE id=?", (row["id"],)
                    ).fetchone():
                        raise ReplicaConflict(
                            "Existing learner row lacks the incoming owner; reconcile identities before import"
                        )
                    _row(conn, table, row, contribution=contribution)
            owner["row_id"] = str(row["id"])
            _row(conn, "context_record_owners", owner, contribution=contribution)


def apply_in_transaction(conn, config, snapshot, contribution=None, before_apply=None):
    """Apply content inside the coordinator's transaction, alongside its durable receipt."""
    if (
        not conn.in_transaction
        or conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1
    ):
        raise ReplicaError(
            "Content application requires a transaction with foreign keys"
        )
    if not isinstance(snapshot, dict) or set(snapshot) != {
        "contract",
        "plan",
        "scope",
        "tables",
        "legacy_owned_table_gaps",
        "lifecycle_reconciled",
        "sha256",
    }:
        raise ReplicaError("Malformed content snapshot")
    if (
        snapshot["contract"] != "session-replica-content/v1"
        or snapshot["lifecycle_reconciled"] is not False
    ):
        raise ReplicaError("Unsupported content phase contract")
    from .staging import MAX_STAGED_ROWS, StagedRows, StagedSnapshot, binding

    staged = isinstance(snapshot, StagedSnapshot)
    if staged:
        binding(snapshot)  # Recheck exact current bytes; do not trust cached size/hash.
    elif len(_json(snapshot).encode()) > MAX_BYTES:
        raise ReplicaError("Snapshot exceeds transfer limit")
    body = {k: v for k, v in snapshot.items() if k != "sha256"}
    if (binding(body)[0] if staged else _hash(_json(body))) != snapshot["sha256"]:
        raise ReplicaError("Snapshot content binding failed")
    plan, scope, tables = snapshot["plan"], snapshot["scope"], snapshot["tables"]
    check_plan(plan, scope=scope)
    peer = PeerPolicy.from_config(config, plan["sender"]["node"])
    if conn.execute(
        "SELECT 1 FROM context_replica_permissions WHERE peer=? AND scope=? AND direction='in'",
        (peer.peer, scope),
    ).fetchone() and (contribution is None or before_apply is None):
        raise ReplicaError(
            "Permission history requires the durable content coordinator"
        )
    if not isinstance(tables, dict) or set(tables) != set(TABLES):
        raise ReplicaError("Snapshot table coverage is invalid")
    if isinstance(snapshot, StagedSnapshot):
        valid_rows = snapshot.stage.sealed and all(
            isinstance(rows, StagedRows) and rows.store is snapshot.stage
            for rows in tables.values()
        )
    else:
        valid_rows = all(isinstance(rows, list) for rows in tables.values())
    if not valid_rows or sum(map(len, tables.values())) > (
        MAX_STAGED_ROWS if staged else MAX_ROWS
    ):
        raise ReplicaError("Snapshot row limit exceeded")
    if hello(conn, peer) != plan["receiver"]:
        raise ReplicaError("Receiver state changed after negotiation")
    for table, rows in tables.items():
        columns = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if any(not isinstance(row, dict) or set(row) != columns for row in rows):
            raise ReplicaError("Snapshot columns do not match the installed schema")
    _closure(tables, peer.policy, scope)
    incoming_assignments = {
        r["session_id"]: r["project_id"] for r in tables["context_session_projects"]
    }
    for row in tables["sessions"]:
        existing = conn.execute(
            "SELECT sp.project_id FROM sessions s LEFT JOIN context_session_projects sp ON sp.session_id=s.id WHERE s.id=?",
            (row["id"],),
        ).fetchone()
        if existing is not None and existing[0] != incoming_assignments.get(row["id"]):
            raise ReplicaConflict(
                "Existing session ownership differs; remote labels cannot reclassify it"
            )
    if before_apply is not None:
        before_apply()
    for table in (
        "sessions",
        "messages",
        "context_session_projects",
        "context_evidence",
        "context_native_message_sources",
        "context_assertions",
        "context_citations",
        "context_relations",
    ):
        for incoming in tables[table]:
            row = dict(incoming)
            if table == "context_session_projects":
                # Machine-local roots can differ. Keep an explicit received
                # assignment so a later local root-policy apply cannot erase it.
                row["assignment_kind"] = "explicit"
            _row(
                conn,
                table,
                row,
                ignore=("first_captured_at",)
                if table == "context_evidence"
                else ("assignment_kind",)
                if table == "context_session_projects"
                else (),
                contribution=contribution,
            )
    _learner(conn, tables, contribution)
    for table in (
        "context_record_study_links",
        "context_observations",
        "context_observation_sources",
        "context_observation_owners",
        "context_observation_session_owners",
        "context_observation_supersedes",
        "context_record_observations",
        "context_review_targets",
        "context_annotation_retirements",
        "context_observation_retired_subjects",
        "session_notes",
        "session_tags",
        "session_learning_metadata",
    ):
        for row in tables[table]:
            _row(conn, table, row, contribution=contribution)
    for incoming in tables["file_references"]:
        row = {k: v for k, v in incoming.items() if k != "id"}
        columns = list(row)
        existing = conn.execute(
            "SELECT * FROM file_references WHERE "
            + " AND ".join(f'"{c}" IS ?' for c in columns),
            list(row.values()),
        ).fetchone()
        if existing is None:
            cur = conn.execute(
                "INSERT INTO file_references ("
                + ",".join(columns)
                + ") VALUES ("
                + ",".join("?" for _ in columns)
                + ")",
                list(row.values()),
            )
            if contribution is not None:
                contribution.record(
                    conn, "file_references", {"id": cur.lastrowid, **row}, existed=False
                )
        elif contribution is not None:
            contribution.record(conn, "file_references", dict(existing), existed=True)
    access = Access(
        scope=Scope(scope),
        projects=frozenset(plan["projects"]),
        include_unassigned=scope == "unclassified",
    )
    store = ContextStore(conn)
    for row in tables["context_evidence"]:
        if store.source(row["id"], access) is None:
            raise ReplicaError("Imported source is unavailable")
    for row in tables["context_assertions"]:
        if store.assertion(row["id"], access) is None:
            raise ReplicaError("Imported assertion is unavailable")
    observations = ObservationStore(conn)
    visible = observations._visible(peer.policy, Scope(scope))
    for row in tables["context_observations"]:
        observations._checked(row, peer.policy, Scope(scope), visible_snapshot=visible)
    _review_bindings(conn, tables, access)
    if conn.execute("PRAGMA foreign_key_check").fetchone():
        raise ReplicaError("Imported dependency graph violates foreign keys")
    if PeerPolicy.from_config(config, peer.peer) != peer:
        raise ReplicaError("Receiver configuration changed during content import")
    return {
        "content_phase_committed": True,
        "sync_complete": False,
        "lifecycle_reconciled": False,
        "legacy_owned_table_gaps": snapshot["legacy_owned_table_gaps"],
        "rows_considered": sum(map(len, tables.values())),
    }


def apply_content(path, config, snapshot):
    """Apply only the content phase; return an explicit incomplete-sync outcome."""
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=rw", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.execute("BEGIN IMMEDIATE")
        result = apply_in_transaction(conn, config, snapshot)
        conn.commit()
        return result
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
