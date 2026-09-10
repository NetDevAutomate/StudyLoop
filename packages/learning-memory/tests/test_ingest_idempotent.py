"""Invariant (a): re-parse of the same source is a no-op, and every occurrence is a row.

ADR-0011 relies on the export sweep being safe to re-run: the harnesses rotate
transcripts, so the sweep runs often and over overlapping windows. Re-import must
add nothing.

v1.1 (council finding 5) changed what "duplicate" means. ``content_hash`` is now
position-bearing, so two identical messages in different turns are two rows --
folding them destroyed 54.7 % of the archive's user/assistant rows and made
``retried = same tool call twice`` underivable. Adjacent *exporter* duplicates are
the adapter's to fold, via ``collapse_adjacent_duplicates``.
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
    collapse_adjacent_duplicates,
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
        assert second.events_skipped == first.events_inserted + first.events_skipped


@given(parsed=parsed_sessions())
def test_five_ingests_are_identical(parsed: ParsedSession) -> None:
    """D5's acceptance probe: the same ParsedSession five times changes nothing."""
    with fresh_store() as store:
        store.ingest(parsed)
        baseline = store.row_counts()
        for _ in range(4):
            store.ingest(parsed)
        assert store.row_counts() == baseline


def test_identical_text_in_two_turns_is_two_rows(store: Store) -> None:
    """D5 flip. Was: one row (position-free hash). Now: one row per occurrence.

    Updated deliberately from the Stage B test that asserted duplicates collapse:
    council finding 5 withdrew that behaviour, because on the archive it folded
    every repeated tool call in a session into one row.
    """
    repeated = "why does this fail?"
    parsed = ParsedSession(
        session=Session(id="s-dup", harness="kiro"),
        events=[
            Event(turn_id=0, seq=0, kind="user", text=repeated, actor="user"),
            Event(turn_id=0, seq=1, kind="assistant_prose", text="because of X", actor="agent"),
            Event(turn_id=1, seq=2, kind="user", text=repeated, actor="user"),
        ],
        adapter_version="kiro@1",
    )
    result = store.ingest(parsed)
    assert result.events_inserted == 3
    assert result.events_skipped == 0
    assert store.row_counts()["events"] == 3


def test_repeated_tool_call_stays_two_rows(store: Store) -> None:
    """The concrete capability finding 5 was protecting: `retried` can now fire."""
    parsed = ParsedSession(
        session=Session(id="s-retry", harness="kiro"),
        events=[
            Event(turn_id=0, seq=0, kind="user", text="run the tests", actor="user"),
            Event(turn_id=0, seq=1, kind="tool_call", text="[tool:Bash]", tool_name="Bash"),
            Event(turn_id=0, seq=2, kind="tool_result", text="exit 1"),
            Event(turn_id=0, seq=3, kind="tool_call", text="[tool:Bash]", tool_name="Bash"),
        ],
        adapter_version="kiro@1",
    )
    store.ingest(parsed)
    calls = store.connection.execute(
        "SELECT count(*) AS n FROM events WHERE session_id = 's-retry' AND kind = 'tool_call'"
    ).fetchone()
    assert calls["n"] == 2


def test_content_hash_is_position_bearing() -> None:
    """Position is in the hash; content still matters too."""
    base = event_content_hash(0, 0, "user", "user", None, "hello")
    assert base == event_content_hash(0, 0, "user", "user", None, "hello")
    assert base != event_content_hash(1, 0, "user", "user", None, "hello"), "turn_id counts"
    assert base != event_content_hash(0, 1, "user", "user", None, "hello"), "seq counts"
    assert base != event_content_hash(0, 0, "user", "user", None, "hello ")
    assert base != event_content_hash(0, 0, "assistant_prose", "user", None, "hello")
    assert base != event_content_hash(0, 0, "user", "agent", None, "hello")
    assert base != event_content_hash(0, 0, "user", "user", "Bash", "hello")


def test_collapse_adjacent_duplicates_folds_only_adjacent_runs() -> None:
    """The adapter's half of finding 5."""
    repeated = Event(turn_id=0, seq=1, kind="assistant_prose", text="same", actor="agent")
    events = [
        Event(turn_id=0, seq=0, kind="user", text="question?", actor="user"),
        repeated,
        Event(turn_id=0, seq=2, kind="assistant_prose", text="same", actor="agent"),
        Event(turn_id=0, seq=3, kind="assistant_prose", text="same", actor="agent"),
        Event(turn_id=1, seq=4, kind="user", text="another?", actor="user"),
        # Not adjacent to the run above, so a real second occurrence.
        Event(turn_id=1, seq=5, kind="assistant_prose", text="same", actor="agent"),
    ]
    survivors, collapsed = collapse_adjacent_duplicates(events)
    assert collapsed == 2
    assert [event.seq for event in survivors] == [0, 1, 4, 5]
    assert survivors[1] is repeated, "the first of a run survives, keeping its position"


def test_collapse_adjacent_duplicates_is_idempotent_and_empty_safe() -> None:
    assert collapse_adjacent_duplicates([]) == ([], 0)
    once, first = collapse_adjacent_duplicates(
        [
            Event(turn_id=0, seq=0, kind="user", text="a", actor="user"),
            Event(turn_id=0, seq=1, kind="user", text="a", actor="user"),
        ]
    )
    twice, second = collapse_adjacent_duplicates(once)
    assert (first, second) == (1, 0)
    assert twice == once


def test_exporter_dupes_collapsed_is_stored_and_reported(store: Store) -> None:
    """The count is auditable on `sessions`, not just inferable from row totals."""
    raw = [
        Event(turn_id=0, seq=0, kind="user", text="a question?", actor="user"),
        Event(turn_id=0, seq=1, kind="assistant_prose", text="an answer", actor="agent"),
        Event(turn_id=0, seq=2, kind="assistant_prose", text="an answer", actor="agent"),
    ]
    events, collapsed = collapse_adjacent_duplicates(raw)
    result = store.ingest(
        ParsedSession(
            session=Session(id="s-dupes", harness="kiro"),
            events=events,
            adapter_version="kiro@1",
            exporter_dupes_collapsed=collapsed,
        )
    )
    assert result.exporter_dupes_collapsed == 1
    row = store.connection.execute(
        "SELECT exporter_dupes_collapsed, adapter_version FROM sessions WHERE id = 's-dupes'"
    ).fetchone()
    assert row["exporter_dupes_collapsed"] == 1
    assert row["adapter_version"] == "kiro@1"


def test_session_metadata_is_updated_not_duplicated(store: Store) -> None:
    """A re-parse with better metadata updates the session row in place."""
    events = [Event(turn_id=0, seq=0, kind="user", text="first question?", actor="user")]
    store.ingest(
        ParsedSession(
            session=Session(id="s-meta", harness="kiro"), events=events, adapter_version="kiro@1"
        )
    )
    store.ingest(
        ParsedSession(
            session=Session(id="s-meta", harness="kiro", project="studyloop", outcome="resolved"),
            events=events,
            adapter_version="kiro@2",
            classifier_version="archive-classifier@1",
        )
    )
    assert store.row_counts()["sessions"] == 1
    row = store.connection.execute(
        "SELECT project, outcome, adapter_version, classifier_version"
        " FROM sessions WHERE id = 's-meta'"
    ).fetchone()
    assert row["project"] == "studyloop"
    assert row["outcome"] == "resolved"
    assert row["adapter_version"] == "kiro@2"
    assert row["classifier_version"] == "archive-classifier@1"


def test_a_bad_event_rolls_back_the_whole_ingest(store: Store) -> None:
    """One transaction means one transaction: a rejected event takes the session with it."""
    parsed = ParsedSession(
        session=Session(id="s-bad", harness="kiro"),
        events=[
            Event(turn_id=0, seq=0, kind="user", text="a real question?"),
            Event(turn_id=0, seq=1, kind=cast("EventKind", "not_a_kind"), text="bogus"),
        ],
        adapter_version="kiro@1",
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.ingest(parsed)
    counts = store.row_counts()
    assert counts["sessions"] == 0
    assert counts["events"] == 0
    assert counts["evidence"] == 0


def test_foreign_keys_are_enforced(store: Store) -> None:
    """PRAGMA foreign_keys is per-connection and off by default; prove it is on.

    It is also what makes the DEFERRED FK on claim_citations a constraint at all.
    """
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        store.connection.execute(
            "INSERT INTO events(session_id, turn_id, seq, kind, text, content_hash)"
            " VALUES ('s-nonexistent', 0, 0, 'user', 'orphan', 'deadbeef')"
        )
