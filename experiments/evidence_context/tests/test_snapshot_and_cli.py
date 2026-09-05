"""Snapshot concurrency, work bounds, and disposable CLI acceptance tests."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from experiments.evidence_context.store import Citation, EvidenceStore, Relationship

CUTOFF = "2026-01-10T00:00:00Z"


def retrieve(store, **options):
    args = {
        "project": "synthetic-project",
        "scope": "personal",
        "as_of": CUTOFF,
        "max_bytes": 20000,
        "neighbor_turns": 0,
        "use_relationships": True,
    }
    args.update(options)
    return store.retrieve("cachepolicy", **args)


def test_retrieval_uses_one_snapshot_when_relationship_arrives_mid_query(store, record):
    store.conn.execute("PRAGMA journal_mode=WAL")
    seed = store.add_evidence(record())
    contrary = store.add_evidence(
        record(message_id="contrary", content="Contrary observation without the search term")
    )
    writer = EvidenceStore.open(store.path.resolve())
    writes = []
    errors = []

    def insert_after_seed_query(sql):
        if writes or "from relationships" not in sql.lower():
            return
        writes.append(True)
        try:
            writer.add_relationship(
                Relationship(
                    source_id=seed,
                    target_id=contrary,
                    kind="contradicts",
                    supporting_citations=(writer.cite(seed), writer.cite(contrary)),
                    asserted_at="2026-01-02T00:00:00Z",
                    available_at="2026-01-02T00:00:01Z",
                    origin="asserted",
                    review_state="reviewed",
                    reviewer="synthetic-concurrent-writer",
                )
            )
        except Exception as exc:  # SQLite suppresses trace callback exceptions.
            errors.append(exc)

    store.conn.set_trace_callback(insert_after_seed_query)
    try:
        first = retrieve(store)
    finally:
        store.conn.set_trace_callback(None)
        writer.close()
    assert writes, "The concurrent write must actually run to test isolation"
    assert not errors
    assert {item.version_id for item in first.evidence} == {seed}
    assert first.relationships == ()
    assert not store.conn.in_transaction
    second = retrieve(store)
    assert {item.version_id for item in second.evidence} == {seed, contrary}
    assert second.relationships


def test_retrieval_error_closes_owned_snapshot_but_preserves_caller_transaction(store, record):
    store.add_evidence(record())
    with pytest.raises(ValueError):
        retrieve(store, max_bytes=1)
    assert not store.conn.in_transaction
    store.conn.execute("BEGIN")
    try:
        with pytest.raises(ValueError):
            retrieve(store, max_bytes=1)
        assert store.conn.in_transaction
        assert retrieve(store).evidence
        assert store.conn.in_transaction
    finally:
        store.conn.rollback()


def test_same_origin_sibling_expansion_is_bounded_and_reports_incomplete(store, record):
    seed = store.add_evidence(record())
    cap = EvidenceStore.VERSION_SIBLING_LIMIT
    for index in range(cap * 3):
        store.add_evidence(record(content=f"Unrelated alternate version number {index}"))
    statements = []
    store.conn.set_trace_callback(statements.append)
    try:
        pack = retrieve(store, use_relationships=False, limit=100, max_bytes=200000)
    finally:
        store.conn.set_trace_callback(None)
    assert seed in {item.version_id for item in pack.evidence}
    assert len(pack.evidence) <= cap + 1
    assert "source_versions_omitted_due_to_limit" in pack.warnings
    assert "context_incomplete" in pack.warnings
    # This measures evidence resolution work, not merely final output truncation.
    resolutions = [sql for sql in statements if "from evidence where version_id=" in sql.lower()]
    assert len(resolutions) <= cap + 1


def test_ineligible_siblings_do_not_consume_visible_bound_or_reveal_hidden_counts(store, record):
    store.add_evidence(record())
    before = retrieve(store, use_relationships=False).to_dict()
    for index in range(EvidenceStore.VERSION_SIBLING_LIMIT + 2):
        store.add_evidence(
            record(content=f"Hidden version number {index}", available_at="2026-02-01T00:00:00Z")
        )
    assert retrieve(store, use_relationships=False).to_dict() == before


def test_cli_creates_synthetic_packs_and_refuses_existing_output(tmp_path):
    output = tmp_path / "demo"
    root = Path(__file__).resolve().parents[3]
    command = [sys.executable, "-m", "experiments.evidence_context", "--output", str(output)]
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    summary = json.loads((output / "summary.json").read_text())
    assert "not answer-quality evidence" in summary["purpose"]
    assert summary["semantic_retrieval"] == "not_run"
    keyword = json.loads((output / "keyword.json").read_text())
    relationships = json.loads((output / "relationships.json").read_text())
    assert len(keyword["evidence"]) == 1
    assert len(relationships["evidence"]) == 2
    assert relationships["relationships"][0]["kind"] == "contradicts"
    store = EvidenceStore.open((output / "evidence.db").resolve())
    try:
        for pack in (keyword, relationships):
            for item in pack["evidence"]:
                assert item["verification_status"] == "unverified_report"
                citation = Citation(**item["citation"])
                assert store.resolve_citation(citation) == citation.text
                assert item["source_locator"].startswith("synthetic:")
    finally:
        store.close()
    marker = output / "keep-me.txt"
    marker.write_text("existing user artifact")
    before = {path.name: path.read_bytes() for path in output.iterdir() if path.is_file()}
    repeated = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    assert repeated.returncode != 0
    assert marker.read_text() == "existing user artifact"
    assert {path.name: path.read_bytes() for path in output.iterdir() if path.is_file()} == before
