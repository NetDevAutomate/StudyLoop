"""Durable offers, atomic content receipts and known-recipient retirement control.

These APIs require the coordinator to authenticate ``peer_name`` independently of
the packet, and to load fresh local config at each boundary. They do not implement
SSH, withdrawal/regrant, full-store restore or complete synchronization.
"""

from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3

from ..context.lifecycle import compact, reconcile_local_retirements
from ..context.provenance import Scope
from ..context.store import ContextStore, _hash, _json, _now
from .content import apply_in_transaction
from .policy import PeerPolicy, ReplicaError, check_plan, hello, state
from .retention import PeerContribution
from .snapshot import MAX_BYTES, MAX_ROWS, _select, export_snapshot

OBJECTS = {
    "session": ("sessions", "sessions"),
    "evidence": ("context_evidence", "evidence"),
    "assertion": ("context_assertions", "assertions"),
    "relation": ("context_relations", "relations"),
    "observation": ("context_observations", "observations"),
    "record": ("context_record_owners", "owners"),
}


@contextmanager
def _write(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=rw", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        state(conn)
        with ContextStore(conn)._atomic():
            yield conn
    finally:
        conn.close()


def _seal(value):
    result = {**value, "id": _hash(_json(value))}
    if len(_json(result).encode()) > MAX_BYTES:
        raise ReplicaError("Replica metadata exceeds transfer limit")
    return result


def _checked(value, contract, fields):
    if not isinstance(value, dict) or set(value) != {"id", "contract", *fields}:
        raise ReplicaError("Malformed replica metadata")
    if len(_json(value).encode()) > MAX_BYTES or value["contract"] != contract:
        raise ReplicaError("Unsupported or oversized replica metadata")
    if _hash(_json({k: v for k, v in value.items() if k != "id"})) != value["id"]:
        raise ReplicaError("Replica metadata binding failed")


def _manifest(snapshot):
    return sorted(
        (
            {"kind": kind, "object_id": r["id"]}
            for kind, (table, _) in OBJECTS.items()
            for r in snapshot["tables"][table]
        ),
        key=lambda r: (r["kind"], r["object_id"]),
    )


def _objects(value, *, controls=False):
    if not isinstance(value, list) or len(value) > MAX_ROWS:
        raise ReplicaError("Invalid replica object manifest")
    expected = {"kind", "object_id"} | ({"scope", "retired_at"} if controls else set())
    seen = set()
    for row in value:
        if (
            not isinstance(row, dict)
            or set(row) != expected
            or not isinstance(row["kind"], str)
            or row["kind"] not in OBJECTS
            or not isinstance(row["object_id"], str)
            or not 0 < len(row["object_id"]) <= 512
        ):
            raise ReplicaError("Invalid replica object identity")
        key = (row["kind"], row["object_id"], row.get("scope"))
        if key in seen:
            raise ReplicaError("Duplicate replica object identity")
        seen.add(key)
        if controls and (
            row["scope"] not in {s.value for s in Scope}
            or not isinstance(row["retired_at"], str)
            or not 0 < len(row["retired_at"]) <= 128
        ):
            raise ReplicaError("Invalid retirement metadata")


def _offer(offer):
    _checked(
        offer,
        "session-replica-offer/v1",
        {"plan", "scope", "snapshot_sha256", "objects"},
    )
    check_plan(offer["plan"], scope=offer["scope"])
    if not isinstance(offer["snapshot_sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", offer["snapshot_sha256"]
    ):
        raise ReplicaError("Invalid offered snapshot hash")
    _objects(offer["objects"])


def _bind(conn, policy, instance):
    if (
        not isinstance(instance, str)
        or not instance
        or instance == state(conn)["instance"]
    ):
        raise ReplicaError("Invalid or duplicated replica instance")
    local = state(conn)["instance"]
    existing = conn.execute(
        "SELECT instance,local_node,local_instance FROM context_replica_peers WHERE peer=?",
        (policy.peer,),
    ).fetchone()
    if existing and tuple(existing) != (instance, policy.node, local):
        raise ReplicaError("Peer instance changed; managed reconciliation is required")
    conn.execute(
        "INSERT OR IGNORE INTO context_replica_peers VALUES (?,?,?,?,?)",
        (policy.peer, instance, policy.node, local, _now()),
    )


def _peer(conn, config, peer_name, *, remote_instance=None):
    policy = PeerPolicy.from_config(config, peer_name, controls_only=True)
    binding = conn.execute(
        "SELECT instance,local_node,local_instance FROM context_replica_peers WHERE peer=?",
        (policy.peer,),
    ).fetchone()
    if (
        binding is None
        or binding[1] != policy.node
        or binding[2] != state(conn)["instance"]
        or (remote_instance is not None and binding[0] != remote_instance)
    ):
        raise ReplicaError("No matching durable peer binding")
    return policy, binding[0]


def _interest(conn, peer, offer):
    conn.executemany(
        "INSERT OR IGNORE INTO context_replica_objects VALUES (?,?,?,?,?)",
        [
            (peer, r["kind"], r["object_id"], offer["scope"], offer["id"])
            for r in offer["objects"]
        ],
    )


def _retired(conn, objects):
    return [
        r
        for r in objects
        if conn.execute(
            "SELECT 1 FROM context_retirements WHERE kind=? AND object_id=?",
            (r["kind"], r["object_id"]),
        ).fetchone()
    ]


def _existing_scope(conn, policy, scope, objects):
    """Reject excluded existing identities using SQL metadata, without reading bodies."""
    _select(conn, policy, Scope(scope))
    conn.execute(
        "CREATE TEMP TABLE offered_objects(kind TEXT,id TEXT,PRIMARY KEY(kind,id))"
    )
    conn.executemany(
        "INSERT INTO offered_objects VALUES (?,?)",
        [(r["kind"], r["object_id"]) for r in objects],
    )
    for kind, (table, selected) in OBJECTS.items():
        if conn.execute(
            f"SELECT 1 FROM offered_objects o JOIN {table} r ON r.id=o.id "
            f"WHERE o.kind=? AND r.id NOT IN (SELECT id FROM replica_{selected}) LIMIT 1",
            (kind,),
        ).fetchone():
            raise ReplicaError("Offer is unavailable in the configured boundary")


def prepare_offer(path, config, plan, scope):
    """Persist an offer before returning metadata; no transcript is persisted in the ledger."""
    snapshot = export_snapshot(path, config, plan, scope)
    offer = _seal(
        {
            "contract": "session-replica-offer/v1",
            "plan": plan,
            "scope": scope,
            "snapshot_sha256": snapshot["sha256"],
            "objects": _manifest(snapshot),
        }
    )
    _offer(offer)
    policy = PeerPolicy.from_config(config, plan["receiver"]["node"])
    with _write(path) as conn:
        if hello(conn, policy) != plan["sender"]:
            raise ReplicaError("Sender state changed while preparing offer")
        _bind(conn, policy, plan["receiver"]["state"]["instance"])
        conn.execute(
            "INSERT OR IGNORE INTO context_replica_offers VALUES (?,'out',?,?,?,'prepared',NULL,NULL,?)",
            (offer["id"], policy.peer, scope, _json(offer), _now()),
        )
        if PeerPolicy.from_config(config, policy.peer) != policy:
            raise ReplicaError("Sender configuration changed while preparing offer")
    return offer


def accept_offer(path, config, peer_name, offer):
    """Register prospective delivery before receiving bodies; this is not a data receipt."""
    _offer(offer)
    plan = offer["plan"]
    policy = PeerPolicy.from_config(config, peer_name)
    if policy.peer != plan["sender"]["node"] or policy.node != plan["receiver"]["node"]:
        raise ReplicaError("Offer does not match the authenticated peer")
    with _write(path) as conn:
        _bind(conn, policy, plan["sender"]["state"]["instance"])
        previous = conn.execute(
            "SELECT acceptance_json FROM context_replica_offers WHERE id=? AND direction='in'",
            (offer["id"],),
        ).fetchone()
        if previous:
            return json.loads(previous[0])
        if hello(conn, policy) != plan["receiver"]:
            raise ReplicaError("Receiver state changed before accepting offer")
        _existing_scope(conn, policy.policy, offer["scope"], offer["objects"])
        retired = _retired(conn, offer["objects"])
        # Old unscoped tombstones do not authorize a new peer to probe retirement
        # membership or inherit a deletion capability for an unrelated identity.
        if any(
            not conn.execute(
                "SELECT 1 FROM context_replica_objects WHERE peer=? AND kind=? AND object_id=? AND scope=?",
                (peer_name, r["kind"], r["object_id"], offer["scope"]),
            ).fetchone()
            for r in retired
        ):
            raise ReplicaError("Offer is unavailable in the configured boundary")
        status = "retired" if retired else "accepted"
        acceptance = _seal(
            {
                "contract": "session-replica-acceptance/v1",
                "offer_id": offer["id"],
                "receiver": policy.node,
                "instance": state(conn)["instance"],
                "status": status,
            }
        )
        conn.execute(
            "INSERT INTO context_replica_offers VALUES (?,'in',?,?,?,?,?,NULL,?)",
            (
                offer["id"],
                peer_name,
                offer["scope"],
                _json(offer),
                status,
                _json(acceptance),
                _now(),
            ),
        )
        _interest(conn, peer_name, offer)
        if PeerPolicy.from_config(config, peer_name) != policy:
            raise ReplicaError("Receiver configuration changed before offer commit")
    return acceptance


def record_acceptance(path, config, peer_name, offer, acceptance):
    """Remember the recipient before any body release, including a lost-body attempt."""
    _offer(offer)
    _checked(
        acceptance,
        "session-replica-acceptance/v1",
        {"offer_id", "receiver", "instance", "status"},
    )
    if (
        acceptance["offer_id"] != offer["id"]
        or acceptance["receiver"] != peer_name
        or acceptance["status"] not in ("accepted", "retired")
    ):
        raise ReplicaError("Acceptance does not bind this offer")
    with _write(path) as conn:
        _peer(conn, config, peer_name, remote_instance=acceptance["instance"])
        previous = conn.execute(
            "SELECT offer_json,acceptance_json FROM context_replica_offers WHERE id=? AND direction='out' AND peer=?",
            (offer["id"], peer_name),
        ).fetchone()
        if (
            previous is None
            or previous[0] != _json(offer)
            or (previous[1] is not None and previous[1] != _json(acceptance))
        ):
            raise ReplicaError("Acceptance has no matching prepared offer")
        if previous[1] is None:
            conn.execute(
                "UPDATE context_replica_offers SET status=?,acceptance_json=? WHERE id=? AND direction='out'",
                (acceptance["status"], _json(acceptance), offer["id"]),
            )
        _interest(conn, peer_name, offer)


def release_content(path, config, peer_name, offer):
    """Revalidate and regenerate the exact accepted snapshot immediately before exposure."""
    _offer(offer)
    with _write(path) as conn:
        _peer(
            conn,
            config,
            peer_name,
            remote_instance=offer["plan"]["receiver"]["state"]["instance"],
        )
        row = conn.execute(
            "SELECT status,offer_json FROM context_replica_offers WHERE id=? AND direction='out' AND peer=?",
            (offer["id"], peer_name),
        ).fetchone()
        if row is None or row[0] != "accepted" or row[1] != _json(offer):
            raise ReplicaError("Content has no accepted offer")
        if _retired(conn, offer["objects"]):
            raise ReplicaError("Offered content was retired before release")
    result = export_snapshot(path, config, offer["plan"], offer["scope"])
    if (
        result["sha256"] != offer["snapshot_sha256"]
        or _manifest(result) != offer["objects"]
    ):
        raise ReplicaError("Accepted snapshot changed before release")
    return result


def receive_content(path, config, peer_name, offer_id, snapshot):
    """Commit bodies and their receipt together; retrying a lost receipt is idempotent."""
    with _write(path) as conn:
        policy, _ = _peer(conn, config, peer_name)
        row = conn.execute(
            "SELECT * FROM context_replica_offers WHERE id=? AND direction='in' AND peer=?",
            (offer_id, peer_name),
        ).fetchone()
        if row is None:
            raise ReplicaError("Content has no registered offer")
        offer = json.loads(row["offer_json"])
        if (
            not isinstance(snapshot, dict)
            or snapshot.get("sha256") != offer["snapshot_sha256"]
            or snapshot.get("plan") != offer["plan"]
            or snapshot.get("scope") != offer["scope"]
        ):
            raise ReplicaError("Content does not match its registered offer")
        if (
            len(_json(snapshot).encode()) > MAX_BYTES
            or _hash(_json({k: v for k, v in snapshot.items() if k != "sha256"}))
            != offer["snapshot_sha256"]
        ):
            raise ReplicaError("Content binding failed before receipt lookup")
        if row["receipt_json"] is not None:
            return json.loads(row["receipt_json"])
        if row["status"] != "accepted" or _retired(conn, offer["objects"]):
            raise ReplicaError("Content offer is retired or unavailable")
        if _manifest(snapshot) != offer["objects"]:
            raise ReplicaError("Content manifest differs from accepted identities")
        apply_in_transaction(
            conn, config, snapshot, PeerContribution(conn, peer_name, offer_id)
        )
        receipt = _seal(
            {
                "contract": "session-replica-content-receipt/v1",
                "offer_id": offer_id,
                "receiver": policy.node,
                "instance": state(conn)["instance"],
                "snapshot_sha256": snapshot["sha256"],
                "committed": True,
            }
        )
        conn.execute(
            "UPDATE context_replica_offers SET status='applied',receipt_json=? WHERE id=? AND direction='in'",
            (_json(receipt), offer_id),
        )
    return receipt


def acknowledge_content(path, config, peer_name, receipt):
    _checked(
        receipt,
        "session-replica-content-receipt/v1",
        {"offer_id", "receiver", "instance", "snapshot_sha256", "committed"},
    )
    if receipt["receiver"] != peer_name or receipt["committed"] is not True:
        raise ReplicaError("Invalid content acknowledgement")
    with _write(path) as conn:
        _peer(conn, config, peer_name, remote_instance=receipt["instance"])
        row = conn.execute(
            "SELECT * FROM context_replica_offers WHERE id=? AND direction='out' AND peer=?",
            (receipt["offer_id"], peer_name),
        ).fetchone()
        if row is None or row["status"] not in ("accepted", "acknowledged"):
            raise ReplicaError("Receipt has no accepted outbound offer")
        if (
            json.loads(row["offer_json"])["snapshot_sha256"]
            != receipt["snapshot_sha256"]
        ):
            raise ReplicaError("Receipt snapshot binding differs")
        if row["receipt_json"] is not None and row["receipt_json"] != _json(receipt):
            raise ReplicaError("Conflicting content receipt")
        conn.execute(
            "UPDATE context_replica_offers SET status='acknowledged',receipt_json=? WHERE id=? AND direction='out'",
            (_json(receipt), receipt["offer_id"]),
        )


def prepare_controls(path, config, peer_name):
    """Return only permanent IDs previously accepted for this still-configured peer."""
    with _write(path) as conn:
        policy, remote = _peer(conn, config, peer_name)
        rows = [
            dict(r)
            for r in conn.execute(
                """SELECT r.kind,r.object_id,o.scope,r.retired_at
            FROM context_retirements r JOIN context_replica_objects o
              ON o.kind=r.kind AND o.object_id=r.object_id WHERE o.peer=?
            ORDER BY r.kind,r.object_id,o.scope LIMIT ?""",
                (peer_name, MAX_ROWS + 1),
            )
        ]
        _objects(rows, controls=True)
        batch = _seal(
            {
                "contract": "session-replica-retirements/v1",
                "sender": policy.node,
                "receiver": peer_name,
                "sender_instance": state(conn)["instance"],
                "receiver_instance": remote,
                "retirements": rows,
            }
        )
        conn.execute(
            "INSERT OR IGNORE INTO context_replica_control_batches VALUES (?,'out',?,?,'prepared',NULL,?)",
            (batch["id"], peer_name, _json(batch), _now()),
        )
        if PeerPolicy.from_config(config, peer_name, controls_only=True) != policy:
            raise ReplicaError("Peer configuration changed while preparing controls")
    return batch


def apply_controls(path, config, peer_name, batch):
    """Purge known identities and retain a receipt; file cleanup is a separate condition."""
    _checked(
        batch,
        "session-replica-retirements/v1",
        {"sender", "receiver", "sender_instance", "receiver_instance", "retirements"},
    )
    _objects(batch["retirements"], controls=True)
    with _write(path) as conn:
        policy, _ = _peer(
            conn, config, peer_name, remote_instance=batch["sender_instance"]
        )
        if (
            batch["sender"] != peer_name
            or batch["receiver"] != policy.node
            or batch["receiver_instance"] != state(conn)["instance"]
        ):
            raise ReplicaError("Controls do not match authenticated replica endpoints")
        previous = conn.execute(
            "SELECT batch_json FROM context_replica_control_batches WHERE id=? AND direction='in' AND peer=?",
            (batch["id"], peer_name),
        ).fetchone()
        if previous is not None and previous[0] != _json(batch):
            raise ReplicaError("Conflicting control identity")
        for row in batch["retirements"]:
            if not conn.execute(
                "SELECT 1 FROM context_replica_objects WHERE peer=? AND kind=? AND object_id=? AND scope=?",
                (peer_name, row["kind"], row["object_id"], row["scope"]),
            ).fetchone():
                raise ReplicaError("Retirement has no recorded peer/object boundary")
        for row in batch["retirements"]:
            conn.execute(
                "INSERT OR IGNORE INTO context_retirements VALUES (?,?,?)",
                (row["kind"], row["object_id"], row["retired_at"]),
            )
        reconcile_local_retirements(conn)
        conn.execute(
            "INSERT OR IGNORE INTO context_replica_control_batches VALUES (?,'in',?,?,'applied',NULL,?)",
            (batch["id"], peer_name, _json(batch), _now()),
        )
        if PeerPolicy.from_config(config, peer_name, controls_only=True) != policy:
            raise ReplicaError("Peer configuration changed during control application")
    cleanup = compact(Path(path))
    with _write(path) as conn:
        policy, _ = _peer(
            conn, config, peer_name, remote_instance=batch["sender_instance"]
        )
        if conn.execute("SELECT 1 FROM context_erasure_pending").fetchone():
            cleanup = {"complete": False, "reason": "cleanup_pending_before_receipt"}
        receipt = _seal(
            {
                "contract": "session-replica-retirement-receipt/v1",
                "batch_id": batch["id"],
                "receiver": policy.node,
                "instance": state(conn)["instance"],
                "logical_committed": True,
                "canonical_cleanup": cleanup,
            }
        )
        conn.execute(
            "UPDATE context_replica_control_batches SET receipt_json=? WHERE id=? AND direction='in'",
            (_json(receipt), batch["id"]),
        )
    return receipt


def acknowledge_controls(path, config, peer_name, receipt):
    _checked(
        receipt,
        "session-replica-retirement-receipt/v1",
        {"batch_id", "receiver", "instance", "logical_committed", "canonical_cleanup"},
    )
    if receipt["receiver"] != peer_name or receipt["logical_committed"] is not True:
        raise ReplicaError("Invalid retirement acknowledgement")
    cleanup = receipt["canonical_cleanup"]
    if cleanup != {"complete": True, "coverage": "canonical_database_and_wal_only"}:
        return {
            "acknowledged": False,
            "reason": "peer_cleanup_pending",
            "sync_complete": False,
        }
    with _write(path) as conn:
        _peer(conn, config, peer_name, remote_instance=receipt["instance"])
        row = conn.execute(
            "SELECT 1 FROM context_replica_control_batches WHERE id=? AND direction='out' AND peer=?",
            (receipt["batch_id"], peer_name),
        ).fetchone()
        if row is None:
            raise ReplicaError("Receipt has no prepared control batch")
        conn.execute(
            "UPDATE context_replica_control_batches SET status='acknowledged',receipt_json=? WHERE id=? AND direction='out'",
            (_json(receipt), receipt["batch_id"]),
        )
    return {
        "acknowledged": True,
        "sync_complete": False,
        "coverage": "known_recipient_canonical_only",
    }
