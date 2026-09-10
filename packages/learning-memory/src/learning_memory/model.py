"""Canonical data model for the ADR-0011 learning-memory store.

The types here are what an adapter produces and what the store consumes. They
are deliberately dumb: capture is lossless and typed, and everything useful
(exchanges, concepts, claims) is *derived* later from these rows.

See ``docs/adr/0011-claim-centric-learning-memory.md``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

__all__ = [
    "CLAIM_KINDS",
    "EVENT_KINDS",
    "PROSE_KINDS",
    "ClaimKind",
    "ClaimRelationKind",
    "ConceptSource",
    "Event",
    "EventKind",
    "EvidenceBasis",
    "HarnessAdapter",
    "ParsedSession",
    "ReviewItemKind",
    "Session",
    "SourceRef",
    "event_content_hash",
]

EventKind = Literal[
    "user",
    "assistant_prose",
    "tool_call",
    "tool_result",
    "system",
    "thinking",
    "error",
]
"""Every adapter must classify each event into exactly one of these kinds.

The point of the ``tool_call``/``tool_result`` split is that 53 % of the legacy
store's ``assistant`` rows were tool echoes; only ``user`` and
``assistant_prose`` are ever indexed for search.
"""

EVENT_KINDS: tuple[EventKind, ...] = (
    "user",
    "assistant_prose",
    "tool_call",
    "tool_result",
    "system",
    "thinking",
    "error",
)

PROSE_KINDS: tuple[EventKind, ...] = ("user", "assistant_prose")
"""The only kinds that reach ``prose_fts``."""

EvidenceBasis = Literal["OBSERVED", "REPORTED"]
"""``OBSERVED`` = the harness still holds the native bytes we captured.

``REPORTED`` = the native transcript has been rotated away and the only surviving
copy is prose we already stored (the archive path, ~5,261 of 5,879 sessions).
"""

ClaimKind = Literal["Problem", "Finding", "Decision", "Procedure", "Preference"]

CLAIM_KINDS: tuple[ClaimKind, ...] = (
    "Problem",
    "Finding",
    "Decision",
    "Procedure",
    "Preference",
)

ClaimRelationKind = Literal["supports", "contradicts", "corrects"]

ConceptSource = Literal["vocab", "alias", "model"]

ReviewItemKind = Literal["flashcard", "quiz", "teach_back"]


def _canonical_json(payload: object) -> bytes:
    """Serialise ``payload`` so equal values always give equal bytes."""
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def event_content_hash(
    kind: EventKind,
    actor: str | None,
    tool_name: str | None,
    text: str,
) -> str:
    """Content address of an event, used for the ``UNIQUE(session_id, content_hash)`` dedupe.

    ``turn_id``/``seq`` are deliberately excluded: the legacy store holds 6,591
    exact-duplicate messages, and the invariant ADR-0011 asks for is that
    re-import is a no-op *and* that a repeated identical message inside one
    session collapses to a single row.
    """
    return hashlib.sha256(
        _canonical_json(
            {"kind": kind, "actor": actor, "tool_name": tool_name, "text": text},
        )
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class Session:
    """One agent session. ``id`` is unchanged from today's exporters (ADR-0011 §6)."""

    id: str
    harness: str
    project: str | None = None
    branch: str | None = None
    parent_id: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    scope: str | None = None
    intent: str | None = None
    outcome: str | None = None


@dataclass(frozen=True, slots=True)
class Event:
    """One typed event inside a session."""

    turn_id: int
    seq: int
    kind: EventKind
    text: str
    actor: str | None = None
    tool_name: str | None = None
    ts: str | None = None

    @property
    def content_hash(self) -> str:
        return event_content_hash(self.kind, self.actor, self.tool_name, self.text)


@dataclass(frozen=True, slots=True)
class SourceRef:
    """A discoverable transcript: a path, or a row in a legacy store."""

    harness: str
    locator: str
    mtime: float | None = None
    size: int | None = None


@dataclass(frozen=True, slots=True)
class ParsedSession:
    """An adapter's whole output for one session.

    ``native_source`` is required when ``evidence_basis == "OBSERVED"``; the
    archive path sets ``REPORTED`` and the store synthesises evidence from the
    prose it holds instead.
    """

    session: Session
    events: Sequence[Event] = ()
    native_source: bytes | None = None
    evidence_basis: EvidenceBasis = "OBSERVED"
    lineage: list[str] = field(default_factory=list)
    """Parent session ids: one ``lineage(parent_id, child_id)`` row each."""


@runtime_checkable
class HarnessAdapter(Protocol):
    """The contract every harness adapter satisfies (ADR-0011, "Adapter contract").

    The shared base owns dedupe, evidence, lineage and derivation; an adapter
    only discovers and parses.
    """

    harness: str

    def discover(self) -> Iterable[SourceRef]:
        """Yield every transcript this harness currently holds."""
        ...

    def parse(self, ref: SourceRef) -> ParsedSession:
        """Turn one ``SourceRef`` into typed events plus its native bytes."""
        ...
