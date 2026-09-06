"""Actual subprocess protocol, current config and recovery without body replay."""

from contextlib import closing
import json
import os
import sqlite3
import sys
import struct
import subprocess

import pytest

from agent_session_tools.context import records
from agent_session_tools.context.lifecycle import purge_session
from agent_session_tools.context.scope import ScopePolicy, apply_policy
from agent_session_tools.context.store import ContextStore
from agent_session_tools.exporters.codex import CodexExporter
from agent_session_tools.replication import coordinator, ledger, permissions, ssh
from agent_session_tools.replication.endpoint import Endpoint
from agent_session_tools.replication.policy import ReplicaError
from agent_session_tools.replication.wire import MARKER, ProcessConnection


@pytest.fixture
def replicas(tmp_path, monkeypatch):
    nodes = {}
    for name, peer in (("a", "b"), ("b", "a")):
        root = tmp_path / name
        root.mkdir()
        db, cfg = root / "sessions.db", root / "config.json"
        config = {
            "database": {"path": str(db)},
            "logging": {"path": str(root / "test.log"), "level": "WARNING"},
            "memory": {
                "default_scope": "personal",
                "projects": {
                    scope: {"scope": scope, "roots": [str(root / scope)]}
                    for scope in ("personal", "work")
                },
                "sync": {
                    "node_id": name,
                    "peers": {peer: {"allowed_scopes": ["personal"]}},
                },
            },
        }
        cfg.write_text(json.dumps(config))
        monkeypatch.setenv("STUDYLOOP_CONFIG", str(cfg))
        monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "personal")
        with closing(records.connect(db)) as conn:
            apply_policy(
                conn, ScopePolicy.from_config(config), actor="fixture", dry_run=False
            )
            native = root / "native"
            native.mkdir()
            for scope in ("personal", "work"):
                rows = [
                    {
                        "type": "session_meta",
                        "payload": {"id": name + scope, "cwd": str(root / scope)},
                    },
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": name + "_STAGE38_" + scope.upper(),
                                }
                            ],
                        },
                    },
                ]
                (native / f"rollout-{name}-{scope}.jsonl").write_text(
                    "".join(json.dumps(r) + "\n" for r in rows)
                )
            assert CodexExporter(native).export_all(conn).added == 2
        nodes[name] = {"db": db, "cfg": cfg, "config": config, "peer": peer}
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(nodes["a"]["cfg"]))
    return nodes


def process(node):
    # This test adapter proves pipe/process behavior, not SSH authentication.
    env = {
        **os.environ,
        "STUDYLOOP_CONFIG": str(node["cfg"]),
        "SSH_ORIGINAL_COMMAND": MARKER,
        "SSH_CONNECTION": "127.0.0.1 40001 127.0.0.1 40002",
    }
    return ProcessConnection(
        [
            sys.executable,
            "-I",
            "-m",
            "agent_session_tools.replication.server",
            "--peer",
            node["peer"],
        ],
        env=env,
        timeout=30,
    )


def local(node):
    return Endpoint(
        node["peer"], db=node["db"], loader=lambda: json.loads(node["cfg"].read_text())
    )


def count(node, text):
    with closing(sqlite3.connect(node["db"])) as conn:
        return conn.execute(
            "SELECT count(*) FROM messages WHERE content=?", (text,)
        ).fetchone()[0]


def exchange(nodes, direction="sync"):
    with closing(process(nodes["a"])) as a, closing(process(nodes["b"])) as b:
        return coordinator.synchronize(a, b, direction=direction)


def test_two_process_scoped_transfer_and_unchanged_retry(replicas):
    result = exchange(replicas, "push")
    assert result["canonical_phase_completed"] and not result["sync_complete"]
    assert count(replicas["b"], "a_STAGE38_PERSONAL") == 1
    assert count(replicas["b"], "a_STAGE38_WORK") == 0
    assert count(replicas["a"], "b_STAGE38_PERSONAL") == 0
    repeated = exchange(replicas, "push")
    assert repeated["transfers"] == []
    assert repeated["unchanged"] == [{"direction": "push", "scope": "personal"}]
    result = exchange(replicas, "pull")
    assert result["transfers"][0]["direction"] == "pull"
    assert count(replicas["a"], "b_STAGE38_PERSONAL") == 1
    assert count(replicas["a"], "b_STAGE38_WORK") == 0


def test_new_content_without_access_change_is_transferred(replicas):
    from agent_session_tools.replication.policy import state

    exchange(replicas, "push")
    with ledger._write(replicas["a"]["db"]) as conn:
        before = state(conn)
        conn.execute(
            "INSERT INTO messages(id,session_id,role,content) VALUES ('new-content','codex_rollout-a-personal','user','new source content')"
        )
        after = state(conn)
    assert after["revision"] == before["revision"]
    assert after["content_revision"] > before["content_revision"]
    result = exchange(replicas, "push")
    assert len(result["transfers"]) == 1 and not result["unchanged"]
    assert count(replicas["b"], "new source content") == 1


def test_other_scope_changes_invalidate_shortcut_without_exporting_that_scope(replicas):
    exchange(replicas, "push")
    with ledger._write(replicas["a"]["db"]) as conn:
        conn.execute(
            "INSERT INTO messages(id,session_id,role,content) VALUES ('work-change','codex_rollout-a-work','user','new private work body')"
        )
    result = exchange(replicas, "push")
    assert len(result["transfers"]) == 1 and not result["unchanged"]
    assert count(replicas["b"], "new private work body") == 0


def test_content_revision_overflow_rolls_back_the_body_write(replicas):
    with ledger._write(replicas["a"]["db"]) as conn:
        conn.execute(
            "UPDATE context_replica_content_state SET revision=?", (2**63 - 1,)
        )
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint"):
        with ledger._write(replicas["a"]["db"]) as conn:
            conn.execute(
                "INSERT INTO messages(id,session_id,role,content) VALUES ('overflow','codex_rollout-a-personal','user','must not commit')"
            )
    assert count(replicas["a"], "must not commit") == 0
    with closing(sqlite3.connect(replicas["a"]["db"])) as conn:
        assert (
            conn.execute(
                "SELECT revision FROM context_replica_content_state"
            ).fetchone()[0]
            == 2**63 - 1
        )


def test_every_projected_table_has_all_three_content_change_triggers(replicas):
    from agent_session_tools.replication.snapshot import TABLES

    with closing(sqlite3.connect(replicas["a"]["db"])) as conn:
        triggers = conn.execute(
            "SELECT tbl_name,sql FROM sqlite_master WHERE type='trigger' AND name LIKE 'replica_content_%'"
        ).fetchall()
    assert {table for table, _ in triggers} == set(TABLES)
    for table in TABLES:
        definitions = [sql for target, sql in triggers if target == table]
        assert len(definitions) == 3
        for event in ("INSERT", "UPDATE", "DELETE"):
            assert any(f"AFTER {event} ON {table} " in sql for sql in definitions)


@pytest.mark.parametrize("lost_operation", ["accept", "receive"])
def test_lost_response_recovers_durable_metadata_before_bodies(
    replicas, lost_operation
):
    class Lost:
        def __init__(self, endpoint):
            self.endpoint = endpoint

        def call(self, operation, arguments):
            result = self.endpoint.call(operation, arguments)
            if operation == lost_operation:
                raise ReplicaError("simulated lost response")
            return result

    with closing(process(replicas["a"])) as a, closing(process(replicas["b"])) as b:
        with pytest.raises(ReplicaError, match="simulated"):
            coordinator.synchronize(a, Lost(b), direction="push")
    result = exchange(replicas, "push")
    assert count(replicas["b"], "a_STAGE38_PERSONAL") == 1
    if lost_operation == "receive":
        assert result["recovered"]["push"]["receipts"] == 1
        assert not result["transfers"]  # No old or new duplicate body is sent.
    else:
        assert result["recovered"]["push"]["superseded"] == 1


def test_push_reconciles_receivers_forgetting_back_to_sender_first(replicas):
    exchange(replicas, "push")
    with (
        closing(records.connect(replicas["b"]["db"])) as conn,
        ContextStore(conn)._atomic(),
    ):
        purge_session(conn, "codex_rollout-a-personal")
    exchange(replicas, "push")
    assert count(replicas["a"], "a_STAGE38_PERSONAL") == 0
    assert count(replicas["b"], "a_STAGE38_PERSONAL") == 0


def test_config_change_inside_receiver_transaction_rolls_back(replicas, monkeypatch):
    original = ledger.apply_in_transaction

    def revoke(*args, **kwargs):
        original(*args, **kwargs)
        config = replicas["b"]["config"]
        config["memory"]["sync"]["peers"]["a"]["allowed_scopes"] = []
        replicas["b"]["cfg"].write_text(json.dumps(config))

    monkeypatch.setattr(ledger, "apply_in_transaction", revoke)
    with pytest.raises(ReplicaError, match="configuration changed"):
        coordinator.synchronize(
            local(replicas["a"]), local(replicas["b"]), direction="push"
        )
    assert count(replicas["b"], "a_STAGE38_PERSONAL") == 0
    with closing(sqlite3.connect(replicas["b"]["db"])) as conn:
        assert not conn.execute(
            "SELECT 1 FROM context_replica_offers WHERE receipt_json IS NOT NULL"
        ).fetchone()


def test_controls_required_before_any_content_operation(replicas):
    a, b = local(replicas["a"]), local(replicas["b"])
    a.call("bind", {"remote": b.call("hello", {})})
    with pytest.raises(ReplicaError, match="both directions"):
        a.call("prepare", {"plan": {}, "scope": "personal"})
    with pytest.raises(ReplicaError, match="Unsupported"):
        a.call("execute_sql", {"sql": "SELECT * FROM messages"})


def test_withdrawal_and_empty_grants_still_reconcile_known_controls(replicas):
    exchange(replicas, "push")
    a = replicas["a"]
    permissions.prepare_change(a["db"], a["config"], "b", "personal", "withdraw")
    for node in replicas.values():
        node["config"]["memory"]["sync"]["peers"][node["peer"]]["allowed_scopes"] = []
        node["cfg"].write_text(json.dumps(node["config"]))
    result = exchange(replicas, "push")
    assert not result["transfers"]
    assert count(replicas["b"], "a_STAGE38_PERSONAL") == 0


def test_ssh_uses_dedicated_key_and_strict_known_hosts(replicas, tmp_path):
    config = replicas["a"]["config"]
    key, known = tmp_path / "key", tmp_path / "known"
    key.write_text("fixture placeholder")
    known.write_text("fixture placeholder")
    config["memory"]["sync"]["peers"]["b"]["ssh"] = {
        "host": "127.0.0.1",
        "user": "fixture",
        "port": 22022,
        "identity_file": str(key),
        "known_hosts": str(known),
    }
    command = ssh.command(config, "b")
    assert command[-3:] == ["--", "127.0.0.1", MARKER]
    assert "StrictHostKeyChecking=yes" in command and "IdentityAgent=none" in command
    assert "ClearAllForwardings=yes" in command and command[1:3] == ["-F", "/dev/null"]
    config["memory"]["sync"]["peers"]["b"]["ssh"]["host"] = "-oProxyCommand=unexpected"
    with pytest.raises(ReplicaError, match="host"):
        ssh.command(config, "b")


def test_forced_command_rejects_caller_command(monkeypatch):
    monkeypatch.setenv("SSH_CONNECTION", "127.0.0.1 1 127.0.0.1 2")
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", "session-sync serve --peer someone-else")
    with pytest.raises(ReplicaError, match="forced command"):
        ssh.require_forced_command()


@pytest.mark.parametrize("body", [b'{"x":1,"x":2}', b'{"x":NaN}', b"\xff", b"{"])
def test_wire_rejects_malformed_json_without_reading_source(replicas, body):
    env = {
        **os.environ,
        "STUDYLOOP_CONFIG": str(replicas["b"]["cfg"]),
        "SSH_ORIGINAL_COMMAND": MARKER,
        "SSH_CONNECTION": "127.0.0.1 1 127.0.0.1 2",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "agent_session_tools.replication.server",
            "--peer",
            "a",
        ],
        input=struct.pack("!I", len(body)) + body,
        env=env,
        capture_output=True,
        timeout=5,
    )
    assert (
        result.returncode == 1 and not result.stdout and b"STAGE38" not in result.stderr
    )


def test_wire_bounds_header_and_deadline(replicas):
    from agent_session_tools.replication.wire import MAX_FRAME

    code = "import os,struct,time;os.write(1,struct.pack('!I',int(__import__('sys').argv[1])));time.sleep(60)"
    with closing(
        ProcessConnection(
            [sys.executable, "-I", "-c", code, str(MAX_FRAME + 1)], timeout=1
        )
    ) as peer:
        with pytest.raises(ReplicaError, match="limit"):
            peer.call("hello", {})
    with closing(
        ProcessConnection(
            [sys.executable, "-I", "-c", "import time;time.sleep(60)"], timeout=0.05
        )
    ) as peer:
        with pytest.raises(ReplicaError, match="deadline"):
            peer.call("hello", {})


def test_hello_cannot_relabel_an_authenticated_peer(replicas):
    a, b = local(replicas["a"]), local(replicas["b"])
    hello = b.call("hello", {})
    hello["node"] = "impostor"
    with pytest.raises(ReplicaError, match="authenticated peer"):
        a.call("bind", {"remote": hello})


def test_all_keeps_push_then_pull_order_and_attempts_other_peers(replicas, monkeypatch):
    from agent_session_tools import sync
    from typer.testing import CliRunner

    config = replicas["a"]["config"]
    config["memory"]["sync"]["peers"]["offline"] = {"allowed_scopes": ["personal"]}
    replicas["a"]["cfg"].write_text(json.dumps(config))
    monkeypatch.setattr(sync, "_config", None)
    seen = []

    def run(peer, *, direction, db=None):
        seen.append((direction, peer))
        if peer == "offline":
            raise ReplicaError("offline fixture")
        return {"cleanup_pending": []}

    monkeypatch.setattr(coordinator, "run", run)
    result = CliRunner().invoke(sync.app, ["all"])
    assert result.exit_code == 1
    assert seen == [
        ("push", "b"),
        ("push", "offline"),
        ("pull", "b"),
        ("pull", "offline"),
    ]


def test_source_change_at_wire_release_refuses_buffered_body(replicas, monkeypatch):
    a = local(replicas["a"])
    original = a._release

    def revoke(offer):
        result = original(offer)
        permissions.prepare_change(
            replicas["a"]["db"], replicas["a"]["config"], "b", "personal", "withdraw"
        )
        return result

    monkeypatch.setattr(a, "_release", revoke)
    with closing(process(replicas["b"])) as b:
        b.before_send = a.before_remote_send
        with pytest.raises(ReplicaError, match="Source or controls changed"):
            coordinator.synchronize(a, b, direction="push")
    assert count(replicas["b"], "a_STAGE38_PERSONAL") == 0


def test_lost_acceptance_then_forget_recovers_interest_before_controls(replicas):
    class LostAcceptance:
        def __init__(self, endpoint):
            self.endpoint = endpoint

        def call(self, operation, arguments):
            value = self.endpoint.call(operation, arguments)
            if operation == "accept":
                raise ReplicaError("lost acceptance fixture")
            return value

    with closing(process(replicas["a"])) as a, closing(process(replicas["b"])) as b:
        with pytest.raises(ReplicaError, match="lost acceptance"):
            coordinator.synchronize(a, LostAcceptance(b), direction="push")
    with (
        closing(records.connect(replicas["a"]["db"])) as conn,
        ContextStore(conn)._atomic(),
    ):
        assert not conn.execute("SELECT 1 FROM context_replica_objects").fetchone()
        purge_session(conn, "codex_rollout-a-personal")
    result = exchange(replicas, "push")
    assert result["recovered"]["push"]["superseded"] == 1
    with closing(sqlite3.connect(replicas["b"]["db"])) as conn:
        assert conn.execute(
            "SELECT 1 FROM context_retirements WHERE kind='session' AND object_id='codex_rollout-a-personal'"
        ).fetchone()
    assert count(replicas["b"], "a_STAGE38_PERSONAL") == 0


def test_historical_offer_schema_can_recover_acceptance_but_not_release(replicas):
    from agent_session_tools.replication.policy import negotiate
    from agent_session_tools.context.store import _json, _now

    a, b = local(replicas["a"]), local(replicas["b"])
    ah, bh = a.call("hello", {}), b.call("hello", {})
    a.call("bind", {"remote": bh})
    b.call("bind", {"remote": ah})
    plan = negotiate(ah, bh)
    plan["sender"]["schema"] = plan["receiver"]["schema"] = 45
    del plan["sender"]["state"]["content_revision"]
    del plan["receiver"]["state"]["content_revision"]
    old = ledger._seal(
        {
            "contract": "session-replica-offer/v2",
            "plan": plan,
            "scope": "personal",
            "snapshot_sha256": "0" * 64,
            "objects": [],
            "generation": 0,
        }
    )
    acceptance = ledger._seal(
        {
            "contract": "session-replica-acceptance/v1",
            "offer_id": old["id"],
            "receiver": "b",
            "instance": bh["state"]["instance"],
            "status": "accepted",
        }
    )
    with ledger._write(replicas["a"]["db"]) as conn:
        conn.execute(
            "INSERT INTO context_replica_offers VALUES (?,'out','b','personal',?,'prepared',NULL,NULL,?)",
            (old["id"], _json(old), _now()),
        )
    ledger.record_acceptance(
        replicas["a"]["db"], replicas["a"]["config"], "b", old, acceptance
    )
    with pytest.raises(ReplicaError, match="schema"):
        ledger.release_content(replicas["a"]["db"], replicas["a"]["config"], "b", old)


def test_schema46_migration_failure_preserves_schema45_content(replicas, monkeypatch):
    from agent_session_tools import migrations

    db = replicas["a"]["db"]
    with closing(sqlite3.connect(db)) as conn:
        for (trigger,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'replica_content_%'"
        ).fetchall():
            conn.execute('DROP TRIGGER "' + trigger + '"')
        conn.execute("DROP TABLE context_replica_content_state")
        conn.execute("DROP TABLE context_replica_superseded")
        conn.execute("PRAGMA user_version=45")
        conn.commit()
        before = list(conn.iterdump())
        description, implementation = migrations.MIGRATIONS[46]

        def fail(connection):
            implementation(connection)
            raise RuntimeError("injected schema46 failure")

        with monkeypatch.context() as fault:
            fault.setitem(migrations.MIGRATIONS, 46, (description, fail))
            with pytest.raises(RuntimeError, match="schema46 failure"):
                migrations.migrate(conn)
        assert list(conn.iterdump()) == before
        migrations.migrate(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 46
        assert not conn.execute("SELECT 1 FROM context_replica_superseded").fetchone()
    assert count(replicas["a"], "a_STAGE38_PERSONAL") == 1


def test_permission_queue_reports_acknowledgement_without_claiming_new_delivery(
    replicas,
):
    exchange(replicas, "push")
    first = coordinator.queue_permission("b", "personal", "withdraw")
    assert (
        first["queued"]
        and not first["delivery_acknowledged"]
        and not first["network_attempted"]
    )
    exchange(replicas, "push")
    repeated = coordinator.queue_permission("b", "personal", "withdraw")
    assert not repeated["queued"] and repeated["delivery_acknowledged"]
    assert (
        repeated["generation"] == first["generation"]
        and not repeated["network_attempted"]
    )


def test_receiver_change_before_no_body_confirmation_is_refused(replicas, monkeypatch):
    exchange(replicas, "push")
    a, b = local(replicas["a"]), local(replicas["b"])
    from agent_session_tools.replication.policy import negotiate

    current = negotiate(a.call("hello", {}), b.call("hello", {}))
    with ledger._write(replicas["a"]["db"]) as check:
        saved = check.execute(
            "SELECT offer_json,receipt_json FROM context_replica_offers WHERE direction='out' AND status='acknowledged'"
        ).fetchone()
    assert current["sender"] == json.loads(saved[0])["plan"]["sender"]
    assert current["receiver"]["state"] == json.loads(saved[1])["committed_state"]
    assert a._unchanged(current, "personal")["unchanged"], (
        current["receiver"],
        json.loads(saved[0])["plan"]["receiver"],
    )
    original = b._confirm_unchanged

    def change(plan, scope):
        with ledger._write(replicas["b"]["db"]) as conn:
            conn.execute(
                "INSERT INTO messages(id,session_id,role,content) VALUES ('late-message','codex_rollout-a-personal','user','late receiver change')"
            )
        return original(plan, scope)

    monkeypatch.setattr(b, "_confirm_unchanged", change)
    with pytest.raises(ReplicaError, match="Receiver changed"):
        coordinator.synchronize(a, b, direction="push")


def test_control_change_before_finish_never_reports_completed_phase(
    replicas, monkeypatch
):
    a, b = local(replicas["a"]), local(replicas["b"])
    original = a._finish

    def change():
        permissions.prepare_change(
            replicas["a"]["db"], replicas["a"]["config"], "b", "personal", "withdraw"
        )
        return original()

    monkeypatch.setattr(a, "_finish", change)
    with pytest.raises(ReplicaError, match="Controls changed"):
        coordinator.synchronize(a, b, direction="push")
    # Earlier permitted content committed; retry must reconcile the newer control.
    assert count(replicas["b"], "a_STAGE38_PERSONAL") == 1
    exchange(replicas, "push")
    assert count(replicas["b"], "a_STAGE38_PERSONAL") == 0


def test_new_control_during_round_is_reconciled_before_content(replicas, monkeypatch):
    a, b = local(replicas["a"]), local(replicas["b"])
    original = b._apply_retirements
    rounds = []

    def change(packet):
        result = original(packet)
        rounds.append(packet["id"])
        if len(rounds) == 1:
            permissions.prepare_change(
                replicas["b"]["db"],
                replicas["b"]["config"],
                "a",
                "personal",
                "withdraw",
            )
        return result

    monkeypatch.setattr(b, "_apply_retirements", change)
    assert coordinator.synchronize(a, b, direction="push")["canonical_phase_completed"]
    assert len(rounds) >= 2
    assert a.call("heads", {})["in"]["personal"] == 1


def test_continuously_unstable_controls_stop_after_eight_rounds(replicas, monkeypatch):
    a, b = local(replicas["a"]), local(replicas["b"])
    calls = []

    def unstable(remote_heads):
        calls.append(remote_heads)
        return {"controls_reconciled": False}

    monkeypatch.setattr(b, "_ready", unstable)
    with pytest.raises(ReplicaError, match="Controls kept changing"):
        coordinator.synchronize(a, b, direction="push")
    assert len(calls) == 8
    assert count(replicas["b"], "a_STAGE38_PERSONAL") == 0
