"""Invariant (d): claims never change.

A claim is a dated assertion with a quote behind it. Editing one in place would
silently rewrite history that receipts already point at, so the only legal
"change" is a new claim whose ``supersedes`` names the old one.
"""

from __future__ import annotations

import sqlite3

import pytest
from hypothesis import given
from hypothesis import strategies as st

from learning_memory import DuplicateClaimError, Event, ParsedSession, Session, Store

try:  # package-scoped run (pytest "prepend" import mode)
    from _helpers import fresh_store
except ImportError:  # workspace-root run (pytest "importlib" import mode)
    from tests._helpers import fresh_store

CLAIM_COLUMNS = (
    "kind",
    "title",
    "statement",
    "tags",
    "confidence",
    "writer",
    "created_at",
    "supersedes",
    "session_id",
    "id",
)


def _seed_claim(store: Store, title: str = "Recall was the failing layer") -> tuple[str, str]:
    body = "the keyword path scored 0.107 macro recall@5 on gold v2"
    store.ingest(
        ParsedSession(
            session=Session(id="s-1", harness="kiro"),
            # v1.1: the citation surface is the prose EVENT, so the body under test
            # is an event's text rather than a native transcript.
            events=[Event(turn_id=0, seq=0, kind="user", text=body, actor="user")],
            adapter_version="kiro@1",
        )
    )
    evidence = store.visible_evidence("s-1")[0]["id"]
    claim = store.add_claim(
        "s-1",
        "Finding",
        title,
        "Macro recall@5 was 0.107 on the blind gold set.",
        ("retrieval", "gold-v2"),
        0.9,
        "test-writer",
        [{"evidence_id": evidence, "quote": "0.107 macro recall@5"}],
    )
    return claim, evidence


@given(column=st.sampled_from(CLAIM_COLUMNS))
def test_update_on_claims_always_raises(column: str) -> None:
    with fresh_store() as store:
        claim, _ = _seed_claim(store)
        with pytest.raises(sqlite3.IntegrityError, match="claims are immutable"):
            store.connection.execute(f'UPDATE claims SET "{column}" = NULL WHERE id = ?', (claim,))
        row = store.connection.execute(
            "SELECT title, statement, confidence FROM claims WHERE id = ?", (claim,)
        ).fetchone()
        assert row["title"] == "Recall was the failing layer"
        assert row["confidence"] == 0.9


def test_update_of_every_row_at_once_still_raises(store: Store) -> None:
    _seed_claim(store)
    with pytest.raises(sqlite3.IntegrityError, match="claims are immutable"):
        store.connection.execute("UPDATE claims SET confidence = 1.0")
    assert store.connection.execute("SELECT confidence FROM claims").fetchone()[0] == 0.9


def test_superseding_is_the_supported_correction(store: Store) -> None:
    original, evidence = _seed_claim(store)
    corrected = store.add_claim(
        "s-1",
        "Finding",
        "Recall was the failing layer (corrected)",
        "Macro recall@5 was 0.107, measured on gold v2 rather than v1.",
        ("retrieval", "gold-v2", "correction"),
        0.95,
        "test-writer",
        [{"evidence_id": evidence, "quote": "gold v2"}],
        supersedes=original,
    )
    row = store.connection.execute(
        "SELECT supersedes FROM claims WHERE id = ?", (corrected,)
    ).fetchone()
    assert row["supersedes"] == original
    assert store.row_counts()["claims"] == 2


def test_adding_the_identical_claim_twice_is_refused(store: Store) -> None:
    """Claim ids are content addresses, so a re-run cannot fork the same assertion."""
    _seed_claim(store)
    with pytest.raises(DuplicateClaimError):
        _seed_claim(store)
    assert store.row_counts()["claims"] == 1


def test_citation_rebinding_is_also_refused(store: Store) -> None:
    """The UPDATE path is guarded too, or an unbound quote could be laundered in."""
    claim, evidence = _seed_claim(store)
    with pytest.raises(sqlite3.IntegrityError, match="citation does not bind"):
        store.connection.execute(
            'UPDATE claim_citations SET "start" = "start" + 1, "end" = "end" + 1 '
            "WHERE claim_id = ?",
            (claim,),
        )
    assert store.claim_citations(claim)[0]["quote"] == "0.107 macro recall@5"
    assert evidence
