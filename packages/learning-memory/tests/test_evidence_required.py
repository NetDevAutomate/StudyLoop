"""Invariant (b) + D7: evidence is per prose event, and a session must have some.

ADR v1.1 (council finding 7) withdrew the session-sized concatenated body. The
citation surface is now one row per prose event, so a claim cites a fragment:
re-derivation, reclassification and reordering cannot shift its offsets, and quote
ambiguity is bounded by one message instead of a whole session.

A session with no prose has nothing citable, so it is still refused (note 17:
15/5,879 sessions, 0.3 %) -- and a native capture row does not rescue it, because
capture is retention, not a citation surface.
"""

from __future__ import annotations

import hashlib
import sqlite3

import pytest
from hypothesis import given

from learning_memory import Event, NoEvidenceError, ParsedSession, Session, Store

try:  # package-scoped run (pytest "prepend" import mode)
    from _helpers import fresh_store, prose_free_sessions
except ImportError:  # workspace-root run (pytest "importlib" import mode)
    from tests._helpers import fresh_store, prose_free_sessions


@given(parsed=prose_free_sessions())
def test_session_without_prose_is_rejected(parsed: ParsedSession) -> None:
    with fresh_store() as store:
        with pytest.raises(NoEvidenceError):
            store.ingest(parsed)

        counts = store.row_counts()
        assert counts["sessions"] == 0, "the rolled-back session must not survive"
        assert counts["events"] == 0
        assert counts["evidence"] == 0


@given(parsed=prose_free_sessions())
def test_rejection_does_not_disturb_existing_rows(parsed: ParsedSession) -> None:
    """A bad ingest must not damage a session that was already stored."""
    with fresh_store() as store:
        store.ingest(
            ParsedSession(
                session=Session(id="s-good", harness="kiro"),
                events=[Event(turn_id=0, seq=0, kind="user", text="what broke?", actor="user")],
                adapter_version="kiro@1",
            )
        )
        before = store.row_counts()

        with pytest.raises(NoEvidenceError):
            store.ingest(parsed)

        assert store.row_counts() == before


def test_tool_only_session_with_native_bytes_is_still_rejected(store: Store) -> None:
    """D7: a capture row is retention, not a citation surface.

    Deliberately replaces the Stage B test that keyed rejection off a declared
    ``evidence_basis``: under v1.1 the store labels each row from what it actually
    received, and the invariant is "nothing citable", not "no bytes".
    """
    parsed = ParsedSession(
        session=Session(id="s-tools", harness="kiro"),
        events=[
            Event(turn_id=0, seq=0, kind="tool_call", text="[tool:Bash]", tool_name="Bash"),
            Event(turn_id=0, seq=1, kind="tool_result", text="exit 0"),
        ],
        native_source=b"a full native transcript nobody can cite from",
        adapter_version="kiro@1",
    )
    with pytest.raises(NoEvidenceError, match="nothing citable"):
        store.ingest(parsed)
    assert store.row_counts()["sessions"] == 0


def test_whitespace_only_prose_is_rejected(store: Store) -> None:
    parsed = ParsedSession(
        session=Session(id="s-blank", harness="archive"),
        events=[Event(turn_id=0, seq=0, kind="user", text="   \n\t ", actor="user")],
        adapter_version="archive@3",
    )
    with pytest.raises(NoEvidenceError):
        store.ingest(parsed)
    assert store.row_counts()["sessions"] == 0


def test_each_prose_event_gets_its_own_evidence_row(store: Store) -> None:
    """D7 flip: N prose events -> N citable rows, tool events -> none."""
    prose = ["why is recall so low?", "because of dedupe", "and the tokenizer?", "measured later"]
    events = [
        Event(turn_id=0, seq=0, kind="user", text=prose[0], actor="user"),
        Event(turn_id=0, seq=1, kind="tool_result", text="EXCLUDED TOOL ECHO", actor="tool"),
        Event(turn_id=0, seq=2, kind="assistant_prose", text=prose[1], actor="agent"),
        Event(turn_id=1, seq=3, kind="user", text=prose[2], actor="user"),
        Event(turn_id=1, seq=4, kind="thinking", text="EXCLUDED THINKING", actor="agent"),
        Event(turn_id=1, seq=5, kind="assistant_prose", text=prose[3], actor="agent"),
    ]
    result = store.ingest(
        ParsedSession(
            session=Session(id="s-per-event", harness="archive"),
            events=events,
            adapter_version="archive@3",
            classifier_version="archive-classifier@1",
        )
    )
    assert result.evidence_inserted == 4

    visible = store.visible_evidence("s-per-event")
    assert [row["body"] for row in visible] == prose, "ordered by (turn_id, seq)"
    assert all(row["event_id"] is not None for row in visible)
    assert [row["turn_id"] for row in visible] == [0, 0, 1, 1]
    bodies = " ".join(row["body"] for row in visible)
    assert "EXCLUDED" not in bodies

    row = store.connection.execute(
        "SELECT origin, basis FROM evidence WHERE session_id = 's-per-event' LIMIT 1"
    ).fetchone()
    assert (row["origin"], row["basis"]) == ("archive", "REPORTED")


def test_a_quote_in_two_events_is_unambiguous_via_evidence_id(store: Store) -> None:
    """D7's point: the same phrase twice in a session is two rows, so it binds.

    Under the Stage B session-sized body this raised ``ambiguous_quote``.
    """
    shared = "the gate failed"
    store.ingest(
        ParsedSession(
            session=Session(id="s-shared", harness="archive"),
            events=[
                Event(turn_id=0, seq=0, kind="user", text=f"{shared} on Monday", actor="user"),
                Event(
                    turn_id=1, seq=1, kind="user", text=f"{shared} again on Tuesday", actor="user"
                ),
            ],
            adapter_version="archive@3",
        )
    )
    visible = store.visible_evidence("s-shared")
    assert len(visible) == 2

    for index, row in enumerate(visible):
        claim = store.add_claim(
            "s-shared",
            "Finding",
            f"the gate failed, occurrence {index}",
            "Both occurrences are separately citable.",
            ("gates", "provenance"),
            0.8,
            "test-writer",
            [{"evidence_id": row["id"], "quote": shared}],
        )
        bound = store.claim_citations(claim)[0]
        assert bound["evidence_id"] == row["id"]
        assert row["body"][bound["start"] : bound["end"]] == shared


def test_reordering_changes_no_existing_evidence_id(store: Store) -> None:
    """Evidence ids are content-addressed, so a re-derivation cannot strand a citation."""
    first = Event(turn_id=0, seq=0, kind="user", text="first message", actor="user")
    second = Event(turn_id=1, seq=1, kind="assistant_prose", text="second message", actor="agent")
    store.ingest(
        ParsedSession(
            session=Session(id="s-order", harness="archive"),
            events=[first, second],
            adapter_version="archive@3",
        )
    )
    before = {row["id"]: row["body"] for row in store.visible_evidence("s-order")}

    reordered = store.ingest(
        ParsedSession(
            session=Session(id="s-order", harness="archive"),
            events=[
                Event(turn_id=0, seq=0, kind="assistant_prose", text=second.text, actor="agent"),
                Event(turn_id=1, seq=1, kind="user", text=first.text, actor="user"),
            ],
            adapter_version="archive@3",
        )
    )
    after = {row["id"]: row["body"] for row in store.visible_evidence("s-order")}

    assert reordered.evidence_inserted == 0, "no new citation targets"
    assert set(before) <= set(after)
    assert {before[key] for key in before} == {after[key] for key in before}


def test_identical_prose_text_shares_one_evidence_row(store: Store) -> None:
    """The documented consequence of content-addressed evidence ids, pinned.

    Two events with byte-identical text are two EVENT rows (position-bearing hash)
    but one evidence row, whose ``event_id`` names the first occurrence. The body is
    still one message, so offsets stay unambiguous -- which is what lets the ids
    survive reordering.
    """
    repeated = "exactly the same sentence"
    store.ingest(
        ParsedSession(
            session=Session(id="s-same", harness="archive"),
            events=[
                Event(turn_id=0, seq=0, kind="user", text=repeated, actor="user"),
                Event(turn_id=1, seq=1, kind="user", text=repeated, actor="user"),
            ],
            adapter_version="archive@3",
        )
    )
    assert store.row_counts()["events"] == 2
    visible = store.visible_evidence("s-same")
    assert len(visible) == 1
    assert visible[0]["seq"] == 0


def test_native_capture_retains_the_raw_bytes(store: Store) -> None:
    """Council finding 15: OBSERVED evidence stores the bytes, not just their digest."""
    native = "native transcript with 日本語 and a lone \udcff surrogate".encode(
        "utf-8", errors="replace"
    )
    store.ingest(
        ParsedSession(
            session=Session(id="s-native", harness="kiro"),
            events=[Event(turn_id=0, seq=0, kind="user", text="hi there", actor="user")],
            native_source=native,
            adapter_version="kiro@1",
        )
    )
    row = store.connection.execute(
        "SELECT raw, body, body_sha256, origin, basis, event_id"
        " FROM evidence WHERE session_id = 's-native' AND event_id IS NULL"
    ).fetchone()
    assert row["raw"] == native
    assert row["body_sha256"] == hashlib.sha256(native).hexdigest()
    assert row["body"] == native.decode("utf-8", errors="replace")
    assert (row["origin"], row["basis"]) == ("native", "OBSERVED")

    captures = store.captures("s-native")
    assert captures[0]["raw_bytes"] == len(native)

    visible = store.visible_evidence("s-native")
    assert [row["body"] for row in visible] == ["hi there"], "captures are not citation targets"
    assert (
        store.connection.execute(
            "SELECT origin FROM evidence WHERE session_id = 's-native' AND event_id IS NOT NULL"
        ).fetchone()["origin"]
        == "native"
    ), "we hold the original, so the per-event rows say so"


def test_schema_refuses_a_reported_row_without_an_event(store: Store) -> None:
    store.ingest(
        ParsedSession(
            session=Session(id="s-shape", harness="kiro"),
            events=[Event(turn_id=0, seq=0, kind="user", text="a question?", actor="user")],
            adapter_version="kiro@1",
        )
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute(
            "INSERT INTO evidence(id, session_id, event_id, body, body_sha256, raw,"
            " origin, basis, captured_at)"
            " VALUES ('x', 's-shape', NULL, 'body', 'sha', NULL, 'archive', 'REPORTED', 'now')"
        )


def test_schema_refuses_an_observed_row_without_raw_bytes(store: Store) -> None:
    store.ingest(
        ParsedSession(
            session=Session(id="s-shape2", harness="kiro"),
            events=[Event(turn_id=0, seq=0, kind="user", text="a question?", actor="user")],
            adapter_version="kiro@1",
        )
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute(
            "INSERT INTO evidence(id, session_id, event_id, body, body_sha256, raw,"
            " origin, basis, captured_at)"
            " VALUES ('y', 's-shape2', NULL, 'body', 'sha', NULL, 'native', 'OBSERVED', 'now')"
        )
