"""Ownership must retain permitted records and remove excluded bodies before SQL limits."""

import json
import sqlite3
from importlib.resources import files

import pytest

from agent_session_tools.context import records
from agent_session_tools.context.record_schema import TABLES as V36_TABLES
from agent_session_tools.context.scope import ScopeError, ScopePolicy, apply_policy


@pytest.fixture
def owned_db(migrated_db, tmp_path, monkeypatch):
    conn, path = migrated_db
    conn.execute("PRAGMA foreign_keys=ON")
    roots = {name: tmp_path / name for name in ("personal", "work")}
    for root in roots.values():
        root.mkdir()
    config = {
        "memory": {
            "projects": {
                name: {"scope": name, "roots": [str(root)]}
                for name, root in roots.items()
            }
        }
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "personal")
    monkeypatch.chdir(roots["personal"])
    for name, root in roots.items():
        conn.execute(
            "INSERT INTO sessions(id,source,project_path) VALUES (?,?,?)",
            (name, "kiro_cli", str(root)),
        )
    conn.commit()
    apply_policy(conn, ScopePolicy.from_config(config), actor="fixture", dry_run=False)
    return conn, path, config_path, config, roots


def insert(conn, table, *, session_id=None, bind=True):
    conn.execute("BEGIN IMMEDIATE")
    try:
        if table == "study_sessions":
            cursor = conn.execute(
                "INSERT INTO study_sessions(id,started_at,notes) VALUES ('record','2026-09-01','BODY')"
            )
            identity = "record"
        elif table == "teach_back_scores":
            cursor = conn.execute(
                "INSERT INTO teach_back_scores(concept,topic,review_type,notes) "
                "VALUES ('generators','python','micro','BODY')"
            )
            identity = cursor.lastrowid
        else:
            cursor = conn.execute(
                "INSERT INTO knowledge_bridges(source_concept,source_domain,target_concept,"
                "target_domain,structural_mapping) VALUES ('a','b','c','d','BODY')"
            )
            identity = cursor.lastrowid
        assert identity is not None
        if bind:
            records.bind(conn, table, identity, session_id=session_id)
        conn.commit()
        return identity
    except BaseException:
        conn.rollback()
        raise


@pytest.mark.parametrize("table", V36_TABLES)
def test_project_ownership_follows_reclassification_and_never_guesses_legacy(
    owned_db, table
):
    conn, _, path, config, _ = owned_db
    identity = insert(conn, table)
    assert records.is_visible(conn, table, identity)
    conn.rollback()
    config["memory"]["projects"]["personal"]["scope"] = "work"
    path.write_text(json.dumps(config))
    with pytest.raises(ScopeError, match="policy apply"):
        records.is_visible(conn, table, identity)
    conn.rollback()
    apply_policy(conn, ScopePolicy.from_config(config), actor="fixture", dry_run=False)
    assert not records.is_visible(conn, table, identity)


@pytest.mark.parametrize("table", V36_TABLES)
def test_native_session_owner_follows_assignment_and_purges_body_on_delete(
    owned_db, table
):
    conn, _, _, _, _ = owned_db
    identity = insert(conn, table, session_id="personal")
    assert records.is_visible(conn, table, identity)
    conn.rollback()
    conn.execute(
        "UPDATE context_session_projects SET project_id='work' WHERE session_id='personal'"
    )
    conn.commit()
    assert not records.is_visible(conn, table, identity)
    conn.rollback()
    # Logical forgetting is the managed event; unrelated legacy parent FKs may
    # prevent a raw DELETE until the full lifecycle coordinator runs.
    conn.execute(
        "INSERT INTO context_tombstones(session_id,deletion_id,deleted_at) "
        "VALUES ('personal','fixture-delete','2026-09-06')"
    )
    conn.commit()
    assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM context_record_owners").fetchone()[0] == 0
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("table", V36_TABLES)
def test_record_delete_removes_owner_without_recursion(owned_db, table):
    conn, _, _, _, _ = owned_db
    identity = insert(conn, table)
    conn.execute(f"DELETE FROM {table} WHERE id=?", (identity,))
    conn.commit()
    assert conn.execute("SELECT count(*) FROM context_record_owners").fetchone()[0] == 0
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_wrong_source_rejects_both_record_and_binding(owned_db):
    conn, _, _, _, _ = owned_db
    with pytest.raises(ScopeError, match="unavailable"):
        insert(conn, "study_sessions", session_id="work")
    assert conn.execute("SELECT count(*) FROM study_sessions").fetchone()[0] == 0


def test_unowned_legacy_body_stays_unclassified(owned_db, monkeypatch):
    conn, _, _, _, _ = owned_db
    identity = insert(conn, "study_sessions", bind=False)
    assert not records.is_visible(conn, "study_sessions", identity)
    conn.rollback()
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "unclassified")
    # Existing cautious legacy policy withholds merged rows in a classified database.
    assert not records.is_visible(conn, "study_sessions", identity)


def test_policy_change_rolls_back_record_and_owner_together(owned_db):
    conn, _, path, config, _ = owned_db
    conn.execute("BEGIN IMMEDIATE")
    with pytest.raises(ScopeError, match="changed during"):
        with records.policy_guard(conn):
            conn.execute(
                "INSERT INTO study_sessions(id,started_at) VALUES ('late','2026-09-01')"
            )
            records.bind(conn, "study_sessions", "late")
            config["memory"]["projects"]["personal"]["scope"] = "work"
            path.write_text(json.dumps(config))
    conn.rollback()
    assert conn.execute("SELECT count(*) FROM study_sessions").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM context_record_owners").fetchone()[0] == 0


def test_v36_upgrade_failure_preserves_old_rows_then_retries(monkeypatch):
    from agent_session_tools import migrations
    from agent_session_tools.context import record_schema

    monkeypatch.setattr(migrations, "CURRENT_VERSION", 36)

    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(files("agent_session_tools").joinpath("schema.sql").read_text())
    with monkeypatch.context() as old:
        old.setattr(migrations, "CURRENT_VERSION", 35)
        migrations.migrate(conn)
    conn.execute(
        "INSERT INTO study_sessions(id,started_at,notes) VALUES ('kept','2026-09-01','OLD')"
    )
    conn.commit()
    install = record_schema.install

    def interrupted(db):
        install(db)
        raise RuntimeError("injected migration interruption")

    with monkeypatch.context() as failed:
        failed.setattr(record_schema, "install", interrupted)
        with pytest.raises(RuntimeError, match="injected"):
            migrations.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 35
    assert not records.available(conn)
    assert conn.execute("SELECT notes FROM study_sessions").fetchone()[0] == "OLD"
    migrations.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 36
    assert records.available(conn)
    assert conn.execute("SELECT count(*) FROM context_record_owners").fetchone()[0] == 0
    assert conn.execute("SELECT notes FROM study_sessions").fetchone()[0] == "OLD"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
