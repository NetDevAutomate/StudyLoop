"""Adversarial direct-SQL contracts for concept-store closure."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Protocol

import pytest
from agent_session_tools.context.lifecycle import forget_session
from agent_session_tools.context.provenance import Origin
from agent_session_tools.context.store import ContextStore, NativeSource

from agent_session_tools.context.concept_schema import _ensure_schema
from agent_session_tools.context.concepts import ConceptService, _ConceptRepository

_NOW = "2026-09-08T12:00:00+00:00"
_SQLITE_MAX_INTEGER = (1 << 63) - 1
_MAX_ALLOCATED_COUNTER = _SQLITE_MAX_INTEGER - 1


class ProductionStore(Protocol):
    """Minimal production fixture contract used by these tests."""

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
            parser_version="concept-integrity-v1",
            machine_id="fixture-machine",
            body=body,
            origin=Origin.CONVERSATION,
            recorded_at=_NOW,
        )
    )


def _bound(
    store: ProductionStore,
    *,
    citation_count: int = 1,
) -> tuple[str, str, str]:
    quotes = [f"exact-{index}" for index in range(citation_count)]
    body = " | ".join(quotes)
    evidence_id = _capture(store, body, key=f"bound-{citation_count}")
    locators: list[dict[str, object]] = []
    for quote in quotes:
        start = body.index(quote)
        locators.append(
            {
                "quote": quote,
                "evidence_id": evidence_id,
                "start": start,
                "end": start + len(quote),
            }
        )
    result = _service(store).winddown(
        "fixture-session-1",
        {
            "concepts": [
                {
                    "type": "Decision",
                    "title": "Direct SQL integrity",
                    "description": "The database closes direct-write bypasses.",
                    "tags": ["direct-sql", "integrity"],
                    "confidence": 0.9,
                    "quotes": locators,
                }
            ]
        },
        actor="model-a",
    )
    assert result.writes == 1
    return result.concept_ids[0], evidence_id, body


def _insert_assertion_and_citation(
    conn: sqlite3.Connection,
    *,
    identity: str,
    statement: str,
    evidence_id: str,
    proposed_state: str = "unknown",
    proposed_target: str | None = None,
    start: int | float = 0,
    end: int | float,
    quote: str,
) -> None:
    conn.execute(
        """INSERT INTO context_assertions
           (id,statement,proposed_state,proposed_target,generator,created_at)
           VALUES (?,?,?,?,?,?)""",
        (identity, statement, proposed_state, proposed_target, "direct-sql", _NOW),
    )
    conn.execute(
        """INSERT INTO context_citations
           (assertion_id,evidence_id,start_offset,end_offset,quote)
           VALUES (?,?,?,?,?)""",
        (identity, evidence_id, start, end, quote),
    )


def _insert_bound_root(
    conn: sqlite3.Connection,
    *,
    assertion_id: str,
    statement: str,
    origin: str = "winddown",
    kind: str = "Decision",
    title: str = "Direct bound root",
    canonical_tags: str = '["direct-sql","integrity"]',
    confidence: float = 0.9,
    source_session_id: str = "fixture-session-1",
    source_uri: str = "sessionweaver://session/fixture-session-1",
    producer: str = "direct-sql",
    legacy_file_sha256: str | None = None,
    supersedes_concept_id: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO context_concepts(
           id,assertion_id,binding_state,origin,kind,title,statement,canonical_tags,
           confidence,source_session_id,source_uri,producer,created_at,
           legacy_file_sha256,supersedes_concept_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            assertion_id,
            assertion_id,
            "bound",
            origin,
            kind,
            title,
            statement,
            canonical_tags,
            confidence,
            source_session_id,
            source_uri,
            producer,
            _NOW,
            legacy_file_sha256,
            supersedes_concept_id,
        ),
    )


@pytest.mark.parametrize(
    ("proposed_state", "proposed_target", "start", "end_delta", "quote"),
    [
        ("planned", None, 0, 0, None),
        ("unknown", "forged-target", 0, 0, None),
        ("unknown", None, 0.5, 0.5, None),
        ("unknown", None, 0, 1, None),
        ("unknown", None, 0, -5, "wrong"),
    ],
    ids=["state", "target", "real-offset", "out-of-bounds", "nonexact-quote"],
)
def test_bound_root_proof_rejects_invalid_assertion_and_exact_citation_closure(
    production_store: ProductionStore,
    proposed_state: str,
    proposed_target: str | None,
    start: int | float,
    end_delta: int | float,
    quote: str | None,
) -> None:
    conn = production_store.conn
    _ensure_schema(conn)
    body = "alpha exact body"
    evidence_id = _capture(production_store, body, key="root-proof")
    identity = hashlib.sha256(
        f"{proposed_state}:{proposed_target}:{start}:{end_delta}:{quote}".encode()
    ).hexdigest()
    _insert_assertion_and_citation(
        conn,
        identity=identity,
        statement="bound statement",
        evidence_id=evidence_id,
        proposed_state=proposed_state,
        proposed_target=proposed_target,
        start=start,
        end=len(body) + end_delta,
        quote=body if quote is None else quote,
    )

    with pytest.raises(sqlite3.IntegrityError, match="bound concept"):
        _insert_bound_root(conn, assertion_id=identity, statement="bound statement")


@pytest.mark.parametrize(
    "attack",
    ["real-offset", "out-of-bounds", "nonexact-quote", "wrong-session", "ninth"],
)
def test_bound_citation_insert_guard_rejects_direct_closure_bypasses(
    production_store: ProductionStore,
    attack: str,
) -> None:
    citation_count = 8 if attack == "ninth" else 1
    concept_id, _, _ = _bound(production_store, citation_count=citation_count)
    if attack == "wrong-session":
        body = "wrong-session evidence"
        evidence_id = _capture(
            production_store,
            body,
            session_id="fixture-session-2",
            key="wrong-session-attack",
        )
    else:
        body = f"secondary exact body for {attack}"
        evidence_id = _capture(production_store, body, key=f"attack-{attack}")

    start: int | float = 0
    end: int | float = len(body)
    quote = body
    if attack == "real-offset":
        start = 0.5
        end = len(body) + 0.5
    elif attack == "out-of-bounds":
        end = len(body) + 1
    elif attack == "nonexact-quote":
        end = 5
        quote = "wrong"

    with pytest.raises(sqlite3.IntegrityError, match="bound citation"):
        production_store.conn.execute(
            """INSERT INTO context_citations
               (assertion_id,evidence_id,start_offset,end_offset,quote)
               VALUES (?,?,?,?,?)""",
            (concept_id, evidence_id, start, end, quote),
        )


def test_deleting_last_bound_citation_fails_while_root_remains(
    production_store: ProductionStore,
) -> None:
    concept_id, _, _ = _bound(production_store)

    with pytest.raises(sqlite3.IntegrityError, match="bound citation"):
        production_store.conn.execute(
            "DELETE FROM context_citations WHERE assertion_id=?", (concept_id,)
        )

    assert (
        production_store.conn.execute(
            "SELECT count(*) FROM context_citations WHERE assertion_id=?", (concept_id,)
        ).fetchone()[0]
        == 1
    )


@pytest.mark.parametrize("parent", ["assertion", "evidence"])
def test_legitimate_parent_deletion_cascades_remove_root_event_and_fts(
    production_store: ProductionStore,
    parent: str,
) -> None:
    concept_id, evidence_id, _ = _bound(production_store)
    if parent == "assertion":
        production_store.conn.execute(
            "DELETE FROM context_assertions WHERE id=?", (concept_id,)
        )
    else:
        production_store.conn.execute(
            "DELETE FROM context_evidence WHERE id=?", (evidence_id,)
        )

    for table, column in (
        ("context_assertions", "id"),
        ("context_citations", "assertion_id"),
        ("context_concepts", "id"),
        ("context_concept_events", "concept_id"),
        ("context_concept_fts", "concept_id"),
    ):
        assert (
            production_store.conn.execute(
                f"SELECT count(*) FROM {table} WHERE {column}=?", (concept_id,)
            ).fetchone()[0]
            == 0
        )


def test_forgetting_source_session_cleans_bound_root_and_fts(
    production_store: ProductionStore,
) -> None:
    concept_id, _, _ = _bound(production_store)
    production_store.conn.commit()

    result = forget_session(
        production_store.conn,
        "fixture-session-1",
        apply=True,
    )

    assert result["applied"] is True
    assert (
        production_store.conn.execute(
            "SELECT count(*) FROM context_concepts WHERE id=?", (concept_id,)
        ).fetchone()[0]
        == 0
    )
    assert (
        production_store.conn.execute(
            "SELECT count(*) FROM context_concept_fts WHERE concept_id=?", (concept_id,)
        ).fetchone()[0]
        == 0
    )


@pytest.mark.parametrize(
    ("origin_seq", "logical_time"),
    [
        (1.5, 2),
        (float("inf"), 2),
        (1, 2.5),
        (1, float("inf")),
        (_SQLITE_MAX_INTEGER, 2),
        (1, _SQLITE_MAX_INTEGER),
    ],
    ids=[
        "real-origin-seq",
        "infinite-origin-seq",
        "real-logical-time",
        "infinite-logical-time",
        "max-origin-seq",
        "max-logical-time",
    ],
)
def test_event_counters_reject_noninteger_and_exhausted_direct_values(
    production_store: ProductionStore,
    origin_seq: int | float,
    logical_time: int | float,
) -> None:
    concept_id, _, _ = _bound(production_store)
    parent = production_store.conn.execute(
        "SELECT id FROM context_concept_events WHERE concept_id=?", (concept_id,)
    ).fetchone()[0]
    event_id = hashlib.sha256(f"{origin_seq}:{logical_time}".encode()).hexdigest()

    with pytest.raises(sqlite3.IntegrityError):
        production_store.conn.execute(
            """INSERT INTO context_concept_events(
               id,concept_id,parent_event_id,standing,actor,reason,display_timestamp,
               origin_instance,origin_seq,logical_time) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                event_id,
                concept_id,
                parent,
                "accepted",
                "remote",
                "counter attack",
                _NOW,
                f"remote-{event_id}",
                origin_seq,
                logical_time,
            ),
        )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("origin_seq", 1.5),
        ("origin_seq", float("inf")),
        ("origin_seq", _SQLITE_MAX_INTEGER),
        ("logical_time", 1.5),
        ("logical_time", float("inf")),
        ("logical_time", _SQLITE_MAX_INTEGER),
    ],
)
def test_clock_counters_reject_noninteger_and_exhausted_direct_values(
    production_store: ProductionStore,
    column: str,
    value: int | float,
) -> None:
    _ensure_schema(production_store.conn)

    with pytest.raises(sqlite3.IntegrityError):
        production_store.conn.execute(
            f"UPDATE context_concept_clock SET {column}=? WHERE id=1", (value,)
        )


def _insert_remote_event(
    conn: sqlite3.Connection,
    *,
    concept_id: str,
    parent_event_id: str,
    standing: str,
    logical_time: int,
    label: str,
) -> str:
    event_id = hashlib.sha256(label.encode()).hexdigest()
    conn.execute(
        """INSERT INTO context_concept_events(
           id,concept_id,parent_event_id,standing,actor,reason,display_timestamp,
           origin_instance,origin_seq,logical_time) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            event_id,
            concept_id,
            parent_event_id,
            standing,
            "remote",
            label,
            _NOW,
            f"remote-{label}",
            1,
            logical_time,
        ),
    )
    return event_id


def test_allocator_strictly_advances_past_observed_remote_integer_time(
    production_store: ProductionStore,
) -> None:
    service = _service(production_store)
    concept_id, _, _ = _bound(production_store)
    initial = production_store.conn.execute(
        "SELECT id FROM context_concept_events WHERE concept_id=?", (concept_id,)
    ).fetchone()[0]
    remote = _insert_remote_event(
        production_store.conn,
        concept_id=concept_id,
        parent_event_id=initial,
        standing="accepted",
        logical_time=100,
        label="advance-to-100",
    )
    production_store.conn.commit()

    result = service.transition(
        concept_id, "retired", actor="owner", reason="strict advance"
    )

    assert result.writes == 1
    assert production_store.conn.execute(
        "SELECT logical_time,typeof(logical_time) FROM context_concept_events WHERE id=?",
        (result.event_id,),
    ).fetchone() == (101, "integer")
    assert production_store.conn.execute(
        "SELECT id FROM context_concept_events WHERE id=?", (remote,)
    ).fetchone() == (remote,)


def test_allocator_rejects_exhausted_observed_remote_time_and_rolls_back(
    production_store: ProductionStore,
) -> None:
    service = _service(production_store)
    concept_id, _, _ = _bound(production_store)
    initial = production_store.conn.execute(
        "SELECT id FROM context_concept_events WHERE concept_id=?", (concept_id,)
    ).fetchone()[0]
    _insert_remote_event(
        production_store.conn,
        concept_id=concept_id,
        parent_event_id=initial,
        standing="accepted",
        logical_time=_MAX_ALLOCATED_COUNTER,
        label="exhausted-remote-time",
    )
    production_store.conn.commit()
    before_clock = production_store.conn.execute(
        "SELECT origin_seq,logical_time FROM context_concept_clock WHERE id=1"
    ).fetchone()
    before_events = production_store.conn.execute(
        "SELECT count(*) FROM context_concept_events"
    ).fetchone()[0]

    with pytest.raises(RuntimeError, match="exhausted"):
        service.transition(
            concept_id, "retired", actor="owner", reason="must roll back"
        )

    assert (
        production_store.conn.execute(
            "SELECT origin_seq,logical_time FROM context_concept_clock WHERE id=1"
        ).fetchone()
        == before_clock
    )
    assert (
        production_store.conn.execute(
            "SELECT count(*) FROM context_concept_events"
        ).fetchone()[0]
        == before_events
    )


def test_allocator_rejects_exhausted_local_origin_sequence_and_rolls_back(
    production_store: ProductionStore,
) -> None:
    service = _service(production_store)
    concept_id, _, _ = _bound(production_store)
    production_store.conn.execute(
        "UPDATE context_concept_clock SET origin_seq=? WHERE id=1",
        (_MAX_ALLOCATED_COUNTER,),
    )
    production_store.conn.commit()
    before_clock = production_store.conn.execute(
        "SELECT origin_seq,logical_time FROM context_concept_clock WHERE id=1"
    ).fetchone()
    before_events = production_store.conn.execute(
        "SELECT count(*) FROM context_concept_events"
    ).fetchone()[0]

    with pytest.raises(RuntimeError, match="exhausted"):
        service.transition(
            concept_id, "accepted", actor="owner", reason="must roll back"
        )

    assert (
        production_store.conn.execute(
            "SELECT origin_seq,logical_time FROM context_concept_clock WHERE id=1"
        ).fetchone()
        == before_clock
    )
    assert (
        production_store.conn.execute(
            "SELECT count(*) FROM context_concept_events"
        ).fetchone()[0]
        == before_events
    )


def _legacy_root(store: ProductionStore) -> str:
    _ensure_schema(store.conn)
    identity = _ConceptRepository(store.conn, now=lambda: _NOW).seed_legacy(
        original_bytes=b"immutable legacy source",
        kind="Procedure",
        title="Legacy immutable title",
        statement="Legacy immutable statement",
        tags=("legacy", "stable"),
        confidence=0.7,
        source_session_id="fixture-session-1",
        source_uri="file:///legacy/source.md",
        producer="legacy-import",
    )
    store.conn.commit()
    return identity


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("kind", "Decision"),
        ("title", "Altered title"),
        ("statement", "Altered statement"),
        ("canonical_tags", '["legacy","replacement"]'),
        ("confidence", 0.8),
        ("source_session_id", "fixture-session-2"),
        ("source_uri", "file:///legacy/replacement.md"),
        ("producer", "replacement-producer"),
        ("legacy_file_sha256", "f" * 64),
    ],
)
def test_legacy_successor_rejects_every_altered_copied_field_without_using_slot(
    production_store: ProductionStore,
    field: str,
    replacement: object,
) -> None:
    legacy_id = _legacy_root(production_store)
    conn = production_store.conn
    cursor = conn.execute("SELECT * FROM context_concepts WHERE id=?", (legacy_id,))
    names = [item[0] for item in cursor.description]
    previous = dict(zip(names, cursor.fetchone(), strict=True))
    successor = {
        "kind": previous["kind"],
        "title": previous["title"],
        "statement": previous["statement"],
        "canonical_tags": previous["canonical_tags"],
        "confidence": previous["confidence"],
        "source_session_id": previous["source_session_id"],
        "source_uri": previous["source_uri"],
        "producer": previous["producer"],
        "legacy_file_sha256": previous["legacy_file_sha256"],
    }
    successor[field] = replacement
    evidence_session = str(successor["source_session_id"])
    body = "exact evidence for direct legacy successor"
    evidence_id = _capture(
        production_store,
        body,
        session_id=evidence_session,
        key=f"legacy-successor-{field}",
    )
    assertion_id = hashlib.sha256(f"successor:{field}".encode()).hexdigest()
    _insert_assertion_and_citation(
        conn,
        identity=assertion_id,
        statement=str(successor["statement"]),
        evidence_id=evidence_id,
        end=len(body),
        quote=body,
    )

    with pytest.raises(sqlite3.IntegrityError, match="legacy successor"):
        _insert_bound_root(
            conn,
            assertion_id=assertion_id,
            origin="legacy-bind",
            kind=str(successor["kind"]),
            title=str(successor["title"]),
            statement=str(successor["statement"]),
            canonical_tags=str(successor["canonical_tags"]),
            confidence=float(successor["confidence"]),
            source_session_id=evidence_session,
            source_uri=str(successor["source_uri"]),
            producer=str(successor["producer"]),
            legacy_file_sha256=str(successor["legacy_file_sha256"]),
            supersedes_concept_id=legacy_id,
        )

    assert (
        conn.execute(
            "SELECT count(*) FROM context_concepts WHERE supersedes_concept_id=?",
            (legacy_id,),
        ).fetchone()[0]
        == 0
    )


def test_root_without_exact_initial_proposed_event_cannot_commit(
    production_store: ProductionStore,
) -> None:
    conn = production_store.conn
    _ensure_schema(conn)
    digest = hashlib.sha256(b"root without initial event").hexdigest()
    conn.commit()
    conn.execute("BEGIN")
    conn.execute(
        """INSERT INTO context_concepts(
           id,assertion_id,binding_state,origin,kind,title,statement,canonical_tags,
           confidence,source_session_id,source_uri,producer,created_at,
           legacy_file_sha256,supersedes_concept_id)
           VALUES (?,NULL,'legacy-unbound','legacy-okf',?,?,?,?,?,?,?,?,?,?,NULL)""",
        (
            f"legacy:{digest}",
            "Finding",
            "Root without event",
            "This transaction omits its initial event.",
            '["initial","lifecycle"]',
            0.7,
            "fixture-session-1",
            "file:///legacy/no-event.md",
            "legacy-import",
            _NOW,
            digest,
        ),
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM context_concepts WHERE id=?", (f"legacy:{digest}",)
        ).fetchone()[0]
        == 1
    )

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        conn.commit()
    conn.rollback()

    assert (
        conn.execute(
            "SELECT count(*) FROM context_concepts WHERE id=?", (f"legacy:{digest}",)
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM context_concept_fts WHERE concept_id=?",
            (f"legacy:{digest}",),
        ).fetchone()[0]
        == 0
    )
