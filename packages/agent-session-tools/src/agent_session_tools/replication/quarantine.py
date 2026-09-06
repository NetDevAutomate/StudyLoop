"""Scoped operator recovery without reclassifying provenance or granting retention.

Keeping quarantine requires no action. Discard removes the entire selected local
copy, including independently retained additions, only after an exact preview and
explicit acknowledgement. Denials and permanent retirements are never cleared.
"""

import base64
import getpass
import json
import re

from ..context.lifecycle import compact
from ..context.scope import ScopeError, active_policy
from ..context.store import _json, _now
from . import ledger
from .policy import ReplicaError, state
from .snapshot import _select
from .withdrawal_preview import preview, purge_objects

MAX_PAGE = 100
MAX_PLAN_BYTES = 32768
EFFECT = "Discard the complete retained local copy and affected derivatives, including local additions. Denials remain; only a fresh permitted transfer can restore sender-covered content."


def _identity(kind, identity):
    if (
        kind not in ledger.OBJECTS
        or not isinstance(identity, str)
        or not 0 < len(identity) <= 512
    ):
        raise ReplicaError("Invalid quarantine object identity")


def _boundary(conn):
    policy = active_policy()
    scope = policy.request_scope()
    _select(conn, policy, scope, _include_withdrawn=True)
    return policy, scope, state(conn)


def _unchanged(conn, policy, scope, observed):
    current = active_policy()
    if current != policy or current.request_scope() != scope:
        raise ScopeError(
            "Scope changed during quarantine recovery; no change committed"
        )
    now = state(conn)
    if any(now[k] != observed[k] for k in ("instance", "file")):
        raise ReplicaError("Database changed during quarantine recovery")


def _authorized(conn, kind, identity):
    selected = ledger.OBJECTS[kind][1]
    if not conn.execute(
        f"SELECT 1 FROM replica_{selected} WHERE id=?", (identity,)
    ).fetchone():
        raise ScopeError("Quarantine object is unavailable in the configured scope")
    denials = [
        dict(r)
        for r in conn.execute(
            "SELECT peer,scope,generation,status FROM context_replica_denials "
            "WHERE kind=? AND object_id=? AND status!='released' ORDER BY peer,scope LIMIT 65",
            (kind, identity),
        )
    ]
    if not denials:
        raise ScopeError("Quarantine object is unavailable in the configured scope")
    if len(denials) > 64:
        raise ReplicaError("Quarantine object exceeds the bounded peer review limit")
    return denials


def _plan(conn, kind, identity, policy, scope, observed):
    denials = _authorized(conn, kind, identity)
    affected = preview(
        conn, denials[0]["peer"], [{"kind": kind, "object_id": identity}]
    )
    if "footprint_sha256" not in affected:
        raise ReplicaError(
            "Quarantine footprint exceeds review limits; no discard plan issued"
        )
    result = ledger._seal(
        {
            "contract": "session-quarantine-discard-plan/v1",
            "kind": kind,
            "object_id": identity,
            "scope": scope.value,
            "policy_digest": policy.digest,
            "state": observed,
            "denials": denials,
            "footprint_sha256": affected["footprint_sha256"],
            "changed_rows": affected["changed_rows"],
            "changed_by_table": affected["changed_by_table"],
            "traced_json_bytes": affected["traced_json_bytes"],
            "history_fact_count": affected["history_fact_count"],
            "history_json_bytes": affected["history_json_bytes"],
            "effect": EFFECT,
            "provenance_authority": "local_operator_intent_only",
            "permanent_forget": False,
            "regrant": False,
        }
    )
    if len(_json(result).encode()) > MAX_PLAN_BYTES:
        raise ReplicaError("Quarantine plan exceeds review byte limit")
    return result


def inspect(path, kind, identity):
    """Return a body-free immutable-impact preview; do not persist a decision."""
    _identity(kind, identity)
    with ledger._write(path) as conn:
        policy, scope, observed = _boundary(conn)
        result = _plan(conn, kind, identity, policy, scope, observed)
        _unchanged(conn, policy, scope, observed)
    return result


def list_objects(path, *, limit=32, cursor=None):
    """Page retained denied IDs across all six object kinds in the active scope."""
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE:
        raise ReplicaError("Quarantine page limit must be between 1 and 100")
    with ledger._write(path) as conn:
        policy, scope, observed = _boundary(conn)
        after = ("", "")
        if cursor is not None:
            if not isinstance(cursor, str) or len(cursor) > 4096:
                raise ReplicaError("Invalid quarantine cursor")
            try:
                payload = json.loads(
                    base64.b64decode(cursor, altchars=b"-_", validate=True)
                )
            except (ValueError, UnicodeError):
                raise ReplicaError("Invalid quarantine cursor") from None
            ledger._checked(
                payload,
                "session-quarantine-page/v1",
                {"scope", "policy_digest", "state", "after"},
            )
            if (
                payload["scope"] != scope.value
                or payload["policy_digest"] != policy.digest
                or payload["state"] != observed
            ):
                raise ReplicaError("Quarantine cursor is stale; restart listing")
            after = payload["after"]
            if not isinstance(after, list) or len(after) != 2:
                raise ReplicaError("Invalid quarantine cursor")
            _identity(*after)
        selects = []
        for kind, (_, selected) in ledger.OBJECTS.items():
            selects.append(
                f"SELECT DISTINCT d.kind,d.object_id FROM context_replica_denials d JOIN replica_{selected} chosen "
                f"ON chosen.id=d.object_id WHERE d.kind='{kind}' AND d.status!='released'"
            )
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM ("
                + " UNION ".join(selects)
                + ") WHERE (kind,object_id)>(?,?) ORDER BY kind,object_id LIMIT ?",
                (*after, limit + 1),
            )
        ]
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = None
        if more:
            payload = ledger._seal(
                {
                    "contract": "session-quarantine-page/v1",
                    "scope": scope.value,
                    "policy_digest": policy.digest,
                    "state": observed,
                    "after": [rows[-1]["kind"], rows[-1]["object_id"]],
                }
            )
            next_cursor = base64.urlsafe_b64encode(_json(payload).encode()).decode()
        _unchanged(conn, policy, scope, observed)
    return {
        "scope": scope.value,
        "items": rows,
        "next_cursor": next_cursor,
        "bodies_included": False,
    }


def discard(
    path, kind, identity, plan_id, *, discard_local_additions=False, actor=None
):
    """Apply an exact reviewed discard; retries return history and never repurge."""
    _identity(kind, identity)
    if discard_local_additions is not True:
        raise ReplicaError(
            "Discard requires explicit acknowledgement of local additions"
        )
    if not isinstance(plan_id, str) or not re.fullmatch(r"[a-f0-9]{64}", plan_id):
        raise ReplicaError("Discard requires the exact preview ID")
    actor = getpass.getuser() if actor is None else actor
    if not isinstance(actor, str) or not actor.strip() or len(actor) > 256:
        raise ReplicaError("Invalid local discard audit identity")
    historical = False
    with ledger._write(path) as conn:
        policy, scope, observed = _boundary(conn)
        previous = conn.execute(
            "SELECT * FROM context_quarantine_discards WHERE id=?", (plan_id,)
        ).fetchone()
        if previous:
            if (
                previous["kind"] != kind
                or previous["object_id"] != identity
                or previous["local_instance"] != observed["instance"]
                or previous["scope"] != scope.value
                or previous["policy_digest"] != policy.digest
            ):
                raise ScopeError(
                    "Discard receipt is unavailable in the configured boundary"
                )
            receipt = json.loads(previous["receipt_json"])
            historical = True
        else:
            plan = _plan(conn, kind, identity, policy, scope, observed)
            if plan["id"] != plan_id:
                raise ReplicaError(
                    "Discard preview is stale; inspect the current copy first"
                )
            purge_objects(conn, [{"kind": kind, "object_id": identity}])
            receipt = {
                "decision_id": plan_id,
                "logical_discard_committed": True,
                "current_body_absence": "not_asserted_by_historical_receipt",
                "canonical_file_cleanup": {
                    "complete": False,
                    "reason": "cleanup_pending",
                },
                "permanent_forget": False,
                "regrant": False,
                "sync_complete": False,
            }
            conn.execute(
                "INSERT INTO context_quarantine_discards VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    plan_id,
                    observed["instance"],
                    scope.value,
                    kind,
                    identity,
                    policy.digest,
                    _json(plan),
                    actor,
                    _now(),
                    _json(receipt),
                ),
            )
        _unchanged(conn, policy, scope, observed)
    if not historical or not receipt["canonical_file_cleanup"].get("complete"):
        cleanup = compact(path)
        with ledger._write(path) as conn:
            latest = active_policy()
            current = state(conn)
            if (
                latest != policy
                or latest.request_scope() != scope
                or any(current[k] != observed[k] for k in ("instance", "file"))
            ):
                raise ReplicaError(
                    "Discard committed; boundary changed before cleanup receipt"
                )
            if conn.execute("SELECT 1 FROM context_erasure_pending").fetchone():
                cleanup = {
                    "complete": False,
                    "reason": "cleanup_pending_before_receipt",
                }
            receipt["canonical_file_cleanup"] = cleanup
            conn.execute(
                "UPDATE context_quarantine_discards SET receipt_json=? WHERE id=?",
                (_json(receipt), plan_id),
            )
    return receipt
