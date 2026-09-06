"""Recover metadata, exchange both control directions, then move scoped content."""

from contextlib import closing

from ..config_loader import load_config
from . import fence, ledger, permissions, ssh
from .endpoint import Endpoint, SCOPES
from .policy import ReplicaError, negotiate

MAX_RECOVERY = 256
MAX_PERMISSION_STEPS = 256


def _recover(sender, receiver):
    after = None
    counts = {"receipts": 0, "superseded": 0, "retired": 0}
    for _ in range(MAX_RECOVERY):
        identity = sender.call("outgoing_next", {"after": after})["offer_id"]
        if identity is None:
            return counts
        status = receiver.call("offer_status", {"offer_id": identity})
        result = sender.call("recover", {"offer_id": identity, "status": status})
        counts[
            "receipts"
            if result.get("recovered_receipt")
            else "retired"
            if result.get("retired")
            else "superseded"
        ] += 1
        after = identity
    raise ReplicaError("Recovery round limit reached; retry remaining durable work")


def _control_round(left, right):
    pending = []
    steps = 0
    for sender, receiver in ((left, right), (right, left)):
        sent, received = sender.call("heads", {}), receiver.call("heads", {})
        for scope in SCOPES:
            first, last = received["in"][scope], sent["out"][scope]
            if first > last:
                raise ReplicaError("Receiver has permission history absent from sender")
            # Revisit the latest existing withdrawal too, so pending canonical
            # cleanup can finish after readers or quarantine recovery unblock it.
            for generation in range(max(1, first), last + 1):
                steps += 1
                if steps > MAX_PERMISSION_STEPS:
                    raise ReplicaError(
                        "Permission reconciliation bound reached; retry remaining work"
                    )
                packet = sender.call(
                    "permission", {"scope": scope, "generation": generation}
                )
                receipt = receiver.call("apply_permission", {"packet": packet})
                result = sender.call("ack_permission", {"receipt": receipt})
                if not result["acknowledged"] and generation == last:
                    pending.append(
                        {"kind": "permission", "scope": scope, "generation": generation}
                    )
        packet = sender.call("retirements", {})
        receipt = receiver.call("apply_retirements", {"packet": packet})
        result = sender.call("ack_retirements", {"receipt": receipt})
        if not result["acknowledged"]:
            pending.append({"kind": "retirement", "batch_id": packet["id"]})
    left_ready = left.call("ready", {"remote_heads": right.call("heads", {})})
    right_ready = right.call("ready", {"remote_heads": left.call("heads", {})})
    return pending, left_ready["controls_reconciled"] and right_ready[
        "controls_reconciled"
    ]


def _controls(left, right):
    for _ in range(8):
        pending, ready = _control_round(left, right)
        if ready:
            return pending
    raise ReplicaError("Controls kept changing; retry before transferring content")


def _stream_transfer(sender, receiver, offer):
    from .wire import MAX_REQUESTS

    try:
        header = sender.call("stream_open", {"offer": offer})
        started = receiver.call(
            "stream_start", {"offer_id": offer["id"], "header": header}
        )
        if "receipt" in started:
            receipt = started["receipt"]
        else:
            for sequence in range(MAX_REQUESTS):
                chunk = sender.call(
                    "stream_next", {"offer_id": offer["id"], "sequence": sequence}
                )
                if chunk is None:
                    break
                receiver.call(
                    "stream_receive", {"offer_id": offer["id"], "chunk": chunk}
                )
            else:
                raise ReplicaError("Content stream exceeded its frame bound")
            receipt = receiver.call("stream_commit", {"offer_id": offer["id"]})
    except BaseException:
        # The original refusal or transport failure remains the reported error.
        # Connection owners also close staging on process exit/connection close.
        for endpoint in (sender, receiver):
            try:
                endpoint.call("stream_close", {})
            except Exception:
                pass
        raise
    sender.call("stream_close", {})
    receiver.call("stream_close", {})
    return receipt


def synchronize(local, remote, *, direction):
    if direction not in ("push", "pull", "sync"):
        raise ReplicaError("Invalid structured sync direction")
    local_hello, remote_hello = local.call("hello", {}), remote.call("hello", {})
    local.call("bind", {"remote": remote_hello})
    remote.call("bind", {"remote": local_hello})
    # Lost acceptance must be recovered before selecting known-recipient controls.
    # No old body is needed to retrieve a durable acceptance or data receipt.
    recovery = {"push": _recover(local, remote), "pull": _recover(remote, local)}
    pending = _controls(local, remote)
    transfers = []
    unchanged = []
    for label, sender, receiver in (("push", local, remote), ("pull", remote, local)):
        if direction not in (label, "sync"):
            continue
        allowed = sorted(
            set(sender.call("content_scopes", {})["out"])
            & set(receiver.call("content_scopes", {})["in"])
        )
        for scope in allowed:
            plan = negotiate(sender.call("hello", {}), receiver.call("hello", {}))
            if sender.call("unchanged", {"plan": plan, "scope": scope})["unchanged"]:
                receiver.call("confirm_unchanged", {"plan": plan, "scope": scope})
                unchanged.append({"direction": label, "scope": scope})
                continue
            prepared = sender.call("prepare_transfer", {"plan": plan, "scope": scope})
            if (
                not isinstance(prepared, dict)
                or set(prepared) != {"mode", "offer"}
                or prepared["mode"] not in ("snapshot", "stream")
            ):
                raise ReplicaError("Invalid prepared transfer mode")
            offer = prepared["offer"]
            acceptance = receiver.call("accept", {"offer": offer})
            sender.call("record_acceptance", {"offer": offer, "acceptance": acceptance})
            if acceptance["status"] != "accepted":
                raise ReplicaError(
                    "A new retirement requires another control reconciliation"
                )
            if prepared["mode"] == "stream":
                receipt = _stream_transfer(sender, receiver, offer)
            else:
                body = sender.call("release", {"offer": offer})
                receipt = receiver.call(
                    "receive", {"offer_id": offer["id"], "snapshot": body}
                )
            sender.call("ack_content", {"receipt": receipt})
            transfers.append(
                {
                    "direction": label,
                    "scope": scope,
                    "offer_id": offer["id"],
                    "committed": True,
                    "mode": prepared["mode"],
                    "retained_local_rows": receipt.get("retained_local_rows", 0),
                }
            )
    local.call("finish", {})
    remote.call("finish", {})
    return {
        "peer": remote_hello["node"],
        "canonical_phase_completed": True,
        "recovered": recovery,
        "transfers": transfers,
        "unchanged": unchanged,
        "cleanup_pending": pending,
        "coverage": "configured_canonical_database_and_known_peer_controls",
        "sync_complete": False,
        "full_store_covered": False,
    }


def run(peer, *, direction, db=None):
    with (
        closing(Endpoint(peer, db=db)) as local,
        closing(ssh.connect(load_config(), peer)) as remote,
    ):
        local.check()
        remote.before_send = local.before_remote_send
        return synchronize(local, remote, direction=direction)


def configured_peers():
    config = load_config()
    raw = config.get("memory", {}).get("sync")
    if raw is None:
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("peers"), dict):
        raise ReplicaError("Configure memory.sync.node_id and memory.sync.peers")
    if not raw["peers"]:
        raise ReplicaError("No structured replica peers configured")
    return sorted(raw["peers"])


def queue_permission(peer, scope, action, *, db=None):
    local = Endpoint(peer, db=db)
    with fence.guarded(local.check):
        packet = permissions.prepare_change(
            local.path, local.config, peer, scope, action
        )
        with ledger._write(local.path) as conn:
            acknowledged = (
                conn.execute(
                    "SELECT status='acknowledged' FROM context_replica_permission_batches WHERE id=? AND direction='out'",
                    (packet["id"],),
                ).fetchone()[0]
                == 1
            )
    return {
        "peer": peer,
        "scope": scope,
        "action": action,
        "generation": packet["generation"],
        "queued": not acknowledged,
        "delivery_acknowledged": acknowledged,
        "network_attempted": False,
    }
