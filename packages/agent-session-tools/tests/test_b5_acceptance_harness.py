"""Regression contracts for the B5 live-evidence harness."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3
from types import ModuleType

import pytest


def _load_harness() -> ModuleType:
    root = Path(__file__).resolve().parents[3]
    path = root / "scripts" / "b5_acceptance.py"
    spec = importlib.util.spec_from_file_location("b5_acceptance", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_flow2_receipt_contract_rejects_verdict_only_evidence() -> None:
    """Removing product metrics/per-question evidence must invalidate a receipt."""
    harness = _load_harness()

    with pytest.raises(ValueError, match="all_25.*per_question"):
        harness._validate_flow2_evidence(  # type: ignore[attr-defined]
            {
                "released_gate": {"verdict": "investigate", "exit_code": 3},
                "mcp_library_identity": {
                    "questions": 25,
                    "ordered_hits_identical": 25,
                    "mismatches": 0,
                },
            }
        )


def test_a6_comparison_keeps_metrics_vector_and_identity_independent() -> None:
    """A hit-vector drift must not be hidden by equal aggregates or 25/25 identity."""
    harness = _load_harness()
    aggregate = {
        "all_25": {"overall": {"n": 2, "hits": 1, "recall_at_5": 0.5}},
        "visible_subset": {"overall": {"n": 2, "hits": 1, "recall_at_5": 0.5}},
        "positive_control": {"status": "pass"},
    }
    reference = {
        **aggregate,
        "per_question": [
            {"id": "K01", "hit": 1},
            {"id": "P01", "hit": 0},
        ],
    }
    current = {
        **aggregate,
        "positive_control": {
            "status": "pass",
            "metrics": {"overall": {"mrr_at_5": 0.75}},
        },
        "per_question": [
            {"id": "K01", "hit": 0},
            {"id": "P01", "hit": 1},
        ],
    }

    comparison = harness._compare_a6_evidence(  # type: ignore[attr-defined]
        current,
        reference,
        {
            "questions": 25,
            "ordered_hits_identical": 25,
            "mismatches": 0,
        },
    )

    assert comparison == {
        "hit_vector_identical": False,
        "aggregate_metrics_identical": True,
        "mcp_library_identity": {
            "questions": 25,
            "ordered_hits_identical": 25,
            "mismatches": 0,
        },
    }


def test_disposable_reidentification_preserves_imported_history(tmp_path) -> None:
    """A real-copy fixture needs a fresh local identity without rewriting old events."""
    harness = _load_harness()
    db = tmp_path / "copy.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE context_access_state(id INTEGER PRIMARY KEY,instance TEXT,revision INTEGER)"
        )
        conn.execute(
            "CREATE TABLE context_concept_clock(id INTEGER PRIMARY KEY,origin_instance TEXT,origin_seq INTEGER,logical_time INTEGER)"
        )
        conn.execute(
            "CREATE TABLE context_concept_events(id TEXT,logical_time INTEGER)"
        )
        conn.execute("INSERT INTO context_access_state VALUES(1,'old',4)")
        conn.execute("INSERT INTO context_concept_clock VALUES(1,'old',7,9)")
        conn.execute(
            "INSERT INTO context_concept_events VALUES('first',11),('second',13)"
        )
        conn.commit()

    harness._reidentify_disposable_copy(db, "new")  # type: ignore[attr-defined]

    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT instance,revision FROM context_access_state WHERE id=1"
        ).fetchone() == ("new", 4)
        assert conn.execute(
            "SELECT origin_instance,origin_seq,logical_time FROM context_concept_clock WHERE id=1"
        ).fetchone() == ("new", 0, 13)
        assert conn.execute(
            "SELECT id,logical_time FROM context_concept_events ORDER BY id"
        ).fetchall() == [("first", 11), ("second", 13)]


def test_disposable_ontology_is_cleared_before_replication(tmp_path) -> None:
    """Inherited derived rows must not masquerade as replicated ontology."""
    harness = _load_harness()
    db = tmp_path / "copy.db"
    tables = (
        "ontology_class",
        "ontology_property",
        "ontology_structural",
        "ontology_individual",
        "ontology_relation",
        "ontology_build_state",
    )
    with sqlite3.connect(db) as conn:
        for table in tables:
            conn.execute(f"CREATE TABLE {table}(value INTEGER)")
            conn.execute(f"INSERT INTO {table} VALUES(1)")
        conn.commit()

    harness._clear_disposable_ontology(db)  # type: ignore[attr-defined]

    with sqlite3.connect(db) as conn:
        assert {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in tables
        } == {table: 0 for table in tables}


def test_replay_idempotence_means_zero_rows_not_zero_receipts() -> None:
    """A harmless committed replay receipt must not be misclassified as row drift."""
    harness = _load_harness()

    proof = harness._replay_proof(  # type: ignore[attr-defined]
        before_rows={"a": 4, "b": 4},
        after_rows={"a": 4, "b": 4},
        before_digests={"a": "same", "b": "same"},
        after_digests={"a": "same", "b": "same"},
        transfer_receipts=2,
    )

    assert proof == {
        "idempotent": True,
        "event_row_delta": 0,
        "digests_unchanged": True,
        "transfer_receipts": 2,
    }


def test_configured_session_sync_route_never_calls_legacy(
    tmp_path, monkeypatch
) -> None:
    """Replacing configured-peer dispatch with legacy SQL must break this test."""
    harness = _load_harness()
    local_db = tmp_path / "a.db"
    local_db.touch()
    config_path = tmp_path / "a.json"
    config_path.write_text(
        '{"memory":{"sync":{"node_id":"a","peers":{"b":{"allowed_scopes":["personal"]}}}}}',
        encoding="utf-8",
    )

    from agent_session_tools import sync
    from agent_session_tools.replication import coordinator

    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))
    monkeypatch.setattr(sync, "_config", None)
    monkeypatch.setattr(
        sync.legacy_guard,
        "check_path",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("configured peer fell through to legacy SQL")
        ),
    )
    monkeypatch.setattr(
        coordinator,
        "run",
        lambda peer, *, direction, db=None: {
            "peer": peer,
            "direction": direction,
            "db_selected": db == local_db,
            "cleanup_pending": [],
        },
    )

    proof = harness._configured_route_proof(  # type: ignore[attr-defined]
        peer="b",
        db=local_db,
        direction="sync",
    )

    assert proof == {
        "exit_code": 0,
        "peer": "b",
        "direction": "sync",
        "db_selected": True,
        "legacy_path_called": False,
    }
