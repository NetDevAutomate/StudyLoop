"""Explicit scope config, preview/application and reusable row visibility."""

import json
import sqlite3
from pathlib import Path

import pytest

from agent_session_tools.context.provenance import Scope
from agent_session_tools.context.scope import (
    ScopeError,
    ScopePolicy,
    apply_policy,
    visibility_sql,
)


def policy(scope="personal", roots=None):
    return ScopePolicy.from_config(
        {
            "memory": {
                "default_scope": scope,
                "projects": {
                    "personal-project": {
                        "scope": "personal",
                        "roots": roots or ["/fixtures/personal"],
                    },
                    "work-project": {"scope": "work", "roots": ["/fixtures/work"]},
                },
            }
        }
    )


@pytest.fixture
def database(migrated_db):
    conn, _ = migrated_db
    for sid, path in [
        ("personal", "/fixtures/personal/repo"),
        ("work", "/fixtures/work/repo"),
        ("unknown", "/fixtures/personal-sibling"),
        ("remote", "/another-machine/project"),
    ]:
        conn.execute(
            "INSERT INTO sessions(id,source,project_path) VALUES (?,?,?)",
            (sid, "same-harness", path),
        )
    conn.commit()
    return conn


def visible(conn, p, scope):
    clause, params = visibility_sql(conn, "s.id", policy=p, scope=scope)
    return [
        r[0]
        for r in conn.execute(
            "SELECT s.id FROM sessions s WHERE " + clause + " ORDER BY s.id", params
        )
    ]


def test_missing_scope_never_defaults_to_personal(monkeypatch):
    monkeypatch.delenv("SESSION_CONTEXT_SCOPE", raising=False)
    with pytest.raises(ScopeError, match="No context scope"):
        ScopePolicy.from_config({}).request_scope(cwd=Path("/not/configured"))


def test_scope_is_from_explicit_roots_not_query_or_harness(monkeypatch):
    monkeypatch.delenv("SESSION_CONTEXT_SCOPE", raising=False)
    p = policy()
    assert p.request_scope(cwd=Path("/fixtures/work/repo")) == Scope.WORK
    assert p.request_scope(cwd=Path("/fixtures/personal/repo")) == Scope.PERSONAL
    assert p.project_for_path("/fixtures/personal-sibling") is None
    assert (
        p.request_scope(cwd=Path("/fixtures/work/repo"), override="personal")
        == Scope.PERSONAL
    )


def test_longest_explicit_root_wins_and_equal_roots_conflict():
    p = ScopePolicy.from_config(
        {
            "memory": {
                "projects": {
                    "outer": {"scope": "personal", "roots": ["/fixtures"]},
                    "inner": {"scope": "work", "roots": ["/fixtures/work"]},
                }
            }
        }
    )
    assert p.request_scope(cwd=Path("/fixtures/work/repo")) == Scope.WORK
    with pytest.raises(ScopeError, match="same root"):
        ScopePolicy.from_config(
            {
                "memory": {
                    "projects": {
                        "one": {"scope": "personal", "roots": ["/fixtures"]},
                        "two": {"scope": "work", "roots": ["/fixtures"]},
                    }
                }
            }
        )


@pytest.mark.parametrize(
    "memory",
    [
        {"default_scope": "auto"},
        {"projects": {"x": {"roots": ["/x"]}}},
        {"projects": {"x": {"scope": "personal", "roots": ["relative"]}}},
        {"projects": {"x": {"scope": "personal", "roots": "/x"}}},
    ],
)
def test_invalid_configuration_is_rejected(memory):
    with pytest.raises(ScopeError):
        ScopePolicy.from_config({"memory": memory})


def test_preview_writes_nothing_and_apply_records_audit(database):
    p = policy()
    before = database.total_changes
    preview = apply_policy(database, p, actor="fixture-user")
    assert preview["dry_run"]
    assert database.total_changes == before
    assert not database.execute("SELECT 1 FROM context_scope_audit").fetchone()
    with pytest.raises(ScopeError, match="changed"):
        visible(database, p, Scope.PERSONAL)
    applied = apply_policy(database, p, actor="fixture-user", dry_run=False)
    assert len(applied["changes"]) == 4
    assert (
        database.execute("SELECT count(*) FROM context_scope_audit").fetchone()[0] == 4
    )
    assert (
        apply_policy(database, p, actor="fixture-user", dry_run=False)["changes"] == []
    )
    assert visible(database, p, Scope.PERSONAL) == ["personal"]
    assert visible(database, p, Scope.WORK) == ["work"]
    assert visible(database, p, Scope.UNCLASSIFIED) == ["remote", "unknown"]


def test_manual_config_change_withholds_reads_until_applied(database):
    p = policy()
    apply_policy(database, p, actor="test", dry_run=False)
    updated = ScopePolicy.from_config(
        {
            "memory": {
                "default_scope": "personal",
                "projects": {
                    "personal-project": {
                        "scope": "work",
                        "roots": ["/fixtures/personal"],
                    },
                    "work-project": {"scope": "work", "roots": ["/fixtures/work"]},
                },
            }
        }
    )
    with pytest.raises(ScopeError, match="changed"):
        visible(database, updated, Scope.PERSONAL)
    apply_policy(database, updated, actor="test", dry_run=False)
    assert visible(database, updated, Scope.PERSONAL) == []
    assert visible(database, updated, Scope.WORK) == ["personal", "work"]
    events = [
        json.loads(r[0])
        for r in database.execute(
            "SELECT after_json FROM context_scope_audit WHERE subject_id=?",
            ("personal-project",),
        )
    ]
    assert events[0]["scope"] == "personal" and events[-1]["scope"] == "work"


def test_root_removal_unassigns_only_root_assignments(database):
    p = policy()
    apply_policy(database, p, actor="test", dry_run=False)
    database.execute(
        "INSERT INTO context_session_projects VALUES ('remote','personal-project','sync')"
    )
    database.commit()
    updated = policy(roots=["/moved/root"])
    apply_policy(database, updated, actor="test", dry_run=False)
    assert visible(database, updated, Scope.PERSONAL) == ["remote"]
    assert "personal" in visible(database, updated, Scope.UNCLASSIFIED)


def test_tombstoned_rows_remain_hidden_during_policy_application(database):
    p = policy()
    apply_policy(database, p, actor="test", dry_run=False)
    database.execute(
        "INSERT INTO context_tombstones VALUES ('personal','gone','2026-09-05T00:00:00Z')"
    )
    assert visible(database, p, Scope.PERSONAL) == []


def test_default_scope_switch_does_not_reclassify_sources(database):
    p = policy()
    apply_policy(database, p, actor="test", dry_run=False)
    switched = policy(scope="work")
    assert switched.digest == p.digest
    assert visible(database, switched, Scope.PERSONAL) == ["personal"]
    assert visible(database, switched, Scope.WORK) == ["work"]


def test_explicit_session_assignment_outranks_root_default(database):
    p = policy()
    apply_policy(database, p, actor="test", dry_run=False)
    database.execute(
        "UPDATE context_session_projects SET project_id='work-project',assignment_kind='explicit' WHERE session_id='personal'"
    )
    database.commit()
    assert apply_policy(database, p, actor="test", dry_run=False)["changes"] == []
    assert visible(database, p, Scope.PERSONAL) == []
    assert visible(database, p, Scope.WORK) == ["personal", "work"]


def test_legacy_inspection_requires_explicit_scope_and_unconfigured_projects(temp_db):
    conn, _ = temp_db
    conn.execute("INSERT INTO sessions(id,source) VALUES ('legacy','fixture')")
    empty = ScopePolicy.from_config({"memory": {"default_scope": "unclassified"}})
    assert visible(conn, empty, Scope.UNCLASSIFIED) == ["legacy"]
    with pytest.raises(ScopeError, match="migration and scope classification"):
        visible(conn, empty, Scope.PERSONAL)
    with pytest.raises(ScopeError, match="policy is not applied"):
        visible(conn, policy(), Scope.UNCLASSIFIED)


def test_failed_audit_rolls_back_policy_and_assignments(database):
    old = database.execute("SELECT digest FROM context_policy_state").fetchone()[0]
    database.execute(
        "CREATE TRIGGER fail_scope_audit BEFORE INSERT ON context_scope_audit "
        "BEGIN SELECT RAISE(ABORT, 'audit storage unavailable'); END"
    )
    database.commit()
    with pytest.raises(sqlite3.IntegrityError, match="audit storage unavailable"):
        apply_policy(database, policy(), actor="test", dry_run=False)
    assert not database.execute("SELECT 1 FROM context_projects").fetchone()
    assert not database.execute("SELECT 1 FROM context_session_projects").fetchone()
    assert (
        database.execute("SELECT digest FROM context_policy_state").fetchone()[0] == old
    )


def test_removed_project_explicit_assignments_are_withheld_until_reconfigured(database):
    p = policy()
    apply_policy(database, p, actor="test", dry_run=False)
    database.execute(
        "UPDATE context_session_projects SET assignment_kind='explicit' "
        "WHERE session_id='personal'"
    )
    database.commit()
    removed = ScopePolicy.from_config({"memory": {"default_scope": "unclassified"}})
    apply_policy(database, removed, actor="test", dry_run=False)
    assert "personal" not in visible(database, removed, Scope.PERSONAL)
    assert "personal" not in visible(database, removed, Scope.UNCLASSIFIED)
    restored = ScopePolicy.from_config(
        {"memory": {"projects": {"personal-project": {"scope": "unclassified"}}}}
    )
    apply_policy(database, restored, actor="test", dry_run=False)
    assert "personal" in visible(database, restored, Scope.UNCLASSIFIED)


def test_scope_predicate_rejects_ambiguous_unqualified_columns(database):
    with pytest.raises(ValueError, match="internal scope SQL identifier"):
        visibility_sql(database, "session_id", policy=policy())


def test_read_guard_pins_policy_and_rows_to_one_snapshot(migrated_db):
    writer, path = migrated_db
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute(
        "INSERT INTO sessions(id,source,project_path) VALUES ('personal','fixture','/fixtures/personal')"
    )
    writer.commit()
    p = policy()
    apply_policy(writer, p, actor="test", dry_run=False)
    reader = sqlite3.connect(path)
    try:
        clause, values = visibility_sql(reader, "s.id", policy=p, scope=Scope.PERSONAL)
        assert reader.in_transaction
        writer.execute(
            "UPDATE context_projects SET scope='work' WHERE id='personal-project'"
        )
        writer.commit()
        # This request began before the mutation; the next request observes it.
        assert reader.execute(
            "SELECT s.id FROM sessions s WHERE " + clause, values
        ).fetchall()
        reader.rollback()
        assert visible(reader, p, Scope.PERSONAL) == []
    finally:
        reader.close()
