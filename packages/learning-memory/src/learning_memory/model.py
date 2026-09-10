"""Canonical data model for the ADR-0011 v1.1 learning-memory store.

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
    "collapse_adjacent_duplicates",
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
"""The only kinds that reach ``prose_fts`` and the citation surface."""

EvidenceBasis = Literal["OBSERVED", "REPORTED"]
"""``OBSERVED`` = a native capture row: the harness's raw bytes, retained.

``REPORTED`` = a per-event citation row: the text of one prose event. Under ADR
v1.1 the store derives the basis of each row from what the adapter actually
handed over, so this is a column label rather than a switch a caller sets.
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
    turn_id: int,
    seq: int,
    kind: EventKind,
    actor: str | None,
    tool_name: str | None,
    text: str,
) -> str:
    """Content address of an event, used for ``UNIQUE(session_id, content_hash)``.

    Position-bearing (ADR v1.1, council finding 5). Re-parsing the same source is
    still a no-op because the same source yields the same positions, but two
    identical messages in different turns are two rows -- which is what makes
    ``retried = same tool call twice`` derivable at all. A position-free hash
    collapsed 54.7 % of the archive's user/assistant rows, including every
    repeated tool call in a session.

    Adjacent *exporter* duplicates are the adapter's to fold before emitting; see
    :func:`collapse_adjacent_duplicates`.
    """
    return hashlib.sha256(
        _canonical_json(
            {
                "turn_id": turn_id,
                "seq": seq,
                "kind": kind,
                "actor": actor,
                "tool_name": tool_name,
                "text": text,
            },
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
        return event_content_hash(
            self.turn_id, self.seq, self.kind, self.actor, self.tool_name, self.text
        )

    @property
    def dedupe_key(self) -> tuple[str, str | None, str | None, str]:
        """What makes two events "the same message" ignoring where they sit."""
        return (self.kind, self.actor, self.tool_name, self.text)


def collapse_adjacent_duplicates(events: Sequence[Event]) -> tuple[list[Event], int]:
    """Fold runs of identical adjacent events, returning the survivors and the count.

    This is the adapter's half of council finding 5: position is in the event hash,
    so the store can no longer collapse anything, and an exporter that wrote the
    same assistant row twice in a row (37,433 assistant / 95 user rows in the
    archive) must be cleaned up before emitting.

    Only *adjacent* runs are folded, and only when kind, actor, tool_name and text
    all match -- a message repeated later in the session is a real second
    occurrence. Surviving events keep their original ``turn_id``/``seq`` so they
    still point at their position in the source; the sequence stays monotone but
    may have gaps.
    """
    survivors: list[Event] = []
    collapsed = 0
    for event in events:
        if survivors and survivors[-1].dedupe_key == event.dedupe_key:
            collapsed += 1
            continue
        survivors.append(event)
    return survivors, collapsed


@dataclass(frozen=True, slots=True)
class SourceRef:
    """A discoverable transcript: a path, or a row in a legacy store."""

    harness: str
    locator: str
    mtime: float | None = None
    size: int | None = None
    source_sha256: str | None = None
    """v1.1: digest of the bytes read, so a receipt can name its input exactly."""


@dataclass(frozen=True, slots=True)
class ParsedSession:
    """An adapter's whole output for one session.

    ``native_source`` is present when the harness still holds the original
    transcript; its bytes are retained as one ``OBSERVED`` capture row. The
    citation surface is always the per-event ``REPORTED`` rows, so a session with
    no prose events has nothing citable and is refused.
    """

    session: Session
    events: Sequence[Event] = ()
    native_source: bytes | None = None
    lineage: list[str] = field(default_factory=list)
    """Parent session ids: one ``lineage`` (or ``lineage_pending``) row each."""
    adapter_version: str = "unspecified"
    """v1.1. Defaulted so fixtures stay short; Stage C's contract suite refuses
    the default, because an unversioned adapter makes a receipt unreproducible."""
    classifier_version: str | None = None
    """v1.1. Set by adapters that *derive* ``kind`` (the archive adapter); ``None``
    where the harness labelled the events itself."""
    exporter_dupes_collapsed: int = 0
    """v1.1. What :func:`collapse_adjacent_duplicates` folded before emitting."""


@runtime_checkable
class HarnessAdapter(Protocol):
    """The contract every harness adapter satisfies (ADR-0011, "Adapter contract").

    The shared base owns dedupe, evidence, lineage and derivation; an adapter
    only discovers and parses.
    """

    harness: str
    adapter_version: str

    def discover(self) -> Iterable[SourceRef]:
        """Yield every transcript this harness currently holds."""
        ...

    def parse(self, ref: SourceRef) -> ParsedSession:
        """Turn one ``SourceRef`` into typed events plus its native bytes."""
        ...
