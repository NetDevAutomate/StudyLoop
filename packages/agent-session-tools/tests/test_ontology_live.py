"""Opt-in ontology acceptance and migration-safety checks on Online Backups.

Most tests here exercise the safety harness itself against the shared
``ontology_production_store`` fixture (a temp database, never the owner's
real one) -- these run in the normal suite. The three tests marked
``live_ontology`` (excluded by default; opt in with ``-m live_ontology``)
touch the owner's real ``sessions.db`` **only** through a SQLite Online
Backup copy under ``/tmp``, per the task's ground rules: the real file is
opened read-only, its own read transaction is rolled back, and only the
disposable backup copy is ever migrated or rebuilt.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Protocol

import pytest

import agent_session_tools.ontology as ontology
import agent_session_tools.ontology_live as ontology_live
from agent_session_tools.migrations import CURRENT_VERSION
from agent_session_tools.ontology_live import (
    run_live_copy_acceptance,
    run_live_copy_migration_receipt,
    write_baseline_evidence,
)


class ProductionStore(Protocol):
    """The production-schema fixture surface used by safety tests."""

    db_path: Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup_artifacts(directory: Path) -> set[str]:
    return {path.name for path in directory.glob("agent-session-tools-ontology-*")}


def test_live_copy_acceptance_mutates_only_backup_and_returns_sanitized_evidence(
    ontology_production_store: ProductionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_hash_before = _sha256(ontology_production_store.db_path)
    real_connect = ontology_live.sqlite3.connect
    connections: list[tuple[Any, dict[str, Any]]] = []

    def tracked_connect(
        database: Any,
        *args: Any,
        **kwargs: Any,
    ) -> sqlite3.Connection:
        connections.append((database, kwargs))
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(ontology_live.sqlite3, "connect", tracked_connect)
    monkeypatch.setattr(ontology, "_utc_now", lambda: "9998-01-01T00:00:00Z")

    evidence = run_live_copy_acceptance(
        ontology_production_store.db_path,
        _backup_dir=tmp_path,
    )
    serialized = json.dumps(evidence, sort_keys=True)
    source_connections = [
        (database, kwargs)
        for database, kwargs in connections
        if kwargs.get("uri") is True
    ]

    assert len(source_connections) == 2
    assert all("mode=ro" in str(database) for database, _kwargs in source_connections)

    assert _sha256(ontology_production_store.db_path) == source_hash_before
    assert _backup_artifacts(tmp_path) == set()
    assert evidence["evidence_schema"] == "agent-session-tools.ontology-tier1-baseline"
    assert len(evidence["source"]["online_backup_sha256"]) == 64
    assert "sha256" not in evidence["source"]
    assert set(evidence["backup"]) == {"post_rebuild_sha256"}
    assert evidence["source"]["session_count"] == 2
    assert evidence["source"]["message_count"] == 4
    assert evidence["migration"]["to_version"] == CURRENT_VERSION
    assert (
        evidence["first_full_rebuild"]["logical_hash"]
        == evidence["second_full_rebuild"]["logical_hash"]
    )
    assert evidence["first_full_rebuild"]["elapsed_seconds"] <= 5
    assert (
        evidence["incremental_rebuild"]["logical_hash"]
        == evidence["second_full_rebuild"]["logical_hash"]
    )
    assert evidence["status"]["healthy"] is True
    assert evidence["source_sentinels_unchanged"] is True
    for forbidden in (
        str(ontology_production_store.db_path),
        "fixture-project",
        "How does fixture",
        "Through commit_batch",
        "fixture-session-1",
    ):
        assert forbidden not in serialized


def test_source_content_receipt_includes_committed_wal_frames(
    ontology_production_store: ProductionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = ontology_production_store.db_path
    wal_conn = sqlite3.connect(source)
    try:
        assert wal_conn.execute("PRAGMA journal_mode = WAL").fetchone() == ("wal",)
        wal_conn.execute("PRAGMA wal_autocheckpoint = 0")
        main_file_hash = _sha256(source)
        wal_conn.execute(
            """
            INSERT INTO sessions(
                id, source, project_path, git_branch, created_at, updated_at, metadata
            ) VALUES (
                'wal-receipt-sentinel', 'kiro', NULL, NULL,
                '2026-09-07T11:00:00Z', '2026-09-07T11:00:00Z', '{}'
            )
            """
        )
        wal_conn.commit()

        wal_path = Path(f"{source}-wal")
        assert wal_path.is_file()
        assert wal_path.stat().st_size > 0
        assert _sha256(source) == main_file_hash

        monkeypatch.setattr(ontology, "_utc_now", lambda: "9998-01-01T00:00:00Z")
        evidence = run_live_copy_acceptance(source, _backup_dir=tmp_path)
    finally:
        wal_conn.close()

    assert evidence["source"]["session_count"] == 3
    assert evidence["source"]["online_backup_sha256"] != main_file_hash
    assert "sha256" not in evidence["source"]
    assert evidence["source_sentinels_unchanged"] is True


def test_live_copy_acceptance_deletes_backup_when_rebuild_fails(
    ontology_production_store: ProductionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_hash_before = _sha256(ontology_production_store.db_path)

    def fail_rebuild(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("forced rebuild failure")

    monkeypatch.setattr(ontology_live, "rebuild_ontology", fail_rebuild)

    with pytest.raises(RuntimeError, match="forced rebuild failure"):
        run_live_copy_acceptance(
            ontology_production_store.db_path, _backup_dir=tmp_path
        )

    assert _sha256(ontology_production_store.db_path) == source_hash_before
    assert _backup_artifacts(tmp_path) == set()


def test_baseline_writer_is_deterministic_and_contains_no_path(
    ontology_production_store: ProductionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ontology, "_utc_now", lambda: "9998-01-01T00:00:00Z")
    evidence = run_live_copy_acceptance(
        ontology_production_store.db_path, _backup_dir=tmp_path
    )
    output = tmp_path / "baseline.json"

    write_baseline_evidence(evidence, output)
    first = output.read_bytes()
    write_baseline_evidence(evidence, output)

    assert output.read_bytes() == first
    assert first.endswith(b"\n")
    assert str(ontology_production_store.db_path).encode() not in first


def test_migration_receipt_mutates_only_backup(
    ontology_production_store: ProductionStore,
    tmp_path: Path,
) -> None:
    """The migration-receipt harness never touches the source, only its backup."""
    source_hash_before = _sha256(ontology_production_store.db_path)

    receipt = run_live_copy_migration_receipt(
        ontology_production_store.db_path,
        _backup_dir=tmp_path,
    )

    assert _sha256(ontology_production_store.db_path) == source_hash_before
    assert _backup_artifacts(tmp_path) == set()
    assert receipt["to_version"] == CURRENT_VERSION
    assert set(receipt["counts"]) >= {"sessions", "messages"} | ontology.ONTOLOGY_TABLES
    for table in ontology.ONTOLOGY_TABLES:
        assert receipt["counts"][table] == 0, "migration installs empty ontology tables"
    assert len(receipt["schema_sha256"]) == 64
    serialized = json.dumps(receipt, sort_keys=True)
    for forbidden in (
        str(ontology_production_store.db_path),
        "fixture-project",
        "How does fixture",
    ):
        assert forbidden not in serialized


def _real_sessions_db() -> Path:
    return Path.home() / ".config" / "studyloop" / "sessions.db"


@pytest.mark.live_ontology
def test_real_v47_backup_upgrades_to_v48_and_retains_a_receipt() -> None:
    """R7 migration-safety item 2: a real Online Backup copy upgrades cleanly.

    Writes ``docs/data/ontology-migration-v48-receipt.json`` -- aggregates
    only (schema SHA, table list, counts), never row content.
    """
    source = _real_sessions_db()
    if not source.is_file():
        pytest.skip(f"no real sessions.db at {source}; set up StudyLoop first")

    receipt = run_live_copy_migration_receipt(source)

    assert receipt["to_version"] == CURRENT_VERSION == 48
    assert receipt["from_version"] <= 48
    assert set(receipt["counts"]) >= {"sessions", "messages"} | ontology.ONTOLOGY_TABLES
    assert receipt["counts"]["sessions"] > 0
    serialized = json.dumps(receipt, sort_keys=True)
    assert str(source) not in serialized

    output = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "data"
        / "ontology-migration-v48-receipt.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    write_baseline_evidence(receipt, output)


@pytest.mark.live_ontology
def test_real_corpus_online_backup_acceptance() -> None:
    """Deliverable #8: full acceptance run against the real corpus.

    Coverage 100%, zero domain/range/FK/orphan violations, identical
    logical hash across two full rebuilds, cold rebuild <= 5s. Writes
    ``docs/data/ontology-tier1-baseline-upstream.json`` (aggregates only)
    and reports any delta against the A2 baseline captured at 15:03Z.
    """
    source_value = os.environ.get("STUDYLOOP_ONTOLOGY_SOURCE")
    source = Path(source_value).expanduser() if source_value else _real_sessions_db()
    if not source.is_file():
        pytest.skip(f"no real sessions.db at {source}; set up StudyLoop first")

    evidence = run_live_copy_acceptance(source)

    assert evidence["source_sentinels_unchanged"] is True
    assert evidence["coverage"]["coverage_ratio"] == 1.0
    assert evidence["coverage"]["missing_sessions"] == 0
    assert evidence["integrity"] == {
        "orphan_session_individuals": 0,
        "orphan_structural_rows": 0,
        "foreign_key_violations": 0,
        "domain_range_violations": 0,
    }
    assert (
        evidence["first_full_rebuild"]["logical_hash"]
        == evidence["second_full_rebuild"]["logical_hash"]
    )
    assert evidence["first_full_rebuild"]["elapsed_seconds"] <= 5
    assert (
        evidence["incremental_rebuild"]["logical_hash"]
        == evidence["second_full_rebuild"]["logical_hash"]
    )
    assert evidence["status"]["healthy"] is True
    assert str(source) not in json.dumps(evidence, sort_keys=True)

    # A2's canonical baseline, captured 2026-09-07T15:03:50Z at 5,678
    # sessions / 133,559 messages (docs/data/ontology-tier1-baseline.json in
    # the SessionWeaver reference repo). The corpus has moved since then --
    # record the delta rather than asserting an exact match.
    a2_baseline = {"session_count": 5678, "message_count": 133559}
    evidence["a2_baseline_delta"] = {
        "a2_baseline_captured_at_utc": "2026-09-07T15:03:50Z",
        "a2_baseline_session_count": a2_baseline["session_count"],
        "a2_baseline_message_count": a2_baseline["message_count"],
        "session_count_delta": (
            evidence["source"]["session_count"] - a2_baseline["session_count"]
        ),
        "message_count_delta": (
            evidence["source"]["message_count"] - a2_baseline["message_count"]
        ),
        "explanation": (
            "This package's own upstream corpus has continued to capture "
            "sessions since A2's baseline snapshot; a nonzero, non-negative "
            "delta here is expected corpus growth, not a regression."
        ),
    }

    output = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "data"
        / "ontology-tier1-baseline-upstream.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    write_baseline_evidence(evidence, output)
