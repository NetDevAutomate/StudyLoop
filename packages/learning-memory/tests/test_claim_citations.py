"""Invariant (c): a claim cannot exist with a citation that does not bind.

This is the invariant the whole design rests on. A claim is only worth serving if
its quote provably IS the text at the offsets it names, and that proof is enforced
by ``claim_citation_bound_proof`` in the database -- not by the writer's goodwill,
and not only by the Python resolver, which a future writer could bypass.

Offsets are **code points**. The tests below prove it by constructing the same
citation from byte and UTF-16 arithmetic (the two classic bugs) and showing the
database refuses both, while the code-point form binds.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from learning_memory import (
    CitationError,
    ClaimValidationError,
    Event,
    ParsedSession,
    Session,
    Store,
)

try:  # package-scoped run (pytest "prepend" import mode)
    from _helpers import fresh_store, text_strategy
except ImportError:  # workspace-root run (pytest "importlib" import mode)
    from tests._helpers import fresh_store, text_strategy

# Deliberately mixes ASCII, accented Latin, CJK and an astral ZWJ emoji sequence.
BODY = (
    "The gate failed because recall was low.\n"
    "Andy asked: pourquoi ça échoue ?\n"
    "日本語のテキストもここにある。\n"
    "family 👨\u200d👩\u200d👧 emoji sits before the ANCHOR token.\n"
    "repeated phrase, repeated phrase.\n"
)
TAGS = ("retrieval", "provenance")


def seed(store: Store, session_id: str = "s-1", body: str = BODY) -> str:
    """Ingest one session whose single prose event -- and so whose single evidence
    body -- is exactly ``body``.

    v1.1: the citation surface is the EVENT, so the text under test is an event's
    text rather than a native transcript. Native bytes now produce a separate
    capture row that is deliberately not a citation target.
    """
    store.ingest(
        ParsedSession(
            session=Session(id=session_id, harness="kiro"),
            events=[Event(turn_id=0, seq=0, kind="user", text=body, actor="user")],
            adapter_version="kiro@1",
        )
    )
    visible = store.visible_evidence(session_id)
    assert len(visible) == 1
    assert visible[0]["body"] == body
    return str(visible[0]["id"])


def add(
    store: Store,
    session_id: str,
    citations: list[dict[str, str]],
    title: str = "Recall was the failing layer",
) -> str:
    return store.add_claim(
        session_id,
        "Finding",
        title,
        "The keyword path scored 0.107 macro recall@5 on gold v2.",
        TAGS,
        0.8,
        "test-writer",
        citations,
    )


def counts(store: Store) -> tuple[int, int]:
    row_counts = store.row_counts()
    return row_counts["claims"], row_counts["claim_citations"]


# --------------------------------------------------------------- happy paths


def test_correct_quote_binds(store: Store) -> None:
    evidence = seed(store)
    claim = add(store, "s-1", [{"evidence_id": evidence, "quote": "recall was low"}])

    bound = store.claim_citations(claim)
    assert len(bound) == 1
    assert bound[0]["quote"] == "recall was low"
    assert BODY[bound[0]["start"] : bound[0]["end"]] == "recall was low"


@pytest.mark.parametrize(
    "quote",
    [
        "pourquoi ça échoue ?",
        "日本語のテキスト",
        "👨\u200d👩\u200d👧",
        # A single code point inside the ZWJ cluster. It binds, and it is meant
        # to: the guarantee is code-point exactness, not grapheme alignment.
        "👨",
        "ANCHOR",
    ],
)
def test_non_ascii_quotes_bind(store: Store, quote: str) -> None:
    evidence = seed(store)
    claim = add(store, "s-1", [{"evidence_id": evidence, "quote": quote}], title=f"q {quote[:20]}")
    bound = store.claim_citations(claim)
    assert BODY[bound[0]["start"] : bound[0]["end"]] == quote


def test_offsets_are_code_points_not_bytes_or_utf16(store: Store) -> None:
    """The proof that the offset unit is right: byte/UTF-16 forms are refused."""
    evidence = seed(store)
    quote = "ANCHOR"
    code_point_start = BODY.find(quote)
    byte_start = len(BODY[:code_point_start].encode("utf-8"))
    utf16_start = len(BODY[:code_point_start].encode("utf-16-le")) // 2
    assert byte_start > code_point_start, "fixture must contain multi-byte characters"
    assert utf16_start > code_point_start, "fixture must contain astral characters"

    claim = add(store, "s-1", [{"evidence_id": evidence, "quote": quote}])
    assert store.claim_citations(claim)[0]["start"] == code_point_start

    for wrong_start in (byte_start, utf16_start):
        with pytest.raises(sqlite3.IntegrityError, match="citation does not bind"):
            store.connection.execute(
                'INSERT INTO claim_citations(claim_id, evidence_id, "start", "end", quote)'
                " VALUES (?, ?, ?, ?, ?)",
                (claim, evidence, wrong_start, wrong_start + len(quote), quote),
            )


# ------------------------------------------------------------- rejection paths


def test_altered_quote_is_rejected(store: Store) -> None:
    """A quote that is not in the body -- the "paraphrased the evidence" case."""
    evidence = seed(store)
    with pytest.raises(CitationError) as err:
        add(store, "s-1", [{"evidence_id": evidence, "quote": "recall was terrible"}])
    assert [p.reason for p in err.value.problems] == ["quote_not_found"]
    assert counts(store) == (0, 0)


def test_altered_body_breaks_a_raw_citation(store: Store) -> None:
    """Even a real quote from a *different* body will not bind here."""
    evidence = seed(store)
    other = seed(store, session_id="s-2", body="a completely different transcript body")
    claim = add(store, "s-1", [{"evidence_id": evidence, "quote": "ANCHOR"}])

    with pytest.raises(sqlite3.IntegrityError, match="citation does not bind"):
        store.connection.execute(
            'INSERT INTO claim_citations(claim_id, evidence_id, "start", "end", quote)'
            " VALUES (?, ?, ?, ?, ?)",
            (claim, evidence, 0, 9, "different"),
        )
    assert other != evidence


def test_stale_offsets_are_rejected(store: Store) -> None:
    """The quote IS in the body, but not at the offsets claimed."""
    evidence = seed(store)
    claim = add(store, "s-1", [{"evidence_id": evidence, "quote": "ANCHOR"}])
    true_start = BODY.find("recall was low")
    quote = "recall was low"

    for wrong_start in (true_start - 1, true_start + 1, true_start + 5):
        with pytest.raises(sqlite3.IntegrityError, match="citation does not bind"):
            store.connection.execute(
                'INSERT INTO claim_citations(claim_id, evidence_id, "start", "end", quote)'
                " VALUES (?, ?, ?, ?, ?)",
                (claim, evidence, wrong_start, wrong_start + len(quote), quote),
            )
    assert counts(store) == (1, 1)


def test_offsets_cutting_a_multi_code_point_cluster_are_rejected(store: Store) -> None:
    """A citation may not span part of a ZWJ sequence and call it the whole thing."""
    evidence = seed(store)
    claim = add(store, "s-1", [{"evidence_id": evidence, "quote": "ANCHOR"}])
    family = "👨\u200d👩\u200d👧"
    start = BODY.find(family)

    truncated_extent = (start, start + 1, family)  # one code point, quotes five
    overlong_extent = (start, start + len(family), "👨")  # five code points, quotes one
    for begin, finish, quote in (truncated_extent, overlong_extent):
        with pytest.raises(sqlite3.IntegrityError, match="citation does not bind"):
            store.connection.execute(
                'INSERT INTO claim_citations(claim_id, evidence_id, "start", "end", quote)'
                " VALUES (?, ?, ?, ?, ?)",
                (claim, evidence, begin, finish, quote),
            )
    assert counts(store) == (1, 1)


def test_unknown_evidence_id_is_rejected(store: Store) -> None:
    seed(store)
    with pytest.raises(CitationError) as err:
        add(store, "s-1", [{"evidence_id": "0" * 64, "quote": "recall was low"}])
    assert [p.reason for p in err.value.problems] == ["unknown_evidence"]
    assert counts(store) == (0, 0)


def test_evidence_from_another_session_is_rejected(store: Store) -> None:
    """A claim may only cite its own session's evidence."""
    seed(store)
    foreign = seed(store, session_id="s-2", body="another session, with recall was low inside")
    with pytest.raises(CitationError) as err:
        add(store, "s-1", [{"evidence_id": foreign, "quote": "recall was low"}])
    assert [p.reason for p in err.value.problems] == ["foreign_evidence"]
    assert counts(store) == (0, 0)


def test_wrong_evidence_id_on_a_raw_citation_is_rejected(store: Store) -> None:
    evidence = seed(store)
    foreign = seed(store, session_id="s-2", body="another session body entirely")
    claim = add(store, "s-1", [{"evidence_id": evidence, "quote": "ANCHOR"}])
    start = BODY.find("ANCHOR")

    with pytest.raises(sqlite3.IntegrityError, match="citation does not bind"):
        store.connection.execute(
            'INSERT INTO claim_citations(claim_id, evidence_id, "start", "end", quote)'
            " VALUES (?, ?, ?, ?, ?)",
            (claim, foreign, start, start + 6, "ANCHOR"),
        )


def test_ambiguous_repeated_quote_is_rejected(store: Store) -> None:
    """Two occurrences means "the" offsets are a guess, so the citation is refused."""
    evidence = seed(store)
    with pytest.raises(CitationError) as err:
        add(store, "s-1", [{"evidence_id": evidence, "quote": "repeated phrase"}])
    problem = err.value.problems[0]
    assert problem.reason == "ambiguous_quote"
    assert "2 times" in problem.detail
    assert counts(store) == (0, 0)


def test_empty_quote_is_rejected(store: Store) -> None:
    """substr() of a zero-width extent equals '' and would bind vacuously."""
    evidence = seed(store)
    with pytest.raises(CitationError) as err:
        add(store, "s-1", [{"evidence_id": evidence, "quote": ""}])
    assert [p.reason for p in err.value.problems] == ["empty_quote"]
    assert counts(store) == (0, 0)


def test_zero_width_raw_citation_is_rejected_by_check_constraint(store: Store) -> None:
    evidence = seed(store)
    claim = add(store, "s-1", [{"evidence_id": evidence, "quote": "ANCHOR"}])
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute(
            'INSERT INTO claim_citations(claim_id, evidence_id, "start", "end", quote)'
            " VALUES (?, ?, ?, ?, ?)",
            (claim, evidence, 5, 5, ""),
        )


def test_one_bad_citation_writes_nothing_at_all(store: Store) -> None:
    """All-or-nothing: a good first citation must not survive a bad second one."""
    evidence = seed(store)
    with pytest.raises(CitationError) as err:
        add(
            store,
            "s-1",
            [
                {"evidence_id": evidence, "quote": "recall was low"},
                {"evidence_id": evidence, "quote": "never appears in the body"},
            ],
        )
    assert [p.reason for p in err.value.problems] == ["quote_not_found"]
    assert counts(store) == (0, 0)


def test_duplicate_citation_in_one_call_rolls_the_claim_back(store: Store) -> None:
    """The one failure that lands *after* the claim row: it must still leave nothing.

    Two identical citations collide on ``claim_citations``' primary key, which the
    database raises only once the claim row is already inside the transaction. This
    is the reachable proof that ``add_claim`` rolls back rather than half-committing.
    """
    evidence = seed(store)
    citation = {"evidence_id": evidence, "quote": "recall was low"}
    with pytest.raises(CitationError) as err:
        add(store, "s-1", [citation, dict(citation)])
    assert [p.reason for p in err.value.problems] == ["duplicate_citation"]
    assert counts(store) == (0, 0)


def test_every_bad_citation_is_reported_not_just_the_first(store: Store) -> None:
    evidence = seed(store)
    with pytest.raises(CitationError) as err:
        add(
            store,
            "s-1",
            [
                {"evidence_id": evidence, "quote": "nowhere to be found"},
                {"evidence_id": evidence, "quote": "repeated phrase"},
                {"evidence_id": "f" * 64, "quote": "recall was low"},
            ],
        )
    assert [p.reason for p in err.value.problems] == [
        "quote_not_found",
        "ambiguous_quote",
        "unknown_evidence",
    ]
    assert counts(store) == (0, 0)


def test_claim_field_contract_is_enforced(store: Store) -> None:
    evidence = seed(store)
    citation = [{"evidence_id": evidence, "quote": "ANCHOR"}]

    def attempt(**overrides: Any) -> None:
        fields: dict[str, Any] = {
            "kind": "Finding",
            "title": "a title",
            "statement": "a statement",
            "tags": TAGS,
            "confidence": 0.8,
            "writer": "test-writer",
        }
        fields.update(overrides)
        store.add_claim(
            "s-1",
            fields["kind"],
            fields["title"],
            fields["statement"],
            fields["tags"],
            fields["confidence"],
            fields["writer"],
            citation,
        )

    out_of_contract: list[dict[str, Any]] = [
        {"kind": "Rumour"},
        {"title": ""},
        {"title": "x" * 121},
        {"statement": ""},
        {"statement": "y" * 501},
        {"tags": ("only-one",)},
        {"tags": ("a", "b", "c", "d", "e", "f")},
        {"confidence": 0.49},
        {"confidence": 1.01},
        {"writer": ""},
    ]
    for override in out_of_contract:
        with pytest.raises(ClaimValidationError):
            attempt(**override)
    assert counts(store) == (0, 0)


def test_claim_field_contract_boundaries_are_inclusive(store: Store) -> None:
    """120/500/0.5/1.0 are legal; the CHECKs and the resolver must agree on that."""
    evidence = seed(store)
    citation = [{"evidence_id": evidence, "quote": "ANCHOR"}]
    for index, (title_len, statement_len, confidence) in enumerate([(120, 500, 0.5), (1, 1, 1.0)]):
        store.add_claim(
            "s-1",
            "Finding",
            "t" * title_len if title_len > 1 else f"t{index}",
            "s" * statement_len,
            TAGS,
            confidence,
            "test-writer",
            citation,
        )
    assert counts(store) == (2, 2)


def test_claim_on_unknown_session_is_rejected(store: Store) -> None:
    """A real citation, so the session check is what fires (not the citation check)."""
    evidence = seed(store)
    with pytest.raises(ClaimValidationError, match="unknown session"):
        add(store, "s-missing", [{"evidence_id": evidence, "quote": "ANCHOR"}])
    assert counts(store) == (0, 0)


# ------------------------------------------- the schema enforces it too, not just Python

RAW_CLAIM = (
    "INSERT INTO claims(id, session_id, kind, title, statement, tags,"
    " confidence, writer, created_at)"
    " VALUES (?, 's-1', ?, ?, ?, ?, ?, 'raw-writer', '2026-09-10T00:00:00+00:00')"
)


@pytest.mark.parametrize(
    ("label", "kind", "title", "statement", "tags", "confidence"),
    [
        ("bad kind", "Rumour", "t", "s", '["a","b"]', 0.8),
        ("empty title", "Finding", "", "s", '["a","b"]', 0.8),
        ("title too long", "Finding", "t" * 121, "s", '["a","b"]', 0.8),
        ("empty statement", "Finding", "t", "", '["a","b"]', 0.8),
        ("statement too long", "Finding", "t", "s" * 501, '["a","b"]', 0.8),
        ("one tag", "Finding", "t", "s", '["a"]', 0.8),
        ("six tags", "Finding", "t", "s", '["a","b","c","d","e","f"]', 0.8),
        ("tags not json", "Finding", "t", "s", "a,b", 0.8),
        ("tags not an array", "Finding", "t", "s", '{"a":1}', 0.8),
        ("confidence too low", "Finding", "t", "s", '["a","b"]', 0.49),
        ("confidence too high", "Finding", "t", "s", '["a","b"]', 1.01),
    ],
)
def test_schema_checks_refuse_out_of_contract_claims(
    store: Store,
    label: str,
    kind: str,
    title: str,
    statement: str,
    tags: str,
    confidence: float,
) -> None:
    """A raw writer that bypasses ``add_claim`` still cannot store a bad claim."""
    seed(store)
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute(
            RAW_CLAIM, (f"raw-{label}", kind, title, statement, tags, confidence)
        )
    assert counts(store) == (0, 0)


def test_schema_accepts_a_contract_abiding_raw_claim(store: Store) -> None:
    """The negative cases above are only meaningful if the positive one passes.

    v1.1: the positive case now has to write its citation FIRST -- a raw claim with
    no citation is refused by ``claims_need_citation`` (council finding 1), so this
    test doubles as the raw-writer proof that the deferred FK ordering works.
    """
    evidence = seed(store)
    quote = "ANCHOR"
    start = BODY.find(quote)
    store.connection.execute("BEGIN IMMEDIATE")
    store.connection.execute(
        'INSERT INTO claim_citations(claim_id, evidence_id, "start", "end", quote)'
        " VALUES ('raw-ok', ?, ?, ?, ?)",
        (evidence, start, start + len(quote), quote),
    )
    store.connection.execute(RAW_CLAIM, ("raw-ok", "Finding", "t", "s", '["a","b"]', 0.5))
    store.connection.execute("COMMIT")
    assert counts(store) == (1, 1)


def test_supersedes_must_name_a_real_claim(store: Store) -> None:
    """Superseding is the only correction path, so a dangling supersedes is refused."""
    evidence = seed(store)
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        store.add_claim(
            "s-1",
            "Finding",
            "supersedes a ghost",
            "This claim points at a claim that does not exist.",
            TAGS,
            0.8,
            "test-writer",
            [{"evidence_id": evidence, "quote": "ANCHOR"}],
            supersedes="no-such-claim",
        )
    assert counts(store) == (0, 0)


# ----------------------------------------------------------------- properties


@given(data=st.data(), body=text_strategy)
def test_unique_substring_always_binds(data: st.DataObject, body: str) -> None:
    """Any unique substring of any body resolves to offsets the database accepts."""
    start = data.draw(st.integers(min_value=0, max_value=max(0, len(body) - 1)))
    end = data.draw(st.integers(min_value=start + 1, max_value=len(body)))
    quote = body[start:end]
    assume(body.count(quote) == 1)

    with fresh_store() as store:
        evidence = seed(store, body=body)
        claim = add(store, "s-1", [{"evidence_id": evidence, "quote": quote}])
        bound = store.claim_citations(claim)[0]
        assert body[bound["start"] : bound["end"]] == quote
        # And the database agrees, using its own substr() rather than Python's.
        row = store.connection.execute(
            'SELECT substr(e.body, c."start" + 1, c."end" - c."start") AS extract '
            "FROM claim_citations c JOIN evidence e ON e.id = c.evidence_id "
            "WHERE c.claim_id = ?",
            (claim,),
        ).fetchone()
        assert row["extract"] == quote


@given(data=st.data(), body=text_strategy, delta=st.sampled_from([-2, -1, 1, 2]))
def test_shifted_offsets_never_bind(data: st.DataObject, body: str, delta: int) -> None:
    """Shift a correct citation by any nonzero amount and the trigger refuses it."""
    start = data.draw(st.integers(min_value=0, max_value=max(0, len(body) - 1)))
    end = data.draw(st.integers(min_value=start + 1, max_value=len(body)))
    quote = body[start:end]
    assume(body.count(quote) == 1)
    shifted = start + delta
    assume(shifted >= 0)
    assume(shifted + len(quote) <= len(body))
    assume(body[shifted : shifted + len(quote)] != quote)

    with fresh_store() as store:
        evidence = seed(store, body=body)
        claim = add(store, "s-1", [{"evidence_id": evidence, "quote": quote}])
        with pytest.raises(sqlite3.IntegrityError, match="citation does not bind"):
            store.connection.execute(
                'INSERT INTO claim_citations(claim_id, evidence_id, "start", "end", quote)'
                " VALUES (?, ?, ?, ?, ?)",
                (claim, evidence, shifted, shifted + len(quote), quote),
            )
        assert len(store.claim_citations(claim)) == 1
