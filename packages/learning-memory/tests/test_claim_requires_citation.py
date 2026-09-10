"""D3: a claim cannot exist without a citation, and the database is what says so.

Council reproduction D3: ``add_claim(..., citations=())`` inserted a claim with zero
citations — an unprovable assertion in a store whose entire premise is that every
claim carries its proof.

Two layers, because one is not enough: ``add_claim`` refuses an empty citation set,
and the database refuses a citation-less claim however it is written. The DB half
only works because ``claim_citations.claim_id`` is ``DEFERRABLE INITIALLY DEFERRED``
and the store writes citations FIRST, so the ``AFTER INSERT`` trigger on ``claims``
can see them.
"""

from __future__ import annotations

import sqlite3

import pytest

from learning_memory import ClaimValidationError, Event, ParsedSession, Session, Store

TAGS = ("retrieval", "provenance")


def seed(store: Store, session_id: str = "s-1") -> str:
    store.ingest(
        ParsedSession(
            session=Session(id=session_id, harness="kiro"),
            events=[
                Event(
                    turn_id=0,
                    seq=0,
                    kind="user",
                    text="the keyword path scored 0.107 macro recall@5",
                    actor="user",
                )
            ],
            adapter_version="kiro@1",
        )
    )
    return store.visible_evidence(session_id)[0]["id"]


def test_add_claim_refuses_an_empty_citation_sequence(store: Store) -> None:
    """Layer one: the exact D3 probe."""
    seed(store)
    with pytest.raises(ClaimValidationError, match="at least one citation"):
        store.add_claim(
            "s-1",
            "Finding",
            "unproven",
            "Nothing backs this up.",
            TAGS,
            0.8,
            "test-writer",
            (),
        )
    counts = store.row_counts()
    assert (counts["claims"], counts["claim_citations"]) == (0, 0)


def test_add_claim_refuses_a_default_empty_citation_argument(store: Store) -> None:
    seed(store)
    with pytest.raises(ClaimValidationError, match="at least one citation"):
        store.add_claim("s-1", "Finding", "unproven", "Nothing.", TAGS, 0.8, "test-writer")
    assert store.row_counts()["claims"] == 0


def test_database_refuses_a_citation_less_claim_written_raw(store: Store) -> None:
    """Layer two: the trigger, exercised through Store.connection.

    This is the layer that matters for Stage E, where a model-driven writer may not
    go through ``add_claim`` at all.
    """
    seed(store)
    with pytest.raises(sqlite3.IntegrityError, match="no citation"):
        store.connection.execute(
            "INSERT INTO claims(id, session_id, kind, title, statement, tags, confidence,"
            " writer, created_at)"
            " VALUES ('raw-1', 's-1', 'Finding', 't', 's', '[\"a\",\"b\"]', 0.8,"
            " 'raw-writer', '2026-09-10T00:00:00+00:00')"
        )
    assert store.row_counts()["claims"] == 0


def test_citations_first_commits(store: Store) -> None:
    """The write order the deferred FK exists for, end to end through add_claim."""
    evidence = seed(store)
    claim = store.add_claim(
        "s-1",
        "Finding",
        "Recall was the failing layer",
        "Macro recall@5 was 0.107.",
        TAGS,
        0.9,
        "test-writer",
        [{"evidence_id": evidence, "quote": "0.107 macro recall@5"}],
    )
    counts = store.row_counts()
    assert (counts["claims"], counts["claim_citations"]) == (1, 1)
    assert store.claim_citations(claim)[0]["evidence_id"] == evidence


def test_citations_first_is_the_actual_write_order(store: Store) -> None:
    """Prove the order rather than assuming it: a raw citation-then-claim pair commits."""
    evidence = seed(store)
    body = store.visible_evidence("s-1")[0]["body"]
    quote = "0.107 macro recall@5"
    start = body.find(quote)
    conn = store.connection
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        'INSERT INTO claim_citations(claim_id, evidence_id, "start", "end", quote)'
        " VALUES ('raw-2', ?, ?, ?, ?)",
        (evidence, start, start + len(quote), quote),
    )
    conn.execute(
        "INSERT INTO claims(id, session_id, kind, title, statement, tags, confidence,"
        " writer, created_at)"
        " VALUES ('raw-2', 's-1', 'Finding', 't', 's', '[\"a\",\"b\"]', 0.8,"
        " 'raw-writer', '2026-09-10T00:00:00+00:00')"
    )
    conn.execute("COMMIT")
    assert store.row_counts()["claims"] == 1


def test_orphan_citation_is_refused_at_commit(store: Store) -> None:
    """The deferred FK's other edge: a citation whose claim never arrives.

    A failed COMMIT leaves the transaction open in SQLite, so the rollback here is
    part of the contract being tested -- ``Store._commit`` does the same.
    """
    evidence = seed(store)
    body = store.visible_evidence("s-1")[0]["body"]
    quote = "0.107 macro recall@5"
    start = body.find(quote)
    conn = store.connection
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        'INSERT INTO claim_citations(claim_id, evidence_id, "start", "end", quote)'
        " VALUES ('never-arrives', ?, ?, ?, ?)",
        (evidence, start, start + len(quote), quote),
    )
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        conn.execute("COMMIT")
    conn.execute("ROLLBACK")
    counts = store.row_counts()
    assert (counts["claims"], counts["claim_citations"]) == (0, 0)


def test_store_commit_recovers_from_a_deferred_failure(store: Store) -> None:
    """After a rejected orphan, the store is still usable -- not stuck in a doomed txn."""
    evidence = seed(store)
    conn = store.connection
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        'INSERT INTO claim_citations(claim_id, evidence_id, "start", "end", quote)'
        " VALUES ('ghost', ?, 0, 3, ?)",
        (evidence, store.visible_evidence("s-1")[0]["body"][:3]),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("COMMIT")
    conn.execute("ROLLBACK")

    claim = store.add_claim(
        "s-1",
        "Finding",
        "still working",
        "The connection recovered.",
        TAGS,
        0.8,
        "test-writer",
        [{"evidence_id": evidence, "quote": "0.107 macro recall@5"}],
    )
    assert store.claim_citations(claim)
