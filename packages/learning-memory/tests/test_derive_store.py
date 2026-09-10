"""Derivation against a store: idempotence, versioning, and the label-set accuracy gate.

Idempotence is the property that lets the export sweep re-derive without fear, so it
is tested on content hashes rather than row counts alone: identical counts with
different content would be a silent rewrite.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from learning_memory import Event, EventKind, ParsedSession, Session, Store
from learning_memory.derive import (
    DERIVATION_VERSION,
    derivation_fingerprint,
    derive_all,
    derive_session,
    load_vocabulary,
    split_exchanges,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

LABEL_SET = Path(__file__).parent / "fixtures" / "derive_label_set.json"


def _session(
    store: Store, session_id: str, harness: str, events: list[Event], day: str = "01"
) -> None:
    """`day` is explicit: recurrence needs sessions a day apart, so it must be visible."""
    store.ingest(
        ParsedSession(
            session=Session(
                id=session_id,
                harness=harness,
                started_at=f"2026-09-{day}T10:00:00+00:00",
            ),
            events=events,
            adapter_version="test@1",
        )
    )


@pytest.fixture
def derived_store(tmp_path: Path) -> Iterator[Store]:
    store = Store.connect(tmp_path / "lm.db")
    store.install()
    _session(
        store,
        "s-spark",
        "claude_code",
        [
            Event(turn_id=0, seq=0, kind="system", text="preamble"),
            Event(turn_id=1, seq=1, kind="user", text="why does spark fail?", actor="learner"),
            Event(turn_id=1, seq=2, kind="tool_call", text="", tool_name="Bash"),
            Event(turn_id=1, seq=3, kind="tool_result", text="exit code 1"),
            Event(turn_id=1, seq=4, kind="tool_call", text="", tool_name="Bash"),
            Event(turn_id=1, seq=5, kind="assistant_prose", text="because pyspark needs glue"),
            Event(turn_id=2, seq=6, kind="user", text="   ", actor="learner"),
            Event(turn_id=3, seq=7, kind="user", text="and the pre commit hook?", actor="learner"),
            Event(turn_id=3, seq=8, kind="assistant_prose", text="pre-commit runs ruff"),
        ],
        day="01",
    )
    _session(
        store,
        "s-codex",
        "codex",
        [
            Event(turn_id=1, seq=0, kind="user", text="<task>\nfix the dbt model\n</task>"),
            Event(turn_id=1, seq=1, kind="assistant_prose", text="dbt and airflow both run"),
        ],
        day="03",
    )
    _session(
        store,
        "s-other",
        "aider",
        [
            Event(turn_id=1, seq=0, kind="user", text="spark again please"),
            Event(turn_id=1, seq=1, kind="assistant_prose", text="spark once more"),
        ],
        day="05",
    )
    yield store
    store.close()


# ------------------------------------------------------------------- idempotence


def test_derive_all_is_idempotent_in_content_not_just_counts(derived_store: Store) -> None:
    first = derive_all(derived_store)
    fingerprint_one = derivation_fingerprint(derived_store)
    counts_one = derived_store.row_counts()

    second = derive_all(derived_store)
    fingerprint_two = derivation_fingerprint(derived_store)

    assert fingerprint_one == fingerprint_two, "a re-derivation must be byte-identical"
    assert derived_store.row_counts() == counts_one
    assert second["exchanges"]["total"] == first["exchanges"]["total"]
    assert second["concepts"]["total_tags"] == first["concepts"]["total_tags"]


def test_derive_session_replaces_only_its_own_version(derived_store: Store) -> None:
    vocab = load_vocabulary()
    derive_session(derived_store, "s-spark", vocab)
    conn = derived_store.connection
    conn.execute(
        "INSERT INTO exchanges(session_id, derivation_version, turn_id, is_question,"
        " had_error, retried, resolved) VALUES ('s-spark', 'derive-v0', 99, 0, 0, 0, 1)"
    )
    before_other = conn.execute(
        "SELECT count(*) AS n FROM exchanges WHERE derivation_version = 'derive-v0'"
    ).fetchone()["n"]

    derive_session(derived_store, "s-spark", vocab)

    after_other = conn.execute(
        "SELECT count(*) AS n FROM exchanges WHERE derivation_version = 'derive-v0'"
    ).fetchone()["n"]
    assert (before_other, after_other) == (1, 1), "another version's rows are untouched"


def test_rewriting_a_session_does_not_duplicate_tags_or_occurrences(
    derived_store: Store,
) -> None:
    vocab = load_vocabulary()
    for _ in range(3):
        derive_session(derived_store, "s-spark", vocab)
    conn = derived_store.connection
    tags = conn.execute(
        """
        SELECT count(*) AS n FROM concept_tags t JOIN exchanges e ON e.id = t.exchange_id
        WHERE e.session_id = 's-spark' AND e.derivation_version = ?
        """,
        (DERIVATION_VERSION,),
    ).fetchone()["n"]
    occurrences = conn.execute(
        "SELECT count(*) AS n FROM concept_occurrences WHERE session_id = 's-spark'"
        " AND derivation_version = ?",
        (DERIVATION_VERSION,),
    ).fetchone()["n"]
    assert tags > 0
    assert occurrences > 0
    assert occurrences == len(
        {
            row["concept_id"]
            for row in conn.execute(
                "SELECT concept_id FROM concept_occurrences WHERE session_id = 's-spark'"
            )
        }
    ), "one occurrence row per concept per session"


# ------------------------------------------------------------ what got written


def test_written_rows_match_the_pure_rules(derived_store: Store) -> None:
    derive_all(derived_store)
    conn = derived_store.connection
    rows = {
        int(row["turn_id"]): row
        for row in conn.execute(
            "SELECT turn_id, is_question, had_error, retried, resolved, question_event_id"
            " FROM exchanges WHERE session_id = 's-spark' AND derivation_version = ?",
            (DERIVATION_VERSION,),
        )
    }
    assert set(rows) == {0, 1, 2, 3}
    assert rows[0]["resolved"] is None and rows[0]["question_event_id"] is None  # pre_first_user
    assert rows[2]["resolved"] is None and rows[2]["question_event_id"] is not None  # empty user
    assert (rows[1]["is_question"], rows[1]["had_error"], rows[1]["retried"]) == (1, 1, 1)
    assert rows[1]["resolved"] == 1
    assert rows[3]["is_question"] == 1


def test_quarantine_rows_are_distinguishable_without_a_reason_column(
    derived_store: Store,
) -> None:
    """Schema v2 has no quarantine_reason; the row shape still separates the two."""
    derive_all(derived_store)
    pre_first_user = derived_store.connection.execute(
        "SELECT count(*) AS n FROM exchanges WHERE derivation_version = ?"
        " AND resolved IS NULL AND question_event_id IS NULL",
        (DERIVATION_VERSION,),
    ).fetchone()["n"]
    empty_user = derived_store.connection.execute(
        "SELECT count(*) AS n FROM exchanges WHERE derivation_version = ?"
        " AND resolved IS NULL AND question_event_id IS NOT NULL",
        (DERIVATION_VERSION,),
    ).fetchone()["n"]
    assert (pre_first_user, empty_user) == (1, 1)


def test_intent_and_outcome_land_on_sessions(derived_store: Store) -> None:
    derive_all(derived_store)
    row = derived_store.connection.execute(
        "SELECT intent, outcome FROM sessions WHERE id = 's-spark'"
    ).fetchone()
    assert row["intent"] == "why does spark fail?"
    assert row["outcome"] == "pre-commit runs ruff"
    codex = derived_store.connection.execute(
        "SELECT intent FROM sessions WHERE id = 's-codex'"
    ).fetchone()
    assert codex["intent"] == "fix the dbt model", "the <task> wrapper is stripped"


def test_concept_rows_carry_canonical_ids_and_alias_sources(derived_store: Store) -> None:
    derive_all(derived_store)
    conn = derived_store.connection
    tagged = {
        (str(row["canonical"]), str(row["source"]))
        for row in conn.execute(
            """
            SELECT c.canonical, t.source FROM concept_tags t
            JOIN concepts c ON c.id = t.concept_id
            JOIN exchanges e ON e.id = t.exchange_id
            WHERE e.session_id = 's-spark' AND e.derivation_version = ?
            """,
            (DERIVATION_VERSION,),
        )
    }
    assert ("spark", "vocab") in tagged
    assert ("pyspark", "vocab") in tagged
    assert ("glue", "vocab") in tagged
    assert ("pre-commit", "alias") in tagged, "'pre commit' is the alias form"
    assert ("pre-commit", "vocab") in tagged, "'pre-commit' also appears verbatim"


def test_concepts_are_not_tagged_from_tool_text(derived_store: Store) -> None:
    """Tagging reads user and assistant_prose only."""
    store = derived_store
    _session(
        store,
        "s-tooltext",
        "kiro_cli",
        [
            Event(turn_id=1, seq=0, kind="user", text="run it"),
            Event(turn_id=1, seq=1, kind="tool_result", text="spark pyspark dbt airflow"),
            Event(turn_id=1, seq=2, kind="assistant_prose", text="all done"),
        ],
        day="07",
    )
    derive_all(store)
    tagged = store.connection.execute(
        """
        SELECT count(*) AS n FROM concept_tags t JOIN exchanges e ON e.id = t.exchange_id
        WHERE e.session_id = 's-tooltext' AND e.derivation_version = ?
        """,
        (DERIVATION_VERSION,),
    ).fetchone()["n"]
    assert tagged == 0


def test_recurrence_needs_two_sessions_a_day_apart(derived_store: Store) -> None:
    receipt = derive_all(derived_store)
    concepts = {item["concept"] for item in receipt["recurrence"]["top_15"]}
    assert "spark" in concepts, "s-spark and s-other are on different days"
    assert receipt["recurrence"]["day_gap_basis"]["unknown"] == 0


def test_receipt_shape(derived_store: Store) -> None:
    receipt = derive_all(derived_store)
    assert receipt["derivation_version"] == DERIVATION_VERSION
    assert receipt["vocab"]["sha256"]
    assert receipt["sessions"]["failed"] == 0
    for key in ("total", "threaded", "by_flags", "quarantined"):
        assert key in receipt["exchanges"]
    assert 0.0 <= receipt["intent_outcome"]["outcome_fill_rate"] <= 1.0


def test_derive_session_rejects_an_unknown_session(derived_store: Store) -> None:
    with pytest.raises(KeyError):
        derive_session(derived_store, "s-nope", load_vocabulary())


# ------------------------------------------------- orchestrator-labelled accuracy


def _labelled_items() -> list[dict[str, Any]]:
    if not LABEL_SET.exists():
        return []
    payload = json.loads(LABEL_SET.read_text(encoding="utf-8"))
    return [
        item
        for item in payload["items"]
        if any(value is not None for value in item["label"].values())
    ]


def test_label_set_exists_and_is_unfilled_or_consistent() -> None:
    """The fixture must be present and shaped; labels themselves may be null."""
    assert LABEL_SET.exists(), "run: python -m learning_memory.run_derive --fixture ..."
    payload = json.loads(LABEL_SET.read_text(encoding="utf-8"))
    assert payload["derivation_version"] == DERIVATION_VERSION
    assert payload["seed"] == 20260910
    assert len(payload["items"]) == 60
    assert {item["group"] for item in payload["items"]} == {
        "claude_code",
        "codex_kiro",
        "other_harnesses",
    }
    for item in payload["items"]:
        assert {"is_question", "had_error", "retried", "resolved", "concepts"} <= set(
            item["label"]
        )  # a free-text ``note`` is allowed alongside the graded fields
        assert set(item["derived"]) <= set(item["label"])


# Measured agreement of derive-v1 with the orchestrator's hand labels (2026-09-10, 60 items).
# These floors are the MEASURED values: the test fails on any regression, and the receipt
# reports the real number. Raising a floor requires a rule change plus a re-label pass.
# ``target`` is the level at which a flag is trusted for the learning tier (ADR-0011 G2-adjacent).
ACCURACY_FLOOR = {"is_question": 42, "had_error": 51, "retried": 48, "resolved": 48}
ACCURACY_TARGET = 54  # 90 % of 60


@pytest.mark.parametrize("flag", ["is_question", "had_error", "retried", "resolved"])
def test_derived_flags_match_orchestrator_labels(flag: str) -> None:
    """Agreement with the human answer key must not fall below the measured floor.

    Skips until a human fills labels in; a model must not write its own answer key.
    The labels found (2026-09-10) that ``is_question`` over-fires on imperative briefs,
    ``retried`` on the archive is only "repeated tool use", and ``had_error`` misses
    errors the LEARNER pasted because the lexicon scanned answers only.
    """
    items = [item for item in _labelled_items() if item["label"][flag] is not None]
    if not items:
        pytest.skip(f"no human labels for {flag} yet")
    agree = sum(1 for item in items if bool(item["derived"][flag]) == bool(item["label"][flag]))
    mismatches = [
        f"{item['session_id'][:24]}#{item['turn_id']}: derived={item['derived'][flag]} "
        f"labelled={item['label'][flag]}"
        for item in items
        if bool(item["derived"][flag]) != bool(item["label"][flag])
    ]
    assert agree >= ACCURACY_FLOOR[flag], (
        f"{flag}: {agree}/{len(items)} agree, below the measured floor "
        f"{ACCURACY_FLOOR[flag]} -- a regression. First mismatches: {mismatches[:5]}"
    )
    if agree < ACCURACY_TARGET:
        pytest.xfail(f"{flag}: {agree}/{len(items)} agree; target {ACCURACY_TARGET} not yet met")


def test_derived_concepts_match_orchestrator_labels() -> None:
    """Concept recall against the orchestrator's labelled concepts (precision is not graded:
    the vocabulary match is mechanical and the labeller lists only concepts they judged
    central, so extra vocab hits are expected)."""
    items = [item for item in _labelled_items() if item["label"]["concepts"] is not None]
    if not items:
        pytest.skip("no human labels for concepts yet")
    labelled = sum(len(item["label"]["concepts"]) for item in items)
    if labelled == 0:
        pytest.skip("labelled items carry no concepts to recall")
    recalled = sum(
        len(set(item["label"]["concepts"]) & set(item["derived"]["concepts"])) for item in items
    )
    assert recalled / labelled >= 0.90, f"concept recall {recalled}/{labelled} below 0.90"


def test_split_exchanges_is_pure_and_reusable(derived_store: Store) -> None:
    """The fixture builder re-derives from events; it must agree with the stored rows."""
    derive_all(derived_store)
    events = [
        Event(
            turn_id=int(row["turn_id"]),
            seq=int(row["seq"]),
            kind=cast("EventKind", str(row["kind"])),
            text=str(row["text"]),
        )
        for row in derived_store.connection.execute(
            "SELECT turn_id, seq, kind, text FROM events WHERE session_id = 's-spark' ORDER BY seq"
        )
    ]
    assert len(events) == 9
    from learning_memory.derive import StoredEvent

    stored = [
        StoredEvent(id=index, turn_id=e.turn_id, seq=e.seq, kind=e.kind, text=e.text)
        for index, e in enumerate(events)
    ]
    turns = [exchange.turn_id for exchange in split_exchanges(stored)]
    assert turns == [0, 1, 2, 3]
