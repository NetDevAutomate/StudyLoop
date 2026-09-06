"""Ordered peer withdrawal and fresh regrant, separate from permanent retirement.

The transport must authenticate peer_name and load current configuration. Bodies
with ambiguous retention history stay hidden and yield incomplete cleanup, never
an erasure receipt. Full-store/restore and SSH coordination are separate gates.
"""

import json
from pathlib import Path

from ..context.lifecycle import compact
from ..context.provenance import Scope
from ..context.store import _json, _now
from . import ledger
from .policy import PeerPolicy, ReplicaError, state
from .snapshot import MAX_ROWS
from .withdrawal_preview import preview, purge_objects


def current(conn, peer, scope, direction):
    row = conn.execute(
        "SELECT generation,status,last_batch FROM context_replica_permissions WHERE peer=? AND scope=? AND direction=?",
        (peer, scope, direction),
    ).fetchone()
    return tuple(row) if row else (0, "granted", None)


def check_offer(conn, peer, offer, direction):
    generation, status, _ = current(conn, peer, offer["scope"], direction)
    if status != "granted" or offer.get("generation", 0) != generation:
        raise ReplicaError(
            "Content offer has a stale or withdrawn permission generation"
        )


def _known(conn, peer, scope, direction):
    statuses = (
        "('accepted','applied','retired')"
        if direction == "in"
        else "('accepted','acknowledged','retired')"
    )
    result = [
        dict(r)
        for r in conn.execute(
            "SELECT DISTINCT json_extract(item.value,'$.kind') kind,json_extract(item.value,'$.object_id') object_id "
            "FROM context_replica_offers o,json_each(o.offer_json,'$.objects') item "
            f"WHERE o.peer=? AND o.scope=? AND o.direction=? AND o.status IN {statuses} "
            "ORDER BY kind,object_id LIMIT ?",
            (peer, scope, direction, MAX_ROWS + 1),
        )
    ]
    ledger._objects(result)
    return result


def _set_permission(conn, peer, scope, direction, generation, action, batch_id):
    conn.execute(
        "INSERT INTO context_replica_permissions VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(peer,direction,scope) DO UPDATE SET generation=excluded.generation,status=excluded.status,last_batch=excluded.last_batch",
        (
            peer,
            direction,
            scope,
            generation,
            "withdrawn" if action == "withdraw" else "granted",
            batch_id,
        ),
    )


def prepare_change(path, config, peer_name, scope, action):
    """Prepare or retry an explicit scope withdrawal/regrant with body-free history."""
    if scope not in {s.value for s in Scope} or action not in ("withdraw", "regrant"):
        raise ReplicaError("Invalid permission change")
    with ledger._write(path) as conn:
        policy, remote = ledger._peer(conn, config, peer_name)
        generation, status, last = current(conn, peer_name, scope, "out")
        desired = "withdrawn" if action == "withdraw" else "granted"
        if last and status == desired:
            return json.loads(
                conn.execute(
                    "SELECT batch_json FROM context_replica_permission_batches WHERE id=? AND direction='out'",
                    (last,),
                ).fetchone()[0]
            )
        if action == "regrant":
            if (
                generation == 0
                or scope not in PeerPolicy.from_config(config, peer_name).allowed
            ):
                raise ReplicaError(
                    "Regrant requires a prior withdrawal and current explicit scope permission"
                )
        if generation >= 2**63 - 1:
            raise ReplicaError(
                "Permission generation is exhausted; reconciliation required"
            )
        objects = _known(conn, peer_name, scope, "out")
        packet = ledger._seal(
            {
                "contract": "session-replica-permission/v1",
                "sender": policy.node,
                "receiver": peer_name,
                "sender_instance": state(conn)["instance"],
                "receiver_instance": remote,
                "scope": scope,
                "generation": generation + 1,
                "action": action,
                "objects": objects,
            }
        )
        conn.execute(
            "INSERT INTO context_replica_permission_batches VALUES (?,'out',?,?,?,?,?,'prepared',NULL,?)",
            (
                packet["id"],
                peer_name,
                scope,
                generation + 1,
                action,
                _json(packet),
                _now(),
            ),
        )
        _set_permission(
            conn, peer_name, scope, "out", generation + 1, action, packet["id"]
        )
        if PeerPolicy.from_config(config, peer_name, controls_only=True) != policy:
            raise ReplicaError(
                "Peer configuration changed during permission preparation"
            )
    return packet


def _packet(packet):
    ledger._checked(
        packet,
        "session-replica-permission/v1",
        {
            "sender",
            "receiver",
            "sender_instance",
            "receiver_instance",
            "scope",
            "generation",
            "action",
            "objects",
        },
    )
    ledger._objects(packet["objects"])
    if (
        packet["scope"] not in {s.value for s in Scope}
        or type(packet["generation"]) is not int
        or not 0 < packet["generation"] < 2**63
        or packet["action"] not in ("withdraw", "regrant")
    ):
        raise ReplicaError("Invalid permission control")


def _receipt(conn, policy, packet, cleanup, assessment):
    return ledger._seal(
        {
            "contract": "session-replica-permission-receipt/v1",
            "batch_id": packet["id"],
            "receiver": policy.node,
            "instance": state(conn)["instance"],
            "scope": packet["scope"],
            "generation": packet["generation"],
            "action": packet["action"],
            "logical_committed": True,
            "canonical_cleanup": cleanup,
            "assessment": assessment,
            "sync_complete": False,
        }
    )


def apply_change(path, config, peer_name, packet):
    """Install denials and purge only an attributable complete footprint atomically."""
    _packet(packet)
    with ledger._write(path) as conn:
        policy, _ = ledger._peer(
            conn, config, peer_name, remote_instance=packet["sender_instance"]
        )
        if (
            packet["sender"] != peer_name
            or packet["receiver"] != policy.node
            or packet["receiver_instance"] != state(conn)["instance"]
        ):
            raise ReplicaError(
                "Permission control does not match authenticated endpoints"
            )
        generation, status, last = current(conn, peer_name, packet["scope"], "in")
        previous = conn.execute(
            "SELECT * FROM context_replica_permission_batches WHERE id=? AND direction='in'",
            (packet["id"],),
        ).fetchone()
        if previous and previous["batch_json"] != _json(packet):
            raise ReplicaError("Conflicting permission control identity")
        if previous and packet["generation"] < generation:
            return json.loads(previous["receipt_json"])
        if packet["generation"] not in (generation + 1, generation) or (
            packet["generation"] == generation and last != packet["id"]
        ):
            raise ReplicaError("Permission controls must arrive in generation order")
        if not previous and (
            (packet["action"] == "regrant" and status != "withdrawn")
            or (packet["action"] == "withdraw" and status != "granted")
        ):
            raise ReplicaError(
                "Permission control does not follow the preceding action"
            )
        known = _known(conn, peer_name, packet["scope"], "in")
        allowed = {(r["kind"], r["object_id"]) for r in known}
        if any((r["kind"], r["object_id"]) not in allowed for r in packet["objects"]):
            raise ReplicaError(
                "Permission control has no recorded inbound object boundary"
            )
        if (
            packet["action"] == "regrant"
            and packet["scope"] not in PeerPolicy.from_config(config, peer_name).allowed
        ):
            raise ReplicaError("Receiver scope policy does not permit regrant")
        if not previous:
            # Receiver may know an acceptance whose response never reached the
            # sender. The whole inbound scope is denied, including those IDs.
            for row in known:
                conn.execute(
                    "INSERT INTO context_replica_denials VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT(peer,scope,kind,object_id) DO UPDATE SET generation=excluded.generation,status=excluded.status",
                    (
                        peer_name,
                        packet["scope"],
                        row["kind"],
                        row["object_id"],
                        packet["generation"],
                        "withdrawn"
                        if packet["action"] == "withdraw"
                        else "awaiting_content",
                    ),
                )
            _set_permission(
                conn,
                peer_name,
                packet["scope"],
                "in",
                packet["generation"],
                packet["action"],
                packet["id"],
            )
        if packet["action"] == "withdraw":
            assessment = preview(conn, peer_name, known)
            if assessment["eligible"]:
                purge_objects(conn, known)
                cleanup = {"complete": False, "reason": "cleanup_pending"}
            else:
                cleanup = {"complete": False, "reason": assessment["reason"]}
        else:
            assessment = {"awaiting_fresh_content": len(known)}
            cleanup = {"complete": False, "reason": "regrant_does_not_erase"}
        receipt = _receipt(conn, policy, packet, cleanup, assessment)
        conn.execute(
            "INSERT INTO context_replica_permission_batches VALUES (?,'in',?,?,?,?,?,'applied',?,?) "
            "ON CONFLICT(id,direction) DO UPDATE SET receipt_json=excluded.receipt_json",
            (
                packet["id"],
                peer_name,
                packet["scope"],
                packet["generation"],
                packet["action"],
                _json(packet),
                _json(receipt),
                _now(),
            ),
        )
        if PeerPolicy.from_config(config, peer_name, controls_only=True) != policy:
            raise ReplicaError(
                "Peer configuration changed during permission application"
            )
    if packet["action"] == "withdraw" and assessment["eligible"]:
        cleanup = compact(Path(path))
        with ledger._write(path) as conn:
            policy, _ = ledger._peer(
                conn, config, peer_name, remote_instance=packet["sender_instance"]
            )
            if (
                current(conn, peer_name, packet["scope"], "in")[0]
                != packet["generation"]
            ):
                cleanup = {
                    "complete": False,
                    "reason": "permission_changed_before_receipt",
                }
            elif conn.execute("SELECT 1 FROM context_erasure_pending").fetchone():
                cleanup = {
                    "complete": False,
                    "reason": "cleanup_pending_before_receipt",
                }
            receipt = _receipt(conn, policy, packet, cleanup, assessment)
            conn.execute(
                "UPDATE context_replica_permission_batches SET receipt_json=? WHERE id=? AND direction='in'",
                (_json(receipt), packet["id"]),
            )
    return receipt


def release_awaiting(conn, peer, offer):
    """Internal content-transaction operation; a packet cannot request this callback."""
    check_offer(conn, peer, offer, "in")
    released = []
    for row in offer["objects"]:
        old = conn.execute(
            "SELECT status,generation FROM context_replica_denials WHERE peer=? AND scope=? AND kind=? AND object_id=?",
            (peer, offer["scope"], row["kind"], row["object_id"]),
        ).fetchone()
        if old and old[0] == "awaiting_content" and old[1] == offer["generation"]:
            conn.execute(
                "UPDATE context_replica_denials SET status='released' WHERE peer=? AND scope=? AND kind=? AND object_id=?",
                (peer, offer["scope"], row["kind"], row["object_id"]),
            )
            released.append(row)
        if conn.execute(
            "SELECT 1 FROM context_replica_denials WHERE kind=? AND object_id=? AND status!='released'",
            (row["kind"], row["object_id"]),
        ).fetchone():
            raise ReplicaError("Offered object has another unresolved withdrawal")
    return released


def check_regrant_coverage(conn, peer, offer, released):
    if (
        released
        and not preview(conn, peer, released, receipt_id=offer["id"])["eligible"]
    ):
        raise ReplicaError(
            "Fresh regrant does not cover every retained body it would expose"
        )


def acknowledge_change(path, config, peer_name, receipt):
    ledger._checked(
        receipt,
        "session-replica-permission-receipt/v1",
        {
            "batch_id",
            "receiver",
            "instance",
            "scope",
            "generation",
            "action",
            "logical_committed",
            "canonical_cleanup",
            "assessment",
            "sync_complete",
        },
    )
    if (
        receipt["receiver"] != peer_name
        or receipt["logical_committed"] is not True
        or receipt["sync_complete"] is not False
    ):
        raise ReplicaError("Invalid permission receipt")
    with ledger._write(path) as conn:
        ledger._peer(conn, config, peer_name, remote_instance=receipt["instance"])
        row = conn.execute(
            "SELECT * FROM context_replica_permission_batches WHERE id=? AND direction='out' AND peer=?",
            (receipt["batch_id"], peer_name),
        ).fetchone()
        if row is None or any(
            row[k] != receipt[k] for k in ("scope", "generation", "action")
        ):
            raise ReplicaError("Permission receipt has no matching prepared change")
        complete = receipt["action"] == "regrant" or receipt["canonical_cleanup"] == {
            "complete": True,
            "coverage": "canonical_database_and_wal_only",
        }
        if complete:
            conn.execute(
                "UPDATE context_replica_permission_batches SET status='acknowledged',receipt_json=? WHERE id=? AND direction='out'",
                (_json(receipt), receipt["batch_id"]),
            )
    return {
        "acknowledged": complete,
        "sync_complete": False,
        "coverage": "known_inbound_canonical_only"
        if complete
        else "logical_denial_with_cleanup_pending",
    }
