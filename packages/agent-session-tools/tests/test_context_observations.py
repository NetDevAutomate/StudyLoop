"""Source-scoped observation ownership, explicit revisions and local retirement."""

import json
import sqlite3

import pytest

from agent_session_tools.context.observations import ObservationStore
from agent_session_tools.context.provenance import Origin, Scope
from agent_session_tools.context.scope import ScopeError, ScopePolicy, apply_policy
from agent_session_tools.context.store import ContextStore, NativeSource


@pytest.fixture
def history(migrated_db, tmp_path, monkeypatch):
    conn, _ = migrated_db
    conn.execute("PRAGMA foreign_keys=ON")
    settings = {
        "memory": {
            "default_scope": "personal",
            "projects": {
                "personal": {"scope": "personal", "roots": ["/observation/personal"]},
                "work": {"scope": "work", "roots": ["/observation/work"]},
            },
        }
    }
    config = tmp_path / "scope.yaml"
    config.write_text(json.dumps(settings))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    for sid, path in [
        ("a", "/observation/personal"),
        ("b", "/observation/personal"),
        ("w", "/observation/work"),
    ]:
        conn.execute(
            "INSERT INTO sessions(id,source,project_path) VALUES (?,?,?)",
            (sid, "fixture", path),
        )
    conn.commit()
    apply_policy(
        conn, ScopePolicy.from_config(settings), actor="fixture", dry_run=False
    )
    canonical = ContextStore(conn)
    refs = {}
    for sid in ("a", "b", "w"):
        refs[sid] = canonical.capture(
            NativeSource(
                session_id=sid,
                native_key="one",
                harness="fixture",
                native_kind="message",
                native_locator="fixture:" + sid,
                parser_version="fixture1",
                machine_id="fixture",
                body=sid + " body",
                origin=Origin.UNKNOWN,
            )
        )
    return conn, ObservationStore(conn), refs, config, settings


def proposal(store, refs=(), **kwargs):
    return store.append(
        kind="studyloop.progress",
        subject="sql:windows",
        payload={"value": "learning"},
        producer="fixture-model",
        authority="model_interpretation" if refs else "reported",
        evidence_ids=refs,
        **kwargs,
    )


def test_source_binding_and_repeat_deduplication(history):
    conn, store, refs, _, _ = history
    identity = proposal(store, [refs["a"]], request_key="repeat")
    assert proposal(store, [refs["a"]], request_key="repeat") == identity
    result = store.get(identity)
    assert result["semantic_status"] == "unverified_interpretation"
    assert result["sources"][0]["id"] == refs["a"]
    assert result["sources"][0]["origin"] == "unknown"
    assert conn.execute("SELECT count(*) FROM context_observations").fetchone()[0] == 1


def test_all_sources_must_be_visible_before_storing_body(history):
    conn, store, refs, _, _ = history
    with pytest.raises(ScopeError, match="source unavailable"):
        proposal(store, [refs["a"], refs["w"]])
    assert conn.execute("SELECT count(*) FROM context_observations").fetchone()[0] == 0


def test_reclassification_changes_access_without_rewriting_observation(
    history, monkeypatch
):
    conn, store, refs, config, settings = history
    identity = proposal(store, [refs["a"]])
    before = tuple(
        conn.execute(
            "SELECT * FROM context_observations WHERE id=?", (identity,)
        ).fetchone()
    )
    settings["memory"]["projects"]["personal"]["scope"] = "work"
    config.write_text(json.dumps(settings))
    with pytest.raises(ScopeError, match="changed"):
        store.get(identity)
    apply_policy(conn, ScopePolicy.from_config(settings), actor="owner", dry_run=False)
    assert store.get(identity) is None
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "work")
    assert store.get(identity)["id"] == identity
    assert (
        tuple(
            conn.execute(
                "SELECT * FROM context_observations WHERE id=?", (identity,)
            ).fetchone()
        )
        == before
    )


def test_concurrent_corrections_remain_two_heads(history):
    _, store, refs, _, _ = history
    original = proposal(store, [refs["a"]])
    left = proposal(store, [refs["b"]], supersedes=[original])
    right = proposal(store, [refs["b"]], supersedes=[original])
    assert {row["id"] for row in store.list("studyloop.progress")} == {left, right}
    assert len(store.list("studyloop.progress", current=False)) == 3


def test_forgotten_correction_never_reactivates_its_predecessor(history):
    conn, store, refs, _, _ = history
    original = proposal(store, [refs["a"]])
    correction = proposal(store, [refs["b"]], supersedes=[original])
    assert store.forget(correction)
    assert store.get(correction) is None
    assert store.get(original) is not None  # historical record still inspectable
    assert store.list("studyloop.progress") == []
    assert (
        conn.execute("SELECT count(*) FROM context_observation_supersedes").fetchone()[
            0
        ]
        == 1
    )


def test_source_purge_removes_dependent_body_and_blocks_exact_replay(history):
    conn, store, refs, _, _ = history
    identity = proposal(store, [refs["a"]], request_key="replay")
    conn.execute("DELETE FROM context_evidence WHERE id=?", (refs["a"],))
    assert store.get(identity) is None
    assert not conn.execute(
        "SELECT 1 FROM context_observation_sources WHERE observation_id=?", (identity,)
    ).fetchone()
    assert conn.execute(
        "SELECT 1 FROM context_observation_tombstones WHERE observation_id=?",
        (identity,),
    ).fetchone()
    assert not conn.execute("PRAGMA foreign_key_check").fetchall()


def test_forgetting_observation_refuses_exact_replay_with_original_source(history):
    _, store, refs, _, _ = history
    identity = proposal(store, [refs["a"]], request_key="replay")
    assert store.forget(identity)
    with pytest.raises(ValueError, match="forgotten"):
        proposal(store, [refs["a"]], request_key="replay")


def test_explicit_manual_scope_overrides_cwd_root(history, monkeypatch):
    conn, store, _, _, _ = history
    monkeypatch.setattr(
        "agent_session_tools.context.observations.Path.cwd",
        lambda: __import__("pathlib").Path("/observation/personal"),
    )
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "work")
    identity = proposal(store)
    assert store.get(identity)["owner"] == {"project_id": None, "fixed_scope": "work"}
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "personal")
    assert store.get(identity) is None
    assert (
        conn.execute(
            "SELECT count(*) FROM context_scope_audit WHERE action='observation_owner'"
        ).fetchone()[0]
        == 1
    )


def test_manual_reassignment_is_audited_but_source_owner_cannot_be_overridden(
    history, monkeypatch
):
    conn, store, refs, _, _ = history
    manual = proposal(store)
    source = proposal(store, [refs["a"]])
    with pytest.raises(ValueError, match="follow the source"):
        store.assign(source, actor="owner", scope=Scope.WORK)
    store.assign(manual, actor="owner", scope=Scope.WORK)
    assert store.get(manual) is None
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "work")
    assert store.get(manual)["scope"] == "work"
    assert (
        conn.execute(
            "SELECT count(*) FROM context_scope_audit WHERE subject_id=?", (manual,)
        ).fetchone()[0]
        == 2
    )


def test_observation_payload_and_binding_are_immutable(history):
    conn, store, refs, _, _ = history
    identity = proposal(store, [refs["a"]])
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE context_observations SET payload='{}' WHERE id=?", (identity,)
        )
    conn.execute("DROP TRIGGER context_observations_immutable")
    conn.execute("UPDATE context_observations SET payload='{}' WHERE id=?", (identity,))
    with pytest.raises(ValueError, match="binding failed"):
        store.get(identity)


def test_model_proposal_requires_actual_source(history):
    _, store, _, _, _ = history
    with pytest.raises(ValueError, match="source dependencies"):
        store.append(
            kind="x",
            subject="y",
            payload={},
            producer="model",
            authority="model_interpretation",
        )
