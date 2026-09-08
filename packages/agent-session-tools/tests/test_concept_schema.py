"""Schema contracts for the transactional concept sidecar."""

from __future__ import annotations

import hashlib
import sqlite3
from importlib import import_module
from importlib.util import find_spec
from typing import Protocol

import pytest
from agent_session_tools.migrations import CURRENT_VERSION

from agent_session_tools.context.concept_schema import (
    SCHEMA_FINGERPRINT,
    SCHEMA_VERSION,
    UPSTREAM_SCHEMA_VERSION,
    _ensure_schema,
    _fts_consistency,
    _rebuild_fts,
    verify_installed_schema,
)


class ProductionStore(Protocol):
    conn: sqlite3.Connection


def test_a3a_modules_are_packaged() -> None:
    """The A3a concept, schema, and parser modules exist in the distribution."""
    assert find_spec("agent_session_tools.context.concept_schema") is not None
    assert find_spec("agent_session_tools.context.winddown") is not None
    assert find_spec("agent_session_tools.context.concepts") is not None


def test_a3a_deep_seam_and_private_adapters_are_defined() -> None:
    """The public service stays small while maintenance seams remain internal."""
    concepts = import_module("agent_session_tools.context.concepts")
    schema = import_module("agent_session_tools.context.concept_schema")
    parser = import_module("agent_session_tools.context.winddown")

    assert {
        "ConceptService",
        "BatchResult",
        "TransitionResult",
        "BindResult",
    } <= set(vars(concepts))
    assert {"_ConceptRepository", "_EvidenceResolver"} <= set(vars(concepts))
    assert {"_ensure_schema", "_fts_consistency", "_rebuild_fts"} <= set(vars(schema))
    assert {"_parse_winddown", "_parse_bind_document"} <= set(vars(parser))


def test_schema_install_is_exact_idempotent_and_does_not_claim_upstream_version(
    production_store: ProductionStore,
) -> None:
    conn = production_store.conn
    before = conn.execute("PRAGMA user_version").fetchone()[0]

    _ensure_schema(conn)
    _ensure_schema(conn)

    # UPSTREAM_SCHEMA_VERSION is pinned to 49, the migration that installs
    # the sidecar (the reference pinned its era's v47 the same way).
    assert before == CURRENT_VERSION == UPSTREAM_SCHEMA_VERSION == 49
    assert conn.execute("PRAGMA user_version").fetchone()[0] == before
    assert conn.execute(
        "SELECT schema_version,schema_fingerprint FROM context_concept_schema WHERE id=1"
    ).fetchone() == (SCHEMA_VERSION, SCHEMA_FINGERPRINT)
    assert conn.execute(
        "SELECT origin_instance,origin_seq,logical_time FROM context_concept_clock WHERE id=1"
    ).fetchone() == (
        conn.execute("SELECT instance FROM context_access_state WHERE id=1").fetchone()[
            0
        ],
        0,
        0,
    )


def test_exact_unmarked_schema_is_adopted_but_partial_or_drifted_schema_is_rejected(
    production_store: ProductionStore,
) -> None:
    conn = production_store.conn
    _ensure_schema(conn)
    conn.execute("DROP TABLE context_concept_schema")

    _ensure_schema(conn)

    assert (
        conn.execute(
            "SELECT schema_fingerprint FROM context_concept_schema WHERE id=1"
        ).fetchone()[0]
        == SCHEMA_FINGERPRINT
    )
    conn.execute("DROP TRIGGER context_concepts_immutable")
    with pytest.raises(RuntimeError, match="fingerprint|drift|incomplete"):
        _ensure_schema(conn)


def _seed_legacy(
    conn: sqlite3.Connection,
    *,
    suffix: str = "one",
    origin_seq: int = 1,
    logical_time: int = 1,
) -> tuple[str, str]:
    payload = f"legacy-{suffix}".encode()
    digest = hashlib.sha256(payload).hexdigest()
    concept_id = f"legacy:{digest}"
    conn.execute(
        """INSERT INTO context_concepts(
        id,assertion_id,binding_state,origin,kind,title,statement,canonical_tags,
        confidence,source_session_id,source_uri,producer,created_at,legacy_file_sha256,
        supersedes_concept_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            concept_id,
            None,
            "legacy-unbound",
            "legacy-okf",
            "Finding",
            f"Legacy {suffix}",
            f"Legacy searchable statement {suffix}",
            '["legacy","searchable"]',
            0.7,
            "fixture-session-1",
            f"file:///legacy/{suffix}.md",
            "legacy-import",
            "2026-09-08T00:00:00+00:00",
            digest,
            None,
        ),
    )
    instance = conn.execute(
        "SELECT origin_instance FROM context_concept_clock WHERE id=1"
    ).fetchone()[0]
    event_payload = f"{concept_id}:{origin_seq}:{logical_time}"
    event_id = hashlib.sha256(event_payload.encode()).hexdigest()
    conn.execute(
        """INSERT INTO context_concept_events(
        id,concept_id,initial_concept_id,parent_event_id,standing,actor,reason,
        display_timestamp,origin_instance,origin_seq,logical_time)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            event_id,
            concept_id,
            concept_id,
            None,
            "proposed",
            "legacy-import",
            "legacy import",
            "2026-09-08T00:00:00+00:00",
            instance,
            origin_seq,
            logical_time,
        ),
    )
    return concept_id, event_id


@pytest.mark.parametrize(
    "tags",
    [
        '["one"]',
        '["one","one"]',
        '["two","one"]',
        '["UPPER","valid"]',
        '["one","two","three","four","five","six"]',
        '["one",2]',
    ],
)
def test_root_schema_rejects_noncanonical_tags(
    production_store: ProductionStore, tags: str
) -> None:
    conn = production_store.conn
    _ensure_schema(conn)
    digest = hashlib.sha256(tags.encode()).hexdigest()

    with pytest.raises(sqlite3.IntegrityError, match="canonical tags"):
        conn.execute(
            """INSERT INTO context_concepts(
            id,assertion_id,binding_state,origin,kind,title,statement,canonical_tags,
            confidence,source_session_id,source_uri,producer,created_at,legacy_file_sha256,
            supersedes_concept_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                f"legacy:{digest}",
                None,
                "legacy-unbound",
                "legacy-okf",
                "Finding",
                "Legacy tags",
                "Legacy statement",
                tags,
                0.7,
                "fixture-session-1",
                "file:///legacy/tags.md",
                "legacy-import",
                "2026-09-08T00:00:00+00:00",
                digest,
                None,
            ),
        )


def test_legacy_shape_root_and_event_are_immutable_and_fts_is_triggered(
    production_store: ProductionStore,
) -> None:
    conn = production_store.conn
    _ensure_schema(conn)
    concept_id, event_id = _seed_legacy(conn)

    assert conn.execute(
        "SELECT title,statement,tags,kind,concept_id FROM context_concept_fts"
    ).fetchone() == (
        "Legacy one",
        "Legacy searchable statement one",
        "legacy searchable",
        "Finding",
        concept_id,
    )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE context_concepts SET title='changed' WHERE id=?", (concept_id,)
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE context_concept_events SET reason='changed' WHERE id=?", (event_id,)
        )


def test_bound_root_trigger_proves_assertion_statement_citations_and_session(
    production_store: ProductionStore,
) -> None:
    conn = production_store.conn
    _ensure_schema(conn)
    conn.execute(
        """INSERT INTO context_assertions
        (id,statement,proposed_state,proposed_target,generator,created_at)
        VALUES ('assertion-no-citations','statement','unknown',NULL,'actor','2026-09-08')"""
    )
    values = (
        "assertion-no-citations",
        "assertion-no-citations",
        "bound",
        "winddown",
        "Decision",
        "No citations",
        "statement",
        '["one","two"]',
        0.9,
        "fixture-session-1",
        "sessionweaver://session/fixture-session-1",
        "actor",
        "2026-09-08T00:00:00+00:00",
        None,
        None,
    )

    with pytest.raises(sqlite3.IntegrityError, match="bound concept"):
        conn.execute(
            """INSERT INTO context_concepts(
            id,assertion_id,binding_state,origin,kind,title,statement,canonical_tags,
            confidence,source_session_id,source_uri,producer,created_at,legacy_file_sha256,
            supersedes_concept_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            values,
        )


def test_event_parent_must_belong_to_same_concept_and_origin_sequence_is_unique(
    production_store: ProductionStore,
) -> None:
    conn = production_store.conn
    _ensure_schema(conn)
    first_id, first_event = _seed_legacy(conn, suffix="first", origin_seq=1)
    second_id, _ = _seed_legacy(conn, suffix="second", origin_seq=2, logical_time=2)
    instance = conn.execute(
        "SELECT origin_instance FROM context_concept_clock WHERE id=1"
    ).fetchone()[0]

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        conn.execute(
            """INSERT INTO context_concept_events(
               id,concept_id,parent_event_id,standing,actor,reason,display_timestamp,
               origin_instance,origin_seq,logical_time) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                "a" * 64,
                second_id,
                first_event,
                "retired",
                "actor",
                "wrong parent",
                "2026-09-08",
                "remote",
                1,
                3,
            ),
        )
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute(
            """INSERT INTO context_concept_events(
               id,concept_id,parent_event_id,standing,actor,reason,display_timestamp,
               origin_instance,origin_seq,logical_time) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                "b" * 64,
                first_id,
                first_event,
                "accepted",
                "actor",
                "duplicate sequence",
                "2026-09-08",
                instance,
                1,
                3,
            ),
        )


def test_fts_consistency_receipt_and_rebuild_are_stable_and_content_derived(
    production_store: ProductionStore,
) -> None:
    conn = production_store.conn
    _ensure_schema(conn)
    _seed_legacy(conn, suffix="first", origin_seq=1)
    _seed_legacy(conn, suffix="second", origin_seq=2, logical_time=2)

    before = _fts_consistency(conn)
    conn.execute(
        "DELETE FROM context_concept_fts WHERE rowid="
        "(SELECT min(rowid) FROM context_concept_fts WHERE concept_id LIKE 'legacy:%')"
    )
    broken = _fts_consistency(conn)
    rebuilt = _rebuild_fts(conn)
    repeated = _rebuild_fts(conn)

    assert before.consistent is True
    assert before.row_count == before.expected_count == 2
    assert broken.consistent is False
    assert rebuilt.consistent is True
    assert rebuilt.row_count == rebuilt.expected_count == 2
    assert rebuilt.digest == repeated.digest == before.digest


def test_fts_consistency_digest_is_stable_for_duplicate_ids_in_any_insertion_order(
    production_store: ProductionStore,
) -> None:
    conn = production_store.conn
    _ensure_schema(conn)
    concept_id, _event_id = _seed_legacy(conn, suffix="duplicate", origin_seq=1)

    def digest_for(rows: list[tuple[str, str, str, str]]) -> str:
        conn.execute(
            "DELETE FROM context_concept_fts WHERE concept_id=?", (concept_id,)
        )
        conn.executemany(
            """INSERT INTO context_concept_fts(title,statement,tags,kind,concept_id)
               VALUES (?,?,?,?,?)""",
            [(*row, concept_id) for row in rows],
        )
        return _fts_consistency(conn).actual_digest

    first = ("Alpha", "first statement", "alpha duplicate", "Finding")
    second = ("Beta", "second statement", "beta duplicate", "Decision")

    assert digest_for([first, second]) == digest_for([second, first])


def test_sidecar_v2_allows_null_session_only_for_unavailable_legacy_roots(
    production_store: ProductionStore,
) -> None:
    from agent_session_tools.context.concepts import _ConceptRepository

    assert SCHEMA_VERSION == 2
    conn = production_store.conn
    _ensure_schema(conn)
    evidence_id, evidence_body = conn.execute(
        """SELECT id,body FROM context_evidence
           WHERE session_id='fixture-session-1' ORDER BY id LIMIT 1"""
    ).fetchone()
    repo = _ConceptRepository(conn, now=lambda: "2026-09-08T00:00:00+00:00")
    legacy_id = repo.seed_legacy(
        original_bytes=b"nullable unavailable legacy source",
        kind="Finding",
        title="Unavailable legacy root",
        statement=evidence_body,
        tags=("legacy", "unavailable"),
        confidence=0.7,
        source_session_id=None,
        source_uri="sessionweaver://session/fixture-session-1",
        producer="legacy-import",
    )
    conn.commit()

    assert conn.execute(
        "SELECT source_session_id,source_uri FROM context_concepts WHERE id=?",
        (legacy_id,),
    ).fetchone() == (None, "sessionweaver://session/fixture-session-1")

    legacy_sha = legacy_id.removeprefix("legacy:")
    for origin in ("winddown", "legacy-bind"):
        assertion_id = hashlib.sha256(f"null-session:{origin}".encode()).hexdigest()
        conn.execute(
            """INSERT INTO context_assertions
               (id,statement,proposed_state,proposed_target,generator,created_at)
               VALUES (?,?, 'unknown',NULL,'direct-test','2026-09-08')""",
            (assertion_id, evidence_body),
        )
        conn.execute(
            """INSERT INTO context_citations
               (assertion_id,evidence_id,start_offset,end_offset,quote)
               VALUES (?,?,?,?,?)""",
            (assertion_id, evidence_id, 0, len(evidence_body), evidence_body),
        )
        with pytest.raises(sqlite3.IntegrityError):
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
                    "Finding",
                    "Unavailable legacy root"
                    if origin == "legacy-bind"
                    else "Bound root",
                    evidence_body,
                    '["legacy","unavailable"]'
                    if origin == "legacy-bind"
                    else '["bound","root"]',
                    0.7,
                    None,
                    "sessionweaver://session/fixture-session-1",
                    "legacy-import" if origin == "legacy-bind" else "direct-test",
                    "2026-09-08T00:00:00+00:00",
                    legacy_sha if origin == "legacy-bind" else None,
                    legacy_id if origin == "legacy-bind" else None,
                ),
            )

    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_verify_installed_schema_rejects_unsupported_upstream_version(
    production_store: ProductionStore,
) -> None:
    """F9: the shared, read-only verifier used by both _ensure_schema and
    projection.py must reject a PRAGMA user_version drift, not just the copy
    that used to live in projection.py."""
    conn = production_store.conn
    _ensure_schema(conn)
    conn.execute(f"PRAGMA user_version={UPSTREAM_SCHEMA_VERSION + 1}")

    try:
        with pytest.raises(RuntimeError, match="Unsupported upstream schema"):
            verify_installed_schema(conn)
    finally:
        conn.execute(f"PRAGMA user_version={UPSTREAM_SCHEMA_VERSION}")


def test_verify_installed_schema_rejects_marker_mismatch(
    production_store: ProductionStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F9: the shared verifier must reject a schema_version/schema_fingerprint
    marker that no longer matches this module's constants."""
    import agent_session_tools.context.concept_schema as concept_schema_module

    conn = production_store.conn
    _ensure_schema(conn)
    monkeypatch.setattr(concept_schema_module, "SCHEMA_FINGERPRINT", "0" * 64)

    with pytest.raises(RuntimeError, match="mismatch"):
        verify_installed_schema(conn)
