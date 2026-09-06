"""Actual SQLite/native-source offer, receipt and permanent-control interleavings."""

import json
import sqlite3
import subprocess
import sys

import pytest

from agent_session_tools.context import annotations, records
from agent_session_tools.context.lifecycle import purge_session
from agent_session_tools.context.scope import ScopePolicy, apply_policy
from agent_session_tools.context.store import ContextStore, _hash, _json
from agent_session_tools.exporters.codex import CodexExporter
from agent_session_tools.replication import ledger
from agent_session_tools.replication.policy import (
    PeerPolicy,
    ReplicaError,
    hello,
    negotiate,
)


@pytest.fixture
def pair(tmp_path, monkeypatch):
    result = {}
    for node, peer in (("a", "b"), ("b", "a")):
        config = {
            "memory": {
                "default_scope": "personal",
                "projects": {
                    name: {"scope": scope, "roots": [str(tmp_path / node / scope)]}
                    for name, scope in (("p", "personal"), ("w", "work"))
                },
                "sync": {
                    "node_id": node,
                    "peers": {peer: {"allowed_scopes": ["personal"]}},
                },
            }
        }
        cfg = tmp_path / (node + ".json")
        cfg.write_text(json.dumps(config))
        path = tmp_path / (node + ".db")
        conn = records.connect(path)
        apply_policy(
            conn, ScopePolicy.from_config(config), actor="fixture", dry_run=False
        )
        result[node] = {"conn": conn, "path": path, "config": config, "cfg": cfg}
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(result["a"]["cfg"]))
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "personal")
    archives = tmp_path / "native"
    archives.mkdir()
    for scope in ("personal", "work"):
        rows = [
            {
                "type": "session_meta",
                "payload": {"id": scope, "cwd": str(tmp_path / "a" / scope)},
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "STAGE34_" + scope.upper() + "_BODY",
                        }
                    ],
                },
            },
        ]
        (archives / ("rollout-" + scope + ".jsonl")).write_text(
            "".join(json.dumps(r) + "\n" for r in rows)
        )
    exporter = CodexExporter(archives)
    assert exporter.export_all(result["a"]["conn"]).added == 2
    conn = result["a"]["conn"]
    with ContextStore(conn)._atomic(), records.policy_guard(conn):
        annotations.write(
            conn,
            "codex_rollout-personal",
            "note",
            {"notes": "STAGE34_PERSONAL_OLD_REPORT"},
        )
        annotations.write(
            conn,
            "codex_rollout-personal",
            "note",
            {"notes": "STAGE34_PERSONAL_NEW_REPORT"},
        )
    result["exporter"] = exporter
    yield result
    for node in ("a", "b"):
        result[node]["conn"].close()


def offer(pair):
    a, b = pair["a"], pair["b"]
    plan = negotiate(
        hello(a["conn"], PeerPolicy.from_config(a["config"], "b")),
        hello(b["conn"], PeerPolicy.from_config(b["config"], "a")),
    )
    return ledger.prepare_offer(a["path"], a["config"], plan, "personal")


def accepted(pair):
    value = offer(pair)
    a, b = pair["a"], pair["b"]
    acceptance = ledger.accept_offer(b["path"], b["config"], "a", value)
    ledger.record_acceptance(a["path"], a["config"], "b", value, acceptance)
    return value


def delivered(pair):
    value = accepted(pair)
    a, b = pair["a"], pair["b"]
    snapshot = ledger.release_content(a["path"], a["config"], "b", value)
    receipt = ledger.receive_content(b["path"], b["config"], "a", value["id"], snapshot)
    return value, snapshot, receipt


def forget(pair, node, scope="personal"):
    with ContextStore(pair[node]["conn"])._atomic():
        purge_session(pair[node]["conn"], "codex_rollout-" + scope)


def reseal(value):
    value["id"] = _hash(_json({k: v for k, v in value.items() if k != "id"}))
    return value


def test_offer_acceptance_and_content_receipt_are_distinct(pair):
    a, b = pair["a"], pair["b"]
    value = offer(pair)
    assert "STAGE34_" not in _json(value) and "codex_rollout-work" not in _json(value)
    assert not a["conn"].execute("SELECT 1 FROM context_replica_objects").fetchone()
    with pytest.raises(ReplicaError, match="accepted offer"):
        ledger.release_content(a["path"], a["config"], "b", value)
    acknowledgement = ledger.accept_offer(b["path"], b["config"], "a", value)
    assert b["conn"].execute("SELECT 1 FROM context_replica_objects").fetchone()
    assert not b["conn"].execute("SELECT 1 FROM sessions").fetchone()
    # Losing this response is recoverable; it does not create a second grant.
    assert ledger.accept_offer(b["path"], b["config"], "a", value) == acknowledgement
    ledger.record_acceptance(a["path"], a["config"], "b", value, acknowledgement)
    snapshot = ledger.release_content(a["path"], a["config"], "b", value)
    receipt = ledger.receive_content(b["path"], b["config"], "a", value["id"], snapshot)
    before = list(b["conn"].iterdump())
    assert (
        ledger.receive_content(b["path"], b["config"], "a", value["id"], snapshot)
        == receipt
    )
    assert list(b["conn"].iterdump()) == before
    ledger.acknowledge_content(a["path"], a["config"], "b", receipt)
    assert (
        a["conn"]
        .execute("SELECT status FROM context_replica_offers WHERE direction='out'")
        .fetchone()[0]
        == "acknowledged"
    )
    assert (
        b["conn"].execute("SELECT count(*) FROM context_observations").fetchone()[0]
        == 2
    )


@pytest.mark.parametrize("already_delivered", [False, True])
def test_forget_routes_known_controls_and_blocks_stale_body(pair, already_delivered):
    a, b = pair["a"], pair["b"]
    value = accepted(pair)
    stale = ledger.release_content(a["path"], a["config"], "b", value)
    if already_delivered:
        ledger.receive_content(b["path"], b["config"], "a", value["id"], stale)
    forget(pair, "a")
    forget(pair, "a", "work")
    with pytest.raises(ReplicaError):
        ledger.release_content(a["path"], a["config"], "b", value)
    batch = ledger.prepare_controls(a["path"], a["config"], "b")
    assert batch["retirements"] and "codex_rollout-work" not in _json(batch)
    receipt = ledger.apply_controls(b["path"], b["config"], "a", batch)
    result = ledger.acknowledge_controls(a["path"], a["config"], "b", receipt)
    assert result["acknowledged"] and result["sync_complete"] is False
    if already_delivered:
        # A receipt records a historical commit, never a claim that bodies still exist.
        assert ledger.receive_content(b["path"], b["config"], "a", value["id"], stale)[
            "committed"
        ]
    else:
        with pytest.raises(ReplicaError, match="retired"):
            ledger.receive_content(b["path"], b["config"], "a", value["id"], stale)
    assert not b["conn"].execute("SELECT 1 FROM sessions").fetchone()
    assert not b["conn"].execute("SELECT 1 FROM context_observations").fetchone()
    assert b"STAGE34_PERSONAL_" not in b["path"].read_bytes()
    replay = pair["exporter"].export_all(b["conn"], incremental=False)
    assert replay.forgotten == 1 and not replay.errors
    assert (
        not b["conn"]
        .execute("SELECT 1 FROM sessions WHERE id='codex_rollout-personal'")
        .fetchone()
    )


def test_receiver_forget_propagates_back_without_content_acknowledgement(pair):
    a, b = pair["a"], pair["b"]
    delivered(pair)  # Sender has not received the content receipt.
    forget(pair, "b")
    controls = ledger.prepare_controls(b["path"], b["config"], "a")
    receipt = ledger.apply_controls(a["path"], a["config"], "b", controls)
    assert ledger.acknowledge_controls(b["path"], b["config"], "a", receipt)[
        "acknowledged"
    ]
    assert (
        not a["conn"]
        .execute("SELECT 1 FROM sessions WHERE id='codex_rollout-personal'")
        .fetchone()
    )
    assert (
        a["conn"]
        .execute("SELECT 1 FROM sessions WHERE id='codex_rollout-work'")
        .fetchone()
    )


def test_empty_current_scopes_allow_only_recorded_controls(pair):
    a, b = pair["a"], pair["b"]
    delivered(pair)
    forget(pair, "a")
    for node, peer in (("a", "b"), ("b", "a")):
        pair[node]["config"]["memory"]["sync"]["peers"][peer]["allowed_scopes"] = []
    controls = ledger.prepare_controls(a["path"], a["config"], "b")
    assert ledger.apply_controls(b["path"], b["config"], "a", controls)[
        "logical_committed"
    ]
    with pytest.raises(ReplicaError, match="allowed_scopes"):
        offer(pair)
    del a["config"]["memory"]["sync"]["peers"]["b"]
    with pytest.raises(ReplicaError, match="not configured"):
        ledger.prepare_controls(a["path"], a["config"], "b")


def test_offer_cannot_register_an_existing_excluded_identity(pair):
    b = pair["b"]
    b["conn"].execute(
        "INSERT INTO sessions(id,source,project_path) VALUES ('private-work','fixture',?)",
        (b["config"]["memory"]["projects"]["w"]["roots"][0],),
    )
    b["conn"].commit()
    apply_policy(
        b["conn"], ScopePolicy.from_config(b["config"]), actor="fixture", dry_run=False
    )
    value = offer(pair)
    value["objects"].append({"kind": "session", "object_id": "private-work"})
    reseal(value)
    before = list(b["conn"].iterdump())
    with pytest.raises(ReplicaError, match="unavailable"):
        ledger.accept_offer(b["path"], b["config"], "a", value)
    assert list(b["conn"].iterdump()) == before


def test_unrecorded_control_cannot_delete_a_local_object(pair):
    a, b = pair["a"], pair["b"]
    delivered(pair)
    forget(pair, "b")
    controls = ledger.prepare_controls(b["path"], b["config"], "a")
    controls["retirements"].append(
        {
            "kind": "session",
            "object_id": "codex_rollout-work",
            "scope": "personal",
            "retired_at": "fixture",
        }
    )
    reseal(controls)
    before = list(a["conn"].iterdump())
    with pytest.raises(ReplicaError, match="recorded peer/object"):
        ledger.apply_controls(a["path"], a["config"], "b", controls)
    assert list(a["conn"].iterdump()) == before


def test_content_and_receipt_rollback_together(pair, monkeypatch):
    a, b = pair["a"], pair["b"]
    value = accepted(pair)
    snapshot = ledger.release_content(a["path"], a["config"], "b", value)
    original = ledger.apply_in_transaction

    def fail(*args):
        original(*args)
        raise RuntimeError("failure after bodies before receipt")

    before = list(b["conn"].iterdump())
    with monkeypatch.context() as fault:
        fault.setattr(ledger, "apply_in_transaction", fail)
        with pytest.raises(RuntimeError, match="after bodies"):
            ledger.receive_content(b["path"], b["config"], "a", value["id"], snapshot)
    assert list(b["conn"].iterdump()) == before
    assert ledger.receive_content(b["path"], b["config"], "a", value["id"], snapshot)[
        "committed"
    ]


def test_controls_and_purge_rollback_together(pair, monkeypatch):
    a, b = pair["a"], pair["b"]
    delivered(pair)
    forget(pair, "a")
    controls = ledger.prepare_controls(a["path"], a["config"], "b")
    original = ledger.reconcile_local_retirements

    def fail(*args):
        original(*args)
        raise RuntimeError("failure after purge")

    before = list(b["conn"].iterdump())
    with monkeypatch.context() as fault:
        fault.setattr(ledger, "reconcile_local_retirements", fail)
        with pytest.raises(RuntimeError, match="after purge"):
            ledger.apply_controls(b["path"], b["config"], "a", controls)
    assert list(b["conn"].iterdump()) == before
    assert ledger.apply_controls(b["path"], b["config"], "a", controls)[
        "logical_committed"
    ]


def test_pending_peer_cleanup_is_not_acknowledged(pair):
    a, b = pair["a"], pair["b"]
    delivered(pair)
    reader = sqlite3.connect(b["path"])
    reader.execute("BEGIN")
    reader.execute("SELECT * FROM sessions").fetchone()
    forget(pair, "a")
    controls = ledger.prepare_controls(a["path"], a["config"], "b")
    pending = ledger.apply_controls(b["path"], b["config"], "a", controls)
    assert not ledger.acknowledge_controls(a["path"], a["config"], "b", pending)[
        "acknowledged"
    ]
    reader.close()
    complete = ledger.apply_controls(b["path"], b["config"], "a", controls)
    assert ledger.acknowledge_controls(a["path"], a["config"], "b", complete)[
        "acknowledged"
    ]


def test_changed_peer_instance_requires_managed_reconciliation(pair, tmp_path):
    a, b = pair["a"], pair["b"]
    accepted(pair)
    changed = records.connect(tmp_path / "different-b.db")
    try:
        apply_policy(
            changed,
            ScopePolicy.from_config(b["config"]),
            actor="fixture",
            dry_run=False,
        )
        plan = negotiate(
            hello(a["conn"], PeerPolicy.from_config(a["config"], "b")),
            hello(changed, PeerPolicy.from_config(b["config"], "a")),
        )
        with pytest.raises(ReplicaError, match="instance changed"):
            ledger.prepare_offer(a["path"], a["config"], plan, "personal")
    finally:
        changed.close()


def test_old_unscoped_retirement_does_not_grant_new_peer_history(pair):
    b = pair["b"]
    with ContextStore(b["conn"])._atomic():
        purge_session(b["conn"], "codex_rollout-personal")
    value = offer(pair)
    with pytest.raises(ReplicaError, match="unavailable"):
        ledger.accept_offer(b["path"], b["config"], "a", value)
    assert not b["conn"].execute("SELECT 1 FROM context_replica_objects").fetchone()


def test_process_death_after_bodies_before_receipt_rolls_back(pair, tmp_path):
    a, b = pair["a"], pair["b"]
    value = accepted(pair)
    snapshot = ledger.release_content(a["path"], a["config"], "b", value)
    payload = tmp_path / "packet.json"
    payload.write_text(json.dumps({"snapshot": snapshot, "offer_id": value["id"]}))
    code = """
import json,os,sys
from contextlib import contextmanager
from pathlib import Path
from agent_session_tools.replication import ledger
original=ledger._write
@contextmanager
def writer(path):
    with original(path) as conn:
        conn.create_function('die_now',0,lambda:os._exit(29))
        conn.execute("CREATE TEMP TRIGGER crash_receipt BEFORE UPDATE ON context_replica_offers WHEN NEW.status='applied' BEGIN SELECT die_now(); END")
        yield conn
ledger._write=writer
packet=json.loads(Path(sys.argv[3]).read_text())
ledger.receive_content(Path(sys.argv[1]),json.loads(Path(sys.argv[2]).read_text()),'a',packet['offer_id'],packet['snapshot'])
"""
    before = list(b["conn"].iterdump())
    run = subprocess.run(
        [sys.executable, "-I", "-c", code, str(b["path"]), str(b["cfg"]), str(payload)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert run.returncode == 29, run.stderr
    assert list(b["conn"].iterdump()) == before
    assert ledger.receive_content(b["path"], b["config"], "a", value["id"], snapshot)[
        "committed"
    ]


def test_retirement_feedback_survives_lost_acceptance_before_body(pair):
    a, b = pair["a"], pair["b"]
    value = offer(pair)
    acceptance = ledger.accept_offer(b["path"], b["config"], "a", value)
    # Recipient cancels the registered source while no source body has arrived.
    forget(pair, "b")
    assert ledger.accept_offer(b["path"], b["config"], "a", value) == acceptance
    ledger.record_acceptance(a["path"], a["config"], "b", value, acceptance)
    batch = ledger.prepare_controls(b["path"], b["config"], "a")
    ledger.apply_controls(a["path"], a["config"], "b", batch)
    with pytest.raises(ReplicaError, match="retired"):
        ledger.release_content(a["path"], a["config"], "b", value)
    assert not b["conn"].execute("SELECT 1 FROM messages").fetchone()


def test_new_offer_for_known_retirement_registers_feedback_without_body(pair):
    a, b = pair["a"], pair["b"]
    delivered(pair)
    forget(pair, "b")
    value = offer(pair)
    acceptance = ledger.accept_offer(b["path"], b["config"], "a", value)
    assert acceptance["status"] == "retired"
    ledger.record_acceptance(a["path"], a["config"], "b", value, acceptance)
    with pytest.raises(ReplicaError, match="accepted offer"):
        ledger.release_content(a["path"], a["config"], "b", value)
    batch = ledger.prepare_controls(b["path"], b["config"], "a")
    assert ledger.apply_controls(a["path"], a["config"], "b", batch)[
        "logical_committed"
    ]


def test_changed_local_identity_cannot_reuse_old_replica_knowledge(pair):
    a = pair["a"]
    accepted(pair)
    a["config"]["memory"]["sync"]["node_id"] = "replacement-a"
    with pytest.raises(ReplicaError, match="peer binding"):
        ledger.prepare_controls(a["path"], a["config"], "b")


def test_corrupt_body_cannot_borrow_a_previous_content_receipt(pair):
    _, snapshot, receipt = delivered(pair)
    snapshot["tables"]["messages"][0]["content"] = (
        "Substituted body with unchanged claimed digest"
    )
    b = pair["b"]
    with pytest.raises(ReplicaError, match="binding failed"):
        ledger.receive_content(
            b["path"], b["config"], "a", receipt["offer_id"], snapshot
        )


def test_config_change_during_offer_acceptance_rolls_back_history(pair, monkeypatch):
    b = pair["b"]
    value = offer(pair)
    original = ledger._interest

    def change(*args):
        original(*args)
        b["config"]["memory"]["sync"]["peers"]["a"]["allowed_scopes"] = ["work"]

    before = list(b["conn"].iterdump())
    monkeypatch.setattr(ledger, "_interest", change)
    with pytest.raises(ReplicaError, match="configuration changed"):
        ledger.accept_offer(b["path"], b["config"], "a", value)
    assert list(b["conn"].iterdump()) == before


def test_schema41_ledger_upgrade_is_additive_and_failure_atomic(tmp_path, monkeypatch):
    from agent_session_tools import migrations
    from agent_session_tools.replication import ledger_schema

    with monkeypatch.context() as old:
        old.setattr(migrations, "CURRENT_VERSION", 41)
        conn = records.connect(tmp_path / "upgrade.db")
    conn.execute("INSERT INTO sessions(id,source) VALUES ('original','fixture')")
    conn.commit()
    before = list(conn.iterdump())
    original = ledger_schema.install

    def fail(database):
        original(database)
        raise RuntimeError("injected ledger migration failure")

    with monkeypatch.context() as broken:
        broken.setattr(ledger_schema, "install", fail)
        with pytest.raises(RuntimeError, match="ledger migration failure"):
            migrations.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 41
    assert list(conn.iterdump()) == before
    assert len(migrations.migrate(conn)) == 1
    assert (
        conn.execute("SELECT source FROM sessions WHERE id='original'").fetchone()[0]
        == "fixture"
    )
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_new_cleanup_after_compaction_prevents_completion_receipt(pair, monkeypatch):
    a, b = pair["a"], pair["b"]
    delivered(pair)
    b["conn"].execute(
        "INSERT INTO sessions(id,source) VALUES ('later-source','fixture')"
    )
    b["conn"].execute(
        "INSERT INTO messages(id,session_id,role,content) VALUES ('later-message','later-source','user','LATER_BODY')"
    )
    b["conn"].commit()
    forget(pair, "a")
    batch = ledger.prepare_controls(a["path"], a["config"], "b")
    original = ledger.compact

    def change(path):
        result = original(path)
        assert result["complete"]
        b["conn"].execute(
            "INSERT INTO context_tombstones VALUES ('later-source','later-control','fixture')"
        )
        b["conn"].commit()
        return result

    with monkeypatch.context() as race:
        race.setattr(ledger, "compact", change)
        receipt = ledger.apply_controls(b["path"], b["config"], "a", batch)
    assert receipt["canonical_cleanup"] == {
        "complete": False,
        "reason": "cleanup_pending_before_receipt",
    }
    assert not ledger.acknowledge_controls(a["path"], a["config"], "b", receipt)[
        "acknowledged"
    ]
    assert (
        b["conn"].execute("SELECT 1 FROM sessions WHERE id='later-source'").fetchone()
    )
    complete = ledger.apply_controls(b["path"], b["config"], "a", batch)
    assert ledger.acknowledge_controls(a["path"], a["config"], "b", complete)[
        "acknowledged"
    ]
    assert (
        not b["conn"]
        .execute("SELECT 1 FROM sessions WHERE id='later-source'")
        .fetchone()
    )


def test_offer_history_cannot_regress_or_swap_its_receipt(pair):
    a = pair["a"]
    _, _, receipt = delivered(pair)
    ledger.acknowledge_content(a["path"], a["config"], "b", receipt)
    for assignment in (
        "status='prepared'",
        "receipt_json='{}'",
        "acceptance_json='{}'",
        "scope='work'",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            a["conn"].execute(
                "UPDATE context_replica_offers SET "
                + assignment
                + " WHERE direction='out'"
            )
        a["conn"].rollback()


@pytest.mark.parametrize(
    "kind", ["evidence", "assertion", "relation", "observation", "record"]
)
def test_individual_artifact_controls_preserve_retirement_on_next_transfer(pair, kind):
    from agent_session_tools.context.provenance import ExecutionState, Scope
    from agent_session_tools.context.store import Access, Citation

    a, b = pair["a"], pair["b"]
    c = a["conn"]
    source = c.execute(
        "SELECT id FROM context_evidence WHERE session_id='codex_rollout-personal'"
    ).fetchone()[0]
    store = ContextStore(c)
    access = Access(scope=Scope.PERSONAL)
    assertions = [
        store.propose(
            statement=text,
            state=ExecutionState.UNKNOWN,
            target=None,
            generator="fixture",
            citations=[Citation(evidence_id=source, start=0, end=7, quote="STAGE34")],
            access=access,
        )
        for text in ["One report", "Another report"]
    ]
    relation = store.relate(
        assertions[0], assertions[1], "contradicts", "fixture", access
    )
    with store._atomic(), records.policy_guard(c):
        c.execute(
            "INSERT INTO study_sessions(id,session_id,started_at,notes) VALUES ('owned-study','codex_rollout-personal','fixture','Learner body')"
        )
        owner = records.bind(
            c, "study_sessions", "owned-study", session_id="codex_rollout-personal"
        )
    observation = c.execute(
        "SELECT id FROM context_observations ORDER BY recorded_at DESC LIMIT 1"
    ).fetchone()[0]
    ids = {
        "evidence": source,
        "assertion": assertions[0],
        "relation": relation,
        "observation": observation,
        "record": owner,
    }
    delivered(pair)
    table = ledger.OBJECTS[kind][0]
    with store._atomic():
        c.execute("DELETE FROM " + table + " WHERE id=?", (ids[kind],))
    controls = ledger.prepare_controls(a["path"], a["config"], "b")
    assert ledger.apply_controls(b["path"], b["config"], "a", controls)[
        "logical_committed"
    ]
    assert (
        not b["conn"]
        .execute("SELECT 1 FROM " + table + " WHERE id=?", (ids[kind],))
        .fetchone()
    )
    assert (
        b["conn"]
        .execute(
            "SELECT 1 FROM context_retirements WHERE kind=? AND object_id=?",
            (kind, ids[kind]),
        )
        .fetchone()
    )
    # A fresh allowed transfer must not disagree solely because peers observed
    # the same permanent retirement at different local times.
    value = accepted(pair)
    packet = ledger.release_content(a["path"], a["config"], "b", value)
    assert ledger.receive_content(b["path"], b["config"], "a", value["id"], packet)[
        "committed"
    ]
    assert (
        not b["conn"]
        .execute("SELECT 1 FROM " + table + " WHERE id=?", (ids[kind],))
        .fetchone()
    )
