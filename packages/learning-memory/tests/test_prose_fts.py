"""prose_fts indexes prose only — including under FTS5's own maintenance commands.

53 % of the legacy store's ``assistant`` rows were tool echoes, and indexing them is
what let a search for a concept return the transcript of a tool that merely mentioned
it.

D4 (council reproduction): with the index's content pointed at ``events``,
``INSERT INTO prose_fts(prose_fts) VALUES ('rebuild')`` re-read every row and pulled
tool output in (0 → 1 hits) — the trigger filter was bypassed by a command FTS5
offers as routine maintenance. The content source is now the ``prose_events`` VIEW,
so the filter is in the data FTS5 reads, not only in the triggers that feed it.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from learning_memory import (
    Event,
    EventKind,
    ParsedSession,
    SchemaError,
    Session,
    Store,
    Tokenizer,
    ddl,
)

if TYPE_CHECKING:
    from pathlib import Path

try:  # package-scoped run (pytest "prepend" import mode)
    from _helpers import NON_PROSE, PROSE_ONLY, fresh_store
except ImportError:  # workspace-root run (pytest "importlib" import mode)
    from tests._helpers import NON_PROSE, PROSE_ONLY, fresh_store

TOOL_TOKEN = "zzqqtoolonly"
PROSE_TOKEN = "zzqqproseonly"


def _ingest_mixed(store: Store) -> None:
    store.ingest(
        ParsedSession(
            session=Session(id="s-fts", harness="kiro"),
            events=[
                Event(turn_id=0, seq=0, kind="user", text=f"why does {PROSE_TOKEN} happen?"),
                Event(turn_id=0, seq=1, kind="tool_call", text=f"grep {TOOL_TOKEN}"),
                Event(turn_id=0, seq=2, kind="tool_result", text=f"stdout: {TOOL_TOKEN} found"),
                Event(turn_id=0, seq=3, kind="thinking", text=f"maybe {TOOL_TOKEN}"),
                Event(turn_id=0, seq=4, kind="error", text=f"boom {TOOL_TOKEN}"),
                Event(turn_id=0, seq=5, kind="system", text=f"prompt {TOOL_TOKEN}"),
                Event(turn_id=1, seq=6, kind="assistant_prose", text=f"because {PROSE_TOKEN}"),
            ],
            adapter_version="kiro@1",
        )
    )


def test_tool_text_is_not_searchable(store: Store) -> None:
    _ingest_mixed(store)
    assert store.search_prose(TOOL_TOKEN) == []


def test_prose_text_is_searchable(store: Store) -> None:
    _ingest_mixed(store)
    hits = store.search_prose(PROSE_TOKEN)
    assert {hit["kind"] for hit in hits} == {"user", "assistant_prose"}
    assert len(hits) == 2


def test_rebuild_keeps_the_index_prose_only(store: Store) -> None:
    """D4 flip: this rebuild used to pull tool output into the index."""
    _ingest_mixed(store)
    before = len(store.search_prose(PROSE_TOKEN))

    store.connection.execute("INSERT INTO prose_fts(prose_fts) VALUES ('rebuild')")

    assert store.search_prose(TOOL_TOKEN) == [], "rebuild must not index tool text"
    assert store.search_prose_raw(TOOL_TOKEN) == []
    assert len(store.search_prose(PROSE_TOKEN)) == before, "prose hits unchanged"
    indexed = store.connection.execute("SELECT count(*) AS n FROM prose_fts_docsize").fetchone()
    assert indexed["n"] == 2


def test_integrity_check_passes_after_rebuild(store: Store) -> None:
    """If the triggers and the VIEW disagreed, FTS5 itself would say so here."""
    _ingest_mixed(store)
    store.connection.execute("INSERT INTO prose_fts(prose_fts) VALUES ('integrity-check')")
    store.connection.execute("INSERT INTO prose_fts(prose_fts) VALUES ('rebuild')")
    store.connection.execute("INSERT INTO prose_fts(prose_fts) VALUES ('integrity-check')")


def test_prose_events_view_is_the_content_source(store: Store) -> None:
    """The filter lives in the data FTS5 reads, not only in the triggers."""
    _ingest_mixed(store)
    view_rows = store.connection.execute("SELECT count(*) AS n FROM prose_events").fetchone()
    all_rows = store.connection.execute("SELECT count(*) AS n FROM events").fetchone()
    assert (view_rows["n"], all_rows["n"]) == (2, 7)
    sql = store.connection.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'prose_fts'"
    ).fetchone()["sql"]
    assert "content='prose_events'" in sql


def test_index_row_count_equals_prose_event_count(store: Store) -> None:
    """Count the FTS index itself, not the content source.

    ``prose_fts_docsize`` is FTS5's shadow table of indexed documents, so it answers
    the question actually being asked: how many rows are IN the index.
    """
    _ingest_mixed(store)
    indexed = store.connection.execute("SELECT count(*) AS n FROM prose_fts_docsize").fetchone()
    assert indexed["n"] == 2


@given(kind=st.sampled_from(NON_PROSE), token=st.sampled_from(["alpha7", "beta8", "gamma9"]))
def test_no_non_prose_kind_ever_reaches_the_index(kind: EventKind, token: str) -> None:
    with fresh_store() as store:
        store.ingest(
            ParsedSession(
                session=Session(id="s-x", harness="kiro"),
                events=[
                    Event(turn_id=0, seq=0, kind="user", text="a citable question?"),
                    Event(turn_id=0, seq=1, kind=kind, text=f"payload {token}"),
                ],
                adapter_version="kiro@1",
            )
        )
        assert store.search_prose(token) == []
        store.connection.execute("INSERT INTO prose_fts(prose_fts) VALUES ('rebuild')")
        assert store.search_prose(token) == [], "still absent after a rebuild"


@given(kind=st.sampled_from(PROSE_ONLY), token=st.sampled_from(["alpha7", "beta8", "gamma9"]))
def test_every_prose_kind_reaches_the_index(kind: EventKind, token: str) -> None:
    with fresh_store() as store:
        store.ingest(
            ParsedSession(
                session=Session(id="s-x", harness="kiro"),
                events=[Event(turn_id=0, seq=0, kind=kind, text=f"payload {token}")],
                adapter_version="kiro@1",
            )
        )
        assert len(store.search_prose(token)) == 1


def test_a_prose_event_with_evidence_cannot_be_deleted(store: Store) -> None:
    """A consequence worth pinning: the citation surface makes prose events durable.

    ``evidence.event_id`` is a real FK and evidence itself is append-only, so a prose
    event that produced a citable row cannot be removed at all. The FTS delete
    trigger below is therefore defensive rather than routine.
    """
    _ingest_mixed(store)
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        store.connection.execute("DELETE FROM events WHERE kind = 'user'")


def test_deleting_a_prose_event_removes_it_from_the_index(store: Store) -> None:
    """Exercised through the one deletable prose event: a duplicate-text second copy.

    Two events with identical text share one content-addressed evidence row, which
    names the first, so the second carries no FK reference and can be deleted.
    """
    token = "zzqqsharedtoken"
    store.ingest(
        ParsedSession(
            session=Session(id="s-del", harness="kiro"),
            events=[
                Event(turn_id=0, seq=0, kind="user", text=f"{token} asked once", actor="user"),
                Event(turn_id=1, seq=1, kind="user", text=f"{token} asked once", actor="user"),
            ],
            adapter_version="kiro@1",
        )
    )
    assert len(store.search_prose(token)) == 2

    store.connection.execute("DELETE FROM events WHERE session_id = 's-del' AND seq = 1")

    assert len(store.search_prose(token)) == 1
    store.connection.execute("INSERT INTO prose_fts(prose_fts) VALUES ('integrity-check')")


# ------------------------------------------------------- tokenizer is a parameter


def test_alternative_tokenizer_installs_and_searches() -> None:
    with fresh_store(tokenizer="unicode61") as store:
        assert store.tokenizer == "unicode61"
        _ingest_mixed(store)
        assert len(store.search_prose(PROSE_TOKEN)) == 2
        row = store.connection.execute("SELECT tokenizer FROM schema_version").fetchone()
        assert row["tokenizer"] == "unicode61"


def test_porter_stems_where_unicode61_does_not() -> None:
    """The two tokenizers are measurably different, which is why it is a parameter."""
    parsed = ParsedSession(
        session=Session(id="s-tok", harness="kiro"),
        events=[Event(turn_id=0, seq=0, kind="user", text="the gates were failing repeatedly")],
        adapter_version="kiro@1",
    )
    with fresh_store(tokenizer="porter unicode61") as porter:
        porter.ingest(parsed)
        assert len(porter.search_prose("fail")) == 1
    with fresh_store(tokenizer="unicode61") as plain:
        plain.ingest(parsed)
        assert plain.search_prose("fail") == []


def test_unknown_tokenizer_is_refused() -> None:
    """The allowlist is a security boundary: the value is interpolated into DDL."""
    with pytest.raises(ValueError, match="unsupported tokenizer"):
        ddl(cast("Tokenizer", "porter unicode61; DROP TABLE claims"))


def test_reopening_with_a_different_tokenizer_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "lm.db"
    first = Store.connect(path, tokenizer="porter unicode61")
    first.install()
    first.close()

    second = Store.connect(path, tokenizer="unicode61")
    try:
        with pytest.raises(SchemaError, match="tokenizer"):
            second.install()
    finally:
        second.close()
