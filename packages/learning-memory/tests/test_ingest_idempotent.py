"""Invariant (a): re-import is a no-op, by content_hash.

ADR-0011 relies on the export sweep being safe to re-run: the harnesses rotate
transcripts, so the sweep runs often and over overlapping windows. If re-import
added rows, the store would inherit the legacy defect it exists to fix (6,591
exact-duplicate messages).
"""

from __future__ import annotations

import sqlite3
from typing import cast

import pytest
from hypothesis import given

from learning_memory import (
    Event,
    EventKind,
    ParsedSession,
    Session,
    Store,
    event_content_hash,
)

try:  # package-scoped run (pytest "prepend" import mode)
    from _helpers import fresh_store, parsed_sessions
except ImportError:  # workspace-root run (pytest "importlib" import mode)
    from tests._helpers import fresh_store, parsed_sessions


@given(parsed=parsed_sessions())
def test_reingest_changes_no_row_counts(parsed: ParsedSession) -> None:
    with fresh_store() as store:
        first = store.ingest(parsed)
        before = store.row_counts()

        second = store.ingest(parsed)
        after = store.row_counts()

        assert after == before, "re-import must not add or remove a single row"
        assert second.events_inserted == 0
        assert second.evidence_inserted == 0
        # Every event the first pass wrote is reported as skipped by the second.
        assert second.events_skipped == first.events_inserted + first.events_skipped


@given(parsed=parsed_sessions())
def test_reingest_is_stable_over_many_passes(parsed: ParsedSession) -> None:
    with fresh_store() as store:
        store.ingest(parsed)
        baseline = store.row_counts()
        for _ in range(3):
            store.ingest(parsed)
        assert store.row_counts() == baseline


def test_duplicate_events_within_one_session_collapse(store: Store) -> None:
    """The same message twice in one transcript is one row, and it is counted."""
    duplicate = Event(turn_id=0, seq=0, kind="user", text="why does this fail?", actor="user")
    parsed = ParsedSession(
        session=Session(id="s-dup", harness="kiro"),
        events=[
            duplicate,
            Event(turn_id=0, seq=1, kind="user", text="why does this fail?", actor="user"),
            Event(turn_id=1, seq=2, kind="assistant_prose", text="because of X", actor="agent"),
        ],
        native_source=b"transcript bytes",
    )
    result = store.ingest(parsed)
    assert result.events_inserted == 2
    assert result.events_skipped == 1
    assert store.row_counts()["events"] == 2


def test_content_hash_ignores_position_but_not_content() -> None:
    """Two events differing only in seq/turn share a hash; differing text does not."""
    same = event_content_hash("user", "user", None, "hello")
    assert same == event_content_hash("user", "user", None, "hello")
    assert same != event_content_hash("user", "user", None, "hello ")
    assert same != event_content_hash("assistant_prose", "user", None, "hello")
    assert same != event_content_hash("user", "agent", None, "hello")


def test_session_metadata_is_updated_not_duplicated(store: Store) -> None:
    """A re-parse with better metadata updates the session row in place."""
    events = [Event(turn_id=0, seq=0, kind="user", text="first question?", actor="user")]
    store.ingest(
        ParsedSession(
            session=Session(id="s-meta", harness="kiro"),
            events=events,
            native_source=b"bytes",
        )
    )
    store.ingest(
        ParsedSession(
            session=Session(id="s-meta", harness="kiro", project="studyloop", outcome="resolved"),
            events=events,
            native_source=b"bytes",
        )
    )
    assert store.row_counts()["sessions"] == 1
    row = store.connection.execute(
        "SELECT project, outcome FROM sessions WHERE id = 's-meta'"
    ).fetchone()
    assert row["project"] == "studyloop"
    assert row["outcome"] == "resolved"


def test_a_bad_event_rolls_back_the_whole_ingest(store: Store) -> None:
    """One transaction means one transaction: a rejected event takes the session with it."""
    parsed = ParsedSession(
        session=Session(id="s-bad", harness="kiro"),
        events=[
            Event(turn_id=0, seq=0, kind="user", text="a real question?"),
            Event(turn_id=0, seq=1, kind=cast("EventKind", "not_a_kind"), text="bogus"),
        ],
        native_source=b"native bytes",
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.ingest(parsed)
    counts = store.row_counts()
    assert counts["sessions"] == 0
    assert counts["events"] == 0
    assert counts["evidence"] == 0


def test_foreign_keys_are_enforced(store: Store) -> None:
    """PRAGMA foreign_keys is per-connection and off by default; prove it is on."""
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        store.connection.execute(
            "INSERT INTO events(session_id, turn_id, seq, kind, text, content_hash)"
            " VALUES ('s-nonexistent', 0, 0, 'user', 'orphan', 'deadbeef')"
        )


def test_lineage_is_recorded_once_the_parent_exists(store: Store) -> None:
    """A sub-agent session can be ingested before its parent; the edge lands on re-run."""
    child = ParsedSession(
        session=Session(id="s-child", harness="kiro", parent_id="s-parent"),
        events=[Event(turn_id=0, seq=0, kind="user", text="sub-agent brief")],
        native_source=b"child bytes",
        lineage=["s-parent"],
    )
    first = store.ingest(child)
    assert first.lineage_inserted == 0
    assert first.lineage_deferred == ("s-parent",)

    store.ingest(
        ParsedSession(
            session=Session(id="s-parent", harness="kiro"),
            events=[Event(turn_id=0, seq=0, kind="user", text="parent question?")],
            native_source=b"parent bytes",
        )
    )
    second = store.ingest(child)
    assert second.lineage_inserted == 1
    assert second.events_inserted == 0
    row = store.connection.execute("SELECT parent_id, child_id FROM lineage").fetchone()
    assert (row["parent_id"], row["child_id"]) == ("s-parent", "s-child")
