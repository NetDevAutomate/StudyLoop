"""Invariant (b): no session row without at least one evidence row.

A session with no evidence is a session whose claims could never be proved. The
store refuses it rather than storing an unprovable shell, and the refusal rolls
back the whole transaction -- so a failed ingest leaves nothing at all behind.
"""

from __future__ import annotations

import hashlib

import pytest
from hypothesis import given

from learning_memory import Event, NoEvidenceError, ParsedSession, Session, Store

try:  # package-scoped run (pytest "prepend" import mode)
    from _helpers import evidence_free_sessions, fresh_store
except ImportError:  # workspace-root run (pytest "importlib" import mode)
    from tests._helpers import evidence_free_sessions, fresh_store


@given(parsed=evidence_free_sessions())
def test_session_without_evidence_or_prose_is_rejected(parsed: ParsedSession) -> None:
    with fresh_store() as store:
        with pytest.raises(NoEvidenceError):
            store.ingest(parsed)

        counts = store.row_counts()
        assert counts["sessions"] == 0, "the rolled-back session must not survive"
        assert counts["events"] == 0
        assert counts["evidence"] == 0


@given(parsed=evidence_free_sessions())
def test_rejection_does_not_disturb_existing_rows(parsed: ParsedSession) -> None:
    """A bad ingest must not damage a session that was already stored."""
    with fresh_store() as store:
        good = ParsedSession(
            session=Session(id="s-good", harness="kiro"),
            events=[Event(turn_id=0, seq=0, kind="user", text="what broke?", actor="user")],
            native_source=b"native transcript bytes",
        )
        store.ingest(good)
        before = store.row_counts()

        with pytest.raises(NoEvidenceError):
            store.ingest(parsed)

        assert store.row_counts() == before


def test_observed_basis_without_native_bytes_is_rejected(store: Store) -> None:
    """OBSERVED means "we hold the original". No bytes, no OBSERVED evidence."""
    parsed = ParsedSession(
        session=Session(id="s-claims-observed", harness="kiro"),
        events=[Event(turn_id=0, seq=0, kind="user", text="plenty of prose here", actor="user")],
        native_source=None,
        evidence_basis="OBSERVED",
    )
    with pytest.raises(NoEvidenceError):
        store.ingest(parsed)
    assert store.row_counts()["sessions"] == 0


def test_reported_basis_synthesises_evidence_from_prose(store: Store) -> None:
    """The archive path: prose we already hold becomes evidence labelled 'archive'."""
    parsed = ParsedSession(
        session=Session(id="s-archive", harness="archive"),
        events=[
            Event(turn_id=0, seq=0, kind="user", text="why is recall so low?", actor="user"),
            Event(turn_id=0, seq=1, kind="tool_result", text="EXCLUDED TOOL ECHO", actor="tool"),
            Event(turn_id=0, seq=2, kind="assistant_prose", text="because of dedupe"),
        ],
        native_source=None,
        evidence_basis="REPORTED",
    )
    result = store.ingest(parsed)
    assert result.evidence_inserted == 1

    visible = store.visible_evidence("s-archive")
    assert len(visible) == 1
    body = visible[0]["body"]
    assert "why is recall so low?" in body
    assert "because of dedupe" in body
    assert "EXCLUDED TOOL ECHO" not in body, "tool text is not prose and is not evidence body"

    row = store.connection.execute(
        "SELECT origin, basis FROM evidence WHERE session_id = 's-archive'"
    ).fetchone()
    assert (row["origin"], row["basis"]) == ("archive", "REPORTED")


def test_reported_basis_with_only_whitespace_prose_is_rejected(store: Store) -> None:
    parsed = ParsedSession(
        session=Session(id="s-blank", harness="archive"),
        events=[Event(turn_id=0, seq=0, kind="user", text="   \n\t ", actor="user")],
        native_source=None,
        evidence_basis="REPORTED",
    )
    with pytest.raises(NoEvidenceError):
        store.ingest(parsed)
    assert store.row_counts()["sessions"] == 0


def test_observed_evidence_hash_is_over_native_bytes(store: Store) -> None:
    """``body_sha256`` records what was captured, not a re-encoding of the body."""
    native = "native transcript with 日本語".encode()
    store.ingest(
        ParsedSession(
            session=Session(id="s-native", harness="kiro"),
            events=[Event(turn_id=0, seq=0, kind="user", text="hi", actor="user")],
            native_source=native,
            evidence_basis="OBSERVED",
        )
    )
    row = store.connection.execute(
        "SELECT body, body_sha256, origin FROM evidence WHERE session_id = 's-native'"
    ).fetchone()
    assert row["body_sha256"] == hashlib.sha256(native).hexdigest()
    assert row["body"] == native.decode()
    assert row["origin"] == "native"
