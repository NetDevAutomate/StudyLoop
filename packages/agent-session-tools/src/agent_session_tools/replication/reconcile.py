"""Exact historical bases for native projection updates, never retention authority.

Only native projection metadata opts into fast-forward. Evidence/interpretations
remain immutable; unknown bases and competing edits remain explicit conflicts.
"""

import re

from ..context.store import _hash, _json
from .policy import ReplicaError

MUTABLE = ("sessions", "messages")


def decide(base, local, incoming):
    """Three-way decision over exact bindings; timestamps never decide ownership."""
    if local == incoming:
        return "identical"
    if base is None:
        return "conflict"
    if local == base:
        return "advance"
    if incoming == base:
        return "keep_local"
    return "conflict"


def row_binding(table, row):
    if table not in MUTABLE or "id" not in row:
        raise ReplicaError("Unsupported mutable projection identity")
    return _hash(_json({"id": row["id"]})), _hash(_json(dict(row)))


def choose_basis(conn, peer, scope):
    row = conn.execute(
        """SELECT o.id,o.direction,o.offer_json FROM context_replica_basis_sets b
        JOIN context_replica_offers o ON o.id=b.offer_id AND o.direction=b.direction
        JOIN context_replica_peers p ON p.peer=o.peer
        JOIN context_access_state a ON a.instance=p.local_instance AND a.id=1
        WHERE o.peer=? AND o.scope=? AND o.receipt_json IS NOT NULL AND (
          (o.direction='out' AND o.status='acknowledged') OR
          (o.direction='in' AND o.status='applied'))
        ORDER BY b.sequence DESC LIMIT 1""",
        (peer, scope),
    ).fetchone()
    if row is None:
        return None
    import json

    return {"offer_id": row[0], "sender": json.loads(row[2])["plan"]["sender"]["node"]}


def record_basis(conn, offer_id, direction, tables):
    """Persist a complete wire-version manifest with its offer/merged receipt.

    An inbound kept-local row can retain an already established old basis. This
    table records reconciliation knowledge, not a claim that this peer authored
    or committed the current local row. No source bodies are retained here.
    """
    if not conn.in_transaction or direction not in ("in", "out"):
        raise ReplicaError("Basis recording requires an offer transaction")
    if conn.execute(
        "SELECT 1 FROM context_replica_basis_sets WHERE offer_id=? AND direction=?",
        (offer_id, direction),
    ).fetchone():
        return
    count = 0
    for table in MUTABLE:
        for row in tables[table]:
            key, binding = row_binding(table, row)
            conn.execute(
                "INSERT INTO context_replica_row_bases VALUES (?,?,?,?,?)",
                (offer_id, direction, table, key, binding),
            )
            count += 1
    conn.execute(
        "INSERT INTO context_replica_basis_sets(offer_id,direction,row_count) VALUES (?,?,?)",
        (offer_id, direction, count),
    )


class Reconciler:
    def __init__(self, conn, peer, local_node, scope, basis):
        self.conn, self.peer = conn, peer
        self.basis, self.direction = None, None
        self.kept_local = 0
        if basis is None:
            return
        if (
            not isinstance(basis, dict)
            or set(basis) != {"offer_id", "sender"}
            or not isinstance(basis["offer_id"], str)
            or re.fullmatch(r"[0-9a-f]{64}", basis["offer_id"]) is None
            or basis["sender"] not in (peer, local_node)
        ):
            raise ReplicaError("Invalid reconciliation basis")
        direction = "out" if basis["sender"] == local_node else "in"
        row = conn.execute(
            """SELECT b.row_count FROM context_replica_basis_sets b
            JOIN context_replica_offers o ON o.id=b.offer_id AND o.direction=b.direction
            JOIN context_replica_peers p ON p.peer=o.peer
            JOIN context_access_state a ON a.instance=p.local_instance AND a.id=1
            WHERE b.offer_id=? AND b.direction=? AND o.peer=? AND o.scope=? AND o.receipt_json IS NOT NULL
              AND o.status=?""",
            (
                basis["offer_id"],
                direction,
                peer,
                scope,
                "acknowledged" if direction == "out" else "applied",
            ),
        ).fetchone()
        if row is None:
            raise ReplicaError("Reconciliation basis has no completed shared transfer")
        actual = conn.execute(
            "SELECT count(*) FROM context_replica_row_bases WHERE offer_id=? AND direction=?",
            (basis["offer_id"], direction),
        ).fetchone()[0]
        if actual != row[0]:
            raise ReplicaError("Reconciliation basis is incomplete")
        self.basis, self.direction = basis["offer_id"], direction

    def action(self, table, local, incoming):
        if table not in MUTABLE:
            return "conflict"
        # Positional native IDs must not overwrite historical conversation text.
        # Native exporters already issue revision IDs for changed role/content.
        fixed = (
            ("id", "source", "project_path")
            if table == "sessions"
            else ("id", "session_id", "role", "content")
        )
        if any(local[key] != incoming[key] for key in fixed):
            return "conflict"
        key, new = row_binding(table, incoming)
        old = row_binding(table, local)[1]
        base = None
        if self.basis is not None:
            row = self.conn.execute(
                "SELECT row_sha256 FROM context_replica_row_bases WHERE offer_id=? AND direction=? AND table_name=? AND key_sha256=?",
                (self.basis, self.direction, table, key),
            ).fetchone()
            base = row[0] if row else None
        action = decide(base, old, new)
        if action == "keep_local":
            self.kept_local += 1
        return action
