"""Annotations about a session inherit its boundary, not fabricated inputs."""

import json
import sqlite3

import pytest

from agent_session_tools.context.observations import ObservationStore
from agent_session_tools.context.scope import ScopeError, ScopePolicy, apply_policy


@pytest.fixture
def owned_session(migrated_db, tmp_path, monkeypatch):
    conn, path = migrated_db
    conn.execute("PRAGMA foreign_keys=ON")
    config = {
        "memory": {
            "default_scope": "personal",
            "projects": {
                "p": {"scope": "personal", "roots": ["/fixture/p"]},
                "w": {"scope": "work", "roots": ["/fixture/w"]},
            },
        }
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "personal")
    conn.executemany(
        "INSERT INTO sessions(id,source,project_path) VALUES (?,?,?)",
        [
            ("personal", "fixture", "/fixture/p"),
            ("work", "fixture", "/fixture/w"),
        ],
    )
    conn.commit()
    apply_policy(conn, ScopePolicy.from_config(config), actor="fixture", dry_run=False)
    return conn, path, config_path, config


def append(conn, sid="personal"):
    return ObservationStore(conn).append(
        kind="session.note",
        subject=sid,
        payload={"notes": "A reported annotation"},
        producer="fixture",
        authority="reported",
        owner_session_id=sid,
    )


def test_empty_session_is_owner_without_inventing_evidence(owned_session):
    conn, _, _, _ = owned_session
    identity = append(conn)
    record = ObservationStore(conn).get(identity)
    assert record is not None
    assert record["owner"] == {"session_id": "personal"}
    assert record["source_relationship"] == "about_session"
    assert record["sources"] == []
    assert conn.execute("SELECT count(*) FROM context_evidence").fetchone()[0] == 0


def test_session_reassignment_changes_annotation_visibility(owned_session, monkeypatch):
    conn, _, _, _ = owned_session
    identity = append(conn)
    conn.execute(
        "UPDATE context_session_projects SET project_id='w' WHERE session_id='personal'"
    )
    conn.commit()
    assert ObservationStore(conn).get(identity) is None
    conn.rollback()
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "work")
    assert ObservationStore(conn).get(identity) is not None


def test_wrong_or_nonexistent_session_refuses_body(owned_session):
    conn, _, _, _ = owned_session
    for sid in ("work", "missing"):
        with pytest.raises(ScopeError, match="unavailable"):
            append(conn, sid)
    assert conn.execute("SELECT count(*) FROM context_observations").fetchone()[0] == 0


@pytest.mark.parametrize("logical", [True, False])
def test_parent_forgetting_purges_body_and_retires_versions(owned_session, logical):
    conn, _, _, _ = owned_session
    identity = append(conn)
    conn.execute(
        "INSERT INTO session_notes(session_id,notes) VALUES ('personal','OLD_SHADOW')"
    )
    conn.execute(
        "INSERT INTO session_tags(session_id,tag) VALUES ('personal','OLD_TAG')"
    )
    if logical:
        conn.execute(
            "INSERT INTO context_tombstones VALUES ('personal','forget','2026-09-06')"
        )
    else:
        # The existing assignment FK intentionally requires explicit cleanup.
        conn.execute("DELETE FROM context_session_projects WHERE session_id='personal'")
        conn.execute("DELETE FROM sessions WHERE id='personal'")
    conn.commit()
    assert not conn.execute(
        "SELECT 1 FROM context_observations WHERE id=?", (identity,)
    ).fetchone()
    assert conn.execute(
        "SELECT 1 FROM context_observation_tombstones WHERE observation_id=?",
        (identity,),
    ).fetchone()
    assert conn.execute("SELECT count(*) FROM session_notes").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM session_tags").fetchone()[0] == 0
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_owner_is_exclusive_and_cannot_be_reassigned(owned_session):
    conn, _, _, _ = owned_session
    identity = append(conn)
    with pytest.raises(sqlite3.IntegrityError, match="session owner"):
        conn.execute(
            "INSERT INTO context_observation_owners VALUES (?,NULL,'personal')",
            (identity,),
        )
    conn.rollback()
    with pytest.raises(ValueError, match="follow their session"):
        ObservationStore(conn).assign(identity, actor="test", project_id="w")
    with pytest.raises(ValueError, match="cannot also claim"):
        ObservationStore(conn).append(
            kind="note",
            subject="personal",
            payload={},
            producer="test",
            authority="reported",
            evidence_ids=["invented"],
            owner_session_id="personal",
        )


def test_forgotten_parent_refuses_legacy_annotation_replay(owned_session):
    conn, _, _, _ = owned_session
    conn.execute(
        "INSERT INTO context_tombstones VALUES ('personal','forget','2026-09-06')"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="forgotten"):
        conn.execute(
            "INSERT INTO session_notes(session_id,notes) VALUES ('personal','STALE')"
        )
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="forgotten"):
        conn.execute(
            "INSERT INTO session_tags(session_id,tag) VALUES ('personal','STALE')"
        )
    conn.rollback()
