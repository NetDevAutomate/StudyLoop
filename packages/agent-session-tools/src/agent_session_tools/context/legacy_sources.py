"""Bind the exact legacy DB messages supplied to a consumer without inventing native provenance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .legacy import session_messages, session_record
from .provenance import Origin
from .scope import ScopeError
from .store import ContextStore, NativeSource, _hash, _json


@dataclass(frozen=True)
class SessionInput:
    session_id: str
    messages: list[dict[str, Any]]
    evidence_ids: tuple[str, ...]
    fingerprint: str
    native_sources: tuple[NativeSource, ...]

    def manifest(self) -> dict[str, Any]:
        """Preserve order and message shape as well as individual source hashes."""
        return {
            "kind": "legacy_session_messages",
            "fingerprint": self.fingerprint,
            "messages": [
                {
                    "evidence_id": ref,
                    "role": message["role"],
                    "content_is_null": message["content"] is None,
                }
                for ref, message in zip(self.evidence_ids, self.messages, strict=True)
            ],
        }


def prepare_session_input(conn, session_id: str) -> SessionInput:
    """Read permitted DB rows without persisting or taking a writer lock.

    The source is a legacy database row, not a verified original harness record.
    Tool-looking text and role names therefore retain unknown native provenance.
    """
    session = session_record(conn, session_id)
    if session is None:
        raise ScopeError("Session unavailable in the configured scope")
    rows = session_messages(conn, session_id)
    sources = []
    messages = []
    for row in rows:
        messages.append({"role": row["role"], "content": row["content"]})
        timestamp = row["timestamp"]
        try:
            stamp = datetime.fromisoformat(timestamp) if timestamp else None
        except (TypeError, ValueError):
            stamp = None
        recorded_at = stamp.isoformat() if stamp and stamp.tzinfo else None
        sources.append(
            NativeSource(
                session_id=session_id,
                native_key="legacy-message:" + row["id"],
                harness=session["source"],
                native_kind="legacy_message:" + (row["role"] or "unknown"),
                native_locator="sessions.db#messages/" + row["id"],
                parser_version="legacy-db-v1",
                machine_id="unknown",
                body=row["content"] or "",
                origin=Origin.UNKNOWN,
                recorded_at=recorded_at,
            )
        )
    refs = tuple(_hash(_json(source.payload())) for source in sources)
    return SessionInput(
        session_id, messages, refs, _hash(_json(messages)), tuple(sources)
    )


def persist_session_input(conn, captured: SessionInput) -> tuple[str, ...]:
    """Bind the earlier input after a provider returns, checking current access.

    Edited rows do not replace what the model actually received. A forgotten or
    reclassified session must fail the current policy check before any write.
    """
    store = ContextStore(conn)
    with store._atomic():
        if session_record(conn, captured.session_id) is None:
            raise ScopeError("Session unavailable in the configured scope")
        refs = tuple(store.capture(source) for source in captured.native_sources)
        if refs != captured.evidence_ids:
            raise ValueError("Captured source binding changed")
        return refs


def capture_session_input(conn, session_id: str) -> SessionInput:
    """Atomically capture a source for an immediate local observation write."""
    with ContextStore(conn)._atomic():
        captured = prepare_session_input(conn, session_id)
        persist_session_input(conn, captured)
        return captured
