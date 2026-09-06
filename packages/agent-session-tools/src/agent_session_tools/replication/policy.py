"""Peer-owned scope negotiation before any conversation or derived body is read.

SSH authenticates the transport account. These identities select reciprocal local
configuration; a peer-supplied label never reclassifies local projects.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..context.provenance import Scope
from ..context.scope import ScopeError, ScopePolicy
from ..context.store import _hash, _json
from ..migrations import CURRENT_VERSION

PROTOCOL = "session-replica/v2"


class ReplicaError(ValueError):
    """No transfer should be claimed successful after this error."""


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value
    ):
        raise ReplicaError("Replica identities must be explicit stable names")
    return value


def scopes(value, *, allow_empty=False):
    if (
        not isinstance(value, list)
        or (not value and not allow_empty)
        or any(type(v) is not str for v in value)
        or len(set(value)) != len(value)
    ):
        raise ReplicaError("Each peer requires a nonempty explicit allowed_scopes list")
    try:
        return tuple(sorted(Scope(v).value for v in value))
    except ValueError as exc:
        raise ReplicaError(
            "Peer scopes must be personal, work or unclassified"
        ) from exc


@dataclass(frozen=True)
class PeerPolicy:
    node: str
    peer: str
    allowed: tuple[str, ...]
    policy: ScopePolicy
    config_digest: str

    @classmethod
    def from_config(cls, config: dict[str, Any], peer: str, *, controls_only=False):
        identity(peer)
        memory = config.get("memory", {})
        raw = memory.get("sync", {}) if isinstance(memory, dict) else {}
        if not isinstance(raw, dict):
            raise ReplicaError("memory.sync must be a mapping")
        node = identity(raw.get("node_id"))
        peers = raw.get("peers", {})
        if not isinstance(peers, dict) or not isinstance(peers.get(peer), dict):
            raise ReplicaError("Peer is not configured in memory.sync.peers")
        if peer == node:
            raise ReplicaError("A replica cannot sync to itself")
        allowed = scopes(peers[peer].get("allowed_scopes"), allow_empty=controls_only)
        policy = ScopePolicy.from_config(config)
        # Transport settings as well as source policy are revoked by an edit.
        digest = _hash(_json({"sync": raw, "policy": policy.digest}))
        return cls(node, peer, allowed, policy, digest)


def state(conn):
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version != CURRENT_VERSION:
        raise ReplicaError(
            "Replica schema mismatch; upgrade/repair both components before transfer"
        )
    row = conn.execute(
        "SELECT instance,revision FROM context_access_state WHERE id=1"
    ).fetchone()
    if row is None:
        raise ReplicaError("Replica access state is missing")
    path = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    if not path.is_file():
        raise ReplicaError("Replication requires a file-backed database")
    stat = path.stat()
    content_revision = conn.execute(
        "SELECT revision FROM context_replica_content_state WHERE id=1"
    ).fetchone()
    if content_revision is None:
        raise ReplicaError("Replica content generation is missing")
    return {
        "instance": row[0],
        "revision": row[1],
        "content_revision": content_revision[0],
        "file": [stat.st_dev, stat.st_ino],
    }


def hello(conn, policy: PeerPolicy):
    """Content-free capability announcement; unknown config fails before body reads."""
    row = conn.execute("SELECT digest FROM context_policy_state WHERE id=1").fetchone()
    if row is None or row[0] != policy.policy.digest:
        raise ScopeError("Apply current project policy before replica negotiation")
    return {
        "protocol": PROTOCOL,
        "schema": CURRENT_VERSION,
        "node": policy.node,
        "peer": policy.peer,
        "allowed_scopes": list(policy.allowed),
        "projects": {
            p.id: p.scope.value
            for p in policy.policy.projects
            if p.scope.value in policy.allowed
        },
        "config_digest": policy.config_digest,
        "state": state(conn),
    }


def _validate_hello(value, *, controls_only=False, historical=False):
    if not isinstance(value, dict) or set(value) != {
        "protocol",
        "schema",
        "node",
        "peer",
        "allowed_scopes",
        "projects",
        "config_digest",
        "state",
    }:
        raise ReplicaError(
            "Unknown or malformed peer capability; no legacy fallback permitted"
        )
    if (
        value["protocol"]
        not in (("session-replica/v1", PROTOCOL) if historical else (PROTOCOL,))
        or type(value["schema"]) is not int
        or (
            not 42 <= value["schema"] <= CURRENT_VERSION
            if historical
            else value["schema"] != CURRENT_VERSION
        )
    ):
        raise ReplicaError(
            "Incompatible replica protocol/schema; no legacy fallback permitted"
        )
    identity(value["node"])
    identity(value["peer"])
    allowed = scopes(value["allowed_scopes"], allow_empty=controls_only)
    projects = value["projects"]
    if not isinstance(projects, dict):
        raise ReplicaError("Malformed peer project map")
    for key, scope in projects.items():
        identity(key)
        if scope not in allowed:
            raise ReplicaError("Peer project scope is outside its announcement")
    stamp = value["state"]
    if (
        not isinstance(stamp, dict)
        or set(stamp)
        != (
            {"instance", "revision", "file"}
            | ({"content_revision"} if value["schema"] >= 46 else set())
        )
        or not isinstance(stamp["instance"], str)
        or not stamp["instance"]
        or type(stamp["revision"]) is not int
        or stamp["revision"] < 0
        or (
            value["schema"] >= 46
            and (
                type(stamp["content_revision"]) is not int
                or not 0 <= stamp["content_revision"] < 2**63
            )
        )
        or not isinstance(stamp["file"], list)
        or len(stamp["file"]) != 2
        or any(type(n) is not int or n < 0 for n in stamp["file"])
        or not isinstance(value["config_digest"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", value["config_digest"])
    ):
        raise ReplicaError("Malformed peer access state")


def negotiate(sender, receiver, *, historical=False):
    """Intersect two local grants; missing project agreement is an error, not omission."""
    for value in (sender, receiver):
        _validate_hello(value, historical=historical)
    if sender["schema"] != receiver["schema"]:
        raise ReplicaError("Replica schemas disagree")
    if sender["protocol"] != receiver["protocol"]:
        raise ReplicaError("Replica protocol versions disagree")
    if sender["node"] != receiver["peer"] or sender["peer"] != receiver["node"]:
        raise ReplicaError("Peer identities are not reciprocal")
    if (
        sender["node"] == receiver["node"]
        or sender["state"]["instance"] == receiver["state"]["instance"]
    ):
        raise ReplicaError(
            "Replica identity is duplicated; do not sync database clones as distinct peers"
        )
    allowed = sorted(set(sender["allowed_scopes"]) & set(receiver["allowed_scopes"]))
    if not allowed:
        raise ReplicaError("The peers have no mutually allowed scope")
    maps = [
        {p: s for p, s in side["projects"].items() if s in allowed}
        for side in (sender, receiver)
    ]
    if maps[0] != maps[1]:
        raise ReplicaError(
            "Project IDs/scopes disagree; configure both peers before transferring bodies"
        )
    # Deep copy rejects non-JSON values and prevents caller mutation changing a plan.
    return json.loads(
        _json(
            {
                "protocol": sender["protocol"],
                "sender": sender,
                "receiver": receiver,
                "scopes": allowed,
                "projects": maps[0],
            }
        )
    )


def check_plan(plan, *, scope, historical=False):
    if not isinstance(plan, dict) or set(plan) != {
        "protocol",
        "sender",
        "receiver",
        "scopes",
        "projects",
    }:
        raise ReplicaError("Malformed transfer plan")
    if plan != negotiate(plan["sender"], plan["receiver"], historical=historical):
        raise ReplicaError("Transfer plan does not match its reciprocal grants")
    if scope not in plan["scopes"]:
        raise ReplicaError("Requested transfer scope was not negotiated")


def open_read(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("BEGIN")
    return conn
