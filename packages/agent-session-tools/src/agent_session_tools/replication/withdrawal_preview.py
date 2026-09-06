"""Inspect the real reversible purge before erasing any independently retained body.

The caller owns an IMMEDIATE write transaction and the authenticated peer boundary.
The rollback-only trace retains hashes rather than bodies, is bounded, and returns
hashes/counts only.
It does not grant permission, install denials or acknowledge physical cleanup.
"""

import json
import sqlite3
from uuid import uuid4

from ..context.lifecycle import eviction, purge_session
from ..context.store import _hash, _json
from .policy import ReplicaError
from .retention import _binding_values, _facts
from .snapshot import TABLES
from .staging import MAX_STAGED_BYTES, MAX_STAGED_ROWS

OBJECT_TABLES = {
    "evidence": "context_evidence",
    "assertion": "context_assertions",
    "relation": "context_relations",
    "observation": "context_observations",
    "record": "context_record_owners",
}


def purge_objects(conn, objects):
    """Internal typed purge; the surrounding withdrawal transaction authorizes it."""
    if (
        not conn.in_transaction
        or conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1
    ):
        raise ReplicaError("Withdrawal purge requires a transaction with foreign keys")
    with eviction(conn):
        # Session purge snapshots learner IDs before SET NULL can detach them.
        # Preserve that established lifecycle order even when manifests sort
        # artifacts alphabetically ahead of their source sessions.
        ordered = sorted(objects, key=lambda row: row["kind"] != "session")
        for row in ordered:
            kind, identity = row["kind"], row["object_id"]
            if kind == "session":
                purge_session(conn, identity, permanent=False)
            elif kind in OBJECT_TABLES:
                conn.execute(
                    f"DELETE FROM {OBJECT_TABLES[kind]} WHERE id=?", (identity,)
                )
            else:
                raise ReplicaError("Unsupported withdrawal object")


def preview(
    conn,
    peer,
    objects,
    *,
    receipt_id=None,
    max_rows=MAX_STAGED_ROWS,
    max_bytes=MAX_STAGED_BYTES,
):
    """Return whether every changed canonical payload has only this peer's history.

    Conservatively unresolved when a local derivative lacks an explicit retention
    dependency proof. This is preferable to silently calling an unknown row remote.
    The actual caller must keep the same write lock through the resulting decision.
    """
    if (
        not conn.in_transaction
        or conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1
    ):
        raise ReplicaError(
            "Withdrawal preview requires a write transaction with foreign keys"
        )
    if conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "off":
        raise ReplicaError("Withdrawal preview requires rollback-capable journaling")
    prefix = "withdraw_preview_" + uuid4().hex
    callback = prefix + "_trace"
    # The first image wins when an FK first changes a row and later deletes it.
    # Hash against the version present before any part of the simulated cascade.
    before = {}
    used_bytes = 0
    overflow = False
    keys = {}
    triggers = []

    def trace(table, encoded):
        nonlocal used_bytes, overflow
        used_bytes += len(encoded.encode())
        if used_bytes > max_bytes:
            overflow = True
            raise ValueError("Withdrawal footprint exceeds byte limit")
        row = json.loads(encoded)
        key = (table, tuple(row[k] for k in keys[table]))
        if key not in before:
            if len(before) >= max_rows:
                overflow = True
                raise ValueError("Withdrawal footprint exceeds row limit")
            before[key] = _binding_values(table, row, keys[table])
        return 1

    conn.create_function(callback, 2, trace)
    try:
        for table in TABLES:
            info = list(conn.execute(f"PRAGMA table_info({table})"))
            keys[table] = [r[1] for r in sorted(info, key=lambda r: r[5]) if r[5]]
            if not keys[table]:
                raise ReplicaError("Unsupported canonical withdrawal identity")
            encoded = (
                "json_object("
                + ",".join(f"'{r[1]}',OLD.\"{r[1]}\"" for r in info)
                + ")"
            )
            for event in ("DELETE", "UPDATE"):
                name = prefix + "_" + table + "_" + event
                conn.execute(
                    f"CREATE TEMP TRIGGER {name} BEFORE {event} ON main.{table} "
                    f"BEGIN SELECT {callback}('{table}',{encoded}); END"
                )
                triggers.append(name)
        conn.execute(f"SAVEPOINT {prefix}")
        try:
            purge_objects(conn, objects)
        except sqlite3.OperationalError:
            if not overflow:
                raise
        finally:
            if conn.in_transaction:
                conn.execute(f"ROLLBACK TO {prefix}")
                conn.execute(f"RELEASE {prefix}")
    finally:
        for trigger in triggers:
            conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
        conn.create_function(callback, 2, None)
    if overflow:
        return {
            "eligible": False,
            "reason": "footprint_limit",
            "changed_rows": len(before),
        }
    unknown = []
    bindings = []
    table_counts = {}
    fact_count = 0
    fact_bytes = 0
    for (table, _), binding in before.items():
        facts = _facts(conn, binding, limit=max_rows - fact_count + 1)
        fact_count += len(facts)
        encoded_facts = [list(fact) for fact in facts]
        fact_bytes += len(_json(encoded_facts).encode())
        if fact_count > max_rows or used_bytes + fact_bytes > max_bytes:
            return {
                "eligible": False,
                "reason": "footprint_limit",
                "changed_rows": len(before),
            }
        bindings.append([*binding, encoded_facts])
        table_counts[table] = table_counts.get(table, 0) + 1
        matched = (
            any(
                r[0] == "peer_commit" and r[1] == peer and r[2] == receipt_id
                for r in facts
            )
            if receipt_id is not None
            else bool(facts)
            and all(r[0] == "peer_commit" and r[1] == peer for r in facts)
        )
        if not matched:
            unknown.append(
                {"table": table, "key_sha256": binding[1], "row_sha256": binding[2]}
            )
    return {
        "eligible": not unknown,
        "reason": "exclusive_peer_history"
        if not unknown
        else "ambiguous_retention_history",
        "changed_rows": len(before),
        "footprint_sha256": _hash(_json(sorted(bindings))),
        "changed_by_table": dict(sorted(table_counts.items())),
        "traced_json_bytes": used_bytes,
        "history_fact_count": fact_count,
        "history_json_bytes": fact_bytes,
        "unresolved_rows": len(unknown),
        "unresolved_bindings": unknown[:100],
        "diagnostics_truncated": len(unknown) > 100,
    }
