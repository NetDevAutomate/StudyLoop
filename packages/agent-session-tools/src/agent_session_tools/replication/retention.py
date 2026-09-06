"""Record exact local capture and committed peer contributions, without body copies.

These are historical facts, not grants or a withdrawal policy. In particular,
two peers delivering the same row do not establish independent upstream origins.
Readers and deletion must continue to use their existing scope/lifecycle guards.
"""

from ..context.store import _hash, _json, _now


def available(conn):
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='context_retention_origins'"
        ).fetchone()
    )


def _binding(conn, table, row):
    # Only production packet tables are accepted; identifiers never come from
    # arbitrary SQL or a packet-supplied table outside that fixed allowlist.
    from .snapshot import TABLES

    if table not in TABLES:
        raise ValueError("Unsupported retention table")
    info = list(conn.execute(f"PRAGMA table_info({table})"))
    keys = [r[1] for r in sorted(info, key=lambda r: r[5]) if r[5]]
    if not keys or set(row) != {r[1] for r in info}:
        raise ValueError("Retention requires a complete row with a primary key")
    return _binding_values(table, row, keys)


def _binding_values(table, row, keys):
    """Pure binding for an already schema-checked row and primary-key list."""
    # These two local bookkeeping fields can differ in an otherwise identical
    # accepted transfer. Content and semantic metadata remain in the binding.
    ignored = {
        "context_evidence": {"first_captured_at"},
        "context_session_projects": {"assignment_kind"},
    }.get(table, set())
    return (
        table,
        _hash(_json({key: row[key] for key in keys})),
        _hash(_json({k: v for k, v in row.items() if k not in ignored})),
    )


def _facts(conn, binding, *, limit=None):
    if limit is not None and (type(limit) is not int or limit < 0):
        raise ValueError("Invalid retention fact limit")
    return list(
        conn.execute(
            "SELECT origin,contributor,receipt_id FROM context_retention_origins "
            "WHERE table_name=? AND key_sha256=? AND row_sha256=? "
            "ORDER BY origin,contributor,receipt_id"
            + (" LIMIT ?" if limit is not None else ""),
            (*binding, limit) if limit is not None else binding,
        )
    )


def _record(conn, binding, origin, contributor, receipt_id):
    if not conn.in_transaction:
        raise ValueError("Retention history must commit with its content")
    conn.execute(
        "INSERT OR IGNORE INTO context_retention_origins VALUES (?,?,?,?,?,?,?)",
        (*binding, origin, contributor, receipt_id, _now()),
    )


def record_native_evidence(conn, identity):
    """Called only after the native exporter validates/captures this exact source.

    It does not claim local authorship, native ownership of the entire session,
    or permission to retain any linked interpretation or learner record.
    """
    if not available(conn):
        return
    cursor = conn.execute("SELECT * FROM context_evidence WHERE id=?", (identity,))
    row = cursor.fetchone()
    if row is None:
        raise ValueError("Captured retention source is unavailable")
    value = dict(zip((c[0] for c in cursor.description), row, strict=True))
    binding = _binding(conn, "context_evidence", value)
    instance = conn.execute(
        "SELECT instance FROM context_access_state WHERE id=1"
    ).fetchone()[0]
    _record(conn, binding, "native_capture", instance, identity)


class PeerContribution:
    """Collect row history under an already accepted inbound offer.

    Construction and every record happen in the same caller-owned transaction as
    content application and its final receipt. This internal helper is not a
    packet field, and standalone content imports do not establish these facts.
    """

    def __init__(self, conn, peer, offer_id):
        if (
            not conn.in_transaction
            or conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1
            or not conn.execute(
                "SELECT 1 FROM context_replica_offers o "
                "JOIN context_replica_peers p ON p.peer=o.peer "
                "JOIN context_access_state a ON a.id=1 AND a.instance=p.local_instance "
                "WHERE o.id=? AND o.direction='in' AND o.peer=? AND o.status='accepted'",
                (offer_id, peer),
            ).fetchone()
        ):
            raise ValueError(
                "Retention contribution requires an accepted offer transaction and current peer binding"
            )
        self.peer, self.offer_id = peer, offer_id

    def record(self, conn, table, row, *, existed):
        binding = _binding(conn, table, row)
        if existed and not _facts(conn, binding, limit=1):
            # Do not let a first new receipt erase uncertainty about a body that
            # was already present before prospective origin tracking began.
            _record(conn, binding, "unattributed", "", "")
        _record(conn, binding, "peer_commit", self.peer, self.offer_id)


def describe(conn, table, row):
    """Body-free facts for one caller-authorized row, never an authorization answer.

    The caller must select the current row through its normal access boundary.
    This helper is internal and intentionally has no arbitrary-ID CLI/MCP route.
    """
    binding = _binding(conn, table, row)
    facts = _facts(conn, binding) if available(conn) else []
    instance = conn.execute(
        "SELECT instance FROM context_access_state WHERE id=1"
    ).fetchone()[0]
    peers = (
        {
            r[0]
            for r in conn.execute(
                "SELECT peer FROM context_replica_peers WHERE local_instance=?",
                (instance,),
            )
        }
        if available(conn)
        else set()
    )
    applicable = [
        r
        for r in facts
        if (r[0] == "native_capture" and r[1] == instance)
        or (r[0] == "peer_commit" and r[1] in peers)
        or r[0] == "unattributed"
    ]
    return {
        "binding": {
            "table": binding[0],
            "key_sha256": binding[1],
            "row_sha256": binding[2],
        },
        "native_capture_observed": any(r[0] == "native_capture" for r in applicable),
        "committed_peers": sorted({r[1] for r in applicable if r[0] == "peer_commit"}),
        "unattributed_history": not facts
        or len(applicable) != len(facts)
        or any(r[0] == "unattributed" for r in applicable),
        "retention_authorized": "not_evaluated",
        "independent_upstream_origins": "not_established",
    }
