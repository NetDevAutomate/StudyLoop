"""Fixed replica operations for one locally authenticated peer and configured DB."""

from contextlib import closing
import json
from pathlib import Path
from typing import Any

from ..config_loader import get_db_path, load_config
from ..context.provenance import Scope
from ..context.store import _hash, _json, _now
from . import fence, ledger, permissions
from .policy import PeerPolicy, ReplicaError, _validate_hello, hello, open_read, state
from .stream import Incoming, Outgoing

SCOPES = tuple(s.value for s in Scope)


def _heads(conn, peer):
    return {
        direction: {
            scope: permissions.current(conn, peer, scope, direction)[0]
            for scope in SCOPES
        }
        for direction in ("in", "out")
    }


class Endpoint:
    """Peer identity comes from trusted local setup, never a request body.

    A connection must recover receipts and reconcile both control directions before
    content operations. The barrier is ephemeral and invalidates on control changes.
    """

    def __init__(self, peer, *, db=None, loader=load_config):
        self.peer = peer
        self.loader = loader
        self.override = Path(db).resolve() if db is not None else None
        self.config = loader()
        self.policy = PeerPolicy.from_config(self.config, peer, controls_only=True)
        self.path = self._path(self.config)
        with closing(open_read(self.path)) as conn:
            self.stamp = state(conn)
            hello(conn, self.policy)
        self.bound = False
        self.sent = None
        self.sent_digest = None
        self.received = False
        self.confirmed = False
        self.barrier = None
        self.outgoing: Outgoing | None = None
        self.incoming: Incoming | None = None
        self.outgoing_id = None
        self.incoming_id = None

    def close(self):
        for stream in (self.outgoing, self.incoming):
            if stream is not None:
                stream.close()
        self.outgoing = self.incoming = None
        self.outgoing_id = self.incoming_id = None

    def _path(self, config):
        return self.override or get_db_path(config).expanduser().resolve()

    def check(self):
        config = self.loader()
        if (
            PeerPolicy.from_config(config, self.peer, controls_only=True) != self.policy
            or self._path(config) != self.path
        ):
            raise ReplicaError(
                "Replica configuration changed; reconnect using current policy"
            )
        with closing(open_read(self.path)) as conn:
            current = state(conn)
        if any(current[k] != self.stamp[k] for k in ("instance", "file")):
            raise ReplicaError(
                "Replica database changed; managed reconciliation required"
            )

    def _control_digest(self):
        with closing(open_read(self.path)) as conn:
            retired = conn.execute(
                "SELECT r.kind,r.object_id,o.scope FROM context_retirements r "
                "JOIN context_replica_objects o ON o.kind=r.kind AND o.object_id=r.object_id "
                "WHERE o.peer=? ORDER BY r.kind,r.object_id,o.scope LIMIT ?",
                (self.peer, ledger.MAX_ROWS + 1),
            ).fetchall()
            if len(retired) > ledger.MAX_ROWS:
                raise ReplicaError("Control state exceeds reconciliation bound")
            return _hash(
                _json(
                    {
                        "heads": _heads(conn, self.peer),
                        "retired": [list(r) for r in retired],
                    }
                )
            )

    def before_body_release(self, snapshot):
        self.check()
        if (
            self.barrier is None
            or self.barrier != self._control_digest()
            or self._hello() != snapshot["plan"]["sender"]
        ):
            raise ReplicaError("Source or controls changed before transport release")

    def before_remote_send(self, operation, arguments):
        self.check()
        if operation == "receive":
            self.before_body_release(arguments["snapshot"])
        elif operation in ("stream_receive", "stream_commit"):
            self._check_outgoing(arguments["offer_id"])

    def before_result(self, operation, result):
        self.check()
        if operation == "release":
            self.before_body_release(result)
        elif operation in ("stream_open", "stream_next"):
            self._check_outgoing(self.outgoing_id)
        elif operation == "finish":
            self._finish()

    def call(self, operation, arguments) -> Any:
        fields = {
            "hello": set(),
            "bind": {"remote"},
            "heads": set(),
            "content_scopes": set(),
            "outgoing_next": {"after"},
            "offer_status": {"offer_id"},
            "recover": {"offer_id", "status"},
            "permission": {"scope", "generation"},
            "apply_permission": {"packet"},
            "ack_permission": {"receipt"},
            "retirements": set(),
            "apply_retirements": {"packet"},
            "ack_retirements": {"receipt"},
            "ready": {"remote_heads"},
            "prepare": {"plan", "scope"},
            "prepare_transfer": {"plan", "scope"},
            "accept": {"offer"},
            "record_acceptance": {"offer", "acceptance"},
            "release": {"offer"},
            "receive": {"offer_id", "snapshot"},
            "ack_content": {"receipt"},
            "unchanged": {"plan", "scope"},
            "confirm_unchanged": {"plan", "scope"},
            "finish": set(),
            "stream_open": {"offer"},
            "stream_start": {"offer_id", "header"},
            "stream_next": {"offer_id", "sequence"},
            "stream_receive": {"offer_id", "chunk"},
            "stream_commit": {"offer_id"},
            "stream_close": set(),
        }
        if (
            not isinstance(operation, str)
            or operation not in fields
            or not isinstance(arguments, dict)
            or set(arguments) != fields[operation]
        ):
            raise ReplicaError("Unsupported replica operation or arguments")
        if operation not in ("hello", "bind") and not self.bound:
            raise ReplicaError("Authenticate and bind the reciprocal replica first")
        if operation == "stream_close":
            self.close()
            return {"staging_closed": True}
        try:
            return self._call_checked(operation, arguments)
        except BaseException:
            self.close()
            raise

    def _call_checked(self, operation, arguments):
        with fence.guarded(self.check):
            if operation in (
                "prepare",
                "prepare_transfer",
                "accept",
                "release",
                "receive",
                "unchanged",
                "confirm_unchanged",
                "finish",
                "stream_open",
                "stream_start",
                "stream_next",
                "stream_receive",
                "stream_commit",
            ):
                if self.barrier is None or self.barrier != self._control_digest():
                    raise ReplicaError(
                        "Reconcile current controls in both directions before content"
                    )
            return getattr(self, "_" + operation)(**arguments)

    def _hello(self):
        with closing(open_read(self.path)) as conn:
            return hello(conn, self.policy)

    def _bind(self, remote):
        _validate_hello(remote, controls_only=True)
        if remote["node"] != self.peer or remote["peer"] != self.policy.node:
            raise ReplicaError("Hello does not match the authenticated peer")
        with ledger._write(self.path) as conn:
            ledger._bind(conn, self.policy, remote["state"]["instance"])
        self.bound = True
        self.sent, self.received, self.confirmed, self.barrier = (
            None,
            False,
            False,
            None,
        )
        return {"bound": True}

    def _heads(self):
        with closing(open_read(self.path)) as conn:
            return _heads(conn, self.peer)

    def _content_scopes(self):
        with closing(open_read(self.path)) as conn:
            return {
                direction: [
                    scope
                    for scope in self.policy.allowed
                    if permissions.current(conn, self.peer, scope, direction)[1]
                    == "granted"
                ]
                for direction in ("in", "out")
            }

    def _outgoing_next(self, after):
        if after is not None and (not isinstance(after, str) or len(after) != 64):
            raise ReplicaError("Invalid pending-offer cursor")
        with closing(open_read(self.path)) as conn:
            row = conn.execute(
                "SELECT o.id FROM context_replica_offers o WHERE o.peer=? AND o.direction='out' "
                "AND o.status IN ('prepared','accepted') AND o.id>? "
                "AND NOT EXISTS (SELECT 1 FROM context_replica_superseded s WHERE s.offer_id=o.id) "
                "ORDER BY o.id LIMIT 1",
                (self.peer, after or ""),
            ).fetchone()
            return {"offer_id": row[0] if row else None}

    def _offer_status(self, offer_id):
        if not isinstance(offer_id, str) or len(offer_id) != 64:
            raise ReplicaError("Invalid offer status identity")
        with closing(open_read(self.path)) as conn:
            row = conn.execute(
                "SELECT acceptance_json,receipt_json FROM context_replica_offers "
                "WHERE id=? AND peer=? AND direction='in'",
                (offer_id, self.peer),
            ).fetchone()
            return (
                None
                if row is None
                else {
                    "acceptance": json.loads(row[0]),
                    "receipt": json.loads(row[1]) if row[1] else None,
                }
            )

    def _recover(self, offer_id, status):
        with closing(open_read(self.path)) as conn:
            row = conn.execute(
                "SELECT offer_json FROM context_replica_offers WHERE id=? AND direction='out' AND peer=?",
                (offer_id, self.peer),
            ).fetchone()
            if row is None:
                raise ReplicaError("Recovery has no local outbound offer")
            offer = json.loads(row[0])
        if status is not None:
            if not isinstance(status, dict) or set(status) != {"acceptance", "receipt"}:
                raise ReplicaError("Invalid recovery status")
            ledger.record_acceptance(
                self.path, self.config, self.peer, offer, status["acceptance"]
            )
            if status["receipt"] is not None:
                ledger.acknowledge_content(
                    self.path, self.config, self.peer, status["receipt"]
                )
                return {"recovered_receipt": True, "body_replayed": False}
            if status["acceptance"]["status"] == "retired":
                return {"retired": True, "body_replayed": False}
        # A fresh offer will replace this attempt. This is not a delivery receipt;
        # retain the original offer and any known recipient interest permanently.
        with ledger._write(self.path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO context_replica_superseded VALUES (?,?,?,?)",
                (
                    offer_id,
                    self.peer,
                    "unknown" if status is None else "accepted",
                    _now(),
                ),
            )
        return {"superseded_at_check": True, "body_replayed": False}

    def _permission(self, scope, generation):
        if scope not in SCOPES or type(generation) is not int or generation < 1:
            raise ReplicaError("Invalid permission cursor")
        with closing(open_read(self.path)) as conn:
            row = conn.execute(
                "SELECT batch_json FROM context_replica_permission_batches "
                "WHERE peer=? AND direction='out' AND scope=? AND generation=?",
                (self.peer, scope, generation),
            ).fetchone()
            if row is None:
                raise ReplicaError(
                    "Permission history is missing; reconcile the replica"
                )
            return json.loads(row[0])

    def _apply_permission(self, packet):
        self.barrier = None
        return permissions.apply_change(self.path, self.config, self.peer, packet)

    def _ack_permission(self, receipt):
        return permissions.acknowledge_change(
            self.path, self.config, self.peer, receipt
        )

    def _retirements(self):
        self.sent_digest = self._control_digest()
        packet = ledger.prepare_controls(self.path, self.config, self.peer)
        self.sent, self.confirmed = packet["id"], False
        return packet

    def _apply_retirements(self, packet):
        self.barrier = None
        receipt = ledger.apply_controls(self.path, self.config, self.peer, packet)
        self.received = True
        return receipt

    def _ack_retirements(self, receipt):
        if self.sent is None or receipt.get("batch_id") != self.sent:
            raise ReplicaError("Control acknowledgement does not match this connection")
        result = ledger.acknowledge_controls(self.path, self.config, self.peer, receipt)
        with ledger._write(self.path) as conn:
            ledger._peer(
                conn, self.config, self.peer, remote_instance=receipt["instance"]
            )
        self.confirmed = True  # Logical application can precede physical cleanup.
        return result

    def _ready(self, remote_heads):
        local = self._heads()
        if not self.received or not self.confirmed:
            raise ReplicaError("Replica control histories are not reconciled")
        current = self._control_digest()
        if current != self.sent_digest or remote_heads != {
            "in": local["out"],
            "out": local["in"],
        }:
            self.barrier = None
            return {"controls_reconciled": False, "full_store_covered": False}
        self.barrier = current
        return {"controls_reconciled": True, "full_store_covered": False}

    def _prepare(self, plan, scope):
        if plan.get("receiver", {}).get("node") != self.peer:
            raise ReplicaError("Plan does not match the authenticated peer")
        return ledger.prepare_offer(self.path, self.config, plan, scope)

    def _prepare_transfer(self, plan, scope):
        from .snapshot import SnapshotTooLarge

        try:
            return {"mode": "snapshot", "offer": self._prepare(plan, scope)}
        except SnapshotTooLarge:
            if plan.get("receiver", {}).get("node") != self.peer:
                raise ReplicaError("Plan does not match authenticated peer")
            offer = ledger.prepare_staged_offer(self.path, self.config, plan, scope)
            return {"mode": "stream", "offer": offer}

    def _check_outgoing(self, offer_id):
        if self.outgoing is None or self.outgoing_id != offer_id:
            raise ReplicaError("No matching outgoing stream")
        self.before_body_release(self.outgoing.snapshot)
        return self.outgoing

    def _stream_open(self, offer):
        if self.outgoing is not None:
            raise ReplicaError("An outgoing stream is already open")
        self.outgoing = Outgoing(
            ledger.release_staged_content(self.path, self.config, self.peer, offer)
        )
        self.outgoing_id = offer["id"]
        return self.outgoing.header()

    def _stream_next(self, offer_id, sequence):
        return self._check_outgoing(offer_id).next(sequence)

    def _stream_start(self, offer_id, header):
        from .snapshot import TABLES

        if self.incoming is not None:
            raise ReplicaError("An incoming stream is already open")
        with ledger._write(self.path) as conn:
            policy, _ = ledger._peer(conn, self.config, self.peer)
            row = conn.execute(
                "SELECT offer_json,status,receipt_json FROM context_replica_offers WHERE id=? AND direction='in' AND peer=?",
                (offer_id, self.peer),
            ).fetchone()
            if row is None or not isinstance(header, dict):
                raise ReplicaError("Stream has no accepted offer")
            offer = json.loads(row[0])
            if any(
                header.get(k) != expected
                for k, expected in {
                    "sha256": offer["snapshot_sha256"],
                    "plan": offer["plan"],
                    "scope": offer["scope"],
                    "contract": "session-replica-content/v2",
                    "lifecycle_reconciled": False,
                }.items()
            ):
                raise ReplicaError("Stream header differs from accepted offer")
            if row[2] is not None:
                return {"receipt": json.loads(row[2])}
            if row[1] != "accepted" or ledger._retired(conn, offer["objects"]):
                raise ReplicaError("Stream offer is unavailable")
            permissions.check_offer(conn, self.peer, offer, "in")
            if hello(conn, policy) != offer["plan"]["receiver"]:
                raise ReplicaError("Receiver changed before staging")
            columns = {
                table: {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
                for table in TABLES
            }
        self.incoming = Incoming(header, columns)
        self.incoming_id = offer_id
        return {"staging_opened": True, "committed": False}

    def _check_incoming(self, offer_id):
        if self.incoming is None or self.incoming_id != offer_id:
            raise ReplicaError("No matching incoming stream")
        if self._hello() != self.incoming.header["plan"]["receiver"]:
            raise ReplicaError("Receiver changed during staging")
        return self.incoming

    def _stream_receive(self, offer_id, chunk):
        return self._check_incoming(offer_id).append(chunk)

    def _stream_commit(self, offer_id):
        incoming = self._check_incoming(offer_id)
        try:
            return ledger.receive_content(
                self.path, self.config, self.peer, offer_id, incoming.snapshot()
            )
        finally:
            incoming.close()
            self.incoming = self.incoming_id = None

    def _unchanged(self, plan, scope):
        from .policy import check_plan

        check_plan(plan, scope=scope)
        if plan["sender"] != self._hello() or plan["receiver"]["node"] != self.peer:
            raise ReplicaError("Unchanged check does not match current endpoints")
        with closing(open_read(self.path)) as conn:
            row = conn.execute(
                "SELECT offer_json,receipt_json FROM context_replica_offers "
                "WHERE peer=? AND direction='out' AND scope=? AND status='acknowledged' "
                "ORDER BY created_at DESC,id DESC LIMIT 1",
                (self.peer, scope),
            ).fetchone()
            if row is None:
                return {"unchanged": False}
            offer, receipt = json.loads(row[0]), json.loads(row[1])
            old_receiver, receiver = offer["plan"]["receiver"], plan["receiver"]
            matched = (
                offer["plan"]["sender"] == plan["sender"]
                and receipt.get("committed_state") == receiver["state"]
                and {k: v for k, v in old_receiver.items() if k != "state"}
                == {k: v for k, v in receiver.items() if k != "state"}
            )
            return {"unchanged": matched}

    def _confirm_unchanged(self, plan, scope):
        from .policy import check_plan

        check_plan(plan, scope=scope)
        if plan["receiver"] != self._hello() or plan["sender"]["node"] != self.peer:
            raise ReplicaError("Receiver changed before unchanged-state confirmation")
        return {"receiver_state_confirmed": True}

    def _finish(self):
        if self.barrier is None or self.barrier != self._control_digest():
            raise ReplicaError("Controls changed before connection completion")
        return {"control_state_current_at_check": True}

    def _accept(self, offer):
        return ledger.accept_offer(self.path, self.config, self.peer, offer)

    def _record_acceptance(self, offer, acceptance):
        ledger.record_acceptance(self.path, self.config, self.peer, offer, acceptance)
        return {"recorded": True}

    def _release(self, offer):
        return ledger.release_content(self.path, self.config, self.peer, offer)

    def _receive(self, offer_id, snapshot):
        return ledger.receive_content(
            self.path, self.config, self.peer, offer_id, snapshot
        )

    def _ack_content(self, receipt):
        ledger.acknowledge_content(self.path, self.config, self.peer, receipt)
        return {"acknowledged": True}
