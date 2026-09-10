"""Transactional concept/evidence/lifecycle behavior behind ConceptService."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any, Protocol

import pytest
from agent_session_tools.context.provenance import Origin
from agent_session_tools.context.store import ContextStore, NativeSource

from agent_session_tools.context.concept_schema import _ensure_schema
from agent_session_tools.context.concepts import ConceptService, _ConceptRepository

_NOW = "2026-09-08T12:00:00+00:00"


class ProductionStore(Protocol):
    conn: sqlite3.Connection
    db_path: Path


def _service(store: ProductionStore) -> ConceptService:
    return ConceptService(store.db_path, now=lambda: _NOW)


def _capture(
    store: ProductionStore,
    body: str,
    *,
    session_id: str = "fixture-session-1",
    key: str | None = None,
) -> str:
    native_key = key or hashlib.sha256(body.encode()).hexdigest()[:16]
    return ContextStore(store.conn).capture(
        NativeSource(
            session_id=session_id,
            native_key=native_key,
            harness="fixture",
            native_kind="message:user",
            native_locator=f"fixture://{session_id}/{native_key}",
            parser_version="concept-test-v1",
            machine_id="fixture-machine",
            body=body,
            origin=Origin.CONVERSATION,
            recorded_at=_NOW,
        )
    )


def _concept(
    quote: str,
    *,
    title: str = "Pin exact evidence",
    description: str = "The concept statement is evidence bound.",
    kind: str = "Decision",
    quotes: list[dict[str, Any]] | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": kind,
        "title": title,
        "description": description,
        "tags": tags or ["evidence", "session-weaver"],
        "confidence": 0.9,
        "quotes": quotes or [{"quote": quote}],
    }


def _document(*concepts: dict[str, Any]) -> dict[str, Any]:
    return {"concepts": list(concepts)}


def _error_codes(result: Any) -> set[str]:
    return {issue.code for issue in result.errors}


def _state(conn: sqlite3.Connection) -> dict[str, Any]:
    return {
        table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in (
            "context_assertions",
            "context_citations",
            "context_concepts",
            "context_concept_events",
            "context_concept_fts",
        )
    } | {
        "clock": conn.execute(
            "SELECT origin_seq,logical_time FROM context_concept_clock WHERE id=1"
        ).fetchone()
    }


def test_winddown_binds_exact_quote_through_pinned_agent_context_contract(
    production_store: ProductionStore,
) -> None:
    service = _service(production_store)
    body = "prefix exact evidence 🙂e\u0301 suffix"
    evidence_id = _capture(production_store, body)
    quote = "exact evidence 🙂e\u0301"

    result = service.winddown(
        "fixture-session-1", _document(_concept(quote)), actor="model-a"
    )

    assert result.writes == 1
    assert result.errors == ()
    concept_id = result.concept_ids[0]
    assertion = production_store.conn.execute(
        "SELECT statement,proposed_state,proposed_target,generator "
        "FROM context_assertions WHERE id=?",
        (concept_id,),
    ).fetchone()
    citation = production_store.conn.execute(
        """SELECT evidence_id,start_offset,end_offset,quote
           FROM context_citations WHERE assertion_id=?""",
        (concept_id,),
    ).fetchone()
    root = production_store.conn.execute(
        """SELECT id,assertion_id,binding_state,origin,source_session_id,canonical_tags
           FROM context_concepts WHERE id=?""",
        (concept_id,),
    ).fetchone()
    event = production_store.conn.execute(
        "SELECT standing,parent_event_id,actor,reason "
        "FROM context_concept_events WHERE concept_id=?",
        (concept_id,),
    ).fetchone()
    start = body.index(quote)

    assert assertion == (
        "The concept statement is evidence bound.",
        "unknown",
        None,
        "model-a",
    )
    assert citation == (evidence_id, start, start + len(quote), quote)
    assert root == (
        concept_id,
        concept_id,
        "bound",
        "winddown",
        "fixture-session-1",
        '["evidence","session-weaver"]',
    )
    assert event == ("proposed", None, "model-a", "winddown")


def test_emoji_and_combining_character_offsets_are_unicode_code_points(
    production_store: ProductionStore,
) -> None:
    service = _service(production_store)
    body = "A🙂e\u0301Z"
    evidence_id = _capture(production_store, body)
    quote = body[1:4]

    result = service.winddown(
        "fixture-session-1",
        _document(
            _concept(
                quote,
                quotes=[
                    {"quote": quote, "evidence_id": evidence_id, "start": 1, "end": 4}
                ],
            )
        ),
        actor="unicode-model",
    )

    assert result.writes == 1
    assert production_store.conn.execute(
        "SELECT start_offset,end_offset,quote FROM context_citations WHERE assertion_id=?",
        (result.concept_ids[0],),
    ).fetchone() == (1, 4, "🙂e\u0301")


def test_quote_only_resolution_is_literal_unique_and_never_leaks_bodies(
    production_store: ProductionStore,
) -> None:
    service = _service(production_store)
    first = _capture(production_store, "secret-body echo then echo", key="repeat-one")
    second = _capture(production_store, "other-secret echo", key="repeat-two")

    repeated = service.winddown(
        "fixture-session-1", _document(_concept("echo")), actor="model"
    )
    absent = service.winddown(
        "fixture-session-1", _document(_concept("ECHO")), actor="model"
    )
    explicit = service.winddown(
        "fixture-session-1",
        _document(
            _concept(
                "echo",
                quotes=[
                    {
                        "quote": "echo",
                        "evidence_id": second,
                        "start": len("other-secret "),
                        "end": len("other-secret echo"),
                    }
                ],
                title="Disambiguate exact evidence",
            )
        ),
        actor="model",
    )

    assert repeated.writes == 0
    assert _error_codes(repeated) == {"ambiguous_quote"}
    assert absent.writes == 0
    assert _error_codes(absent) == {"quote_not_found"}
    assert all(
        "secret-body" not in issue.message
        for issue in (*repeated.errors, *absent.errors)
    )
    assert explicit.writes == 1
    assert (
        production_store.conn.execute(
            "SELECT evidence_id FROM context_citations WHERE assertion_id=?",
            (explicit.concept_ids[0],),
        ).fetchone()[0]
        == second
    )
    assert first != second


def test_repeated_quote_across_two_bodies_is_ambiguous(
    production_store: ProductionStore,
) -> None:
    service = _service(production_store)
    _capture(production_store, "one globally repeated literal", key="body-one")
    _capture(production_store, "two globally repeated literal", key="body-two")

    result = service.winddown(
        "fixture-session-1",
        _document(_concept("globally repeated literal")),
        actor="model",
    )

    assert result.writes == 0
    assert _error_codes(result) == {"ambiguous_quote"}


def test_visible_sources_cache_is_keyed_on_the_degrade_oversized_flag(
    production_store: ProductionStore,
) -> None:
    """A3c hardening: a second call must not silently reuse the wrong flag's cache."""
    from agent_session_tools.context.public import open_context

    from agent_session_tools.context.concepts import _EvidenceResolver

    _capture(production_store, "cache-key evidence body", key="cache-key-evidence")

    with open_context(production_store.db_path) as context:
        resolver = _EvidenceResolver(context, "fixture-session-1")
        first = resolver._visible_sources()

        assert resolver._visible_sources() is first

        with pytest.raises(RuntimeError, match="degrade_oversized"):
            resolver._visible_sources(degrade_oversized=True)


def test_explicit_locator_rejects_wrong_session_mismatch_and_unavailable_evidence(
    production_store: ProductionStore,
) -> None:
    service = _service(production_store)
    wrong_session = _capture(
        production_store,
        "wrong session quote",
        session_id="fixture-session-2",
        key="wrong-session",
    )
    matching = _capture(production_store, "right session quote", key="right-session")

    wrong = service.winddown(
        "fixture-session-1",
        _document(
            _concept(
                "wrong session quote",
                quotes=[
                    {
                        "quote": "wrong session quote",
                        "evidence_id": wrong_session,
                        "start": 0,
                        "end": 19,
                    }
                ],
            )
        ),
        actor="model",
    )
    mismatch = service.winddown(
        "fixture-session-1",
        _document(
            _concept(
                "right session quote",
                title="Mismatched locator",
                quotes=[
                    {
                        "quote": "right session quote",
                        "evidence_id": matching,
                        "start": 1,
                        "end": 20,
                    }
                ],
            )
        ),
        actor="model",
    )
    overrun = service.winddown(
        "fixture-session-1",
        _document(
            _concept(
                "right session quote",
                title="Overrun locator",
                quotes=[
                    {
                        "quote": "right session quote",
                        "evidence_id": matching,
                        "start": 0,
                        "end": 999,
                    }
                ],
            )
        ),
        actor="model",
    )

    assert _error_codes(wrong) == {"evidence_unavailable"}
    assert _error_codes(mismatch) == {"locator_mismatch"}
    assert _error_codes(overrun) == {"locator_mismatch"}
    assert wrong.writes == mismatch.writes == overrun.writes == 0


@pytest.mark.parametrize("hidden_by", ["scope", "tombstone", "withdrawal"])
def test_resolver_enforces_scope_session_lifecycle_and_evidence_withdrawal(
    production_store: ProductionStore,
    hidden_by: str,
) -> None:
    service = _service(production_store)
    body = f"hidden {hidden_by} quote"
    evidence_id = _capture(production_store, body, key=f"hidden-{hidden_by}")
    conn = production_store.conn
    if hidden_by == "scope":
        conn.execute(
            "INSERT INTO context_projects VALUES ('hidden-work','work','manual',?)",
            (_NOW,),
        )
        conn.execute(
            "INSERT INTO context_session_projects VALUES (?,?,?)",
            ("fixture-session-1", "hidden-work", "explicit"),
        )
    elif hidden_by == "tombstone":
        conn.execute(
            "INSERT INTO context_tombstones VALUES (?,?,?)",
            ("fixture-session-1", "delete-fixture-session-1", _NOW),
        )
    else:
        local = conn.execute(
            "SELECT instance FROM context_access_state WHERE id=1"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO context_replica_peers VALUES (?,?,?,?,?)",
            ("fixture-peer", "remote", "local-node", local, _NOW),
        )
        conn.execute(
            "INSERT INTO context_replica_denials VALUES (?,?,?,?,?,?)",
            ("fixture-peer", "unclassified", "evidence", evidence_id, 1, "withdrawn"),
        )
    conn.commit()

    result = service.winddown(
        "fixture-session-1",
        _document(
            _concept(
                body,
                quotes=[
                    {
                        "quote": body,
                        "evidence_id": evidence_id,
                        "start": 0,
                        "end": len(body),
                    }
                ],
            )
        ),
        actor="model",
    )

    assert result.writes == 0
    assert _error_codes(result) == {"evidence_unavailable"}


def test_all_quotes_resolve_before_any_assertion_and_duplicate_citations_fail(
    production_store: ProductionStore,
) -> None:
    service = _service(production_store)
    body = "valid exact quote"
    evidence_id = _capture(production_store, body)
    baseline = _state(production_store.conn)

    later_missing = service.winddown(
        "fixture-session-1",
        _document(
            _concept(body),
            _concept("not present", title="Second concept fails resolution"),
        ),
        actor="model",
    )
    duplicate_citation = service.winddown(
        "fixture-session-1",
        _document(
            _concept(
                body,
                title="Duplicate canonical citation",
                quotes=[
                    {"quote": body},
                    {
                        "quote": body,
                        "evidence_id": evidence_id,
                        "start": 0,
                        "end": len(body),
                    },
                ],
            )
        ),
        actor="model",
    )

    assert later_missing.writes == 0
    assert _error_codes(later_missing) == {"quote_not_found"}
    assert duplicate_citation.writes == 0
    assert _error_codes(duplicate_citation) == {"duplicate_citation"}
    assert _state(production_store.conn) == baseline


def test_malformed_later_concept_reports_zero_writes(
    production_store: ProductionStore,
) -> None:
    service = _service(production_store)
    _capture(production_store, "valid quote")
    baseline = _state(production_store.conn)
    invalid = _concept("missing", title="   ")

    result = service.winddown(
        "fixture-session-1",
        _document(_concept("valid quote"), invalid),
        actor="model",
    )

    assert result.writes == 0
    assert (result.errors[0].path, result.errors[0].code) == (
        "/concepts/1/title",
        "blank",
    )
    assert _state(production_store.conn) == baseline


def test_one_and_eight_exact_citations_reach_upstream_but_nine_does_not(
    production_store: ProductionStore,
) -> None:
    service = _service(production_store)
    body = " ".join(f"quote-{index}" for index in range(8))
    _capture(production_store, body)
    quotes = [{"quote": f"quote-{index}"} for index in range(8)]

    result = service.winddown(
        "fixture-session-1",
        _document(_concept("quote-0", quotes=quotes)),
        actor="model",
    )
    rejected = service.winddown(
        "fixture-session-1",
        _document(
            _concept(
                "quote-0",
                title="Nine citations rejected",
                quotes=[*quotes, {"quote": "ninth"}],
            )
        ),
        actor="model",
    )

    assert result.writes == 1
    assert (
        production_store.conn.execute(
            "SELECT count(*) FROM context_citations WHERE assertion_id=?",
            (result.concept_ids[0],),
        ).fetchone()[0]
        == 8
    )
    assert rejected.writes == 0
    assert _error_codes(rejected) == {"too_many_items"}


@pytest.mark.parametrize(
    "checkpoint", ["after_assertion", "after_root", "after_clock", "after_event"]
)
def test_failure_after_each_write_stage_rolls_back_rows_fts_and_clock(
    production_store: ProductionStore,
    monkeypatch: pytest.MonkeyPatch,
    checkpoint: str,
) -> None:
    service = _service(production_store)
    _capture(production_store, "rollback exact quote")
    baseline = _state(production_store.conn)

    def fail(self: _ConceptRepository, name: str) -> None:
        if name == checkpoint:
            raise RuntimeError(f"injected {checkpoint}")

    monkeypatch.setattr(_ConceptRepository, "_checkpoint", fail)

    with pytest.raises(RuntimeError, match=checkpoint):
        service.winddown(
            "fixture-session-1",
            _document(_concept("rollback exact quote")),
            actor="model",
        )

    assert _state(production_store.conn) == baseline


def test_failure_in_second_concept_rolls_back_the_whole_batch(
    production_store: ProductionStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(production_store)
    _capture(production_store, "first rollback quote")
    _capture(production_store, "second rollback quote")
    baseline = _state(production_store.conn)
    roots = 0

    def fail_on_second_root(self: _ConceptRepository, name: str) -> None:
        nonlocal roots
        if name == "after_root":
            roots += 1
            if roots == 2:
                raise RuntimeError("injected second root")

    monkeypatch.setattr(_ConceptRepository, "_checkpoint", fail_on_second_root)

    with pytest.raises(RuntimeError, match="second root"):
        service.winddown(
            "fixture-session-1",
            _document(
                _concept("first rollback quote", title="First atomic concept"),
                _concept("second rollback quote", title="Second atomic concept"),
            ),
            actor="model",
        )

    assert _state(production_store.conn) == baseline


def test_assertions_citations_roots_and_events_reject_updates(
    production_store: ProductionStore,
) -> None:
    service = _service(production_store)
    _capture(production_store, "immutable exact quote")
    result = service.winddown(
        "fixture-session-1",
        _document(_concept("immutable exact quote")),
        actor="model",
    )
    concept_id = result.concept_ids[0]
    conn = production_store.conn

    statements = (
        ("UPDATE context_assertions SET statement='changed' WHERE id=?", (concept_id,)),
        (
            "UPDATE context_citations SET quote='changed' WHERE assertion_id=?",
            (concept_id,),
        ),
        ("UPDATE context_concepts SET title='changed' WHERE id=?", (concept_id,)),
        (
            "UPDATE context_concept_events SET reason='changed' WHERE concept_id=?",
            (concept_id,),
        ),
    )
    for sql, params in statements:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(sql, params)


def test_lifecycle_rules_and_retirement_leave_source_and_siblings_untouched(
    production_store: ProductionStore,
) -> None:
    service = _service(production_store)
    first_evidence = _capture(production_store, "first lifecycle quote")
    second_evidence = _capture(production_store, "second lifecycle quote")
    created = service.winddown(
        "fixture-session-1",
        _document(
            _concept("first lifecycle quote", title="First lifecycle concept"),
            _concept("second lifecycle quote", title="Second lifecycle concept"),
        ),
        actor="model",
    )
    first, second = created.concept_ids
    accepted = service.transition(first, "accepted", actor="owner", reason="reviewed")
    duplicate_accept = service.transition(
        first, "accepted", actor="owner", reason="repeat"
    )
    retired = service.transition(first, "retired", actor="owner", reason="obsolete")
    terminal = service.transition(first, "accepted", actor="owner", reason="regress")
    conn = production_store.conn
    repo = _ConceptRepository(conn, now=lambda: _NOW)

    assert accepted.writes == 1 and accepted.standing == "accepted"
    assert duplicate_accept.writes == 0
    assert _error_codes(duplicate_accept) == {"invalid_transition"}
    assert retired.writes == 1 and retired.standing == "retired"
    assert terminal.writes == 0
    assert _error_codes(terminal) == {"retired_terminal"}
    assert repo.current_event(first)["standing"] == "retired"
    assert repo.current_event(second)["standing"] == "proposed"
    assert (
        conn.execute(
            "SELECT count(*) FROM sessions WHERE id='fixture-session-1'"
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM context_evidence WHERE id IN (?,?)",
            (first_evidence, second_evidence),
        ).fetchone()[0]
        == 2
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM context_assertions WHERE id IN (?,?)", (first, second)
        ).fetchone()[0]
        == 2
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM context_concepts WHERE id IN (?,?)", (first, second)
        ).fetchone()[0]
        == 2
    )
    assert conn.execute("SELECT count(*) FROM context_tombstones").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM context_concept_fts").fetchone()[0] == 2
    assert repo.search_fts("First") == []
    assert [hit["concept_id"] for hit in repo.search_fts("Second")] == [second]


def test_current_state_total_order_is_independent_of_timestamp_and_insert_order(
    production_store: ProductionStore,
) -> None:
    service = _service(production_store)
    _capture(production_store, "order one quote")
    _capture(production_store, "order two quote")
    created = service.winddown(
        "fixture-session-1",
        _document(
            _concept("order one quote", title="Order concept one"),
            _concept("order two quote", title="Order concept two"),
        ),
        actor="model",
    )
    conn = production_store.conn
    for concept_id, standings in zip(
        created.concept_ids,
        (("accepted", "retired"), ("retired", "accepted")),
        strict=True,
    ):
        initial = conn.execute(
            "SELECT id FROM context_concept_events WHERE concept_id=? AND parent_event_id IS NULL",
            (concept_id,),
        ).fetchone()[0]
        for index, standing in enumerate(standings, start=1):
            logical = 100 if standing == "accepted" else 1
            payload = f"{concept_id}:{standing}:{index}"
            conn.execute(
                """INSERT INTO context_concept_events(
                   id,concept_id,parent_event_id,standing,actor,reason,display_timestamp,
                   origin_instance,origin_seq,logical_time) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    hashlib.sha256(payload.encode()).hexdigest(),
                    concept_id,
                    initial,
                    standing,
                    "remote",
                    f"remote {standing}",
                    _NOW,
                    f"remote-{concept_id}-{index}",
                    1,
                    logical,
                ),
            )
    conn.commit()
    repo = _ConceptRepository(conn, now=lambda: _NOW)

    # Frozen cross-machine standing order (design.md): the winner is
    # max(events, key=(lamport, machine_id, event_id)) -- for both concepts
    # the accepted event carries logical_time 100 against the retired
    # event's 1, so 'accepted' wins on both regardless of the order the
    # rows were inserted in and regardless of their identical display
    # timestamps. (The reference gave standing kind precedence over the
    # clock; B3 replaces that with the frozen pure-triple order.)
    assert [repo.current_event(cid)["standing"] for cid in created.concept_ids] == [
        "accepted",
        "accepted",
    ]


def _seed_legacy(
    store: ProductionStore,
    *,
    title: str = "Legacy Aurora",
    statement: str = "Legacy nebula procedure",
    kind: str = "Procedure",
    tags: tuple[str, ...] = ("legacy", "orbit"),
) -> str:
    _ensure_schema(store.conn)
    repo = _ConceptRepository(store.conn, now=lambda: _NOW)
    identity = repo.seed_legacy(
        original_bytes=b"immutable legacy file bytes",
        kind=kind,
        title=title,
        statement=statement,
        tags=tags,
        confidence=0.7,
        source_session_id="fixture-session-1",
        source_uri="file:///legacy/concept.md",
        producer="legacy-import",
    )
    store.conn.commit()
    return identity


def test_legacy_accept_is_refused_and_safe_bind_copies_metadata_without_auto_accept(
    production_store: ProductionStore,
) -> None:
    service = _service(production_store)
    body = "evidence for the immutable legacy statement"
    evidence_id = _capture(production_store, body)
    legacy_id = _seed_legacy(production_store)

    refused = service.transition(
        legacy_id, "accepted", actor="owner", reason="cannot trust yet"
    )
    bound = service.bind_legacy(
        legacy_id,
        {
            "quotes": [
                {
                    "quote": body,
                    "evidence_id": evidence_id,
                    "start": 0,
                    "end": len(body),
                }
            ]
        },
        actor="owner",
        reason="exact evidence found",
    )
    conn = production_store.conn
    repo = _ConceptRepository(conn, now=lambda: _NOW)
    new_id = bound.concept_id
    assert new_id is not None

    assert refused.writes == 0
    assert _error_codes(refused) == {"legacy_unbound_requires_bind"}
    assert bound.writes == 4
    assert bound.assertion_id == new_id
    assert conn.execute(
        """SELECT kind,title,statement,canonical_tags,confidence,source_session_id,
                  source_uri,origin,binding_state,supersedes_concept_id
           FROM context_concepts WHERE id=?""",
        (new_id,),
    ).fetchone() == (
        "Procedure",
        "Legacy Aurora",
        "Legacy nebula procedure",
        '["legacy","orbit"]',
        0.7,
        "fixture-session-1",
        "file:///legacy/concept.md",
        "legacy-bind",
        "bound",
        legacy_id,
    )
    assert conn.execute(
        "SELECT proposed_state,proposed_target FROM context_assertions WHERE id=?",
        (new_id,),
    ).fetchone() == ("unknown", None)
    assert repo.current_event(new_id)["standing"] == "proposed"
    old_event = repo.current_event(legacy_id)
    assert old_event["standing"] == "retired"
    assert new_id in old_event["reason"]


def test_legacy_bind_rejects_metadata_rewrite_with_zero_writes(
    production_store: ProductionStore,
) -> None:
    service = _service(production_store)
    _capture(production_store, "legacy exact quote")
    legacy_id = _seed_legacy(production_store)
    baseline = _state(production_store.conn)

    result = service.bind_legacy(
        legacy_id,
        {"quotes": [{"quote": "legacy exact quote"}], "title": "rewrite"},
        actor="owner",
        reason="attempt",
    )

    assert result.writes == 0
    assert _error_codes(result) == {"extra_field"}
    assert _state(production_store.conn) == baseline


@pytest.mark.parametrize(
    "checkpoint",
    [
        "after_assertion",
        "after_root",
        "after_clock",
        "after_event",
        "after_bound_initial_event",
        "after_legacy_retired_event",
    ],
)
def test_injected_legacy_bind_failure_rolls_back_new_rows_old_retirement_and_clock(
    production_store: ProductionStore,
    monkeypatch: pytest.MonkeyPatch,
    checkpoint: str,
) -> None:
    service = _service(production_store)
    _capture(production_store, "legacy rollback quote")
    legacy_id = _seed_legacy(production_store)
    baseline = _state(production_store.conn)

    def fail(self: _ConceptRepository, name: str) -> None:
        if name == checkpoint:
            raise RuntimeError(f"bind {checkpoint}")

    monkeypatch.setattr(_ConceptRepository, "_checkpoint", fail)

    with pytest.raises(RuntimeError, match=checkpoint):
        service.bind_legacy(
            legacy_id,
            {"quotes": [{"quote": "legacy rollback quote"}]},
            actor="owner",
            reason="bind atomically",
        )

    assert _state(production_store.conn) == baseline
    assert (
        _ConceptRepository(production_store.conn, now=lambda: _NOW).current_event(
            legacy_id
        )["standing"]
        == "proposed"
    )


def test_private_fts_query_indexes_all_fields_labels_legacy_and_filters_retired(
    production_store: ProductionStore,
) -> None:
    service = _service(production_store)
    legacy_id = _seed_legacy(production_store)
    _capture(production_store, "bound quasar quote")
    bound = service.winddown(
        "fixture-session-1",
        _document(
            _concept(
                "bound quasar quote",
                title="Bound Pulsar",
                description="Bound quasar statement",
                kind="Finding",
                tags=["cosmos", "signal"],
            )
        ),
        actor="model",
    )
    repo = _ConceptRepository(production_store.conn, now=lambda: _NOW)

    for term in ("Aurora", "nebula", "orbit", "Procedure"):
        hits = repo.search_fts(term)
        assert [(hit["concept_id"], hit["trust_label"]) for hit in hits] == [
            (legacy_id, "legacy-unbound")
        ]
    for term in ("Pulsar", "quasar", "cosmos", "Finding"):
        hits = repo.search_fts(term)
        assert [(hit["concept_id"], hit["trust_label"]) for hit in hits] == [
            (bound.concept_ids[0], "model-proposed")
        ]

    retired = service.transition(
        legacy_id, "retired", actor="owner", reason="legacy no longer useful"
    )

    assert retired.writes == 1
    assert repo.search_fts("Aurora") == []
    assert (
        production_store.conn.execute(
            "SELECT count(*) FROM context_concept_fts WHERE concept_id=?", (legacy_id,)
        ).fetchone()[0]
        == 1
    )
