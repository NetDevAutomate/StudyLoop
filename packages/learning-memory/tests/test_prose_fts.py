"""prose_fts indexes prose only.

53 % of the legacy store's ``assistant`` rows were tool echoes, and indexing them
is what let a search for a concept return the transcript of a tool that merely
mentioned it. Here the FTS index has exactly two writers -- the triggers -- and
they only fire for ``user`` and ``assistant_prose``.
"""

from __future__ import annotations

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
            native_source=b"native transcript",
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


def test_index_row_count_equals_prose_event_count(store: Store) -> None:
    """Count the FTS index itself, not the content table.

    ``SELECT count(*) FROM prose_fts`` would scan ``events`` (external content) and
    report 7. ``prose_fts_docsize`` is FTS5's shadow table of indexed documents, so
    it answers the question actually being asked: how many rows are IN the index.
    """
    _ingest_mixed(store)
    indexed = store.connection.execute("SELECT count(*) AS n FROM prose_fts_docsize").fetchone()
    prose_events = store.connection.execute(
        "SELECT count(*) AS n FROM events WHERE kind IN ('user', 'assistant_prose')"
    ).fetchone()
    total_events = store.connection.execute("SELECT count(*) AS n FROM events").fetchone()
    assert indexed["n"] == prose_events["n"] == 2
    assert total_events["n"] == 7


@given(kind=st.sampled_from(NON_PROSE), token=st.sampled_from(["alpha7", "beta8", "gamma9"]))
def test_no_non_prose_kind_ever_reaches_the_index(kind: EventKind, token: str) -> None:
    with fresh_store() as store:
        store.ingest(
            ParsedSession(
                session=Session(id="s-x", harness="kiro"),
                events=[Event(turn_id=0, seq=0, kind=kind, text=f"payload {token}")],
                native_source=b"native bytes",
            )
        )
        assert store.search_prose(token) == []


@given(kind=st.sampled_from(PROSE_ONLY), token=st.sampled_from(["alpha7", "beta8", "gamma9"]))
def test_every_prose_kind_reaches_the_index(kind: EventKind, token: str) -> None:
    with fresh_store() as store:
        store.ingest(
            ParsedSession(
                session=Session(id="s-x", harness="kiro"),
                events=[Event(turn_id=0, seq=0, kind=kind, text=f"payload {token}")],
                native_source=b"native bytes",
            )
        )
        assert len(store.search_prose(token)) == 1


def test_deleting_a_prose_event_removes_it_from_the_index(store: Store) -> None:
    _ingest_mixed(store)
    store.connection.execute("DELETE FROM events WHERE kind = 'user'")
    assert len(store.search_prose(PROSE_TOKEN)) == 1


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
    events = [Event(turn_id=0, seq=0, kind="user", text="the gates were failing repeatedly")]
    parsed = ParsedSession(
        session=Session(id="s-tok", harness="kiro"),
        events=events,
        native_source=b"native bytes",
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
