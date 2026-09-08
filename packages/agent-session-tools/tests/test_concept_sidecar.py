"""Concept-sidecar provisioning: exact lift, install/adopt/verify, fail-closed drift."""

from __future__ import annotations

import sqlite3
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest

from agent_session_tools.concept_sidecar import (
    SCHEMA_FINGERPRINT,
    SCHEMA_VERSION,
    UPSTREAM_SCHEMA_VERSION,
    SidecarError,
    ensure_concept_sidecar,
    verify_installed_sidecar,
)
from agent_session_tools.context.provenance import Origin
from agent_session_tools.context.store import NativeSource
from agent_session_tools.exporters.base import ExportStats, commit_batch
from agent_session_tools.migrations import CURRENT_VERSION, migrate

# The definitions are lifted byte-for-byte from SessionWeaver's
# session_weaver/concept_schema.py; SessionWeaver's verify_installed_schema refuses
# any store whose sidecar identity differs from this exact value. If this test
# fails, the lift has drifted and MUST be reconciled across both repositories —
# never re-pin without coordinating.
PINNED_SESSIONWEAVER_FINGERPRINT = "af95685e6e39e166148006519862bee3be1a15219d76772236a82890fe11011d"  # pragma: allowlist secret


def _native_source(
    session_id: str, key: str, kind: str, body: str, origin: Origin
) -> NativeSource:
    return NativeSource(
        session_id=session_id,
        native_key=key,
        harness="codex",
        native_kind=kind,
        native_locator=f"fixture://codex/{session_id}#{key}",
        parser_version="codex-native-v1",
        machine_id="fixture-machine",
        body=body,
        origin=origin,
        recorded_at="2026-09-07T12:00:00+00:00",
    )


def _fixture_batch(project: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    session_id = "sidecar-fixture-session"
    session = {
        "id": session_id,
        "source": "codex",
        "project_path": str(project),
        "git_branch": "main",
        "created_at": "2026-09-07T12:00:00+00:00",
        "updated_at": "2026-09-07T12:10:00+00:00",
        "metadata": "{}",
        "status": "added",
        "native_sources": [
            _native_source(
                session_id,
                "session-envelope",
                "session:metadata",
                "Envelope.",
                Origin.UNKNOWN,
            )
        ],
    }
    message = {
        "id": "sidecar-fixture-message-1",
        "session_id": session_id,
        "role": "user",
        "content": "Provision the concept sidecar.",
        "model": "fixture-model",
        "timestamp": "2026-09-07T12:01:00+00:00",
        "metadata": "{}",
        "seq": 1,
        "native_sources": [
            _native_source(
                session_id,
                "message-1",
                "message:user",
                "Provision the concept sidecar.",
                Origin.CONVERSATION,
            )
        ],
    }
    return [session], [message]


def _base_conn(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "sessions.db")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        files("agent_session_tools").joinpath("schema.sql").read_text(encoding="utf-8")
    )
    migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == CURRENT_VERSION
    return conn


def _production_conn(tmp_path: Path) -> sqlite3.Connection:
    conn = _base_conn(tmp_path)
    sessions, messages = _fixture_batch(tmp_path / "fixture-project")
    commit_batch(conn, sessions, messages, ExportStats())
    return conn


def test_fingerprint_is_pinned_to_the_sessionweaver_lift() -> None:
    assert SCHEMA_VERSION == 2
    assert UPSTREAM_SCHEMA_VERSION == CURRENT_VERSION == 47
    assert SCHEMA_FINGERPRINT == PINNED_SESSIONWEAVER_FINGERPRINT


def test_ensure_installs_on_a_fresh_production_store(tmp_path: Path) -> None:
    conn = _production_conn(tmp_path)
    try:
        assert ensure_concept_sidecar(conn) == "installed"
        verify_installed_sidecar(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == CURRENT_VERSION
        marker = conn.execute(
            "SELECT schema_version, schema_fingerprint FROM context_concept_schema WHERE id=1"
        ).fetchone()
        assert tuple(marker) == (SCHEMA_VERSION, SCHEMA_FINGERPRINT)
    finally:
        conn.close()


def test_ensure_is_idempotent(tmp_path: Path) -> None:
    conn = _production_conn(tmp_path)
    try:
        assert ensure_concept_sidecar(conn) == "installed"
        assert ensure_concept_sidecar(conn) == "verified"
    finally:
        conn.close()


def test_ensure_installs_from_base_schema_alone(tmp_path: Path) -> None:
    # schema.sql ships the context layer, so a migrated store needs no capture
    # to provision the sidecar.
    conn = _base_conn(tmp_path)
    try:
        assert ensure_concept_sidecar(conn) == "installed"
        verify_installed_sidecar(conn)
    finally:
        conn.close()


def test_ensure_skips_without_the_context_layer() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY)")
        conn.execute(f"PRAGMA user_version = {UPSTREAM_SCHEMA_VERSION}")
        assert ensure_concept_sidecar(conn) == "skipped: context layer not installed"
        assert (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='context_concept_schema'"
            ).fetchone()
            is None
        )
    finally:
        conn.close()


def test_ensure_fails_closed_on_object_drift(tmp_path: Path) -> None:
    conn = _production_conn(tmp_path)
    try:
        assert ensure_concept_sidecar(conn) == "installed"
        conn.execute("DROP TRIGGER context_concepts_immutable")
        with pytest.raises(SidecarError, match="incomplete or has fingerprint drift"):
            ensure_concept_sidecar(conn)
        with pytest.raises(SidecarError):
            verify_installed_sidecar(conn)
    finally:
        conn.close()


def test_ensure_requires_foreign_keys_on(tmp_path: Path) -> None:
    conn = _production_conn(tmp_path)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        with pytest.raises(SidecarError, match="foreign_keys"):
            ensure_concept_sidecar(conn)
    finally:
        conn.close()
