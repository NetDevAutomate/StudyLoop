"""D2: evidence is append-only.

Council reproduction D2: ``UPDATE evidence SET body='tampered'`` succeeded after a
claim cited that row, and the citation survived — so every bound-proof was a
statement about the past, not the present. Mutable evidence makes the whole
provenance chain decorative.

The fix is unconditional: BEFORE UPDATE and BEFORE DELETE both abort, cited or not.
A re-capture is a new row with a new id, which is why nothing needs to mutate.
"""

from __future__ import annotations

import sqlite3

import pytest
from hypothesis import given
from hypothesis import strategies as st

from learning_memory import Event, ParsedSession, Session, Store

EVIDENCE_COLUMNS = ("body", "body_sha256", "origin", "basis", "captured_at", "event_id", "raw")


def _seed_cited_evidence(store: Store) -> tuple[str, str]:
    """One session, one prose event, one claim citing it. Returns (evidence_id, claim_id)."""
    store.ingest(
        ParsedSession(
            session=Session(id="s-1", harness="kiro"),
            events=[
                Event(
                    turn_id=0,
                    seq=0,
                    kind="user",
                    text="the keyword path scored 0.107 macro recall@5 on gold v2",
                    actor="user",
                )
            ],
            adapter_version="kiro@1",
        )
    )
    evidence = store.visible_evidence("s-1")[0]["id"]
    claim = store.add_claim(
        "s-1",
        "Finding",
        "Recall was the failing layer",
        "Macro recall@5 was 0.107 on the blind gold set.",
        ("retrieval", "gold-v2"),
        0.9,
        "test-writer",
        [{"evidence_id": evidence, "quote": "0.107 macro recall@5"}],
    )
    return evidence, claim


def test_update_of_cited_evidence_is_refused(store: Store) -> None:
    """The exact D2 probe."""
    evidence, claim = _seed_cited_evidence(store)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.connection.execute("UPDATE evidence SET body = 'tampered' WHERE id = ?", (evidence,))
    body = store.connection.execute(
        "SELECT body FROM evidence WHERE id = ?", (evidence,)
    ).fetchone()["body"]
    assert "tampered" not in body
    assert store.claim_citations(claim)[0]["quote"] == "0.107 macro recall@5"


def test_delete_of_cited_evidence_is_refused(store: Store) -> None:
    evidence, _ = _seed_cited_evidence(store)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.connection.execute("DELETE FROM evidence WHERE id = ?", (evidence,))
    assert store.row_counts()["evidence"] == 1


@given(column=st.sampled_from(EVIDENCE_COLUMNS))
def test_no_column_of_evidence_can_be_updated(column: str) -> None:
    """Unconditional: not "only the body", and not "only when cited"."""
    from learning_memory import Store as _Store

    store = _Store.connect(":memory:")
    store.install()
    try:
        _seed_cited_evidence(store)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            store.connection.execute(f'UPDATE evidence SET "{column}" = NULL')
    finally:
        store.close()


def test_uncited_evidence_is_equally_immutable(store: Store) -> None:
    store.ingest(
        ParsedSession(
            session=Session(id="s-2", harness="kiro"),
            events=[Event(turn_id=0, seq=0, kind="user", text="nobody cites me", actor="user")],
            adapter_version="kiro@1",
        )
    )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.connection.execute("UPDATE evidence SET body = 'x'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.connection.execute("DELETE FROM evidence")


def test_reingest_is_unaffected_by_the_immutability_triggers(store: Store) -> None:
    """The store's own writes are inserts with ON CONFLICT DO NOTHING, never updates."""
    parsed = ParsedSession(
        session=Session(id="s-3", harness="kiro"),
        events=[Event(turn_id=0, seq=0, kind="user", text="a question?", actor="user")],
        native_source=b"native bytes",
        adapter_version="kiro@1",
    )
    store.ingest(parsed)
    before = store.row_counts()
    second = store.ingest(parsed)
    assert second.evidence_inserted == 0
    assert second.evidence_skipped == 2, "one per-event row + one capture row, both already there"
    assert store.row_counts() == before
