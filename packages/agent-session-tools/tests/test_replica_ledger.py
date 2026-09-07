"""Actual SQLite/native-source offer, receipt and permanent-control interleavings."""

import json
import sqlite3
import subprocess
import sys

import pytest

from agent_session_tools.context import annotations, records
from agent_session_tools.context.lifecycle import purge_session
from agent_session_tools.context.scope import ScopeError, ScopePolicy, apply_policy
from agent_session_tools.context.store import ContextStore, _hash, _json
from agent_session_tools.exporters.codex import CodexExporter
from agent_session_tools import migrations
from agent_session_tools.replication import ledger, retention, retention_schema
from agent_session_tools.replication.content import apply_content
from agent_session_tools.replication.snapshot import TABLES
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
from agent_session_tools import migrations
from agent_session_tools.replication import ledger, retention, retention_schema
from agent_session_tools.replication.content import apply_content
from agent_session_tools.replication.snapshot import TABLES
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
    assert len(migrations.migrate(conn)) == migrations.CURRENT_VERSION - 41
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


def source(conn):
    return dict(
        conn.execute(
            "SELECT * FROM context_evidence WHERE session_id='codex_rollout-personal'"
        ).fetchone()
    )


def test_native_capture_is_local_evidence_history_not_a_whole_session_grant(pair):
    a = pair["a"]
    facts = retention.describe(a["conn"], "context_evidence", source(a["conn"]))
    assert facts["native_capture_observed"]
    assert facts["committed_peers"] == []
    assert not facts["unattributed_history"]
    assert facts["retention_authorized"] == "not_evaluated"
    # The source receipt does not claim native authorship of an agent's report.
    report = dict(
        a["conn"].execute("SELECT * FROM context_observations LIMIT 1").fetchone()
    )
    assert retention.describe(a["conn"], "context_observations", report)[
        "unattributed_history"
    ]


def test_accepted_offer_is_not_a_contribution_and_received_origins_are_not_local(pair):
    a, b = pair["a"], pair["b"]
    value = accepted(pair)
    assert not b["conn"].execute("SELECT 1 FROM context_retention_origins").fetchone()
    snapshot = ledger.release_content(a["path"], a["config"], "b", value)
    assert "context_retention_origins" not in snapshot["tables"]
    ledger.receive_content(b["path"], b["config"], "a", value["id"], snapshot)
    facts = retention.describe(b["conn"], "context_evidence", source(b["conn"]))
    assert facts["committed_peers"] == ["a"]
    assert not facts["native_capture_observed"]
    assert not facts["unattributed_history"]
    assert facts["independent_upstream_origins"] == "not_established"
    for table, rows in snapshot["tables"].items():
        if rows:
            assert (
                b["conn"]
                .execute(
                    "SELECT 1 FROM context_retention_origins WHERE table_name=? AND origin='peer_commit'",
                    (table,),
                )
                .fetchone()
            ), table


def test_preexisting_untracked_body_stays_explicitly_unattributed_after_delivery(pair):
    a, b = pair["a"], pair["b"]
    value = offer(pair)
    # The lower content-phase API intentionally has no authenticated ledger receipt.
    from agent_session_tools.replication.snapshot import export_snapshot

    snapshot = export_snapshot(a["path"], a["config"], value["plan"], "personal")
    apply_content(b["path"], b["config"], snapshot)
    assert retention.describe(b["conn"], "context_evidence", source(b["conn"]))[
        "unattributed_history"
    ]
    delivered(pair)
    facts = retention.describe(b["conn"], "context_evidence", source(b["conn"]))
    assert facts["committed_peers"] == ["a"] and facts["unattributed_history"]
    assert not facts["native_capture_observed"]


def test_changed_body_cannot_borrow_an_old_contribution(pair):
    delivered(pair)
    b = pair["b"]["conn"]
    row = dict(b.execute("SELECT * FROM messages LIMIT 1").fetchone())
    original = retention.describe(b, "messages", row)
    assert original["committed_peers"] == ["a"]
    b.execute("UPDATE messages SET content='CHANGED_BODY' WHERE id=?", (row["id"],))
    b.commit()
    row["content"] = "CHANGED_BODY"
    changed = retention.describe(b, "messages", row)
    assert changed["unattributed_history"] and changed["committed_peers"] == []
    assert changed["binding"]["row_sha256"] != original["binding"]["row_sha256"]


def test_receipt_retry_does_not_duplicate_origin_history(pair):
    value, snapshot, receipt = delivered(pair)
    b = pair["b"]
    before = list(b["conn"].iterdump())
    assert (
        ledger.receive_content(b["path"], b["config"], "a", value["id"], snapshot)
        == receipt
    )
    assert list(b["conn"].iterdump()) == before


def test_native_recapture_adds_capture_fact_without_relabeling_received_history(pair):
    delivered(pair)
    b = pair["b"]["conn"]
    pair["exporter"].export_all(b, incremental=False)
    facts = retention.describe(b, "context_evidence", source(b))
    assert facts["native_capture_observed"] and facts["committed_peers"] == ["a"]
    assert facts["retention_authorized"] == "not_evaluated"
    # This fact cannot implement regrant: withdrawal epochs are a separate gate.


def test_origin_history_does_not_save_body_paths_or_raw_composite_keys(pair):
    _, snapshot, _ = delivered(pair)
    b = pair["b"]["conn"]
    history = _json(
        [dict(r) for r in b.execute("SELECT * FROM context_retention_origins")]
    )
    assert "STAGE34_" not in history
    assert pair["a"]["config"]["memory"]["projects"]["p"]["roots"][0] not in history
    assert all(
        r["table_name"] in TABLES
        for r in b.execute("SELECT * FROM context_retention_origins")
    )
    assert snapshot["sha256"] not in history  # offers bind the snapshot separately


def test_origin_history_cannot_be_rewritten_or_constructed_without_offer(pair):
    conn = pair["a"]["conn"]
    for sql in (
        "DELETE FROM context_retention_origins",
        "UPDATE context_retention_origins SET origin='peer_commit'",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="managed reconciliation"):
            conn.execute(sql)
        conn.rollback()
    with pytest.raises(ValueError, match="accepted offer transaction"):
        retention.PeerContribution(conn, "b", "not-offered")


def test_origin_migration_preserves_unknown_legacy_and_rolls_back_on_failure(
    tmp_path, monkeypatch
):
    with monkeypatch.context() as old:
        old.setattr(migrations, "CURRENT_VERSION", 42)
        conn = records.connect(tmp_path / "old.db")
    conn.execute("INSERT INTO sessions(id,source) VALUES ('legacy','fixture')")
    conn.commit()
    before = list(conn.iterdump())
    original = retention_schema.install

    def fail(database):
        original(database)
        raise RuntimeError("origin migration failure")

    with monkeypatch.context() as fault:
        fault.setattr(retention_schema, "install", fail)
        with pytest.raises(RuntimeError, match="origin migration failure"):
            migrations.migrate(conn)
    assert list(conn.iterdump()) == before
    assert len(migrations.migrate(conn)) == migrations.CURRENT_VERSION - 42
    assert not conn.execute("SELECT 1 FROM context_retention_origins").fetchone()
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_two_delivering_peers_are_not_asserted_independent_origins(pair, tmp_path):
    delivered(pair)
    a, b = pair["a"], pair["b"]
    config = json.loads(json.dumps(a["config"]))
    config["memory"]["sync"] = {
        "node_id": "c",
        "peers": {
            "a": {"allowed_scopes": ["personal"]},
            "b": {"allowed_scopes": ["personal"]},
        },
    }
    cpath = tmp_path / "c.db"
    conn = records.connect(cpath)
    apply_policy(conn, ScopePolicy.from_config(config), actor="fixture", dry_run=False)
    a["config"]["memory"]["sync"]["peers"]["c"] = {"allowed_scopes": ["personal"]}
    b["config"]["memory"]["sync"]["peers"]["c"] = {"allowed_scopes": ["personal"]}
    c = {"path": cpath, "conn": conn, "config": config}
    try:
        for sender, receiver, sid, rid in ((a, c, "a", "c"), (c, b, "c", "b")):
            plan = negotiate(
                hello(sender["conn"], PeerPolicy.from_config(sender["config"], rid)),
                hello(
                    receiver["conn"], PeerPolicy.from_config(receiver["config"], sid)
                ),
            )
            value = ledger.prepare_offer(
                sender["path"], sender["config"], plan, "personal"
            )
            receipt = ledger.accept_offer(
                receiver["path"], receiver["config"], sid, value
            )
            ledger.record_acceptance(
                sender["path"], sender["config"], rid, value, receipt
            )
            packet = ledger.release_content(
                sender["path"], sender["config"], rid, value
            )
            ledger.receive_content(
                receiver["path"], receiver["config"], sid, value["id"], packet
            )
        facts = retention.describe(b["conn"], "context_evidence", source(b["conn"]))
        assert facts["committed_peers"] == ["a", "c"]
        assert facts["independent_upstream_origins"] == "not_established"
    finally:
        conn.close()


@pytest.mark.parametrize("node", ["a", "b"])
def test_replaced_database_instance_cannot_borrow_old_local_history(pair, node):
    delivered(pair)
    conn = pair[node]["conn"]
    conn.execute("UPDATE context_access_state SET instance='replacement' WHERE id=1")
    conn.commit()
    facts = retention.describe(conn, "context_evidence", source(conn))
    assert not facts["native_capture_observed"] and facts["committed_peers"] == []
    assert facts["unattributed_history"]


def test_integer_remapping_binds_contribution_to_received_learner_row(pair):
    a, b = pair["a"]["conn"], pair["b"]["conn"]
    for conn, label in ((a, "SENT"), (b, "UNRELATED_LOCAL")):
        conn.execute(
            "INSERT INTO knowledge_bridges(source_concept,source_domain,target_concept,target_domain) "
            "VALUES (?,'fixture','query','fixture')",
            (label,),
        )
        conn.commit()
    with ContextStore(a)._atomic(), records.policy_guard(a):
        owner = records.bind(
            a, "knowledge_bridges", 1, session_id="codex_rollout-personal"
        )
    delivered(pair)
    local_id = b.execute(
        "SELECT row_id FROM context_record_owners WHERE id=?", (owner,)
    ).fetchone()[0]
    assert local_id != "1"
    received = dict(
        b.execute("SELECT * FROM knowledge_bridges WHERE id=?", (local_id,)).fetchone()
    )
    unrelated = dict(b.execute("SELECT * FROM knowledge_bridges WHERE id=1").fetchone())
    assert retention.describe(b, "knowledge_bridges", received)["committed_peers"] == [
        "a"
    ]
    assert retention.describe(b, "knowledge_bridges", unrelated)["unattributed_history"]


def test_failed_native_history_write_rolls_back_the_native_body(pair, monkeypatch):
    conn = pair["b"]["conn"]
    original = retention.record_native_evidence

    def fail(*args):
        original(*args)
        raise RuntimeError("failure after native history")

    with monkeypatch.context() as fault:
        fault.setattr(retention, "record_native_evidence", fail)
        failed = pair["exporter"].export_all(conn, incremental=False)
    # The exporter records the failure and returns rather than propagating, so
    # one bad batch cannot abandon the remaining sources (base.flush_batch).
    # Assert it fired: without this, the empty-table checks below would also
    # pass for a fault that never triggered.
    assert failed.errors >= 1
    assert failed.added == 0
    for table in (
        "sessions",
        "messages",
        "context_evidence",
        "context_retention_origins",
    ):
        assert not conn.execute("SELECT 1 FROM " + table).fetchone()
    assert pair["exporter"].export_all(conn, incremental=False).added == 2


def test_contribution_requires_matching_peer_and_current_database_binding(pair):
    value = accepted(pair)
    conn = pair["b"]["conn"]
    with ContextStore(conn)._atomic():
        with pytest.raises(ValueError, match="peer binding"):
            retention.PeerContribution(conn, "never-registered", value["id"])
    conn.execute("UPDATE context_access_state SET instance='new-instance' WHERE id=1")
    conn.commit()
    with ContextStore(conn)._atomic():
        with pytest.raises(ValueError, match="peer binding"):
            retention.PeerContribution(conn, "a", value["id"])
    assert not conn.execute("SELECT 1 FROM context_retention_origins").fetchone()


def test_withdrawal_preview_uses_actual_cascades_without_changing_data(pair):
    from agent_session_tools.replication.withdrawal_preview import preview

    value, _, _ = delivered(pair)
    conn = pair["b"]["conn"]
    before = list(conn.iterdump())
    with ContextStore(conn)._atomic():
        result = preview(conn, "a", value["objects"])
    assert result["eligible"] and result["changed_rows"] > len(value["objects"])
    assert list(conn.iterdump()) == before
    assert not conn.execute(
        "SELECT 1 FROM sqlite_temp_master WHERE type='trigger'"
    ).fetchone()


@pytest.mark.parametrize(
    "change", ["new_message", "native_capture", "local_derivative"]
)
def test_withdrawal_preview_preserves_ambiguous_local_contributions(
    pair, change, monkeypatch
):
    from agent_session_tools.replication.withdrawal_preview import preview

    value, _, _ = delivered(pair)
    conn = pair["b"]["conn"]
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(pair["b"]["cfg"]))
    if change == "new_message":
        conn.execute(
            "INSERT INTO messages(id,session_id,role,content) VALUES ('new','codex_rollout-personal','user','LOCAL_ADDITION')"
        )
        conn.commit()
    elif change == "native_capture":
        pair["exporter"].export_all(conn, incremental=False)
    else:
        with ContextStore(conn)._atomic(), records.policy_guard(conn):
            annotations.write(
                conn, "codex_rollout-personal", "note", {"notes": "LOCAL_DERIVATIVE"}
            )
    before = list(conn.iterdump())
    with ContextStore(conn)._atomic():
        result = preview(conn, "a", value["objects"])
    assert not result["eligible"] and result["unresolved_rows"]
    assert "LOCAL_" not in _json(result)
    assert list(conn.iterdump()) == before


def permission_change(pair, action):
    from agent_session_tools.replication import permissions

    a, b = pair["a"], pair["b"]
    packet = permissions.prepare_change(a["path"], a["config"], "b", "personal", action)
    receipt = permissions.apply_change(b["path"], b["config"], "a", packet)
    return packet, receipt


def test_withdrawal_purges_without_permanent_retirement_and_fresh_regrant_restores(
    pair, monkeypatch
):
    from agent_session_tools.replication import permissions

    value, old_body, old_receipt = delivered(pair)
    a, b = pair["a"], pair["b"]
    before_ids = [
        r[0]
        for r in b["conn"].execute("SELECT id FROM context_observations ORDER BY id")
    ]
    packet, receipt = permission_change(pair, "withdraw")
    assert packet["generation"] == 1 and receipt["canonical_cleanup"]["complete"]
    assert permissions.acknowledge_change(a["path"], a["config"], "b", receipt)[
        "acknowledged"
    ]
    assert not b["conn"].execute("SELECT 1 FROM sessions").fetchone()
    assert not b["conn"].execute("SELECT 1 FROM context_retirements").fetchone()
    with pytest.raises(ReplicaError):
        ledger.release_content(a["path"], a["config"], "b", value)
    assert (
        ledger.receive_content(b["path"], b["config"], "a", value["id"], old_body)
        == old_receipt
    )
    assert not b["conn"].execute("SELECT 1 FROM sessions").fetchone()
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(b["cfg"]))
    assert pair["exporter"].export_all(b["conn"], incremental=False).withdrawn == 1
    grant, grant_receipt = permission_change(pair, "regrant")
    assert (
        grant["generation"] == 2
        and grant_receipt["assessment"]["awaiting_fresh_content"]
    )
    assert (
        not b["conn"]
        .execute("SELECT 1 FROM sessions WHERE id='codex_rollout-personal'")
        .fetchone()
    )
    fresh, _, _ = delivered(pair)
    assert fresh["generation"] == 2
    assert [
        r[0]
        for r in b["conn"].execute("SELECT id FROM context_observations ORDER BY id")
    ] == before_ids
    assert (
        not b["conn"]
        .execute("SELECT 1 FROM context_replica_denials WHERE status!='released'")
        .fetchone()
    )
    assert not b["conn"].execute("SELECT 1 FROM context_retirements").fetchone()


def test_withdrawal_quarantines_local_extra_and_regrant_cannot_expose_unoffered_body(
    pair, monkeypatch
):
    from agent_session_tools.context.scope import visibility_sql
    from agent_session_tools.context.store import Access
    from agent_session_tools.context.provenance import Scope
    from agent_session_tools.context.observations import ObservationStore
    from agent_session_tools.replication import permissions

    delivered(pair)
    a, b = pair["a"], pair["b"]
    c = b["conn"]
    eid = c.execute("SELECT id FROM context_evidence LIMIT 1").fetchone()[0]
    oid = c.execute("SELECT id FROM context_observations LIMIT 1").fetchone()[0]
    c.execute(
        "INSERT INTO messages(id,session_id,role,content) VALUES ('local-extra','codex_rollout-personal','user','UNSHARED_LOCAL_BODY')"
    )
    c.commit()
    packet, receipt = permission_change(pair, "withdraw")
    assert (
        not receipt["canonical_cleanup"]["complete"]
        and receipt["assessment"]["unresolved_rows"]
    )
    assert not permissions.acknowledge_change(a["path"], a["config"], "b", receipt)[
        "acknowledged"
    ]
    assert c.execute("SELECT 1 FROM messages WHERE id='local-extra'").fetchone()
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(b["cfg"]))
    clause, values = visibility_sql(c, "s.id")
    assert not c.execute("SELECT 1 FROM sessions s WHERE " + clause, values).fetchone()
    assert ContextStore(c).source(eid, Access(scope=Scope.PERSONAL)) is None
    assert ObservationStore(c).get(oid) is None
    c.rollback()
    permission_change(pair, "regrant")
    value = accepted(pair)
    body = ledger.release_content(a["path"], a["config"], "b", value)
    with pytest.raises(ReplicaError, match="does not cover"):
        ledger.receive_content(b["path"], b["config"], "a", value["id"], body)
    assert c.execute("SELECT 1 FROM messages WHERE id='local-extra'").fetchone()
    assert ContextStore(c).source(eid, Access(scope=Scope.PERSONAL)) is None
    c.rollback()


def test_empty_scope_can_withdraw_but_cannot_regrant_and_replays_do_not_regress(pair):
    from agent_session_tools.replication import permissions

    delivered(pair)
    a, b = pair["a"], pair["b"]
    for node, peer in ((a, "b"), (b, "a")):
        node["config"]["memory"]["sync"]["peers"][peer]["allowed_scopes"] = []
    packet, receipt = permission_change(pair, "withdraw")
    assert receipt["canonical_cleanup"]["complete"]
    with pytest.raises(ReplicaError):
        permissions.prepare_change(a["path"], a["config"], "b", "personal", "regrant")
    for node, peer in ((a, "b"), (b, "a")):
        node["config"]["memory"]["sync"]["peers"][peer]["allowed_scopes"] = ["personal"]
    grant, _ = permission_change(pair, "regrant")
    assert permissions.apply_change(b["path"], b["config"], "a", packet) == receipt
    assert (
        permissions.current(b["conn"], "a", "personal", "in")[0] == grant["generation"]
    )


def test_withdrawal_covers_receiver_acceptance_when_response_was_lost(pair):
    from agent_session_tools.replication import permissions

    a, b = pair["a"], pair["b"]
    value = offer(pair)
    acceptance = ledger.accept_offer(b["path"], b["config"], "a", value)
    packet, receipt = permission_change(pair, "withdraw")
    assert packet["objects"] == [] and receipt["canonical_cleanup"]["complete"]
    assert (
        b["conn"]
        .execute(
            "SELECT 1 FROM context_replica_denials WHERE object_id='codex_rollout-personal'"
        )
        .fetchone()
    )
    ledger.record_acceptance(a["path"], a["config"], "b", value, acceptance)
    with pytest.raises(ReplicaError):
        ledger.release_content(a["path"], a["config"], "b", value)
    assert permissions.current(b["conn"], "a", "personal", "in")[1] == "withdrawn"


def test_withdrawal_preview_overflow_rolls_back_and_leaves_no_mode_or_triggers(pair):
    from agent_session_tools.replication.withdrawal_preview import preview

    value, _, _ = delivered(pair)
    conn = pair["b"]["conn"]
    before = list(conn.iterdump())
    with ContextStore(conn)._atomic():
        result = preview(conn, "a", value["objects"], max_rows=1)
    assert result["reason"] == "footprint_limit" and not result["eligible"]
    assert list(conn.iterdump()) == before
    assert not conn.execute(
        "SELECT 1 FROM sqlite_temp_master WHERE type='trigger'"
    ).fetchone()


def test_withdrawal_preview_preserves_error_when_sqlite_aborts_whole_transaction(pair):
    from agent_session_tools.replication.withdrawal_preview import preview

    value, _, _ = delivered(pair)
    conn = pair["b"]["conn"]
    before = list(conn.iterdump())
    conn.execute(
        "CREATE TEMP TRIGGER abort_withdrawal BEFORE DELETE ON main.messages BEGIN SELECT RAISE(ROLLBACK,'injected whole transaction abort'); END"
    )
    with pytest.raises(
        sqlite3.IntegrityError, match="injected whole transaction abort"
    ):
        with ContextStore(conn)._atomic(), ContextStore(conn)._atomic():
            preview(conn, "a", value["objects"])
    assert not conn.in_transaction
    assert list(conn.iterdump()) == before
    assert not conn.execute(
        "SELECT 1 FROM sqlite_temp_master WHERE name LIKE 'withdraw_preview_%'"
    ).fetchone()


def test_scoped_public_forget_can_erase_quarantine_without_revealing_body(
    pair, monkeypatch
):
    from agent_session_tools.context.lifecycle import forget_session
    from agent_session_tools.context.scope import ScopeError

    delivered(pair)
    b = pair["b"]
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(b["cfg"]))
    with ContextStore(b["conn"])._atomic(), records.policy_guard(b["conn"]):
        b["conn"].execute(
            "INSERT INTO study_sessions(id,session_id,started_at,notes) VALUES ('local-study','codex_rollout-personal','fixture','LOCAL_PRIVATE_STUDY')"
        )
        records.bind(
            b["conn"],
            "study_sessions",
            "local-study",
            session_id="codex_rollout-personal",
        )
        b["conn"].execute(
            "INSERT INTO study_notes(study_session_id,title,body) VALUES ('local-study','fixture','LOCAL_PRIVATE_NOTE')"
        )
        records.bind(b["conn"], "study_notes", 1, session_id="codex_rollout-personal")
    _, receipt = permission_change(pair, "withdraw")
    assert not receipt["canonical_cleanup"]["complete"]
    before = list(b["conn"].iterdump())
    with monkeypatch.context() as wrong_scope:
        wrong_scope.setenv("SESSION_CONTEXT_SCOPE", "work")
        with pytest.raises(ScopeError):
            forget_session(b["conn"], "codex_rollout-personal", apply=True)
    assert list(b["conn"].iterdump()) == before
    preview = forget_session(b["conn"], "codex_rollout-personal")
    assert not preview["applied"] and preview["selected_counts"]["learner_records"] == 2
    assert "LOCAL_PRIVATE" not in _json(preview)
    assert list(b["conn"].iterdump()) == before
    assert forget_session(b["conn"], "codex_rollout-personal", apply=True)["applied"]
    for table in ("sessions", "study_sessions", "study_notes", "context_record_owners"):
        assert not b["conn"].execute("SELECT 1 FROM " + table).fetchone()


def test_foreign_key_refusal_rolls_back_withdrawal_and_denials(pair):
    from agent_session_tools.replication import permissions

    delivered(pair)
    a, b = pair["a"], pair["b"]
    b["conn"].execute(
        "CREATE TABLE test_restrict_purge(session_id TEXT REFERENCES sessions(id) ON DELETE RESTRICT)"
    )
    b["conn"].execute(
        "INSERT INTO test_restrict_purge VALUES ('codex_rollout-personal')"
    )
    b["conn"].commit()
    packet = permissions.prepare_change(
        a["path"], a["config"], "b", "personal", "withdraw"
    )
    before = list(b["conn"].iterdump())
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        permissions.apply_change(b["path"], b["config"], "a", packet)
    assert list(b["conn"].iterdump()) == before
    assert permissions.current(b["conn"], "a", "personal", "in")[:2] == (0, "granted")


def test_preview_byte_limit_preserves_complete_database(pair):
    from agent_session_tools.replication.withdrawal_preview import preview

    value, _, _ = delivered(pair)
    conn = pair["b"]["conn"]
    before = list(conn.iterdump())
    with ContextStore(conn)._atomic():
        result = preview(conn, "a", value["objects"], max_bytes=1)
    assert result["reason"] == "footprint_limit" and not result["eligible"]
    assert list(conn.iterdump()) == before


def test_concurrent_withdrawal_preparation_uses_one_generation(pair):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from agent_session_tools.replication import permissions

    delivered(pair)
    a = pair["a"]
    gate = Barrier(2)

    def prepare(_):
        gate.wait(timeout=5)
        return permissions.prepare_change(
            a["path"], a["config"], "b", "personal", "withdraw"
        )

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(prepare, range(2)))
    assert results[0] == results[1]
    assert permissions.current(a["conn"], "b", "personal", "out")[:2] == (
        1,
        "withdrawn",
    )
    assert (
        a["conn"]
        .execute("SELECT count(*) FROM context_replica_permission_batches")
        .fetchone()[0]
        == 1
    )


@pytest.fixture
def quarantined_pair(pair, monkeypatch):
    from pathlib import Path
    from agent_session_tools.context.observations import ObservationStore
    from agent_session_tools.context.provenance import ExecutionState, Scope
    from agent_session_tools.context.store import Access, Citation

    a, b = pair["a"], pair["b"]
    conn = a["conn"]
    store = ContextStore(conn)
    access = Access(scope=Scope.PERSONAL)
    eid = source(conn)["id"]
    claims = [
        store.propose(
            statement=text,
            state=ExecutionState.UNKNOWN,
            target=None,
            generator="fixture",
            citations=[Citation(evidence_id=eid, start=0, end=7, quote="STAGE34")],
            access=access,
        )
        for text in ("One claim", "Conflicting claim")
    ]
    relation = store.relate(claims[0], claims[1], "contradicts", "fixture", access)
    root = Path(a["config"]["memory"]["projects"]["p"]["roots"][0])
    with store._atomic(), records.policy_guard(conn):
        conn.execute(
            "INSERT INTO knowledge_bridges(source_concept,source_domain,target_concept,target_domain) VALUES ('LOCAL_PROJECT_RECORD','fixture','query','fixture')"
        )
        owner = records.bind(conn, "knowledge_bridges", 1, owner_path=root)
        observation = ObservationStore(conn).append(
            kind="fixture.project",
            subject="fixture",
            payload={"text": "PROJECT_ONLY_REPORT"},
            producer="fixture",
            authority="reported",
            owner_path=root,
        )
        records.link_observation(conn, owner, observation)
    value, _, _ = delivered(pair)
    b["conn"].execute(
        "INSERT INTO messages(id,session_id,role,content) VALUES ('local-extra','codex_rollout-personal','user','PRIVATE_LOCAL_ADDITION')"
    )
    b["conn"].commit()
    _, receipt = permission_change(pair, "withdraw")
    assert not receipt["canonical_cleanup"]["complete"]
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(b["cfg"]))
    pair["quarantine_ids"] = {
        "session": "codex_rollout-personal",
        "evidence": eid,
        "assertion": claims[0],
        "relation": relation,
        "observation": observation,
        "record": owner,
    }
    pair["initial_offer"] = value
    return pair


@pytest.mark.parametrize("kind", list(ledger.OBJECTS))
def test_quarantine_discard_supports_each_kind_and_preserves_denial(
    quarantined_pair, kind
):
    from agent_session_tools.replication import quarantine

    pair = quarantined_pair
    b = pair["b"]
    identity = pair["quarantine_ids"][kind]
    before = list(b["conn"].iterdump())
    plan = quarantine.inspect(b["path"], kind, identity)
    assert plan["changed_rows"] > 0 and plan["changed_by_table"]
    assert "PRIVATE_LOCAL_ADDITION" not in _json(
        plan
    ) and "PROJECT_ONLY_REPORT" not in _json(plan)
    assert list(b["conn"].iterdump()) == before
    with pytest.raises(ReplicaError, match="acknowledgement"):
        quarantine.discard(b["path"], kind, identity, plan["id"])
    assert list(b["conn"].iterdump()) == before
    result = quarantine.discard(
        b["path"],
        kind,
        identity,
        plan["id"],
        discard_local_additions=True,
        actor="fixture operator",
    )
    assert (
        result["logical_discard_committed"]
        and result["canonical_file_cleanup"]["complete"]
    )
    assert (
        not result["permanent_forget"]
        and not result["regrant"]
        and not result["sync_complete"]
    )
    table = ledger.OBJECTS[kind][0]
    assert (
        not b["conn"]
        .execute("SELECT 1 FROM " + table + " WHERE id=?", (identity,))
        .fetchone()
    )
    assert (
        b["conn"]
        .execute(
            "SELECT 1 FROM context_replica_denials WHERE kind=? AND object_id=? AND status!='released'",
            (kind, identity),
        )
        .fetchone()
    )
    assert not b["conn"].execute("SELECT 1 FROM context_retirements").fetchone()
    assert "context_quarantine_discards" not in TABLES
    assert not b["conn"].execute("PRAGMA foreign_key_check").fetchall()


def test_quarantine_listing_is_bounded_scoped_and_body_free(
    quarantined_pair, monkeypatch
):
    from agent_session_tools.replication import quarantine

    b = quarantined_pair["b"]
    before = list(b["conn"].iterdump())
    seen = []
    cursor = None
    while True:
        page = quarantine.list_objects(b["path"], limit=2, cursor=cursor)
        assert not page["bodies_included"] and len(page["items"]) <= 2
        assert "PRIVATE_" not in _json(page)
        seen.extend((r["kind"], r["object_id"]) for r in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == sorted(set(seen))
    assert {kind for kind, _ in seen} == set(ledger.OBJECTS)
    assert list(b["conn"].iterdump()) == before
    with monkeypatch.context() as wrong_scope:
        wrong_scope.setenv("SESSION_CONTEXT_SCOPE", "work")
        assert quarantine.list_objects(b["path"])["items"] == []
        with pytest.raises(ScopeError, match="unavailable"):
            quarantine.inspect(b["path"], "session", "codex_rollout-personal")


def test_quarantine_discard_recovers_fresh_transfer_and_retry_does_not_delete_it(
    quarantined_pair,
):
    from agent_session_tools.replication import quarantine

    pair = quarantined_pair
    b = pair["b"]
    identity = pair["quarantine_ids"]["session"]
    plan = quarantine.inspect(b["path"], "session", identity)
    receipt = quarantine.discard(
        b["path"], "session", identity, plan["id"], discard_local_additions=True
    )
    assert (
        not b["conn"]
        .execute("SELECT 1 FROM messages WHERE id='local-extra'")
        .fetchone()
    )
    permission_change(pair, "regrant")
    delivered(pair)
    assert (
        b["conn"].execute("SELECT 1 FROM sessions WHERE id=?", (identity,)).fetchone()
    )
    before = list(b["conn"].iterdump())
    assert (
        quarantine.discard(
            b["path"], "session", identity, plan["id"], discard_local_additions=True
        )
        == receipt
    )
    assert list(b["conn"].iterdump()) == before


def test_quarantine_plan_and_cursor_reject_new_permission_generation(quarantined_pair):
    from agent_session_tools.replication import quarantine

    pair = quarantined_pair
    b = pair["b"]
    plan = quarantine.inspect(b["path"], "session", "codex_rollout-personal")
    page = quarantine.list_objects(b["path"], limit=1)
    permission_change(pair, "regrant")
    before = list(b["conn"].iterdump())
    with pytest.raises(ReplicaError, match="stale"):
        quarantine.discard(
            b["path"],
            "session",
            "codex_rollout-personal",
            plan["id"],
            discard_local_additions=True,
        )
    with pytest.raises(ReplicaError, match="stale"):
        quarantine.list_objects(b["path"], cursor=page["next_cursor"])
    assert list(b["conn"].iterdump()) == before


def test_quarantine_discard_does_not_need_removed_peer_configuration(quarantined_pair):
    from agent_session_tools.replication import quarantine

    b = quarantined_pair["b"]
    plan = quarantine.inspect(b["path"], "session", "codex_rollout-personal")
    original_peers = b["config"]["memory"]["sync"]["peers"]
    b["config"]["memory"]["sync"]["peers"] = {}
    b["cfg"].write_text(json.dumps(b["config"]))
    assert quarantine.discard(
        b["path"],
        "session",
        "codex_rollout-personal",
        plan["id"],
        discard_local_additions=True,
    )["logical_discard_committed"]
    assert (
        b["conn"]
        .execute("SELECT 1 FROM context_replica_denials WHERE status!='released'")
        .fetchone()
    )
    b["config"]["memory"]["sync"]["peers"] = original_peers
    b["cfg"].write_text(json.dumps(b["config"]))
    assert not b["conn"].execute("SELECT 1 FROM sessions").fetchone()
    permission_change(quarantined_pair, "regrant")
    delivered(quarantined_pair)
    assert b["conn"].execute("SELECT 1 FROM sessions").fetchone()


def test_quarantine_cli_requires_explicit_loss_acknowledgement(quarantined_pair):
    from agent_session_tools.replication import quarantine

    b = quarantined_pair["b"]
    common = [
        sys.executable,
        "-I",
        "-m",
        "agent_session_tools.context.cli",
        "quarantine",
    ]

    def cli(*args):
        return subprocess.run(
            [*common, *args, "--db", str(b["path"])],
            capture_output=True,
            text=True,
            timeout=15,
        )

    listing = cli("list")
    assert listing.returncode == 0, listing.stderr
    assert json.loads(listing.stdout)["items"]
    read = cli("inspect", "codex_rollout-personal")
    assert read.returncode == 0, read.stderr
    plan = json.loads(read.stdout)
    assert "PRIVATE_LOCAL_ADDITION" not in read.stdout
    before = list(b["conn"].iterdump())
    refusal = cli("discard", "codex_rollout-personal", "--expect", plan["id"])
    assert refusal.returncode == 2 and "acknowledgement" in refusal.stderr
    assert "Traceback" not in refusal.stderr
    assert list(b["conn"].iterdump()) == before
    applied = cli(
        "discard",
        "codex_rollout-personal",
        "--expect",
        plan["id"],
        "--discard-local-additions",
    )
    assert applied.returncode == 0, applied.stderr
    assert json.loads(applied.stdout)["logical_discard_committed"]
    assert quarantine.list_objects(b["path"])["items"]  # project-owned roots remain


def test_quarantine_plan_binds_new_retention_facts_without_revision_change(
    quarantined_pair,
):
    from agent_session_tools.replication import quarantine

    b = quarantined_pair["b"]
    plan = quarantine.inspect(b["path"], "session", "codex_rollout-personal")
    revision = (
        b["conn"].execute("SELECT revision FROM context_access_state").fetchone()[0]
    )
    row = source(b["conn"])
    with ContextStore(b["conn"])._atomic():
        retention._record(
            b["conn"],
            retention._binding(b["conn"], "context_evidence", row),
            "unattributed",
            "",
            "",
        )
    assert (
        b["conn"].execute("SELECT revision FROM context_access_state").fetchone()[0]
        == revision
    )
    updated = quarantine.inspect(b["path"], "session", "codex_rollout-personal")
    assert updated["footprint_sha256"] != plan["footprint_sha256"]
    with pytest.raises(ReplicaError, match="stale"):
        quarantine.discard(
            b["path"],
            "session",
            "codex_rollout-personal",
            plan["id"],
            discard_local_additions=True,
        )


def test_quarantine_plan_cannot_override_later_permanent_forgetting(quarantined_pair):
    from agent_session_tools.context.lifecycle import forget_session
    from agent_session_tools.replication import quarantine

    b = quarantined_pair["b"]
    plan = quarantine.inspect(b["path"], "session", "codex_rollout-personal")
    forget_session(b["conn"], "codex_rollout-personal", apply=True)
    before = list(b["conn"].iterdump())
    with pytest.raises(ScopeError, match="unavailable"):
        quarantine.discard(
            b["path"],
            "session",
            "codex_rollout-personal",
            plan["id"],
            discard_local_additions=True,
        )
    assert list(b["conn"].iterdump()) == before
    assert not b["conn"].execute("SELECT 1 FROM context_quarantine_discards").fetchone()


def test_quarantine_discard_process_exit_before_audit_rolls_back(quarantined_pair):
    from agent_session_tools.replication import quarantine

    b = quarantined_pair["b"]
    plan = quarantine.inspect(b["path"], "session", "codex_rollout-personal")
    code = """
import os,sys
from contextlib import contextmanager
from pathlib import Path
from agent_session_tools.replication import ledger,quarantine
original=ledger._write
@contextmanager
def writer(path):
    with original(path) as conn:
        conn.create_function('die_now',0,lambda:os._exit(37))
        conn.execute("CREATE TEMP TRIGGER crash_discard BEFORE INSERT ON main.context_quarantine_discards BEGIN SELECT die_now(); END")
        yield conn
ledger._write=writer
quarantine.discard(Path(sys.argv[1]),'session','codex_rollout-personal',sys.argv[2],discard_local_additions=True)
"""
    before = list(b["conn"].iterdump())
    process = subprocess.run(
        [sys.executable, "-I", "-c", code, str(b["path"]), plan["id"]],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert process.returncode == 37, process.stderr
    assert list(b["conn"].iterdump()) == before
    assert quarantine.discard(
        b["path"],
        "session",
        "codex_rollout-personal",
        plan["id"],
        discard_local_additions=True,
    )["logical_discard_committed"]


def test_quarantine_discard_pending_cleanup_retries_without_new_decision(
    quarantined_pair,
):
    from agent_session_tools.replication import quarantine

    b = quarantined_pair["b"]
    plan = quarantine.inspect(b["path"], "session", "codex_rollout-personal")
    reader = sqlite3.connect(b["path"])
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT 1 FROM sessions").fetchone()
        pending = quarantine.discard(
            b["path"],
            "session",
            "codex_rollout-personal",
            plan["id"],
            discard_local_additions=True,
        )
        assert (
            pending["logical_discard_committed"]
            and not pending["canonical_file_cleanup"]["complete"]
        )
    finally:
        reader.close()
    done = quarantine.discard(
        b["path"],
        "session",
        "codex_rollout-personal",
        plan["id"],
        discard_local_additions=True,
    )
    assert done["canonical_file_cleanup"]["complete"]
    assert (
        b["conn"]
        .execute("SELECT count(*) FROM context_quarantine_discards")
        .fetchone()[0]
        == 1
    )


def test_quarantine_migration_rolls_back_and_preserves_existing_intent(
    tmp_path, monkeypatch
):
    from agent_session_tools.replication import quarantine_schema

    with monkeypatch.context() as old:
        old.setattr(migrations, "CURRENT_VERSION", 44)
        conn = records.connect(tmp_path / "old-quarantine.db")
    conn.execute("INSERT INTO sessions(id,source) VALUES ('legacy','fixture')")
    conn.commit()
    before = list(conn.iterdump())
    original = quarantine_schema.install

    def fail(database):
        original(database)
        raise RuntimeError("quarantine migration failure")

    try:
        with monkeypatch.context() as fault:
            fault.setattr(quarantine_schema, "install", fail)
            with pytest.raises(RuntimeError, match="quarantine migration failure"):
                migrations.migrate(conn)
        assert list(conn.iterdump()) == before
        assert len(migrations.migrate(conn)) == migrations.CURRENT_VERSION - 44
        assert not conn.execute("SELECT 1 FROM context_quarantine_discards").fetchone()
        assert conn.execute("SELECT id FROM sessions").fetchone()[0] == "legacy"
    finally:
        conn.close()


def test_quarantine_scope_file_change_during_discard_rolls_back(
    quarantined_pair, monkeypatch
):
    from agent_session_tools.replication import quarantine

    b = quarantined_pair["b"]
    plan = quarantine.inspect(b["path"], "session", "codex_rollout-personal")
    before = list(b["conn"].iterdump())
    original = quarantine.purge_objects

    def change(conn, objects):
        original(conn, objects)
        b["config"]["memory"]["projects"]["p"]["scope"] = "work"
        b["cfg"].write_text(json.dumps(b["config"]))

    monkeypatch.setattr(quarantine, "purge_objects", change)
    with pytest.raises(ScopeError, match="Scope changed"):
        quarantine.discard(
            b["path"],
            "session",
            "codex_rollout-personal",
            plan["id"],
            discard_local_additions=True,
        )
    assert list(b["conn"].iterdump()) == before


def test_quarantine_retention_fact_budget_never_issues_partial_fingerprint(
    quarantined_pair,
):
    from agent_session_tools.replication.withdrawal_preview import preview

    b = quarantined_pair["b"]
    binding = retention._binding(b["conn"], "context_evidence", source(b["conn"]))
    with ContextStore(b["conn"])._atomic():
        for number in range(101):
            retention._record(
                b["conn"], binding, "peer_commit", "a", f"historical-receipt-{number}"
            )
    before = list(b["conn"].iterdump())
    with ContextStore(b["conn"])._atomic():
        result = preview(
            b["conn"],
            "a",
            [{"kind": "session", "object_id": "codex_rollout-personal"}],
            max_rows=100,
        )
    assert result["reason"] == "footprint_limit" and "footprint_sha256" not in result
    assert list(b["conn"].iterdump()) == before


def test_quarantine_discard_audit_cannot_be_rewritten_or_deleted(quarantined_pair):
    from agent_session_tools.replication import quarantine

    b = quarantined_pair["b"]
    plan = quarantine.inspect(b["path"], "session", "codex_rollout-personal")
    quarantine.discard(
        b["path"],
        "session",
        "codex_rollout-personal",
        plan["id"],
        discard_local_additions=True,
    )
    for sql in (
        "DELETE FROM context_quarantine_discards",
        "UPDATE context_quarantine_discards SET actor='different actor'",
        "UPDATE context_quarantine_discards SET plan_json='{}'",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            b["conn"].execute(sql)
        b["conn"].rollback()


def test_quarantine_inspection_does_not_enable_ordinary_body_routes(quarantined_pair):
    from agent_session_tools.context.observations import ObservationStore
    from agent_session_tools.context.provenance import Scope
    from agent_session_tools.context.scope import active_policy, visibility_sql
    from agent_session_tools.context.store import Access
    from agent_session_tools.replication import quarantine, snapshot

    b = quarantined_pair["b"]
    ids = quarantined_pair["quarantine_ids"]
    for kind, identity in ids.items():
        assert quarantine.inspect(b["path"], kind, identity)["changed_rows"]
    conn = b["conn"]
    clause, values = visibility_sql(conn, "s.id")
    assert not conn.execute(
        "SELECT 1 FROM sessions s WHERE " + clause, values
    ).fetchone()
    assert (
        ContextStore(conn).source(ids["evidence"], Access(scope=Scope.PERSONAL)) is None
    )
    assert ObservationStore(conn).get(ids["observation"]) is None
    assert not records.is_visible(conn, "knowledge_bridges", 1)
    conn.rollback()
    with ledger._write(b["path"]) as selected:
        rows, _ = snapshot.collect(selected, active_policy(), Scope.PERSONAL)
        assert not any(rows.values())


def test_quarantine_receipt_scope_is_separate_from_policy_digest(
    quarantined_pair, monkeypatch
):
    from agent_session_tools.context.scope import active_policy
    from agent_session_tools.replication import quarantine

    b = quarantined_pair["b"]
    plan = quarantine.inspect(b["path"], "session", "codex_rollout-personal")
    quarantine.discard(
        b["path"],
        "session",
        "codex_rollout-personal",
        plan["id"],
        discard_local_additions=True,
    )
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "work")
    # Request scope intentionally does not change stored project classification.
    assert active_policy().digest == plan["policy_digest"]
    with pytest.raises(ScopeError, match="configured boundary"):
        quarantine.discard(
            b["path"],
            "session",
            "codex_rollout-personal",
            plan["id"],
            discard_local_additions=True,
        )


def test_quarantine_cleanup_receipt_detects_new_pending_work(
    quarantined_pair, monkeypatch
):
    from agent_session_tools.replication import quarantine

    b = quarantined_pair["b"]
    plan = quarantine.inspect(b["path"], "session", "codex_rollout-personal")
    original = quarantine.compact

    def interleave(path):
        result = original(path)
        assert result["complete"]
        with ledger._write(path) as writer:
            writer.execute("INSERT INTO context_erasure_pending VALUES (1,'new-work')")
        return result

    monkeypatch.setattr(quarantine, "compact", interleave)
    receipt = quarantine.discard(
        b["path"],
        "session",
        "codex_rollout-personal",
        plan["id"],
        discard_local_additions=True,
    )
    assert receipt["logical_discard_committed"]
    assert receipt["canonical_file_cleanup"] == {
        "complete": False,
        "reason": "cleanup_pending_before_receipt",
    }
    monkeypatch.setattr(quarantine, "compact", original)
    done = quarantine.discard(
        b["path"],
        "session",
        "codex_rollout-personal",
        plan["id"],
        discard_local_additions=True,
    )
    assert done["canonical_file_cleanup"]["complete"]
    assert (
        b["conn"]
        .execute("SELECT count(*) FROM context_quarantine_discards")
        .fetchone()[0]
        == 1
    )


@pytest.mark.parametrize("recursive", [0, 1])
def test_withdrawal_trace_covers_native_owned_learner_cascades(pair, recursive):
    from agent_session_tools.replication.withdrawal_preview import preview

    a, b = pair["a"]["conn"], pair["b"]["conn"]
    with ContextStore(a)._atomic(), records.policy_guard(a):
        a.execute(
            "INSERT INTO study_sessions(id,session_id,started_at,notes) VALUES ('study','codex_rollout-personal','fixture','SOURCE_OWNED_STUDY')"
        )
        records.bind(a, "study_sessions", "study", session_id="codex_rollout-personal")
        a.execute(
            "INSERT INTO study_notes(study_session_id,title,body) VALUES ('study','fixture','SOURCE_OWNED_NOTE')"
        )
        records.bind(a, "study_notes", 1, session_id="codex_rollout-personal")
        a.execute(
            "INSERT INTO parked_topics(study_session_id,question) VALUES ('study','SOURCE_OWNED_QUESTION')"
        )
        records.bind(a, "parked_topics", 1, session_id="codex_rollout-personal")
    value, _, _ = delivered(pair)
    b.execute(f"PRAGMA recursive_triggers={recursive}")
    before = list(b.iterdump())
    with ContextStore(b)._atomic():
        result = preview(b, "a", value["objects"])
    assert result["eligible"]
    assert list(b.iterdump()) == before
    _, receipt = permission_change(pair, "withdraw")
    assert receipt["canonical_cleanup"]["complete"]
    for table in (
        "study_sessions",
        "study_notes",
        "parked_topics",
        "context_record_owners",
    ):
        assert not b.execute("SELECT 1 FROM " + table).fetchone()
    assert not b.execute("PRAGMA foreign_key_check").fetchall()


def test_withdrawal_preview_holds_writer_lock_and_hides_simulated_purge(
    pair, monkeypatch
):
    from agent_session_tools.replication import withdrawal_preview

    value, _, _ = delivered(pair)
    b = pair["b"]
    other = sqlite3.connect(b["path"], timeout=0)
    original = withdrawal_preview.purge_objects
    observations = []

    def inspect(conn, objects):
        original(conn, objects)
        assert not conn.execute("SELECT 1 FROM sessions").fetchone()
        observations.append(
            other.execute("SELECT count(*) FROM sessions").fetchone()[0]
        )
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            other.execute("BEGIN IMMEDIATE")

    try:
        monkeypatch.setattr(withdrawal_preview, "purge_objects", inspect)
        with ContextStore(b["conn"])._atomic():
            assert withdrawal_preview.preview(b["conn"], "a", value["objects"])[
                "eligible"
            ]
        assert observations == [1]
        other.execute("BEGIN IMMEDIATE")
        other.rollback()
    finally:
        other.close()


@pytest.mark.parametrize("point", ["preview", "purge", "receipt"])
def test_process_death_during_withdrawal_leaves_no_partial_permission(
    pair, tmp_path, point
):
    from agent_session_tools.replication import permissions

    delivered(pair)
    a, b = pair["a"], pair["b"]
    packet = permissions.prepare_change(
        a["path"], a["config"], "b", "personal", "withdraw"
    )
    payload = tmp_path / "withdrawal.json"
    payload.write_text(json.dumps(packet))
    code = """
import json,os,sys
from contextlib import contextmanager
from pathlib import Path
from agent_session_tools.replication import ledger,permissions,withdrawal_preview
point=sys.argv[4]
if point in ('preview','purge'):
    target=withdrawal_preview if point=='preview' else permissions
    original=target.purge_objects
    def dying(conn,objects):
        original(conn,objects)
        os._exit(36)
    target.purge_objects=dying
else:
    original=ledger._write
    @contextmanager
    def writer(path):
        with original(path) as conn:
            conn.create_function('die_now',0,lambda:os._exit(36))
            conn.execute("CREATE TEMP TRIGGER crash_withdrawal BEFORE INSERT ON main.context_replica_permission_batches BEGIN SELECT die_now(); END")
            yield conn
    ledger._write=writer
permissions.apply_change(Path(sys.argv[1]),json.loads(Path(sys.argv[2]).read_text()),'a',json.loads(Path(sys.argv[3]).read_text()))
"""
    before = list(b["conn"].iterdump())
    run = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            code,
            str(b["path"]),
            str(b["cfg"]),
            str(payload),
            point,
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert run.returncode == 36, run.stderr
    assert list(b["conn"].iterdump()) == before
    assert permissions.apply_change(b["path"], b["config"], "a", packet)[
        "canonical_cleanup"
    ]["complete"]


def test_permission_migration_is_additive_and_rolls_back_on_failure(
    tmp_path, monkeypatch
):
    from agent_session_tools.replication import withdrawal_schema

    with monkeypatch.context() as old:
        old.setattr(migrations, "CURRENT_VERSION", 43)
        conn = records.connect(tmp_path / "old-permissions.db")
    conn.execute("INSERT INTO sessions(id,source) VALUES ('legacy','fixture')")
    conn.commit()
    before = list(conn.iterdump())
    original = withdrawal_schema.install

    def fail(database):
        original(database)
        raise RuntimeError("permission migration failure")

    try:
        with monkeypatch.context() as fault:
            fault.setattr(withdrawal_schema, "install", fail)
            with pytest.raises(RuntimeError, match="permission migration failure"):
                migrations.migrate(conn)
        assert list(conn.iterdump()) == before
        assert len(migrations.migrate(conn)) == migrations.CURRENT_VERSION - 43
        assert conn.execute("SELECT id FROM sessions").fetchone()[0] == "legacy"
        assert not conn.execute("SELECT 1 FROM context_replica_denials").fetchone()
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        conn.close()


def test_direct_content_api_cannot_bypass_permission_history(pair):
    from agent_session_tools.replication.snapshot import export_snapshot

    delivered(pair)
    a, b = pair["a"], pair["b"]
    permission_change(pair, "withdraw")
    plan = negotiate(
        hello(a["conn"], PeerPolicy.from_config(a["config"], "b")),
        hello(b["conn"], PeerPolicy.from_config(b["config"], "a")),
    )
    with pytest.raises(ReplicaError, match="withdrawn"):
        export_snapshot(a["path"], a["config"], plan, "personal")
    permission_change(pair, "regrant")
    value = accepted(pair)
    body = ledger.release_content(a["path"], a["config"], "b", value)
    before = list(b["conn"].iterdump())
    with pytest.raises(ReplicaError, match="durable content coordinator"):
        apply_content(b["path"], b["config"], body)
    assert list(b["conn"].iterdump()) == before
    assert ledger.receive_content(b["path"], b["config"], "a", value["id"], body)[
        "committed"
    ]


@pytest.mark.parametrize(
    "change",
    ["gap", "boolean_generation", "unknown_object", "wrong_instance", "first_regrant"],
)
def test_invalid_permission_control_cannot_change_receiver(pair, change):
    from agent_session_tools.replication import permissions

    delivered(pair)
    a, b = pair["a"], pair["b"]
    packet = permissions.prepare_change(
        a["path"], a["config"], "b", "personal", "withdraw"
    )
    if change == "gap":
        packet["generation"] = 2
    elif change == "boolean_generation":
        packet["generation"] = True
    elif change == "unknown_object":
        packet["objects"] = [{"kind": "session", "object_id": "never-received"}]
    elif change == "wrong_instance":
        packet["sender_instance"] = "different-machine"
    else:
        packet["action"] = "regrant"
    reseal(packet)
    before = list(b["conn"].iterdump())
    with pytest.raises(ReplicaError):
        permissions.apply_change(b["path"], b["config"], "a", packet)
    assert list(b["conn"].iterdump()) == before


def test_withdrawal_cleanup_retries_after_reader_releases_snapshot(pair):
    from agent_session_tools.replication import permissions

    delivered(pair)
    a, b = pair["a"], pair["b"]
    reader = sqlite3.connect(b["path"])
    try:
        reader.execute("BEGIN")
        assert reader.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1
        packet, pending = permission_change(pair, "withdraw")
        assert not pending["canonical_cleanup"]["complete"]
        assert not permissions.acknowledge_change(a["path"], a["config"], "b", pending)[
            "acknowledged"
        ]
        assert not b["conn"].execute("SELECT 1 FROM sessions").fetchone()
        assert reader.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1
    finally:
        reader.close()
    done = permissions.apply_change(b["path"], b["config"], "a", packet)
    assert done["canonical_cleanup"]["complete"]
    assert permissions.acknowledge_change(a["path"], a["config"], "b", done)[
        "acknowledged"
    ]


def test_regrant_between_compaction_and_receipt_prevents_cleanup_ack(pair, monkeypatch):
    from agent_session_tools.replication import permissions

    delivered(pair)
    a, b = pair["a"], pair["b"]
    original = permissions.compact

    def race(path):
        result = original(path)
        assert result["complete"]
        permission_change(pair, "regrant")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(permissions, "compact", race)
        packet, receipt = permission_change(pair, "withdraw")
    assert receipt["canonical_cleanup"] == {
        "complete": False,
        "reason": "permission_changed_before_receipt",
    }
    assert not permissions.acknowledge_change(a["path"], a["config"], "b", receipt)[
        "acknowledged"
    ]
    assert permissions.current(b["conn"], "a", "personal", "in")[:2] == (2, "granted")
    assert permissions.apply_change(b["path"], b["config"], "a", packet) == receipt


def test_permanent_forget_wins_over_withdrawal_regrant_and_native_reimport(
    pair, monkeypatch
):
    from agent_session_tools.replication import permissions

    delivered(pair)
    a, b = pair["a"], pair["b"]
    forget(pair, "b")
    retired = list(b["conn"].execute("SELECT * FROM context_retirements"))
    permission_change(pair, "withdraw")
    permission_change(pair, "regrant")
    value = offer(pair)
    acceptance = ledger.accept_offer(b["path"], b["config"], "a", value)
    assert acceptance["status"] == "retired"
    ledger.record_acceptance(a["path"], a["config"], "b", value, acceptance)
    with pytest.raises(ReplicaError):
        ledger.release_content(a["path"], a["config"], "b", value)
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(b["cfg"]))
    stats = pair["exporter"].export_all(b["conn"], incremental=False)
    assert stats.forgotten == 1 and stats.withdrawn == 0
    assert list(b["conn"].execute("SELECT * FROM context_retirements")) == retired
    assert (
        not b["conn"]
        .execute("SELECT 1 FROM sessions WHERE id='codex_rollout-personal'")
        .fetchone()
    )
    assert permissions.current(b["conn"], "a", "personal", "in")[0] == 2
