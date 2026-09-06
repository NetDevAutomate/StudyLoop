"""Versioned reports about native sessions, with optimistic editor concurrency.

An owning session is an access/deletion dependency, not evidence that a note was
derived from its transcript. Older mutable values remain unattributed snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .observations import ObservationStore
from .scope import ScopeError, active_policy, visibility_sql
from .store import _hash, _json

KINDS = {
    "note": "session.annotation.note",
    "tags": "session.annotation.tags",
    "learning": "session.annotation.learning",
}


@dataclass(frozen=True)
class Snapshot:
    session_id: str
    kind: str
    current: list[dict]
    history: list[dict]
    legacy: dict | None
    token: str
    access: tuple


def _access(conn) -> tuple:
    policy = active_policy()
    scope = policy.request_scope()
    generation = None
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='context_access_state'"
    ).fetchone():
        generation = tuple(
            conn.execute(
                "SELECT instance,revision FROM context_access_state WHERE id=1"
            ).fetchone()
        )
    path = conn.execute("PRAGMA database_list").fetchone()[2]
    stat = Path(path).stat() if path else None
    return policy, scope, generation, (stat.st_dev, stat.st_ino) if stat else None


def _legacy(conn, sid: str, kind: str) -> dict | None:
    if kind == "note":
        row = conn.execute(
            "SELECT notes,updated_at FROM session_notes WHERE session_id=?", (sid,)
        ).fetchone()
        return {"notes": row[0], "legacy_updated_at": row[1]} if row else None
    if kind == "tags":
        rows = conn.execute(
            "SELECT tag FROM session_tags WHERE session_id=? ORDER BY tag", (sid,)
        ).fetchall()
        return {"tags": [r[0] for r in rows]} if rows else None
    row = conn.execute(
        "SELECT * FROM session_learning_metadata WHERE session_id=?", (sid,)
    ).fetchone()
    return dict(row) if row else None


def snapshot(
    conn, session_id: str, kind: str = "note", *, include_history: bool = True
) -> Snapshot:
    if kind not in KINDS:
        raise ValueError("Annotation kind must be note, tags or learning")
    visible, values = visibility_sql(conn, "s.id")
    if not conn.execute(
        "SELECT 1 FROM sessions s WHERE s.id=? AND " + visible, [session_id, *values]
    ).fetchone():
        raise ScopeError("Annotation session unavailable in current scope")
    current: list[dict] = []
    history: list[dict] = []
    legacy = _legacy(conn, session_id, kind)
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='context_observations'"
    ).fetchone():
        store = ObservationStore(conn)
        if include_history:
            history = [
                r
                for r in store.list(KINDS[kind], subject=session_id, current=False)
                if r["owner"] == {"session_id": session_id}
            ]
        has_history = (
            bool(history)
            or conn.execute(
                "SELECT 1 FROM context_observations o JOIN context_observation_session_owners own "
                "ON own.observation_id=o.id WHERE o.kind=? AND o.subject=? AND own.session_id=? LIMIT 1",
                (KINDS[kind], session_id, session_id),
            ).fetchone()
            if store._session_owners_available()
            else False
        )
        current = [
            r
            for r in store.list(KINDS[kind], subject=session_id)
            if r["owner"] == {"session_id": session_id}
        ]
        retired = conn.execute(
            "SELECT 1 FROM context_observation_retired_subjects WHERE subject_sha256=?",
            (_hash(_json([KINDS[kind], session_id])),),
        ).fetchone()
        if (
            store._session_owners_available()
            and conn.execute(
                "SELECT 1 FROM context_annotation_retirements WHERE session_id=? AND kind=?",
                (session_id, kind),
            ).fetchone()
        ):
            retired = True
        if has_history or retired:
            legacy = None
    token = _hash(
        _json({"current": sorted(r["id"] for r in current), "legacy": legacy})
    )
    return Snapshot(session_id, kind, current, history, legacy, token, _access(conn))


def write(
    conn, session_id: str, kind: str, payload: dict, *, expected: Snapshot | None = None
) -> str:
    """Caller holds BEGIN IMMEDIATE and a final policy guard around the commit."""
    if not conn.in_transaction:
        raise RuntimeError("Annotation writes require an owned transaction")
    if kind not in ("note", "tags"):
        raise ValueError("This adapter writes note or tags reports")
    if kind == "note":
        if set(payload) != {"notes"} or not isinstance(payload["notes"], str):
            raise ValueError("Note payload must contain only notes text")
    else:
        tags = payload.get("tags")
        if (
            set(payload) != {"tags"}
            or not isinstance(tags, list)
            or any(not isinstance(t, str) or not t for t in tags)
        ):
            raise ValueError("Tags payload must contain nonempty text tags")
        payload = {"tags": sorted(set(tags))}
    now = snapshot(conn, session_id, kind, include_history=False)
    if expected is not None and (
        expected.session_id != session_id
        or expected.kind != kind
        or now.token != expected.token
        or now.access != expected.access
    ):
        raise ScopeError(
            "Annotation or access changed while editing; nothing was saved"
        )
    if (
        len(now.current) == 1
        and now.current[0]["payload"] == payload
        and now.legacy is None
    ):
        return now.current[0]["id"]
    store = ObservationStore(conn)
    previous = [r["id"] for r in now.current]
    if now.legacy is not None:
        previous.append(
            store.append(
                kind=KINDS[kind],
                subject=session_id,
                payload=now.legacy,
                producer="session-annotation.legacy-snapshot",
                authority="reported",
                owner_session_id=session_id,
                request_key="legacy-snapshot",
            )
        )
    identity = store.append(
        kind=KINDS[kind],
        subject=session_id,
        payload=payload,
        producer="session-annotation.local-report",
        authority="reported",
        owner_session_id=session_id,
        supersedes=previous,
    )
    # The prior value is now preserved in immutable history. Avoid a mutable
    # shadow becoming a second authority or an old sync fallback.
    table = "session_notes" if kind == "note" else "session_tags"
    conn.execute(f"DELETE FROM {table} WHERE session_id=?", (session_id,))
    return identity


def values(state: Snapshot) -> list[dict]:
    return [r["payload"] for r in state.current] or (
        [state.legacy] if state.legacy else []
    )


def view(
    conn,
    session_id: str,
    *,
    kind: str = "note",
    max_bytes: int = 32768,
    cursor: str | None = None,
    limit: int = 32,
) -> dict[str, Any]:
    """Bounded current group and history page; scope checked again at delivery."""
    from .annotation_pages import page

    return page(
        conn, session_id, kind=kind, max_bytes=max_bytes, cursor=cursor, limit=limit
    )
