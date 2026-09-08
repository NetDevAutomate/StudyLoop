"""Scope-aware deterministic Markdown projection from authoritative concept state."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import pytest
import yaml
from agent_session_tools.context.provenance import Origin
from agent_session_tools.context.scope import ScopePolicy, apply_policy
from agent_session_tools.context.store import ContextStore, NativeSource

from agent_session_tools.context.concepts import ConceptService, _ConceptRepository

_NOW = "2026-09-08T12:00:00+00:00"
_MARKER = ".session-weaver-projection.json"
_MANIFEST = ".session-weaver-projection-manifest.json"


class ProductionStore(Protocol):
    conn: sqlite3.Connection
    db_path: Path
    config_path: Path


def _capture(
    store: ProductionStore,
    body: str,
    *,
    session_id: str = "fixture-session-1",
    key: str = "projection-evidence",
) -> str:
    return ContextStore(store.conn).capture(
        NativeSource(
            session_id=session_id,
            native_key=key,
            harness="fixture",
            native_kind="message:user",
            native_locator=f"fixture://{session_id}/{key}",
            parser_version="projection-test-v1",
            machine_id="fixture-machine",
            body=body,
            origin=Origin.CONVERSATION,
            recorded_at=_NOW,
        )
    )


def _bound_document(
    quote: str,
    *,
    title: str = "Visible bound concept",
    statement: str = "Published statement.",
) -> dict[str, Any]:
    return {
        "concepts": [
            {
                "type": "Finding",
                "title": title,
                "description": statement,
                "tags": ["projection", "session-weaver"],
                "confidence": 0.9,
                "quotes": [{"quote": quote}],
            }
        ]
    }


def _concept_counts(conn: sqlite3.Connection) -> tuple[int, ...]:
    return tuple(
        conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in (
            "context_assertions",
            "context_citations",
            "context_concepts",
            "context_concept_events",
            "context_concept_fts",
        )
    )


def test_project_writes_one_visible_bound_concept_without_mutating_database(
    production_store: ProductionStore,
    tmp_path: Path,
) -> None:
    quote = "PRIVATE EVIDENCE BODY MUST NOT BE PROJECTED"
    _capture(production_store, quote)
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    created = service.winddown(
        "fixture-session-1",
        _bound_document(quote),
        actor="fixture-model",
    )
    concept_id = created.concept_ids[0]
    before = _concept_counts(production_store.conn)
    before_dump = tuple(production_store.conn.iterdump())
    out = tmp_path / "projection"

    report = service.project(out)

    assert report.status == "ok"
    assert report.selected == report.rendered == report.created == report.writes == 1
    assert (
        report.unchanged == report.replaced == report.deleted == report.conflicts == 0
    )
    assert report.skipped_unavailable == report.skipped_retired == 0
    assert report.scope == "unclassified"
    assert report.project is None
    assert len(report.policy_digest) == 64
    assert report.access_revision >= 0
    assert _concept_counts(production_store.conn) == before
    assert tuple(production_store.conn.iterdump()) == before_dump

    expected_name = f"{concept_id[:12]}-visible-bound-concept.md"
    generated = out / expected_name
    assert generated.is_file()
    payload = generated.read_bytes()
    text = payload.decode("utf-8")
    assert "\r" not in text
    assert quote not in text
    assert f"concept_id: {json.dumps(concept_id)}" in text
    assert 'concept_kind: "Finding"' in text
    assert 'binding_state: "bound"' in text
    assert 'standing: "proposed"' in text
    assert 'model_authorship: "model-proposed"' in text
    assert 'citation_binding: "machine-confirmed"' in text
    assert text.endswith("\nPublished statement.\n")

    marker = json.loads((out / _MARKER).read_text(encoding="utf-8"))
    assert marker == {
        "owner": "session-weaver",
        "project": None,
        "schema": 1,
        "scope": "unclassified",
    }
    manifest = json.loads((out / _MANIFEST).read_text(encoding="utf-8"))
    assert manifest == {
        expected_name: {
            "concept_id": concept_id,
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    }


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(root.iterdir())}


def test_project_rerun_is_byte_identical_and_reports_unchanged(
    production_store: ProductionStore,
    tmp_path: Path,
) -> None:
    quote = "rerun exact evidence"
    _capture(production_store, quote, key="rerun-evidence")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    service.winddown(
        "fixture-session-1",
        _bound_document(quote, title="Stable rerun"),
        actor="fixture-model",
    )
    out = tmp_path / "projection-rerun"
    first = service.project(out)
    before = _tree_bytes(out)

    second = service.project(out)

    assert first.created == first.writes == 1
    assert second.status == "ok"
    assert second.selected == second.rendered == second.unchanged == 1
    assert second.created == second.replaced == second.deleted == second.writes == 0
    assert _tree_bytes(out) == before


def _seed_legacy(
    store: ProductionStore,
    *,
    title: str,
    statement: str,
    source_session_id: str | None,
) -> str:
    identity = _ConceptRepository(store.conn, now=lambda: _NOW).seed_legacy(
        original_bytes=f"legacy:{title}:{statement}".encode(),
        kind="Finding",
        title=title,
        statement=statement,
        tags=("legacy", "projection"),
        confidence=0.8,
        source_session_id=source_session_id,
        source_uri="sessionweaver://session/fixture-session-1",
        producer="fixture-writer/0.1",
    )
    store.conn.commit()
    return identity


def test_project_authorizes_bound_and_provenanced_legacy_but_omits_unavailable_and_retired(
    production_store: ProductionStore,
    tmp_path: Path,
) -> None:
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    _capture(production_store, "visible bound quote", key="visible-bound")
    visible = service.winddown(
        "fixture-session-1",
        _bound_document("visible bound quote", title="Visible bound"),
        actor="fixture-model",
    ).concept_ids[0]
    _capture(production_store, "retired bound quote", key="retired-bound")
    retired = service.winddown(
        "fixture-session-1",
        _bound_document("retired bound quote", title="Retired bound"),
        actor="fixture-model",
    ).concept_ids[0]
    assert (
        service.transition(retired, "retired", actor="owner", reason="obsolete").writes
        == 1
    )
    legacy = _seed_legacy(
        production_store,
        title="Visible legacy",
        statement="Legacy projected statement.",
        source_session_id="fixture-session-1",
    )
    _seed_legacy(
        production_store,
        title="Unavailable legacy",
        statement="Must not project.",
        source_session_id=None,
    )

    report = service.project(tmp_path / "authorized-projection")

    assert report.selected == report.rendered == report.created == 2
    assert report.skipped_unavailable == 1
    assert report.skipped_retired == 1
    manifest = json.loads(
        (tmp_path / "authorized-projection" / _MANIFEST).read_text(encoding="utf-8")
    )
    assert len(manifest) == 2
    assert any(name.startswith(visible[:12]) for name in manifest)
    legacy_name = next(name for name in manifest if name.startswith("legacy-"))
    assert legacy.removeprefix("legacy:")[:12] in legacy_name
    legacy_text = (tmp_path / "authorized-projection" / legacy_name).read_text(
        encoding="utf-8"
    )
    assert 'binding_state: "legacy-unbound"' in legacy_text
    assert 'citation_binding: "absent"' in legacy_text
    assert 'standing: "proposed"' in legacy_text
    assert "Legacy projected statement." in legacy_text


def test_project_rechecks_complete_bound_visibility_after_evidence_withdrawal(
    production_store: ProductionStore,
    tmp_path: Path,
) -> None:
    quote = "withdrawn projection evidence"
    evidence_id = _capture(production_store, quote, key="withdrawn-projection")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    service.winddown(
        "fixture-session-1",
        _bound_document(quote, title="Withdrawn concept"),
        actor="fixture-model",
    )
    local = production_store.conn.execute(
        "SELECT instance FROM context_access_state WHERE id=1"
    ).fetchone()[0]
    production_store.conn.execute(
        "INSERT INTO context_replica_peers VALUES (?,?,?,?,?)",
        ("projection-peer", "remote", "local-node", local, _NOW),
    )
    production_store.conn.execute(
        "INSERT INTO context_replica_denials VALUES (?,?,?,?,?,?)",
        ("projection-peer", "unclassified", "evidence", evidence_id, 1, "withdrawn"),
    )
    production_store.conn.commit()

    report = service.project(tmp_path / "withdrawn-projection")

    assert report.selected == report.rendered == report.created == 0
    assert report.skipped_unavailable == 1
    assert (
        json.loads(
            (tmp_path / "withdrawn-projection" / _MANIFEST).read_text(encoding="utf-8")
        )
        == {}
    )


def test_retirement_removes_only_the_exact_stale_managed_file(
    production_store: ProductionStore,
    tmp_path: Path,
) -> None:
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    for key, quote, title in (
        ("retire-first", "first retirement quote", "First retained sibling"),
        ("retire-second", "second retirement quote", "Second becomes stale"),
    ):
        _capture(production_store, quote, key=key)
        service.winddown(
            "fixture-session-1",
            _bound_document(quote, title=title, statement=f"{title} statement."),
            actor="fixture-model",
        )
    concept_ids = [
        row[0]
        for row in production_store.conn.execute(
            "SELECT id FROM context_concepts ORDER BY title"
        )
    ]
    out = tmp_path / "retirement-projection"
    first = service.project(out)
    initial_manifest = json.loads((out / _MANIFEST).read_text(encoding="utf-8"))
    stale_name = next(
        name
        for name, entry in initial_manifest.items()
        if entry["concept_id"] == concept_ids[1]
    )
    sibling_name = next(name for name in initial_manifest if name != stale_name)
    sibling_bytes = (out / sibling_name).read_bytes()

    assert (
        service.transition(
            concept_ids[1], "retired", actor="owner", reason="obsolete"
        ).writes
        == 1
    )
    second = service.project(out)

    assert first.created == 2
    assert second.status == "ok"
    assert second.selected == second.rendered == second.unchanged == 1
    assert second.deleted == second.writes == 1
    assert second.created == second.replaced == second.conflicts == 0
    assert second.skipped_retired == 1
    assert not (out / stale_name).exists()
    assert (out / sibling_name).read_bytes() == sibling_bytes
    assert list(json.loads((out / _MANIFEST).read_text(encoding="utf-8"))) == [
        sibling_name
    ]


def test_filename_collision_is_refused_before_output_creation(
    production_store: ProductionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    for index in range(2):
        quote = f"collision quote {index}"
        _capture(production_store, quote, key=f"collision-{index}")
        service.winddown(
            "fixture-session-1",
            _bound_document(quote, title=f"Collision {index}"),
            actor="fixture-model",
        )
    monkeypatch.setattr(
        "agent_session_tools.context.projection._filename", lambda _concept: "same.md"
    )
    out = tmp_path / "collision-projection"

    report = service.project(out)

    assert report.status == "conflict"
    assert report.conflicts == 1
    assert report.selected == report.rendered == 2
    assert report.writes == 0
    assert not out.exists()


def test_symlink_output_root_is_refused_without_touching_target(
    production_store: ProductionStore,
    tmp_path: Path,
) -> None:
    quote = "symlink root evidence"
    _capture(production_store, quote, key="symlink-root")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    service.winddown(
        "fixture-session-1",
        _bound_document(quote, title="Symlink root"),
        actor="fixture-model",
    )
    target = tmp_path / "outside"
    target.mkdir()
    sentinel = target / "sentinel.txt"
    sentinel.write_bytes(b"user-owned")
    linked = tmp_path / "linked-output"
    linked.symlink_to(target, target_is_directory=True)

    report = service.project(linked)

    assert report.status == "conflict"
    assert report.conflicts == 1
    assert report.writes == 0
    assert sentinel.read_bytes() == b"user-owned"
    assert set(target.iterdir()) == {sentinel}


def test_exact_crash_orphan_is_adopted_but_manifest_is_published(
    production_store: ProductionStore,
    tmp_path: Path,
) -> None:
    quote = "crash orphan evidence"
    _capture(production_store, quote, key="crash-orphan")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    service.winddown(
        "fixture-session-1",
        _bound_document(quote, title="Adopt exact orphan"),
        actor="fixture-model",
    )
    complete = tmp_path / "complete-projection"
    service.project(complete)
    generated_name = next(
        name for name in _tree_bytes(complete) if name.endswith(".md")
    )
    orphan = tmp_path / "orphan-projection"
    orphan.mkdir()
    (orphan / _MARKER).write_bytes((complete / _MARKER).read_bytes())
    (orphan / generated_name).write_bytes((complete / generated_name).read_bytes())

    report = service.project(orphan)

    assert report.status == "ok"
    assert report.unchanged == 1
    assert report.created == report.replaced == report.deleted == report.writes == 0
    assert (orphan / _MANIFEST).read_bytes() == (complete / _MANIFEST).read_bytes()


def test_manifest_failure_restores_prior_tree_and_cleans_invocation_artifacts(
    production_store: ProductionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_session_tools.context.projection as projection_module

    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    for index in range(2):
        quote = f"manifest rollback quote {index}"
        _capture(production_store, quote, key=f"manifest-rollback-{index}")
        service.winddown(
            "fixture-session-1",
            _bound_document(quote, title=f"Manifest rollback {index}"),
            actor="fixture-model",
        )
    out = tmp_path / "manifest-rollback"
    service.project(out)
    before = _tree_bytes(out)
    retire_id = production_store.conn.execute(
        "SELECT id FROM context_concepts ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    assert (
        service.transition(
            retire_id, "retired", actor="owner", reason="rollback fixture"
        ).writes
        == 1
    )
    real_write = projection_module._write_atomic

    def fail_manifest(descriptor: int, name: str, payload: bytes) -> None:
        if name == _MANIFEST:
            raise OSError("PRIVATE MANIFEST FAILURE")
        real_write(descriptor, name, payload)

    monkeypatch.setattr(projection_module, "_write_atomic", fail_manifest)

    report = service.project(out)

    assert report.status == "storage_failure"
    assert report.writes == 0
    assert _tree_bytes(out) == before
    assert not any(name.endswith(".tmp") for name in _tree_bytes(out))


@pytest.mark.parametrize(
    "checkpoint",
    (
        "after_temp_open",
        "after_temp_write",
        "after_temp_fsync",
        "before_replace",
        "after_replace",
        "after_directory_fsync",
        "before_manifest",
        "after_manifest",
    ),
)
def test_initial_publication_interruption_leaves_no_invocation_files(
    production_store: ProductionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    checkpoint: str,
) -> None:
    import agent_session_tools.context.projection as projection_module

    quote = f"interruption evidence {checkpoint}"
    _capture(production_store, quote, key=f"interrupt-{checkpoint}")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    service.winddown(
        "fixture-session-1",
        _bound_document(quote, title=f"Interrupt {checkpoint}"),
        actor="fixture-model",
    )
    injected = False

    def fail_once(name: str) -> None:
        nonlocal injected
        if name == checkpoint and not injected:
            injected = True
            raise OSError(f"PRIVATE INTERRUPTION {checkpoint}")

    monkeypatch.setattr(projection_module, "_checkpoint", fail_once)
    out = tmp_path / f"interrupt-{checkpoint}"

    report = service.project(out)

    assert injected is True
    assert report.status == "storage_failure"
    assert report.writes == 0
    assert out.is_dir()
    assert list(out.iterdir()) == []


def test_unowned_and_modified_files_are_preserved_and_reported_as_conflicts(
    production_store: ProductionStore,
    tmp_path: Path,
) -> None:
    quote = "ownership conflict evidence"
    _capture(production_store, quote, key="ownership-conflict")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    service.winddown(
        "fixture-session-1",
        _bound_document(quote, title="Ownership conflict"),
        actor="fixture-model",
    )
    unowned = tmp_path / "unowned"
    unowned.mkdir()
    arbitrary = unowned / "notes.txt"
    arbitrary.write_bytes(b"user-owned")

    first_conflict = service.project(unowned)

    assert first_conflict.status == "conflict"
    assert first_conflict.conflicts == 1
    assert arbitrary.read_bytes() == b"user-owned"
    assert set(unowned.iterdir()) == {arbitrary}

    out = tmp_path / "managed-conflict"
    service.project(out)
    generated = next(path for path in out.iterdir() if path.suffix == ".md")
    generated.write_bytes(generated.read_bytes() + b"user modification\n")
    extra = out / "notes.txt"
    extra.write_bytes(b"also user-owned")
    before = _tree_bytes(out)

    second_conflict = service.project(out)

    assert second_conflict.status == "conflict"
    assert second_conflict.conflicts == 2
    assert second_conflict.writes == 0
    assert _tree_bytes(out) == before


@pytest.mark.parametrize("entry", ("generated", "marker", "manifest"))
def test_symlinked_projection_entries_are_refused_and_external_bytes_are_untouched(
    production_store: ProductionStore,
    tmp_path: Path,
    entry: str,
) -> None:
    quote = f"symlink child evidence {entry}"
    _capture(production_store, quote, key=f"symlink-child-{entry}")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    service.winddown(
        "fixture-session-1",
        _bound_document(quote, title=f"Symlink child {entry}"),
        actor="fixture-model",
    )
    out = tmp_path / f"symlink-child-{entry}"
    service.project(out)
    generated = next(path for path in out.iterdir() if path.suffix == ".md")
    selected = {
        "generated": generated,
        "marker": out / _MARKER,
        "manifest": out / _MANIFEST,
    }[entry]
    selected.unlink()
    external = tmp_path / f"external-{entry}"
    external.write_bytes(b"external-user-bytes")
    selected.symlink_to(external)

    report = service.project(out)

    assert report.status == "conflict"
    assert report.conflicts >= 1
    assert report.writes == 0
    assert selected.is_symlink()
    assert external.read_bytes() == b"external-user-bytes"


@pytest.mark.parametrize(
    "checkpoint",
    ("before_prepublication_recheck", "after_manifest"),
)
def test_access_generation_drift_before_or_after_publication_restores_prior_manifest(
    production_store: ProductionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    checkpoint: str,
) -> None:
    import agent_session_tools.context.projection as projection_module

    quote = f"generation drift evidence {checkpoint}"
    _capture(production_store, quote, key=f"generation-{checkpoint}")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    concept_id = service.winddown(
        "fixture-session-1",
        _bound_document(quote, title=f"Generation {checkpoint}"),
        actor="fixture-model",
    ).concept_ids[0]
    out = tmp_path / f"generation-{checkpoint}"
    service.project(out)
    before = _tree_bytes(out)
    assert (
        service.transition(
            concept_id, "accepted", actor="owner", reason="force replacement"
        ).writes
        == 1
    )
    injected = False

    def change_generation(name: str) -> None:
        nonlocal injected
        if name != checkpoint or injected:
            return
        injected = True
        production_store.conn.execute(
            "INSERT INTO context_projects VALUES ('drift-away','unclassified','fixture',?)",
            (_NOW,),
        )
        production_store.conn.execute(
            "DELETE FROM context_projects WHERE id='drift-away'"
        )
        production_store.conn.commit()

    monkeypatch.setattr(projection_module, "_checkpoint", change_generation)

    report = service.project(out)

    assert injected is True
    assert report.status == "stale_snapshot"
    assert report.writes == 0
    assert _tree_bytes(out) == before
    assert not any(name.endswith((".tmp", ".bak")) for name in _tree_bytes(out))


def test_policy_scope_drift_after_publication_restores_prior_tree(
    production_store: ProductionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_session_tools.context.projection as projection_module

    quote = "policy drift evidence"
    _capture(production_store, quote, key="policy-drift")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    concept_id = service.winddown(
        "fixture-session-1",
        _bound_document(quote, title="Policy drift"),
        actor="fixture-model",
    ).concept_ids[0]
    out = tmp_path / "policy-drift"
    service.project(out)
    before = _tree_bytes(out)
    service.transition(concept_id, "accepted", actor="owner", reason="replacement")
    injected = False

    def change_policy(name: str) -> None:
        nonlocal injected
        if name != "after_manifest" or injected:
            return
        injected = True
        config = yaml.safe_load(
            production_store.config_path.read_text(encoding="utf-8")
        )
        config["memory"]["default_scope"] = "personal"
        production_store.config_path.write_text(
            yaml.safe_dump(config, sort_keys=False),
            encoding="utf-8",
        )

    monkeypatch.setattr(projection_module, "_checkpoint", change_policy)

    report = service.project(out)

    assert injected is True
    assert report.status == "stale_snapshot"
    assert report.writes == 0
    assert _tree_bytes(out) == before


def test_logical_concept_state_drift_is_detected_even_without_access_generation_change(
    production_store: ProductionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_session_tools.context.projection as projection_module

    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    concept_ids: list[str] = []
    for index in range(2):
        quote = f"logical drift quote {index}"
        _capture(production_store, quote, key=f"logical-drift-{index}")
        concept_ids.extend(
            service.winddown(
                "fixture-session-1",
                _bound_document(quote, title=f"Logical drift {index}"),
                actor="fixture-model",
            ).concept_ids
        )
    out = tmp_path / "logical-drift"
    service.project(out)
    before = _tree_bytes(out)
    service.transition(concept_ids[0], "accepted", actor="owner", reason="replacement")
    revision_before = production_store.conn.execute(
        "SELECT revision FROM context_access_state WHERE id=1"
    ).fetchone()[0]
    injected = False

    def retire_other_concept(name: str) -> None:
        nonlocal injected
        if name != "before_postpublication_recheck" or injected:
            return
        injected = True
        result = service.transition(
            concept_ids[1], "retired", actor="owner", reason="concurrent retirement"
        )
        assert result.writes == 1

    monkeypatch.setattr(projection_module, "_checkpoint", retire_other_concept)

    report = service.project(out)

    assert injected is True
    assert report.status == "stale_snapshot"
    assert report.writes == 0
    assert _tree_bytes(out) == before
    assert (
        production_store.conn.execute(
            "SELECT revision FROM context_access_state WHERE id=1"
        ).fetchone()[0]
        == revision_before
    )


def test_stale_snapshot_rollback_preserves_user_modified_published_file(
    production_store: ProductionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_session_tools.context.projection as projection_module

    quote = "rollback modification evidence"
    _capture(production_store, quote, key="rollback-user-modification")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    concept_id = service.winddown(
        "fixture-session-1",
        _bound_document(quote, title="Rollback modification"),
        actor="fixture-model",
    ).concept_ids[0]
    out = tmp_path / "rollback-user-modification"
    service.project(out)
    old_manifest = (out / _MANIFEST).read_bytes()
    service.transition(concept_id, "accepted", actor="owner", reason="replacement")
    injected = False

    def modify_then_stale(name: str) -> None:
        nonlocal injected
        if name != "after_manifest" or injected:
            return
        injected = True
        generated = next(path for path in out.iterdir() if path.suffix == ".md")
        generated.write_bytes(generated.read_bytes() + b"user edit after publication\n")
        production_store.conn.execute(
            "INSERT INTO context_projects VALUES ('rollback-drift','unclassified','fixture',?)",
            (_NOW,),
        )
        production_store.conn.execute(
            "DELETE FROM context_projects WHERE id='rollback-drift'"
        )
        production_store.conn.commit()

    monkeypatch.setattr(projection_module, "_checkpoint", modify_then_stale)

    report = service.project(out)

    generated = next(path for path in out.iterdir() if path.suffix == ".md")
    assert report.status == "stale_snapshot"
    assert report.conflicts == 1
    assert report.writes == 0
    assert generated.read_bytes().endswith(b"user edit after publication\n")
    assert (out / _MANIFEST).read_bytes() == old_manifest
    assert not any(path.name.endswith((".tmp", ".bak")) for path in out.iterdir())


@pytest.mark.parametrize("swap", ("root", "parent"))
def test_output_directory_swap_races_fail_closed(
    production_store: ProductionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    swap: str,
) -> None:
    import agent_session_tools.context.projection as projection_module

    quote = f"directory swap evidence {swap}"
    _capture(production_store, quote, key=f"directory-swap-{swap}")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    service.winddown(
        "fixture-session-1",
        _bound_document(quote, title=f"Directory swap {swap}"),
        actor="fixture-model",
    )
    parent = tmp_path / f"parent-{swap}"
    parent.mkdir()
    out = parent / "projection"
    outside_parent = tmp_path / f"outside-{swap}"
    outside_parent.mkdir()
    outside_output = outside_parent / "projection"
    outside_output.mkdir()
    pinned_parent = tmp_path / f"pinned-parent-{swap}"
    pinned_output = parent / "pinned-output"
    injected = False

    def swap_path(name: str) -> None:
        nonlocal injected, pinned_output
        if name != "after_temp_fsync" or injected:
            return
        injected = True
        if swap == "root":
            out.rename(pinned_output)
            out.symlink_to(outside_output, target_is_directory=True)
        else:
            parent.rename(pinned_parent)
            parent.symlink_to(outside_parent, target_is_directory=True)
            pinned_output = pinned_parent / "projection"

    monkeypatch.setattr(projection_module, "_checkpoint", swap_path)

    report = service.project(out)

    assert injected is True
    assert report.status == "storage_failure"
    assert report.writes == 0
    assert list(outside_output.iterdir()) == []
    assert pinned_output.is_dir()
    assert list(pinned_output.iterdir()) == []


def test_scope_reclassification_deletes_only_the_newly_hidden_session_concept(
    production_store: ProductionStore,
    tmp_path: Path,
) -> None:
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    ids: dict[str, str] = {}
    for index in (1, 2):
        session_id = f"fixture-session-{index}"
        quote = f"scope reclassification quote {index}"
        _capture(
            production_store,
            quote,
            session_id=session_id,
            key=f"scope-reclassification-{index}",
        )
        ids[session_id] = service.winddown(
            session_id,
            _bound_document(quote, title=f"Scope reclassification {index}"),
            actor="fixture-model",
        ).concept_ids[0]
    out = tmp_path / "scope-reclassification"
    service.project(out)
    before_manifest = json.loads((out / _MANIFEST).read_text(encoding="utf-8"))
    hidden_name = next(
        name
        for name, entry in before_manifest.items()
        if entry["concept_id"] == ids["fixture-session-2"]
    )
    retained_name = next(name for name in before_manifest if name != hidden_name)
    retained_bytes = (out / retained_name).read_bytes()
    production_store.conn.execute(
        "INSERT INTO context_projects VALUES ('hidden-work','work','manual',?)",
        (_NOW,),
    )
    production_store.conn.execute(
        "INSERT INTO context_session_projects VALUES (?,?,?)",
        ("fixture-session-2", "hidden-work", "explicit"),
    )
    production_store.conn.commit()

    report = service.project(out)

    assert report.status == "ok"
    assert report.selected == report.unchanged == 1
    assert report.skipped_unavailable == 1
    assert report.deleted == report.writes == 1
    assert not (out / hidden_name).exists()
    assert (out / retained_name).read_bytes() == retained_bytes


def test_explicit_project_selector_is_bound_to_marker_and_filters_other_projects(
    production_store: ProductionStore,
    tmp_path: Path,
) -> None:
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    ids: list[str] = []
    for index in (1, 2):
        session_id = f"fixture-session-{index}"
        quote = f"project selector quote {index}"
        _capture(
            production_store,
            quote,
            session_id=session_id,
            key=f"project-selector-{index}",
        )
        ids.extend(
            service.winddown(
                session_id,
                _bound_document(quote, title=f"Project selector {index}"),
                actor="fixture-model",
            ).concept_ids
        )
    config = yaml.safe_load(production_store.config_path.read_text(encoding="utf-8"))
    config["memory"]["projects"] = {
        "alpha": {"scope": "unclassified", "roots": []},
        "beta": {"scope": "unclassified", "roots": []},
    }
    production_store.config_path.write_text(
        yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )
    apply_policy(
        production_store.conn,
        ScopePolicy.from_config(config),
        actor="projection-test",
        dry_run=False,
    )
    production_store.conn.executemany(
        "INSERT INTO context_session_projects VALUES (?,?,?)",
        (
            ("fixture-session-1", "alpha", "explicit"),
            ("fixture-session-2", "beta", "explicit"),
        ),
    )
    production_store.conn.commit()
    alpha_out = tmp_path / "project-alpha"

    alpha = service.project(alpha_out, project="alpha")
    wrong_selector = service.project(alpha_out, project="beta")
    beta = service.project(tmp_path / "project-beta", project="beta")

    assert alpha.status == beta.status == "ok"
    assert alpha.selected == beta.selected == 1
    assert alpha.project == "alpha" and beta.project == "beta"
    assert alpha.skipped_unavailable == beta.skipped_unavailable == 1
    assert wrong_selector.status == "conflict"
    assert wrong_selector.writes == 0
    alpha_marker = json.loads((alpha_out / _MARKER).read_text(encoding="utf-8"))
    assert alpha_marker["project"] == "alpha"
    alpha_manifest = json.loads((alpha_out / _MANIFEST).read_text(encoding="utf-8"))
    assert {entry["concept_id"] for entry in alpha_manifest.values()} == {ids[0]}


def test_acceptance_replaces_same_filename_with_honest_standing(
    production_store: ProductionStore,
    tmp_path: Path,
) -> None:
    quote = "acceptance replacement evidence"
    _capture(production_store, quote, key="acceptance-replacement")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    concept_id = service.winddown(
        "fixture-session-1",
        _bound_document(quote, title="Acceptance replacement"),
        actor="fixture-model",
    ).concept_ids[0]
    out = tmp_path / "acceptance-replacement"
    service.project(out)
    name = next(path.name for path in out.iterdir() if path.suffix == ".md")
    assert (
        service.transition(
            concept_id, "accepted", actor="owner", reason="reviewed"
        ).writes
        == 1
    )

    report = service.project(out)

    assert report.replaced == report.writes == 1
    assert report.created == report.deleted == report.unchanged == 0
    text = (out / name).read_text(encoding="utf-8")
    assert 'standing: "accepted"' in text
    assert 'model_authorship: "model-proposed"' in text
    assert 'citation_binding: "machine-confirmed"' in text


def test_unicode_slug_and_manifest_order_are_stable(
    production_store: ProductionStore,
    tmp_path: Path,
) -> None:
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    titles = ("Zulu concept", "Café Δelta / 数据 🙂")
    for index, title in enumerate(titles):
        quote = f"unicode ordering quote {index}"
        _capture(production_store, quote, key=f"unicode-order-{index}")
        service.winddown(
            "fixture-session-1",
            _bound_document(quote, title=title),
            actor="fixture-model",
        )
    out = tmp_path / "unicode-order"

    service.project(out)
    first = _tree_bytes(out)
    service.project(out)

    assert _tree_bytes(out) == first
    manifest_text = (out / _MANIFEST).read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert list(manifest) == sorted(manifest)
    assert any("-café-δelta-数据.md" in name for name in manifest)
    assert (
        manifest_text
        == json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


@pytest.mark.parametrize("metadata", (_MARKER, _MANIFEST))
def test_tampered_projection_metadata_is_preserved_and_refused(
    production_store: ProductionStore,
    tmp_path: Path,
    metadata: str,
) -> None:
    quote = f"metadata tamper evidence {metadata}"
    _capture(production_store, quote, key=f"metadata-tamper-{metadata}")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    service.winddown(
        "fixture-session-1",
        _bound_document(quote, title="Metadata tamper"),
        actor="fixture-model",
    )
    out = tmp_path / f"metadata-tamper-{metadata.removeprefix('.')}"
    service.project(out)
    target = out / metadata
    target.write_bytes(b'{"tampered":true}\n')
    before = _tree_bytes(out)

    report = service.project(out)

    assert report.status == "conflict"
    assert report.conflicts == 1
    assert report.writes == 0
    assert _tree_bytes(out) == before


def test_modified_stale_managed_file_is_not_deleted(
    production_store: ProductionStore,
    tmp_path: Path,
) -> None:
    quote = "modified stale evidence"
    _capture(production_store, quote, key="modified-stale")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    concept_id = service.winddown(
        "fixture-session-1",
        _bound_document(quote, title="Modified stale"),
        actor="fixture-model",
    ).concept_ids[0]
    out = tmp_path / "modified-stale"
    service.project(out)
    generated = next(path for path in out.iterdir() if path.suffix == ".md")
    generated.write_bytes(generated.read_bytes() + b"user-owned change\n")
    before = _tree_bytes(out)
    service.transition(concept_id, "retired", actor="owner", reason="obsolete")

    report = service.project(out)

    assert report.status == "conflict"
    assert report.conflicts == 1
    assert report.deleted == report.writes == 0
    assert _tree_bytes(out) == before


@pytest.mark.parametrize(
    "checkpoint",
    (
        "after_backup",
        "after_temp_fsync",
        "after_replace",
        "after_directory_fsync",
        "before_manifest",
        "after_manifest",
    ),
)
def test_update_interruption_restores_previous_manifest_and_files(
    production_store: ProductionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    checkpoint: str,
) -> None:
    import agent_session_tools.context.projection as projection_module

    quote = f"update interruption evidence {checkpoint}"
    _capture(production_store, quote, key=f"update-interrupt-{checkpoint}")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    concept_id = service.winddown(
        "fixture-session-1",
        _bound_document(quote, title=f"Update interruption {checkpoint}"),
        actor="fixture-model",
    ).concept_ids[0]
    out = tmp_path / f"update-interrupt-{checkpoint}"
    service.project(out)
    before = _tree_bytes(out)
    service.transition(concept_id, "accepted", actor="owner", reason="replace")
    injected = False

    def fail_once(name: str) -> None:
        nonlocal injected
        if name == checkpoint and not injected:
            injected = True
            raise OSError(f"PRIVATE UPDATE INTERRUPTION {checkpoint}")

    monkeypatch.setattr(projection_module, "_checkpoint", fail_once)

    report = service.project(out)

    assert injected is True
    assert report.status == "storage_failure"
    assert report.writes == 0
    assert _tree_bytes(out) == before
    assert not any(path.name.endswith((".tmp", ".bak")) for path in out.iterdir())


def test_postpublication_file_change_is_preserved_and_prevents_success(
    production_store: ProductionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_session_tools.context.projection as projection_module

    quote = "postpublication integrity evidence"
    _capture(production_store, quote, key="postpublication-integrity")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    concept_id = service.winddown(
        "fixture-session-1",
        _bound_document(quote, title="Postpublication integrity"),
        actor="fixture-model",
    ).concept_ids[0]
    out = tmp_path / "postpublication-integrity"
    service.project(out)
    old_manifest = (out / _MANIFEST).read_bytes()
    service.transition(concept_id, "accepted", actor="owner", reason="replace")
    injected = False

    def modify_published_file(name: str) -> None:
        nonlocal injected
        if name != "after_manifest" or injected:
            return
        injected = True
        generated = next(path for path in out.iterdir() if path.suffix == ".md")
        generated.write_bytes(generated.read_bytes() + b"concurrent user edit\n")

    monkeypatch.setattr(projection_module, "_checkpoint", modify_published_file)

    report = service.project(out)

    generated = next(path for path in out.iterdir() if path.suffix == ".md")
    assert injected is True
    assert report.status == "storage_failure"
    assert report.conflicts == 1
    assert report.writes == 0
    assert generated.read_bytes().endswith(b"concurrent user edit\n")
    assert (out / _MANIFEST).read_bytes() == old_manifest
    assert not any(path.name.endswith((".tmp", ".bak")) for path in out.iterdir())


def test_projection_root_and_files_use_private_modes(
    production_store: ProductionStore,
    tmp_path: Path,
) -> None:
    quote = "private mode evidence"
    _capture(production_store, quote, key="private-mode")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    service.winddown(
        "fixture-session-1",
        _bound_document(quote, title="Private modes"),
        actor="fixture-model",
    )
    out = tmp_path / "private-modes"

    service.project(out)

    assert stat.S_IMODE(out.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in out.iterdir())


def test_manifest_path_traversal_is_refused_without_touching_external_file(
    production_store: ProductionStore,
    tmp_path: Path,
) -> None:
    quote = "manifest traversal evidence"
    _capture(production_store, quote, key="manifest-traversal")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    service.winddown(
        "fixture-session-1",
        _bound_document(quote, title="Manifest traversal"),
        actor="fixture-model",
    )
    out = tmp_path / "manifest-traversal"
    service.project(out)
    outside = tmp_path / "outside.md"
    outside.write_bytes(b"user-owned")
    manifest = json.loads((out / _MANIFEST).read_text(encoding="utf-8"))
    entry = next(iter(manifest.values()))
    (out / _MANIFEST).write_text(
        json.dumps({"../outside.md": entry}, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )

    report = service.project(out)

    assert report.status == "conflict"
    assert report.writes == 0
    assert outside.read_bytes() == b"user-owned"


def test_tombstoned_source_session_is_omitted(
    production_store: ProductionStore,
    tmp_path: Path,
) -> None:
    quote = "tombstoned projection evidence"
    _capture(production_store, quote, key="tombstoned-projection")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    service.winddown(
        "fixture-session-1",
        _bound_document(quote, title="Tombstoned projection"),
        actor="fixture-model",
    )
    production_store.conn.execute(
        "INSERT INTO context_tombstones VALUES (?,?,?)",
        ("fixture-session-1", "delete-fixture-session-1", _NOW),
    )
    production_store.conn.commit()

    report = service.project(tmp_path / "tombstoned-projection")

    assert report.status == "ok"
    assert report.selected == report.rendered == report.created == 0
    assert report.skipped_unavailable == 1


@pytest.mark.parametrize("fail", (False, True))
def test_projection_closes_output_descriptors_on_success_and_failure(
    production_store: ProductionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail: bool,
) -> None:
    import agent_session_tools.context.projection as projection_module

    quote = f"descriptor closure evidence {fail}"
    _capture(production_store, quote, key=f"descriptor-closure-{fail}")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    service.winddown(
        "fixture-session-1",
        _bound_document(quote, title=f"Descriptor closure {fail}"),
        actor="fixture-model",
    )
    real_open = projection_module._open_output_directory
    descriptors: list[int] = []

    @contextmanager
    def tracked_open(path: Path):
        with real_open(path) as output:
            descriptors.extend((output.parent_descriptor, output.descriptor))
            yield output

    monkeypatch.setattr(projection_module, "_open_output_directory", tracked_open)
    if fail:
        monkeypatch.setattr(
            projection_module,
            "_checkpoint",
            lambda name: (
                (_ for _ in ()).throw(OSError("fixture failure"))
                if name == "before_manifest"
                else None
            ),
        )

    report = service.project(tmp_path / f"descriptor-closure-{fail}")

    assert report.status == ("storage_failure" if fail else "ok")
    assert descriptors
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


# --- A3b2-fix adversarial review closure (F1-F12 plus council-required tests) ---


def test_db_side_policy_digest_drift_raises_scope_error_and_rolls_back(
    production_store: ProductionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F1: a bare upstream ScopeError from DB-side policy digest drift must be
    caught and rolled back, not escape uncaught and orphan .bak litter."""
    import agent_session_tools.context.projection as projection_module

    quote = "policy digest drift evidence"
    _capture(production_store, quote, key="policy-digest-drift")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    concept_id = service.winddown(
        "fixture-session-1",
        _bound_document(quote, title="Policy digest drift"),
        actor="fixture-model",
    ).concept_ids[0]
    out = tmp_path / "policy-digest-drift"
    service.project(out)
    before = _tree_bytes(out)
    assert (
        service.transition(
            concept_id, "accepted", actor="owner", reason="force replacement"
        ).writes
        == 1
    )
    original_digest = production_store.conn.execute(
        "SELECT digest FROM context_policy_state WHERE id=1"
    ).fetchone()[0]
    injected = False

    def corrupt_policy_digest(name: str) -> None:
        nonlocal injected
        if name != "after_manifest" or injected:
            return
        injected = True
        raw = sqlite3.connect(production_store.db_path)
        try:
            raw.execute(
                "UPDATE context_policy_state SET digest=? WHERE id=1", ("a" * 64,)
            )
            raw.commit()
        finally:
            raw.close()

    monkeypatch.setattr(projection_module, "_checkpoint", corrupt_policy_digest)

    report = service.project(out)

    assert injected is True
    assert report.status == "stale_snapshot"
    assert report.writes == 0
    assert _tree_bytes(out) == before
    assert not any(name.endswith((".tmp", ".bak")) for name in _tree_bytes(out))

    raw = sqlite3.connect(production_store.db_path)
    try:
        raw.execute(
            "UPDATE context_policy_state SET digest=? WHERE id=1", (original_digest,)
        )
        raw.commit()
    finally:
        raw.close()

    followup = service.project(out)
    assert followup.status == "ok"
    assert followup.replaced == 1


def test_partial_backup_cleanup_failure_is_recorded_and_never_touches_published_files(
    production_store: ProductionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F2 + council test (b): a mid-loop backup-unlink failure during commit()
    must be idempotent and never unwind already-published content."""
    import agent_session_tools.context.projection as projection_module

    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    concept_ids: list[str] = []
    for index in range(2):
        quote = f"partial cleanup quote {index}"
        _capture(production_store, quote, key=f"partial-cleanup-{index}")
        concept_ids.extend(
            service.winddown(
                "fixture-session-1",
                _bound_document(quote, title=f"Partial cleanup {index}"),
                actor="fixture-model",
            ).concept_ids
        )
    out = tmp_path / "partial-cleanup"
    service.project(out)
    for concept_id in concept_ids:
        assert (
            service.transition(
                concept_id, "accepted", actor="owner", reason="force replace"
            ).writes
            == 1
        )

    real_unlink = os.unlink
    attempts = {"count": 0}

    def flaky_unlink(path: Any, *args: Any, **kwargs: Any) -> None:
        name = path if isinstance(path, str) else os.fsdecode(path)
        if name.endswith(".bak"):
            attempts["count"] += 1
            if attempts["count"] == 2:
                raise OSError("PRIVATE BACKUP CLEANUP FAILURE")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(projection_module.os, "unlink", flaky_unlink)

    report = service.project(out)

    assert attempts["count"] == 3
    assert report.status == "ok"
    assert report.replaced == 2
    assert report.conflicts == 1
    assert report.writes == 2
    tree = _tree_bytes(out)
    bak_names = [name for name in tree if name.endswith(".bak")]
    assert len(bak_names) == 1
    manifest = json.loads((out / _MANIFEST).read_text(encoding="utf-8"))
    assert len(manifest) == 2
    for name, entry in manifest.items():
        payload = tree[name]
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"]
        assert 'standing: "accepted"' in payload.decode("utf-8")


def test_rollback_preserves_managed_file_when_backup_is_tampered_at_commit_time(
    production_store: ProductionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F6: if a mutation's .bak is missing or tampered when rollback runs, the
    live (already-published) content must be preserved, not deleted outright."""
    import agent_session_tools.context.projection as projection_module

    quote = "tampered backup evidence"
    _capture(production_store, quote, key="tampered-backup")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    concept_id = service.winddown(
        "fixture-session-1",
        _bound_document(quote, title="Tampered backup"),
        actor="fixture-model",
    ).concept_ids[0]
    out = tmp_path / "tampered-backup"
    service.project(out)
    generated = next(path for path in out.iterdir() if path.suffix == ".md")
    assert (
        service.transition(
            concept_id, "accepted", actor="owner", reason="force replace"
        ).writes
        == 1
    )
    tampered = False

    def tamper_backup_then_fail_manifest(name: str) -> None:
        nonlocal tampered
        if name == "after_backup" and not tampered:
            tampered = True
            backups = [path for path in out.iterdir() if path.name.endswith(".bak")]
            assert len(backups) == 1
            backups[0].write_bytes(b"TAMPERED BACKUP BYTES")
        elif name == "before_manifest":
            raise OSError("PRIVATE MANIFEST INTERRUPTION")

    monkeypatch.setattr(
        projection_module, "_checkpoint", tamper_backup_then_fail_manifest
    )

    report = service.project(out)

    assert tampered is True
    assert report.status == "storage_failure"
    assert report.conflicts >= 1
    assert generated.is_file()
    text = generated.read_text(encoding="utf-8")
    assert 'standing: "accepted"' in text


def test_rollback_contains_per_mutation_failures_and_continues_unwinding(
    production_store: ProductionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F4 + council test (c): one mutation's restore failing during rollback
    must not abort the unwind of the remaining mutations, nor escape uncaught."""
    import agent_session_tools.context.projection as projection_module

    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    concept_ids: list[str] = []
    for index in range(2):
        quote = f"rollback containment quote {index}"
        _capture(production_store, quote, key=f"rollback-containment-{index}")
        concept_ids.extend(
            service.winddown(
                "fixture-session-1",
                _bound_document(quote, title=f"Rollback containment {index}"),
                actor="fixture-model",
            ).concept_ids
        )
    out = tmp_path / "rollback-containment"
    service.project(out)
    before = _tree_bytes(out)
    for concept_id in concept_ids:
        assert (
            service.transition(
                concept_id, "accepted", actor="owner", reason="force replace"
            ).writes
            == 1
        )

    real_replace = os.replace
    restore_attempts = {"count": 0}

    def flaky_replace(src: Any, dst: Any, *args: Any, **kwargs: Any) -> None:
        name = src if isinstance(src, str) else os.fsdecode(src)
        if name.endswith(".bak"):
            restore_attempts["count"] += 1
            if restore_attempts["count"] == 1:
                raise OSError("PRIVATE ROLLBACK RESTORE FAILURE")
        real_replace(src, dst, *args, **kwargs)

    def fail_before_manifest(name: str) -> None:
        if name == "before_manifest":
            raise OSError("PRIVATE MANIFEST INTERRUPTION")

    monkeypatch.setattr(projection_module.os, "replace", flaky_replace)
    monkeypatch.setattr(projection_module, "_checkpoint", fail_before_manifest)

    report = service.project(out)

    assert restore_attempts["count"] == 2
    assert report.status == "storage_failure"
    assert report.conflicts >= 1
    tree = _tree_bytes(out)
    assert tree[_MANIFEST] == before[_MANIFEST]
    md_names = [name for name in before if name.endswith(".md")]
    assert len(md_names) == 2
    restored = [name for name in md_names if tree[name] == before[name]]
    not_restored = [name for name in md_names if tree[name] != before[name]]
    assert len(restored) == 1
    assert len(not_restored) == 1
    assert 'standing: "accepted"' in tree[not_restored[0]].decode("utf-8")


def test_symlinked_ancestor_of_output_directory_is_resolved_but_leaf_still_refused(
    production_store: ProductionStore,
    tmp_path: Path,
) -> None:
    """F3/F5: a symlinked ancestor of --out must be resolved and accepted, but a
    symlinked leaf must still be refused even when its own parent is a symlink."""
    quote = "symlinked ancestor evidence"
    _capture(production_store, quote, key="symlinked-ancestor")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    service.winddown(
        "fixture-session-1",
        _bound_document(quote, title="Symlinked ancestor"),
        actor="fixture-model",
    )
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(real_root, target_is_directory=True)
    out = linked_root / "projection"

    report = service.project(out)

    assert report.status == "ok"
    assert report.created == report.writes == 1
    real_out = real_root / "projection"
    assert real_out.is_dir()
    assert not real_out.is_symlink()
    generated = next(path for path in real_out.iterdir() if path.suffix == ".md")
    assert generated.is_file()

    outside = tmp_path / "outside-leaf-target"
    outside.mkdir()
    leaf_linked = linked_root / "leaf-projection"
    leaf_linked.symlink_to(outside, target_is_directory=True)

    leaf_report = service.project(leaf_linked)

    assert leaf_report.status == "conflict"
    assert leaf_report.writes == 0
    assert list(outside.iterdir()) == []


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="Exercises macOS's stock /tmp -> /private/tmp ancestor symlink",
)
def test_unresolved_slash_tmp_ancestor_is_accepted_on_macos(
    production_store: ProductionStore,
) -> None:
    """F3/F5: projecting under an unresolved /tmp/... path must succeed on macOS,
    where every ancestor up to /tmp is itself a symlink to /private/tmp."""
    quote = "unresolved slash tmp evidence"
    _capture(production_store, quote, key="unresolved-slash-tmp")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    service.winddown(
        "fixture-session-1",
        _bound_document(quote, title="Unresolved slash tmp"),
        actor="fixture-model",
    )
    out = Path(f"/tmp/session-weaver-a3b2-fix-{uuid4().hex}")
    try:
        report = service.project(out)

        assert report.status == "ok"
        assert report.created == report.writes == 1
        assert out.is_dir()
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_directory_swap_after_successful_apply_is_unwound_through_the_descriptor(
    production_store: ProductionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F7 + council test (d): swapping --out for a symlink strictly after apply()
    has fully published must still be unwound through the held descriptor rather
    than bailing out and silently leaving orphaned, fully-published bytes behind."""
    import agent_session_tools.context.projection as projection_module

    quote = "post-apply directory swap evidence"
    _capture(production_store, quote, key="post-apply-swap")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    service.winddown(
        "fixture-session-1",
        _bound_document(quote, title="Post apply swap"),
        actor="fixture-model",
    )
    parent = tmp_path / "post-apply-swap-parent"
    parent.mkdir()
    out = parent / "projection"
    outside_parent = tmp_path / "post-apply-swap-outside"
    outside_parent.mkdir()
    outside_output = outside_parent / "projection"
    outside_output.mkdir()
    pinned_output = parent / "pinned-projection"
    injected = False

    def swap_after_apply(name: str) -> None:
        nonlocal injected
        if name != "after_manifest" or injected:
            return
        injected = True
        out.rename(pinned_output)
        out.symlink_to(outside_output, target_is_directory=True)

    monkeypatch.setattr(projection_module, "_checkpoint", swap_after_apply)

    report = service.project(out)

    assert injected is True
    assert report.status == "storage_failure"
    assert report.writes == 0
    assert report.conflicts >= 1
    assert list(outside_output.iterdir()) == []
    assert pinned_output.is_dir()
    assert list(pinned_output.iterdir()) == []


def test_schema_mismatch_detected_after_first_snapshot_returns_storage_failure_report(
    production_store: ProductionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F9: the shared schema verifier's mismatch failure, when it fires on a
    recheck after an initial snapshot already exists, must return through the
    documented ProjectionReport contract rather than a bare exception."""
    import agent_session_tools.context.concept_schema as concept_schema_module
    import agent_session_tools.context.projection as projection_module

    quote = "schema drift evidence"
    _capture(production_store, quote, key="schema-drift")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    service.winddown(
        "fixture-session-1",
        _bound_document(quote, title="Schema drift"),
        actor="fixture-model",
    )
    out = tmp_path / "schema-drift"
    service.project(out)
    before = _tree_bytes(out)
    injected = False

    def corrupt_fingerprint(name: str) -> None:
        nonlocal injected
        if name != "before_prepublication_recheck" or injected:
            return
        injected = True
        monkeypatch.setattr(concept_schema_module, "SCHEMA_FINGERPRINT", "0" * 64)

    monkeypatch.setattr(projection_module, "_checkpoint", corrupt_fingerprint)

    report = service.project(out)

    assert injected is True
    assert report.status == "storage_failure"
    assert report.writes == 0
    assert _tree_bytes(out) == before


def test_schema_mismatch_on_first_capture_is_a_documented_library_raise(
    production_store: ProductionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F9: with no snapshot ever captured, there is no scope/policy/counts to
    build a ProjectionReport from; this re-raise (mirroring every other
    before-first-snapshot RuntimeError in this module) is intentional and is
    safely contained at the CLI boundary (see test_concept_cli.py)."""
    import agent_session_tools.context.concept_schema as concept_schema_module

    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    monkeypatch.setattr(concept_schema_module, "SCHEMA_FINGERPRINT", "0" * 64)

    with pytest.raises(RuntimeError, match="mismatch"):
        service.project(tmp_path / "schema-mismatch-first-capture")


def test_concurrent_projection_invocation_sees_in_flight_publication_and_fails_closed(
    production_store: ProductionStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Council test (a): two concurrent invocations targeting the same --out.
    Posture: fail closed with a clear conflict status, no lock. The second
    invocation is started (on its own thread, so it gets its own read-boundary
    context) from inside the first's in-flight publication and must see the
    first's not-yet-published temp file and refuse cleanly, touching nothing."""
    import agent_session_tools.context.projection as projection_module

    quote = "concurrent invocation evidence"
    _capture(production_store, quote, key="concurrent-invocation")
    service = ConceptService(production_store.db_path, now=lambda: _NOW)
    service.winddown(
        "fixture-session-1",
        _bound_document(quote, title="Concurrent invocation"),
        actor="fixture-model",
    )
    out = tmp_path / "concurrent-projection"
    second_reports: list[Any] = []
    injected = False

    def race_second_invocation(name: str) -> None:
        nonlocal injected
        if name != "after_temp_fsync" or injected:
            return
        injected = True

        def run_second() -> None:
            second_reports.append(service.project(out))

        thread = threading.Thread(target=run_second)
        thread.start()
        thread.join(timeout=30)

    monkeypatch.setattr(projection_module, "_checkpoint", race_second_invocation)

    first_report = service.project(out)

    assert injected is True
    assert len(second_reports) == 1
    second_report = second_reports[0]
    assert second_report.status == "conflict"
    assert second_report.writes == 0
    assert first_report.status == "ok"
    assert first_report.writes == 1
    assert not any(name.endswith(".tmp") for name in _tree_bytes(out))
