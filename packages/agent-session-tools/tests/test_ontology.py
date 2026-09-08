"""Deterministic Tier-1 ontology contracts.

Lifted from SessionWeaver's reference ``tests/test_ontology.py`` (read-only
lift source, per the phase-2 retrofit design). The ``production_store``
fixture used throughout is ``ontology_production_store`` from this package's
own ``tests/conftest.py`` (shared with ``test_ontology_live.py``); see that
fixture's docstring for why it is not merely similar to the reference
fixture but the same code. Every test body, assertion, and helper below is
otherwise unchanged from the reference.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from typing import Protocol

import pytest

import agent_session_tools.ontology as ontology
from agent_session_tools.ontology import (
    EXTRACTION_VERSION,
    ONTOLOGY_TABLES,
    CanonicalMessage,
    OntologyStatus,
    OntologyValidationError,
    canonical_messages,
    ontology_logical_hash,
    ontology_status,
    rebuild_ontology,
)


class ProductionStore(Protocol):
    """The production-schema fixture surface used by ontology tests."""

    conn: sqlite3.Connection


@pytest.fixture
def production_store(ontology_production_store):
    """Alias to the shared fixture, matching the reference test's fixture name."""
    return ontology_production_store


def _insert_session(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    source: str = "codex",
    project_path: str | None = "/Users/ataylor/code/example/project.py",
    git_branch: str | None = "main",
    created_at: str | None = "2026-09-07T10:00:00+00:00",
    updated_at: str | None = "2026-09-07T10:30:00+00:00",
    metadata: str | None = "{}",
) -> None:
    conn.execute(
        """
        INSERT INTO sessions(
            id, source, project_path, git_branch, created_at, updated_at, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            source,
            project_path,
            git_branch,
            created_at,
            updated_at,
            metadata,
        ),
    )


def _insert_message(
    conn: sqlite3.Connection,
    message_id: str,
    session_id: str,
    *,
    role: str,
    content: str | None,
    timestamp: str | None = None,
    seq: int | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO messages(id, session_id, role, content, timestamp, metadata, seq)
        VALUES (?, ?, ?, ?, ?, '{}', ?)
        """,
        (message_id, session_id, role, content, timestamp, seq),
    )


def _ids(messages: Iterable[CanonicalMessage]) -> list[str]:
    return [message.id for message in messages]


def test_canonical_messages_apply_the_normalization_matrix_and_tool_boundary(
    production_store: ProductionStore,
) -> None:
    """Only canonical user/assistant conversation text survives exact PoC filters."""
    conn = production_store.conn
    session_id = "canonical-matrix"
    _insert_session(conn, session_id)
    tool_119 = "[tool:" + ("x" * (119 - len("[tool:")))
    tool_120 = "[tool:" + ("x" * (120 - len("[tool:")))
    rows = (
        ("user", "  hello  "),
        ("assistant", "\nresponse\t"),
        ("tool_use", "ignored tool role"),
        ("tool_result", "ignored tool result"),
        ("system", "ignored system role"),
        ("user", None),
        ("assistant", " \t\n "),
        ("user", "  [tool:short]  "),
        ("assistant", tool_119),
        ("assistant", tool_120),
    )
    for seq, (role, content) in enumerate(rows, start=1):
        _insert_message(
            conn,
            f"matrix-{seq}",
            session_id,
            role=role,
            content=content,
            timestamp=f"2026-09-07T11:{seq:02d}:00+00:00",
            seq=seq,
        )
    conn.commit()

    messages = list(canonical_messages(conn, {session_id}))

    assert [(message.role, message.content) for message in messages] == [
        ("user", "hello"),
        ("assistant", "response"),
        ("assistant", tool_120),
    ]
    assert len(messages[-1].content) == 120
    assert list(canonical_messages(conn, [])) == []


def test_canonical_messages_deduplicate_per_session_in_canonical_order(
    production_store: ProductionStore,
) -> None:
    """Physical insertion order never chooses the duplicate survivor or result order."""
    conn = production_store.conn
    for session_id in ("dedup-forward", "dedup-reverse"):
        _insert_session(conn, session_id)

    forward = (
        ("forward-z", "same", "2026-09-07T09:00:00Z", 4),
        ("forward-a", " same ", "not-a-timestamp", 1),
    )
    reverse = (
        ("reverse-a", " same ", "not-a-timestamp", 1),
        ("reverse-z", "same", "2026-09-07T09:00:00Z", 4),
    )
    for message_id, content, timestamp, seq in forward:
        _insert_message(
            conn,
            message_id,
            "dedup-forward",
            role="user",
            content=content,
            timestamp=timestamp,
            seq=seq,
        )
    for message_id, content, timestamp, seq in reverse:
        _insert_message(
            conn,
            message_id,
            "dedup-reverse",
            role="user",
            content=content,
            timestamp=timestamp,
            seq=seq,
        )

    ordered_rows = (
        ("ordered-seq", "nonnull seq", "invalid", 9),
        ("ordered-valid-late", "valid late", "2026-09-07T12:00:00Z", None),
        ("ordered-invalid", "invalid timestamp", "not-a-timestamp", None),
        ("ordered-valid-early", "valid early", "2026-09-07T08:00:00+00:00", None),
        ("ordered-null", "null timestamp", None, None),
    )
    for message_id, content, timestamp, seq in reversed(ordered_rows):
        _insert_message(
            conn,
            message_id,
            "dedup-forward",
            role="assistant",
            content=content,
            timestamp=timestamp,
            seq=seq,
        )
    conn.commit()

    forward_messages = list(canonical_messages(conn, {"dedup-forward"}))
    reverse_messages = list(canonical_messages(conn, {"dedup-reverse"}))

    assert forward_messages[0].id == "forward-a"
    assert reverse_messages[0].id == "reverse-a"
    assert [message.content for message in forward_messages].count("same") == 1
    assert [message.content for message in reverse_messages].count("same") == 1
    assert _ids(forward_messages) == [
        "forward-a",
        "ordered-seq",
        "ordered-valid-early",
        "ordered-valid-late",
        "ordered-null",
        "ordered-invalid",
    ]


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _structural_id(session_id: str, entity_type: str, key: str) -> str:
    identity = {"key": key, "session_id": session_id, "type": entity_type}
    return hashlib.sha256(_canonical_json(identity).encode()).hexdigest()


def _table_snapshot(conn: sqlite3.Connection) -> dict[str, list[tuple[object, ...]]]:
    return {
        table: sorted(conn.execute(f"SELECT * FROM {table}").fetchall(), key=repr)
        for table in ONTOLOGY_TABLES
    }


def test_rebuild_materializes_tbox_structural_entities_and_shared_abox(
    production_store: ProductionStore,
) -> None:
    """The maintained graph preserves the measured Tier-1 entity semantics."""
    conn = production_store.conn
    parent_id = "12345678-1234-1234-1234-123456789abc"
    child_id = "agent-child"
    project_path = "/Users/ataylor/code/shared/project"
    artifact_path = "/Users/ataylor/code/shared/module.py"
    summary = "12 passed, 2 skipped, 1 deselected in 1.23s"
    _insert_session(
        conn, parent_id, project_path=project_path, git_branch="feat/ontology"
    )
    _insert_session(
        conn,
        child_id,
        project_path=project_path,
        git_branch="feat/ontology",
        metadata=json.dumps(
            {"transcript": f"/tmp/{parent_id}/subagents/agent-child.jsonl"}
        ),
    )
    _insert_message(
        conn,
        "structural-parent",
        parent_id,
        role="assistant",
        seq=1,
        timestamp="2026-09-07T11:00:00+00:00",
        content=(
            f"{summary}\n{artifact_path}\n"
            "```bash\nuv run pytest tests/test_ontology.py\n```\n"
            "$ uv run pytest tests/ignored-second-command.py"
        ),
    )
    _insert_message(
        conn,
        "structural-child",
        child_id,
        role="user",
        seq=1,
        timestamp="2026-09-07T11:05:00+00:00",
        content=f"Inspect {artifact_path}\n$ python -m pytest",
    )
    conn.commit()

    result = rebuild_ontology(conn)

    assert result.mode == "full"
    assert result.extraction_version == EXTRACTION_VERSION
    assert result.logical_hash == ontology_logical_hash(conn)
    assert {row[0] for row in conn.execute("SELECT name FROM ontology_class")} == {
        "Project",
        "Harness",
        "Session",
        "SubagentSession",
        "Artifact",
        "Command",
        "TestRun",
    }
    assert {row[0] for row in conn.execute("SELECT name FROM ontology_property")} == {
        "ranIn",
        "conductedBy",
        "childOf",
        "touched",
        "executed",
        "produced",
    }
    ontology_tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert ontology_tables >= ONTOLOGY_TABLES
    assert {
        "idx_ontology_structural_session_type",
        "idx_ontology_individual_class_label",
        "idx_ontology_relation_subject_predicate_object",
        "idx_ontology_relation_predicate_subject_object",
        "idx_ontology_relation_object_predicate_subject",
    } <= {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
    }

    parent_rows = conn.execute(
        """
        SELECT id, type, key, value, ts, extraction_version
        FROM ontology_structural
        WHERE session_id = ?
        ORDER BY type, key
        """,
        (parent_id,),
    ).fetchall()
    assert (
        _structural_id(parent_id, "project", project_path),
        "project",
        project_path,
        "feat/ontology",
        "2026-09-07T10:30:00+00:00",
        EXTRACTION_VERSION,
    ) in parent_rows
    assert (
        _structural_id(parent_id, "testrun", summary),
        "testrun",
        summary,
        summary,
        "2026-09-07T11:00:00+00:00",
        EXTRACTION_VERSION,
    ) in parent_rows
    assert conn.execute(
        """
        SELECT value FROM ontology_structural
        WHERE session_id = ? AND type = 'command' AND key = 'uv'
        """,
        (parent_id,),
    ).fetchone() == ("uv run pytest tests/test_ontology.py",)

    child_class = conn.execute(
        "SELECT class FROM ontology_individual WHERE id = ?", (f"session:{child_id}",)
    ).fetchone()
    assert child_class == ("SubagentSession",)
    assert conn.execute(
        "SELECT 1 FROM ontology_relation WHERE subject = ? "
        "AND predicate = 'childOf' AND object = ?",
        (f"session:{child_id}", f"session:{parent_id}"),
    ).fetchone() == (1,)
    assert conn.execute(
        "SELECT COUNT(*) FROM ontology_individual WHERE id = ?",
        (f"artifact:{artifact_path}",),
    ).fetchone() == (1,)
    assert conn.execute(
        "SELECT COUNT(*) FROM ontology_relation WHERE predicate = 'touched' AND object = ?",
        (f"artifact:{artifact_path}",),
    ).fetchone() == (2,)
    assert conn.execute(
        "SELECT attrs FROM ontology_individual WHERE id = 'command:uv'"
    ).fetchone() == (_canonical_json({"binary": "uv"}),)

    test_run_id = f"testrun:{parent_id}:{hashlib.sha256(summary.encode()).hexdigest()}"
    test_run_attrs = json.loads(
        conn.execute(
            "SELECT attrs FROM ontology_individual WHERE id = ?", (test_run_id,)
        ).fetchone()[0]
    )
    assert test_run_attrs == {
        "deselected": 1,
        "passed": 12,
        "skipped": 2,
        "summary": summary,
    }
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO ontology_structural(
                id, session_id, type, key, value, ts, extraction_version
            ) VALUES ('invalid', ?, 'widened-type', 'x', 'x', NULL, ?)
            """,
            (parent_id, EXTRACTION_VERSION),
        )
    conn.rollback()


def test_rebuild_and_reordered_source_insertion_have_the_same_logical_hash(
    production_store: ProductionStore,
) -> None:
    """The graph hash depends on canonical meaning, never source row order."""
    conn = production_store.conn
    session_id = "hash-order"
    _insert_session(conn, session_id)
    source_rows = (
        ("hash-z", "$ uv run pytest tests/z.py", "2026-09-07T11:02:00Z", 2),
        ("hash-a", "$ python -m pytest", "2026-09-07T11:01:00Z", 1),
    )
    for message_id, content, timestamp, seq in source_rows:
        _insert_message(
            conn,
            message_id,
            session_id,
            role="assistant",
            content=content,
            timestamp=timestamp,
            seq=seq,
        )
    conn.commit()

    first = rebuild_ontology(conn)
    first_structural = conn.execute(
        "SELECT * FROM ontology_structural ORDER BY id"
    ).fetchall()
    second = rebuild_ontology(conn)

    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    for message_id, content, timestamp, seq in reversed(source_rows):
        _insert_message(
            conn,
            message_id,
            session_id,
            role="assistant",
            content=content,
            timestamp=timestamp,
            seq=seq,
        )
    conn.commit()
    reordered = rebuild_ontology(conn)

    assert first.logical_hash == second.logical_hash == reordered.logical_hash
    assert (
        first_structural
        == conn.execute("SELECT * FROM ontology_structural ORDER BY id").fetchall()
    )


def test_failure_before_swap_preserves_the_previous_complete_graph(
    production_store: ProductionStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A staging failure cannot expose a partial graph or advance build state."""
    conn = production_store.conn
    baseline = rebuild_ontology(conn)
    snapshot = _table_snapshot(conn)
    _insert_session(conn, "rollback-source")
    _insert_message(
        conn,
        "rollback-message",
        "rollback-source",
        role="user",
        content="$ uv run pytest tests/new.py",
        timestamp="2026-09-07T11:00:00Z",
        seq=1,
    )
    conn.commit()

    def fail_before_swap(_conn: sqlite3.Connection) -> None:
        raise RuntimeError("injected before swap")

    monkeypatch.setattr(ontology, "_before_swap", fail_before_swap)

    with pytest.raises(RuntimeError, match="injected before swap"):
        rebuild_ontology(conn)

    assert ontology_logical_hash(conn) == baseline.logical_hash
    assert _table_snapshot(conn) == snapshot
    assert conn.in_transaction is False
    assert conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name LIKE '__ontology_%_next'"
    ).fetchone() == (0,)


def test_incremental_reextracts_newer_and_missing_sessions_then_matches_full(
    production_store: ProductionStore,
) -> None:
    """Incremental mode copies safe rows and rebuilds one complete equivalent A-Box."""
    conn = production_store.conn
    rebuild_ontology(conn)
    conn.execute(
        "UPDATE ontology_build_state SET completed_at = '2026-09-07T13:00:00Z'"
    )
    unchanged_before = conn.execute(
        "SELECT * FROM ontology_structural WHERE session_id = 'fixture-session-2' ORDER BY id"
    ).fetchall()
    conn.execute(
        "UPDATE sessions SET updated_at = '2026-09-07T14:00:00Z' WHERE id = 'fixture-session-1'"
    )
    _insert_message(
        conn,
        "incremental-newer-message",
        "fixture-session-1",
        role="assistant",
        content="$ uv run pytest tests/incremental.py",
        timestamp="2026-09-07T14:00:00Z",
        seq=99,
    )
    _insert_session(
        conn,
        "incremental-missing-project",
        updated_at="2026-09-07T12:00:00Z",
    )
    conn.commit()

    incremental = rebuild_ontology(conn, incremental=True)

    assert incremental.mode == "incremental"
    assert incremental.fallback_reason is None
    assert incremental.candidate_sessions == 2
    assert conn.execute(
        """
        SELECT value FROM ontology_structural
        WHERE session_id = 'fixture-session-1' AND type = 'command' AND key = 'uv'
        """
    ).fetchone() == ("uv run pytest tests/incremental.py",)
    assert conn.execute(
        """
        SELECT key FROM ontology_structural
        WHERE session_id = 'incremental-missing-project' AND type = 'project'
        """
    ).fetchone() == ("/Users/ataylor/code/example/project.py",)
    assert (
        unchanged_before
        == conn.execute(
            "SELECT * FROM ontology_structural WHERE session_id = 'fixture-session-2' ORDER BY id"
        ).fetchall()
    )

    full = rebuild_ontology(conn)
    assert incremental.logical_hash == full.logical_hash


@pytest.mark.parametrize(
    ("damage", "expected_reason"),
    (
        ("missing", "missing-build-state"),
        ("version", "extraction-version-mismatch"),
        ("invalid", "invalid-build-state"),
    ),
)
def test_incremental_invalid_state_falls_back_to_full(
    production_store: ProductionStore,
    damage: str,
    expected_reason: str,
) -> None:
    """Only a complete, current, parseable build state can authorize row reuse."""
    conn = production_store.conn
    baseline = rebuild_ontology(conn)
    if damage == "missing":
        conn.execute("DROP TABLE ontology_build_state")
    elif damage == "version":
        conn.execute(
            "UPDATE ontology_build_state SET extraction_version = 'tier1-obsolete'"
        )
    else:
        conn.execute("UPDATE ontology_build_state SET completed_at = 'not-a-timestamp'")
    conn.commit()

    result = rebuild_ontology(conn, incremental=True)

    assert result.mode == "full"
    assert result.fallback_reason == expected_reason
    assert result.logical_hash == baseline.logical_hash
    assert conn.execute(
        "SELECT extraction_version FROM ontology_build_state"
    ).fetchone() == (EXTRACTION_VERSION,)


def test_incremental_removes_absent_session_rows(
    production_store: ProductionStore,
) -> None:
    """Source deletion removes old structural rows, individuals, and relations."""
    conn = production_store.conn
    session_id = "incremental-removed"
    _insert_session(conn, session_id)
    _insert_message(
        conn,
        "incremental-removed-message",
        session_id,
        role="user",
        content="$ python -m pytest",
        timestamp="2026-09-07T11:00:00Z",
        seq=1,
    )
    conn.commit()
    rebuild_ontology(conn)

    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()

    result = rebuild_ontology(conn, incremental=True)

    assert result.mode == "incremental"
    assert conn.execute(
        "SELECT COUNT(*) FROM ontology_structural WHERE session_id = ?", (session_id,)
    ).fetchone() == (0,)
    assert conn.execute(
        "SELECT COUNT(*) FROM ontology_individual WHERE id = ?",
        (f"session:{session_id}",),
    ).fetchone() == (0,)
    assert conn.execute(
        """
        SELECT COUNT(*) FROM ontology_relation
        WHERE subject = ? OR object = ?
        """,
        (f"session:{session_id}", f"session:{session_id}"),
    ).fetchone() == (0,)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_incremental_unexplained_message_count_change_falls_back_to_full(
    production_store: ProductionStore,
) -> None:
    """A message change without a source freshness signal cannot reuse structure."""
    conn = production_store.conn
    rebuild_ontology(conn)
    _insert_message(
        conn,
        "unexplained-message",
        "fixture-session-1",
        role="assistant",
        content="$ python -m pytest tests/unexplained.py",
        timestamp="2026-09-07T14:00:00Z",
        seq=100,
    )
    conn.commit()

    result = rebuild_ontology(conn, incremental=True)

    assert result.mode == "full"
    assert result.fallback_reason == "unexplained-source-count-change"
    assert conn.execute(
        """
        SELECT COUNT(*) FROM ontology_structural
        WHERE session_id = 'fixture-session-1' AND type = 'command' AND key = 'python'
        """
    ).fetchone() == (1,)


def _healthy_status(
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> OntologyStatus:
    monkeypatch.setattr(ontology, "_utc_now", lambda: "9998-01-01T00:00:00Z")
    rebuild_ontology(conn)
    return ontology_status(conn)


def test_status_reports_a_healthy_graph_without_mutating_the_store(
    production_store: ProductionStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Health inspection is complete, deterministic, and strictly read-only."""
    conn = production_store.conn
    status = _healthy_status(conn, monkeypatch)
    schema_before = conn.execute(
        "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
    ).fetchall()
    changes_before = conn.total_changes

    repeated = ontology_status(conn)

    assert status.healthy is True
    assert repeated == status
    assert status.extraction_version == EXTRACTION_VERSION
    assert status.extraction_version_matches is True
    assert status.missing_tables == ()
    assert status.missing_indexes == ()
    assert status.schema_errors == ()
    assert status.covered_sessions == status.source_sessions
    assert status.missing_sessions == 0
    assert status.coverage_ratio == 1.0
    assert status.orphan_session_individuals == 0
    assert status.orphan_structural_rows == 0
    assert status.foreign_key_violations == 0
    assert status.domain_range_violations == 0
    assert status.source_counts_match is True
    assert status.fresh is True
    assert status.hash_matches is True
    assert status.diagnostics == ()
    assert conn.total_changes == changes_before
    assert (
        conn.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
        == schema_before
    )


@pytest.mark.parametrize("missing_kind", ("table", "index"))
def test_status_reports_each_missing_schema_component(
    production_store: ProductionStore,
    monkeypatch: pytest.MonkeyPatch,
    missing_kind: str,
) -> None:
    """A missing required table or traversal index is an explicit health fault."""
    conn = production_store.conn
    _healthy_status(conn, monkeypatch)
    if missing_kind == "table":
        conn.execute("DROP TABLE ontology_relation")
    else:
        conn.execute("DROP INDEX idx_ontology_relation_object_predicate_subject")
    conn.commit()

    status = ontology_status(conn)

    assert status.healthy is False
    if missing_kind == "table":
        assert "ontology_relation" in status.missing_tables
    else:
        assert (
            "idx_ontology_relation_object_predicate_subject" in status.missing_indexes
        )


@pytest.mark.parametrize(
    "replacement_sql",
    (
        """
        CREATE INDEX idx_ontology_relation_subject_predicate_object
        ON ontology_relation(subject, predicate, object)
        WHERE predicate = 'childOf'
        """,
        """
        CREATE UNIQUE INDEX idx_ontology_relation_subject_predicate_object
        ON ontology_relation(subject, predicate, object)
        """,
        """
        CREATE INDEX idx_ontology_relation_subject_predicate_object
        ON ontology_relation(subject DESC, predicate, object)
        """,
    ),
    ids=("partial", "unique", "descending-key"),
)
def test_status_rejects_noncanonical_index_semantics(
    production_store: ProductionStore,
    monkeypatch: pytest.MonkeyPatch,
    replacement_sql: str,
) -> None:
    """Canonical names and columns do not hide malformed index semantics."""
    conn = production_store.conn
    _healthy_status(conn, monkeypatch)
    index = "idx_ontology_relation_subject_predicate_object"
    conn.execute(f'DROP INDEX "{index}"')
    conn.execute(replacement_sql)
    conn.commit()

    status = ontology_status(conn)

    assert status.healthy is False
    assert status.missing_indexes == ()
    assert any(index in error for error in status.schema_errors)


def test_status_reports_session_coverage_below_ninety_nine_percent(
    production_store: ProductionStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Coverage below the public 99% threshold is unhealthy with exact counts."""
    conn = production_store.conn
    _healthy_status(conn, monkeypatch)
    missing_id = "session:fixture-session-1"
    conn.execute(
        "DELETE FROM ontology_relation WHERE subject = ? OR object = ?",
        (missing_id, missing_id),
    )
    conn.execute("DELETE FROM ontology_individual WHERE id = ?", (missing_id,))
    conn.commit()

    status = ontology_status(conn)

    assert status.healthy is False
    assert status.covered_sessions == 1
    assert status.missing_sessions == 1
    assert status.coverage_ratio == 0.5
    assert "session coverage 50.00% is below 99.00%" in status.diagnostics


@pytest.mark.parametrize(
    ("fault", "expected_field"),
    (
        ("newer", "fresh"),
        ("malformed", "fresh"),
        ("source-count", "source_counts_match"),
        ("version", "extraction_version_matches"),
        ("completed-at", "completed_at_valid"),
    ),
)
def test_status_reports_each_freshness_and_version_fault(
    production_store: ProductionStore,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    expected_field: str,
) -> None:
    """Freshness dimensions fail independently instead of being silently repaired."""
    conn = production_store.conn
    _healthy_status(conn, monkeypatch)
    if fault == "newer":
        conn.execute(
            "UPDATE sessions SET updated_at = '9999-01-01T00:00:00Z' WHERE id = 'fixture-session-1'"
        )
    elif fault == "malformed":
        conn.execute(
            "UPDATE sessions SET updated_at = 'not-a-timestamp' WHERE id = 'fixture-session-1'"
        )
    elif fault == "source-count":
        _insert_message(
            conn,
            "status-count-change",
            "fixture-session-1",
            role="assistant",
            content="count changed",
            seq=200,
        )
    elif fault == "version":
        conn.execute(
            "UPDATE ontology_build_state SET extraction_version = 'tier1-obsolete'"
        )
    else:
        conn.execute("UPDATE ontology_build_state SET completed_at = 'invalid'")
    conn.commit()

    status = ontology_status(conn)

    assert status.healthy is False
    assert not getattr(status, expected_field)
    if fault == "malformed":
        assert status.malformed_timestamps == ("fixture-session-1",)


@pytest.mark.parametrize("orphan_kind", ("individual", "structural"))
def test_status_reports_ontology_references_to_absent_sessions(
    production_store: ProductionStore,
    monkeypatch: pytest.MonkeyPatch,
    orphan_kind: str,
) -> None:
    """Both A-Box session ids and structural source references are checked."""
    conn = production_store.conn
    _healthy_status(conn, monkeypatch)
    if orphan_kind == "individual":
        conn.execute(
            """
            INSERT INTO ontology_individual(id, class, label, attrs)
            VALUES ('session:absent', 'Session', 'absent', '{}')
            """
        )
    else:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """
            INSERT INTO ontology_structural(
                id, session_id, type, key, value, ts, extraction_version
            ) VALUES (?, 'absent', 'project', 'unknown', '', NULL, ?)
            """,
            (_structural_id("absent", "project", "unknown"), EXTRACTION_VERSION),
        )
    conn.commit()

    status = ontology_status(conn)

    assert status.healthy is False
    if orphan_kind == "individual":
        assert status.orphan_session_individuals == 1
    else:
        assert status.orphan_structural_rows == 1


def test_status_reports_foreign_key_violation(
    production_store: ProductionStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Foreign-key diagnostics do not depend on connection enforcement state."""
    conn = production_store.conn
    _healthy_status(conn, monkeypatch)
    subject = conn.execute(
        "SELECT id FROM ontology_individual WHERE class IN ('Session', 'SubagentSession') LIMIT 1"
    ).fetchone()[0]
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        """
        INSERT INTO ontology_relation(subject, predicate, object)
        VALUES (?, 'ranIn', 'project:absent')
        """,
        (subject,),
    )
    conn.commit()

    status = ontology_status(conn)

    assert status.healthy is False
    assert status.foreign_key_violations == 1


def test_status_reports_recursive_domain_range_violation(
    production_store: ProductionStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid foreign keys are still unhealthy when relation typing is invalid."""
    conn = production_store.conn
    _healthy_status(conn, monkeypatch)
    project_id = conn.execute(
        "SELECT id FROM ontology_individual WHERE class = 'Project' LIMIT 1"
    ).fetchone()[0]
    harness_id = conn.execute(
        "SELECT id FROM ontology_individual WHERE class = 'Harness' LIMIT 1"
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO ontology_relation(subject, predicate, object)
        VALUES (?, 'conductedBy', ?)
        """,
        (project_id, harness_id),
    )
    conn.commit()

    status = ontology_status(conn)

    assert status.healthy is False
    assert status.foreign_key_violations == 0
    assert status.domain_range_violations == 1


def test_status_reports_logical_hash_tamper(
    production_store: ProductionStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Logical row tampering is detected independently of DDL and row order."""
    conn = production_store.conn
    _healthy_status(conn, monkeypatch)
    conn.execute(
        "UPDATE ontology_individual SET label = 'tampered' WHERE id = 'session:fixture-session-1'"
    )
    conn.commit()

    status = ontology_status(conn)

    assert status.healthy is False
    assert status.hash_matches is False
    assert status.recomputed_logical_hash != status.recorded_logical_hash


def test_structural_duplicate_matches_keep_the_first_canonical_timestamp(
    production_store: ProductionStore,
) -> None:
    """Test-run and artifact identity dedup retains the first canonical match."""
    conn = production_store.conn
    session_id = "structural-dedup"
    summary = "3 passed, 1 skipped in 0.42s"
    artifact = "/Users/ataylor/code/example/repeated.py"
    _insert_session(conn, session_id)
    for seq, timestamp in ((1, "2026-09-07T11:00:00Z"), (2, "2026-09-07T12:00:00Z")):
        _insert_message(
            conn,
            f"structural-dedup-{seq}",
            session_id,
            role="assistant",
            content=f"{summary}\n{artifact}\nmessage-{seq}",
            timestamp=timestamp,
            seq=seq,
        )
    conn.commit()

    rebuild_ontology(conn)

    assert conn.execute(
        """
        SELECT type, key, ts FROM ontology_structural
        WHERE session_id = ? AND type IN ('artifact', 'testrun')
        ORDER BY type
        """,
        (session_id,),
    ).fetchall() == [
        ("artifact", artifact, "2026-09-07T11:00:00Z"),
        ("testrun", summary, "2026-09-07T11:00:00Z"),
    ]


def test_extraction_keeps_frozen_platform_path_and_command_regex_boundaries(
    production_store: ProductionStore,
) -> None:
    """Tier-1 v2 does not broaden the measured macOS path or shell patterns."""
    conn = production_store.conn
    session_id = "frozen-regex"
    _insert_session(conn, session_id)
    _insert_message(
        conn,
        "frozen-regex-message",
        session_id,
        role="user",
        seq=1,
        content=(
            "/home/ataylor/code/example/not-matched.py\n"
            "/Users/ATaylor/code/example/not-matched.py\n"
            "```fish\nfish-command --not-matched\n```\n"
            "$ 9invalid-command argument\n"
            "$ echo matched-command"
        ),
    )
    conn.commit()

    rebuild_ontology(conn)

    assert conn.execute(
        "SELECT key, value FROM ontology_structural WHERE session_id = ? AND type = 'command'",
        (session_id,),
    ).fetchall() == [("echo", "echo matched-command")]
    assert conn.execute(
        "SELECT COUNT(*) FROM ontology_structural WHERE session_id = ? AND type = 'artifact'",
        (session_id,),
    ).fetchone() == (0,)


def test_parent_metadata_without_a_live_parent_still_types_subagent(
    production_store: ProductionStore,
) -> None:
    """PoC parent metadata controls class while childOf requires a live parent."""
    conn = production_store.conn
    missing_parent = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    _insert_session(
        conn,
        "metadata-subagent",
        metadata=json.dumps(
            {"transcript": f"/tmp/{missing_parent}/subagents/child.jsonl"}
        ),
    )
    conn.commit()

    rebuild_ontology(conn)

    assert conn.execute(
        "SELECT class FROM ontology_individual WHERE id = 'session:metadata-subagent'"
    ).fetchone() == ("SubagentSession",)
    assert conn.execute(
        "SELECT COUNT(*) FROM ontology_relation WHERE subject = 'session:metadata-subagent' "
        "AND predicate = 'childOf'"
    ).fetchone() == (0,)


def test_conflicting_attrs_for_one_stable_individual_are_validation_error(
    production_store: ProductionStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stable-id collision never silently adopts the first individual's attrs."""
    conn = production_store.conn
    baseline = rebuild_ontology(conn)
    _insert_session(conn, "individual-collision")
    _insert_message(
        conn,
        "individual-collision-message",
        "individual-collision",
        role="assistant",
        content="1 passed in 0.1s\n2 passed in 0.2s",
        seq=1,
    )
    conn.commit()
    monkeypatch.setattr(
        ontology,
        "_test_run_id",
        lambda _session_id, _summary: "testrun:forced-collision",
    )

    with pytest.raises(OntologyValidationError, match="conflicting individual id"):
        rebuild_ontology(conn)

    assert ontology_logical_hash(conn) == baseline.logical_hash


def test_ontology_tables_are_excluded_from_normal_sync_controls_and_dump_sql() -> None:
    """Normal delta sync stays positive while every maintained ontology table is local-only."""
    from agent_session_tools import sync

    assert sync.SYNC_TABLES
    assert sync.GLOBAL_SYNC_TABLES
    assert sync.TABLE_SYNC_COLUMNS
    assert all(sync.TABLE_SYNC_COLUMNS.values())
    assert sync.GLOBAL_TABLE_PRIMARY_KEYS
    assert all(sync.GLOBAL_TABLE_PRIMARY_KEYS.values())
    assert "sessions" in sync.SYNC_TABLES
    assert set(sync.SYNC_TABLES) <= set(sync.TABLE_SYNC_COLUMNS)
    assert set(sync.GLOBAL_SYNC_TABLES) <= set(sync.TABLE_SYNC_COLUMNS)
    assert set(sync.GLOBAL_SYNC_TABLES) <= set(sync.GLOBAL_TABLE_PRIMARY_KEYS)

    normal_allow_lists = (
        set(sync.SYNC_TABLES),
        set(sync.GLOBAL_SYNC_TABLES),
        set(sync.TABLE_SYNC_COLUMNS),
        set(sync.GLOBAL_TABLE_PRIMARY_KEYS),
    )
    for allow_list in normal_allow_lists:
        assert ONTOLOGY_TABLES.isdisjoint(allow_list)

    available_tables = set().union(*normal_allow_lists, ONTOLOGY_TABLES)
    dump_sql = "\n".join(
        sync._build_dump_queries(
            {"sync-sentinel"},
            available_tables,
            include_seq=True,
            parked_columns=sync.TABLE_SYNC_COLUMNS["parked_topics"],
        )
    )

    assert "INSERT INTO sessions" in dump_sql
    assert "FROM sessions" in dump_sql
    for table in ONTOLOGY_TABLES:
        assert table not in dump_sql


@pytest.mark.parametrize("timestamp_location", ("source", "build-state"))
def test_status_treats_blob_timestamps_as_unhealthy_diagnostics(
    production_store: ProductionStore,
    monkeypatch: pytest.MonkeyPatch,
    timestamp_location: str,
) -> None:
    conn = production_store.conn
    _healthy_status(conn, monkeypatch)
    if timestamp_location == "source":
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = 'fixture-session-1'",
            (sqlite3.Binary(b"not-text"),),
        )
    else:
        conn.execute(
            "UPDATE ontology_build_state SET completed_at = ?",
            (sqlite3.Binary(b"not-text"),),
        )
    conn.commit()

    status = ontology_status(conn)

    assert status.healthy is False
    if timestamp_location == "source":
        assert status.malformed_timestamps == ("fixture-session-1",)
        assert (
            "malformed non-null session updated_at values: fixture-session-1"
            in status.diagnostics
        )
    else:
        assert status.completed_at is None
        assert status.completed_at_valid is False
        assert "completed-at is missing or malformed" in status.diagnostics
