"""Shared strategies and builders for the learning-memory suite.

Kept out of ``conftest.py`` so test modules can import it explicitly (the sibling
packages follow the same ``tests/_helpers.py`` convention).
"""

from __future__ import annotations

from hypothesis import strategies as st

from learning_memory import (
    Event,
    EventKind,
    EvidenceBasis,
    ParsedSession,
    Session,
    Store,
    Tokenizer,
)

# A curated alphabet instead of st.characters(...): it exercises accented Latin,
# CJK and an astral ZWJ emoji sequence -- the cases where byte or UTF-16 offset
# arithmetic desynchronises from code-point offsets.
ALPHABET = "abcdeé日本語👨\u200d👩\u200d👧 \n\t?!.,'\"-_/"

PROSE_ONLY: tuple[EventKind, ...] = ("user", "assistant_prose")
NON_PROSE: tuple[EventKind, ...] = (
    "tool_call",
    "tool_result",
    "system",
    "thinking",
    "error",
)
ALL_KINDS: tuple[EventKind, ...] = PROSE_ONLY + NON_PROSE
BASES: tuple[EvidenceBasis, ...] = ("OBSERVED", "REPORTED")

text_strategy = st.text(alphabet=ALPHABET, min_size=1, max_size=60).filter(
    lambda value: bool(value.strip())
)
session_ids = st.text(alphabet="abcdef0123456789", min_size=4, max_size=12)


def fresh_store(tokenizer: Tokenizer = "porter unicode61") -> Store:
    """An installed, empty, in-memory store."""
    store = Store.connect(":memory:", tokenizer=tokenizer)
    store.install()
    return store


@st.composite
def events(draw: st.DrawFn, kinds: tuple[EventKind, ...] = ALL_KINDS) -> list[Event]:
    """A list of events with monotonic ``seq`` and plausible ``turn_id``s."""
    bodies = draw(st.lists(text_strategy, min_size=1, max_size=6))
    chosen: list[EventKind] = [draw(st.sampled_from(kinds)) for _ in bodies]
    return [
        Event(turn_id=index // 2, seq=index, kind=kind, text=body, actor=kind)
        for index, (kind, body) in enumerate(zip(chosen, bodies, strict=True))
    ]


@st.composite
def parsed_sessions(draw: st.DrawFn) -> ParsedSession:
    """A ParsedSession that is valid for ingest, i.e. one that carries evidence."""
    basis = draw(st.sampled_from(BASES))
    event_list = draw(events())
    native: bytes | None = None
    if basis == "REPORTED":
        # REPORTED evidence is synthesised from prose, so guarantee some exists.
        head = Event(turn_id=0, seq=0, kind="user", text=draw(text_strategy), actor="user")
        event_list = [
            head,
            *[
                Event(
                    turn_id=event.turn_id,
                    seq=index + 1,
                    kind=event.kind,
                    text=event.text,
                    actor=event.actor,
                )
                for index, event in enumerate(event_list)
            ],
        ]
    else:
        native = draw(text_strategy).encode("utf-8")
    return ParsedSession(
        session=Session(
            id=f"s-{draw(session_ids)}",
            harness=draw(st.sampled_from(["kiro", "codex", "archive"])),
        ),
        events=event_list,
        native_source=native,
        evidence_basis=basis,
        lineage=[],
    )


@st.composite
def evidence_free_sessions(draw: st.DrawFn) -> ParsedSession:
    """A ParsedSession with no native bytes and no prose: it must be refused."""
    bodies = draw(st.lists(text_strategy, min_size=0, max_size=5))
    kinds: list[EventKind] = [draw(st.sampled_from(NON_PROSE)) for _ in bodies]
    return ParsedSession(
        session=Session(id=f"s-{draw(session_ids)}", harness="archive"),
        events=[
            Event(turn_id=index, seq=index, kind=kind, text=body, actor=kind)
            for index, (kind, body) in enumerate(zip(kinds, bodies, strict=True))
        ],
        native_source=None,
        evidence_basis=draw(st.sampled_from(BASES)),
        lineage=[],
    )
