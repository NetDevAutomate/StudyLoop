"""Real-schema two-replica content tests; lifecycle/SSH are not inferred from them."""

import json
from pathlib import Path

import pytest

from agent_session_tools.context import annotations, records
from agent_session_tools.context.observations import ObservationStore
from agent_session_tools.context.provenance import ExecutionState, Origin, Scope
from agent_session_tools.context.scope import ScopePolicy, apply_policy
from agent_session_tools.context.store import (
    Access,
    Citation,
    ContextStore,
    NativeSource,
    _hash,
    _json,
)
from agent_session_tools.replication import snapshot as projection
from agent_session_tools.replication.content import ReplicaConflict, apply_content
from agent_session_tools.replication.policy import (
    PeerPolicy,
    ReplicaError,
    hello,
    negotiate,
)


@pytest.fixture
def replicas(tmp_path, monkeypatch):
    result = {}
    for node, other in (("a", "b"), ("b", "a")):
        config = {
            "memory": {
                "default_scope": "personal",
                "projects": {
                    "p": {
                        "scope": "personal",
                        "roots": [str(tmp_path / node / "personal")],
                    },
                    "w": {"scope": "work", "roots": [str(tmp_path / node / "work")]},
                },
                "sync": {
                    "node_id": node,
                    "peers": {other: {"allowed_scopes": ["personal"]}},
                },
            }
        }
        path = tmp_path / f"{node}.db"
        conn = records.connect(path)
        apply_policy(
            conn, ScopePolicy.from_config(config), actor="fixture", dry_run=False
        )
        result[node] = {"conn": conn, "path": path, "config": config}
    config_path = tmp_path / "active.json"
    config_path.write_text(json.dumps(result["a"]["config"]))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "personal")
    yield result
    for row in result.values():
        row["conn"].close()


def plan(replicas):
    hellos = []
    for node, other in (("a", "b"), ("b", "a")):
        item = replicas[node]
        item["conn"].rollback()
        hellos.append(
            hello(item["conn"], PeerPolicy.from_config(item["config"], other))
        )
    return negotiate(*hellos)


def seed(replicas):
    item = replicas["a"]
    conn, config = item["conn"], item["config"]
    for sid, project, body in (
        ("personal", "p", "Observed fixture result"),
        ("work", "w", "EXCLUDED_WORK_BODY"),
    ):
        root = config["memory"]["projects"][project]["roots"][0]
        conn.execute(
            "INSERT INTO sessions(id,source,project_path) VALUES (?,?,?)",
            (sid, "codex", root),
        )
        conn.execute(
            "INSERT INTO messages(id,session_id,role,content) VALUES (?,?,?,?)",
            (sid + "-m", sid, "assistant", body),
        )
    conn.commit()
    apply_policy(conn, ScopePolicy.from_config(config), actor="fixture", dry_run=False)
    store = ContextStore(conn)
    sources = {}
    for sid, body in (
        ("personal", "Observed fixture result"),
        ("work", "EXCLUDED_WORK_EVIDENCE"),
    ):
        sources[sid] = store.capture(
            NativeSource(
                session_id=sid,
                native_key=sid + "-m",
                harness="codex",
                native_kind="message",
                native_locator="fictional.jsonl:1",
                parser_version="fixture",
                machine_id="a",
                body=body,
                origin=Origin.CONVERSATION,
            )
        )
    assertion = store.propose(
        statement="Fixture interpretation",
        state=ExecutionState.UNKNOWN,
        target=None,
        generator="fixture",
        citations=[
            Citation(evidence_id=sources["personal"], start=0, end=8, quote="Observed")
        ],
        access=Access(scope=Scope.PERSONAL),
    )
    with store._atomic(), records.policy_guard(conn):
        bridge = conn.execute(
            "INSERT INTO knowledge_bridges(source_concept,source_domain,target_concept,target_domain) VALUES ('route','fixture','query','fixture')"
        )
        owner = records.bind(
            conn, "knowledge_bridges", bridge.lastrowid, session_id="personal"
        )
        observation = ObservationStore(conn).append(
            kind="fixture.report",
            subject="fixture",
            payload={"text": "Owned result"},
            producer="fixture",
            authority="reported",
            owner_session_id="personal",
        )
        records.link_observation(conn, owner, observation)
        note1 = annotations.write(conn, "personal", "note", {"notes": "First report"})
        note2 = annotations.write(
            conn, "personal", "note", {"notes": "Explicit correction"}
        )
    return {
        "sources": sources,
        "assertion": assertion,
        "owner": owner,
        "observation": observation,
        "notes": [note1, note2],
    }


def snapshot(replicas):
    return projection.export_snapshot(
        replicas["a"]["path"], replicas["a"]["config"], plan(replicas), "personal"
    )


def reseal(value):
    value["sha256"] = _hash(_json({k: v for k, v in value.items() if k != "sha256"}))


def staged_accepted(replicas):
    from agent_session_tools.replication import ledger

    a, b = replicas["a"], replicas["b"]
    offered = ledger.prepare_staged_offer(
        a["path"], a["config"], plan(replicas), "personal"
    )
    acceptance = ledger.accept_offer(b["path"], b["config"], "a", offered)
    ledger.record_acceptance(a["path"], a["config"], "b", offered, acceptance)
    return offered


def test_staged_scope_above_old_limit_commits_with_exact_receipt(replicas):
    from agent_session_tools.replication import ledger

    seeded = seed(replicas)
    a, b = replicas["a"], replicas["b"]
    a["conn"].executemany(
        "INSERT INTO messages(id,session_id,role,content) VALUES (?,'personal','user',?)",
        ((f"large-{i:06d}", "fictional large message " * 800) for i in range(2300)),
    )
    a["conn"].commit()
    with pytest.raises(ReplicaError, match="transfer limits"):
        snapshot(replicas)
    offered = staged_accepted(replicas)
    with ledger.release_staged_content(a["path"], a["config"], "b", offered) as staged:
        assert staged.encoded_bytes > 32 * 1024 * 1024
        assert not b["conn"].execute("SELECT 1 FROM messages").fetchone()
        receipt = ledger.receive_content(
            b["path"], b["config"], "a", offered["id"], staged
        )
        assert (
            ledger.receive_content(b["path"], b["config"], "a", offered["id"], staged)
            == receipt
        )
    ledger.acknowledge_content(a["path"], a["config"], "b", receipt)
    assert b["conn"].execute("SELECT count(*) FROM messages").fetchone()[0] == 2301
    assert (
        b["conn"]
        .execute(
            "SELECT 1 FROM context_evidence WHERE id=?",
            (seeded["sources"]["personal"],),
        )
        .fetchone()
    )
    assert not b["conn"].execute("SELECT 1 FROM sessions WHERE id='work'").fetchone()
    assert not b["conn"].execute("PRAGMA foreign_key_check").fetchall()


def test_staged_receiver_mutation_rolls_back_without_receipt(replicas):
    from agent_session_tools.replication import ledger

    seed(replicas)
    a, b = replicas["a"], replicas["b"]
    offered = staged_accepted(replicas)
    with ledger.release_staged_content(a["path"], a["config"], "b", offered) as staged:
        b["conn"].execute(
            "INSERT INTO sessions(id,source) VALUES ('new-local','codex')"
        )
        b["conn"].commit()
        with pytest.raises(ReplicaError, match="Receiver state changed"):
            ledger.receive_content(b["path"], b["config"], "a", offered["id"], staged)
    assert not b["conn"].execute("SELECT 1 FROM messages").fetchone()
    assert (
        b["conn"]
        .execute(
            "SELECT receipt_json FROM context_replica_offers WHERE id=?",
            (offered["id"],),
        )
        .fetchone()[0]
        is None
    )


def test_staged_withdrawal_before_promotion_keeps_body_unavailable(replicas):
    from agent_session_tools.replication import ledger, permissions

    seed(replicas)
    a, b = replicas["a"], replicas["b"]
    offered = staged_accepted(replicas)
    with ledger.release_staged_content(a["path"], a["config"], "b", offered) as staged:
        packet = permissions.prepare_change(
            a["path"], a["config"], "b", "personal", "withdraw"
        )
        permissions.apply_change(b["path"], b["config"], "a", packet)
        with pytest.raises(ReplicaError):
            ledger.receive_content(b["path"], b["config"], "a", offered["id"], staged)
    assert not b["conn"].execute("SELECT 1 FROM messages").fetchone()


def test_staged_cross_session_review_preserves_every_source(replicas):
    from agent_session_tools.context.public import AgentContext
    from agent_session_tools.context.reviews import ReviewStore
    from agent_session_tools.replication import ledger

    seeded = seed(replicas)
    a, b = replicas["a"], replicas["b"]
    conn = a["conn"]
    conn.execute("INSERT INTO sessions(id,source) VALUES ('second','codex')")
    conn.execute(
        "INSERT INTO context_session_projects VALUES ('second','p','explicit')"
    )
    conn.commit()
    store = ContextStore(conn)
    extra = store.capture(
        NativeSource(
            session_id="second",
            native_key="second-message",
            harness="codex",
            native_kind="message",
            native_locator="fictional-second.jsonl:1",
            parser_version="fixture",
            machine_id="a",
            body="Contrary report",
            origin=Origin.CONVERSATION,
        )
    )
    assertion = store.propose(
        statement="Two reports disagree",
        state=ExecutionState.UNKNOWN,
        target=None,
        generator="fixture",
        access=Access(scope=Scope.PERSONAL),
        citations=[
            Citation(
                evidence_id=seeded["sources"]["personal"],
                start=0,
                end=8,
                quote="Observed",
            ),
            Citation(evidence_id=extra, start=0, end=8, quote="Contrary"),
        ],
    )
    review = ReviewStore(AgentContext(conn)).append(
        target_kind="assertion",
        target_id=assertion,
        verdict="uncertain",
        rationale="Both reports need applicable validation.",
        citations=[{"evidence_id": extra, "start": 0, "end": 8, "quote": "Contrary"}],
        producer="fixture reviewer",
    )
    conn.commit()
    offered = staged_accepted(replicas)
    with ledger.release_staged_content(a["path"], a["config"], "b", offered) as staged:
        ledger.receive_content(b["path"], b["config"], "a", offered["id"], staged)
    assert (
        b["conn"]
        .execute(
            "SELECT count(*) FROM context_citations WHERE assertion_id=?", (assertion,)
        )
        .fetchone()[0]
        == 2
    )
    assert (
        b["conn"]
        .execute(
            "SELECT count(*) FROM context_observation_sources WHERE observation_id=?",
            (review,),
        )
        .fetchone()[0]
        == 2
    )
    assert not b["conn"].execute("PRAGMA foreign_key_check").fetchall()


def test_process_death_during_staged_promotion_rolls_back_body_and_receipt(replicas):
    import os
    import subprocess
    import sys
    from agent_session_tools.replication import ledger

    seed(replicas)
    a, b = replicas["a"], replicas["b"]
    offered = staged_accepted(replicas)
    script = """
import json,os,sys
from agent_session_tools.replication import ledger,content
a,b,offer=json.loads(sys.argv[1])
original=content._row
def crash(conn,table,row,**kwargs):
    result=original(conn,table,row,**kwargs)
    if table=='messages': os._exit(39)
    return result
content._row=crash
with ledger.release_staged_content(a['path'],a['config'],'b',offer) as snapshot:
    ledger.receive_content(b['path'],b['config'],'a',offer['id'],snapshot)
"""
    args = [{"path": str(node["path"]), "config": node["config"]} for node in (a, b)]
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, json.dumps([*args, offered])],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 39, result.stderr
    assert not b["conn"].execute("SELECT 1 FROM messages").fetchone()
    assert (
        b["conn"]
        .execute(
            "SELECT receipt_json FROM context_replica_offers WHERE id=?",
            (offered["id"],),
        )
        .fetchone()[0]
        is None
    )
    with ledger.release_staged_content(
        a["path"], a["config"], "b", offered
    ) as snapshot:
        receipt = ledger.receive_content(
            b["path"], b["config"], "a", offered["id"], snapshot
        )
    assert receipt["committed"]


def test_reciprocal_negotiation_uses_project_ids_not_machine_roots(replicas):
    result = plan(replicas)
    assert result["scopes"] == ["personal"] and result["projects"] == {"p": "personal"}
    assert "roots" not in _json(result) and "work" not in _json(result)


@pytest.mark.parametrize(
    "change", ["scope", "project", "protocol", "identity", "schema", "clone"]
)
def test_negotiation_refuses_incompatible_peers_before_body_projection(
    replicas, change
):
    proposed = plan(replicas)
    receiver = proposed["receiver"]
    if change == "scope":
        receiver["allowed_scopes"] = ["work"]
        receiver["projects"] = {"w": "work"}
    elif change == "project":
        receiver["projects"] = {"different": "personal"}
    elif change == "protocol":
        receiver["protocol"] = "sql/v0"
    elif change == "identity":
        receiver["node"] = "other"
    elif change == "schema":
        receiver["schema"] = True
    else:
        receiver["state"]["instance"] = proposed["sender"]["state"]["instance"]
    with pytest.raises(ReplicaError):
        negotiate(proposed["sender"], receiver)


def test_actual_projection_excludes_work_before_row_materialization(
    replicas, monkeypatch
):
    seed(replicas)
    original = projection.Projection.read
    checked = []

    def observe(self, *args, **kwargs):
        rows = original(self, *args, **kwargs)
        assert "EXCLUDED_WORK" not in _json(rows)
        checked.append(args[0])
        return rows

    monkeypatch.setattr(projection.Projection, "read", observe)
    result = snapshot(replicas)
    assert "EXCLUDED_WORK" not in _json(result)
    assert checked and result["lifecycle_reconciled"] is False
    assert len(result["tables"]["context_observations"]) == 3


def test_content_roundtrip_preserves_bindings_and_remaps_integer_collision(replicas):
    ids = seed(replicas)
    dest = replicas["b"]
    dest["conn"].execute(
        "INSERT INTO knowledge_bridges(source_concept,source_domain,target_concept,target_domain) VALUES ('keep','local','me','local')"
    )
    dest["conn"].commit()
    result = apply_content(dest["path"], dest["config"], snapshot(replicas))
    assert result["content_phase_committed"] and result["sync_complete"] is False
    conn = dest["conn"]
    owner = conn.execute(
        "SELECT row_id FROM context_record_owners WHERE id=?", (ids["owner"],)
    ).fetchone()[0]
    assert (
        owner == "2"
        and conn.execute(
            "SELECT source_concept FROM knowledge_bridges WHERE id=1"
        ).fetchone()[0]
        == "keep"
    )
    assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1
    assert conn.execute(
        "SELECT body_sha256 FROM context_evidence WHERE id=?",
        (ids["sources"]["personal"],),
    ).fetchone()
    assert (
        conn.execute(
            "SELECT previous_id FROM context_observation_supersedes WHERE observation_id=?",
            (ids["notes"][1],),
        ).fetchone()[0]
        == ids["notes"][0]
    )
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert (
        conn.execute(
            "SELECT count(*) FROM context_evidence_fts WHERE context_evidence_fts MATCH 'Observed'"
        ).fetchone()[0]
        == 1
    )
    second = apply_content(dest["path"], dest["config"], snapshot(replicas))
    assert second["content_phase_committed"]
    assert conn.execute("SELECT count(*) FROM knowledge_bridges").fetchone()[0] == 2


def test_divergent_mutable_record_rolls_back_whole_content_phase(replicas):
    seed(replicas)
    dest = replicas["b"]
    apply_content(dest["path"], dest["config"], snapshot(replicas))
    dest["conn"].execute("UPDATE knowledge_bridges SET quality='concurrent edit'")
    dest["conn"].commit()
    source = replicas["a"]["conn"]
    source.execute(
        "INSERT INTO messages(id,session_id,role,content) VALUES ('later','personal','user','later body')"
    )
    source.commit()
    with pytest.raises(ReplicaConflict, match="Divergent knowledge_bridges"):
        apply_content(dest["path"], dest["config"], snapshot(replicas))
    assert (
        dest["conn"].execute("SELECT quality FROM knowledge_bridges").fetchone()[0]
        == "concurrent edit"
    )
    assert (
        not dest["conn"].execute("SELECT 1 FROM messages WHERE id='later'").fetchone()
    )


@pytest.mark.parametrize(
    "change", ["scope", "binding", "citation", "dependency", "columns"]
)
def test_corrupt_or_incomplete_snapshot_is_not_committed(replicas, change):
    seed(replicas)
    incoming = snapshot(replicas)
    tables = incoming["tables"]
    if change == "scope":
        tables["context_session_projects"][0]["project_id"] = "w"
    elif change == "binding":
        tables["context_evidence"][0]["body"] += " altered"
    elif change == "citation":
        tables["context_citations"][0]["quote"] = "mismatch"
    elif change == "dependency":
        tables["knowledge_bridges"] = []
    else:
        tables["sessions"][0]["invented"] = "unsupported"
    reseal(incoming)
    dest = replicas["b"]
    with pytest.raises((ValueError, ReplicaError)):
        apply_content(dest["path"], dest["config"], incoming)
    assert dest["conn"].execute("SELECT count(*) FROM sessions").fetchone()[0] == 0


def test_access_change_during_projection_refuses_result(replicas, monkeypatch):
    seed(replicas)
    original = projection.collect

    def revoke(conn, *args):
        result = original(conn, *args)
        other = replicas["a"]["conn"]
        other.execute(
            "UPDATE context_session_projects SET project_id='w' WHERE session_id='personal'"
        )
        other.commit()
        return result

    monkeypatch.setattr(projection, "collect", revoke)
    with pytest.raises(ReplicaError, match="access changed"):
        snapshot(replicas)


def test_negotiated_scope_is_independent_of_interactive_request_scope(
    replicas, monkeypatch
):
    seed(replicas)
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "work")
    result = snapshot(replicas)
    assert "EXCLUDED_WORK" not in _json(result)
    assert len(result["tables"]["knowledge_bridges"]) == 1


def test_transfer_limit_returns_no_truncated_snapshot(replicas, monkeypatch):
    seed(replicas)
    monkeypatch.setattr(projection, "MAX_ROWS", 2)
    with pytest.raises(ReplicaError, match="no truncated"):
        snapshot(replicas)


def test_existing_local_session_is_not_reclassified_by_a_peer(replicas):
    seed(replicas)
    dest = replicas["b"]
    dest["conn"].execute("INSERT INTO sessions(id,source) VALUES ('personal','codex')")
    dest["conn"].commit()
    with pytest.raises(ReplicaConflict, match="cannot reclassify"):
        apply_content(dest["path"], dest["config"], snapshot(replicas))
    assert dest["conn"].execute("SELECT count(*) FROM messages").fetchone()[0] == 0
    assert (
        dest["conn"]
        .execute("SELECT count(*) FROM context_session_projects")
        .fetchone()[0]
        == 0
    )


@pytest.mark.parametrize("side", ["sender", "receiver"])
def test_changed_peer_grant_during_content_phase_rolls_back(
    replicas, monkeypatch, side
):
    from agent_session_tools.replication import content

    seed(replicas)
    if side == "sender":
        original = projection.collect

        def change_sender(*args):
            result = original(*args)
            replicas["a"]["config"]["memory"]["sync"]["peers"]["b"][
                "allowed_scopes"
            ] = ["work"]
            return result

        monkeypatch.setattr(projection, "collect", change_sender)
        with pytest.raises(ReplicaError, match="configuration changed"):
            snapshot(replicas)
    else:
        incoming = snapshot(replicas)
        original = content._row

        def change_receiver(*args, **kwargs):
            result = original(*args, **kwargs)
            replicas["b"]["config"]["memory"]["sync"]["peers"]["a"][
                "allowed_scopes"
            ] = ["work"]
            return result

        monkeypatch.setattr(content, "_row", change_receiver)
        with pytest.raises(ReplicaError):
            apply_content(replicas["b"]["path"], replicas["b"]["config"], incoming)
    assert (
        replicas["b"]["conn"].execute("SELECT count(*) FROM messages").fetchone()[0]
        == 0
    )


@pytest.mark.parametrize("corrupt", [False, True])
def test_review_target_is_bound_after_transport(replicas, corrupt):
    from agent_session_tools.context.public import AgentContext
    from agent_session_tools.context.reviews import ReviewStore

    ids = seed(replicas)
    conn = replicas["a"]["conn"]
    ctx = AgentContext(conn)
    review = ReviewStore(ctx).append(
        target_kind="assertion",
        target_id=ids["assertion"],
        verdict="uncertain",
        rationale="Fixture source is a report, not a command validation.",
        citations=[
            {
                "evidence_id": ids["sources"]["personal"],
                "start": 0,
                "end": 8,
                "quote": "Observed",
            }
        ],
        producer="fixture-reviewer",
    )
    conn.commit()
    incoming = snapshot(replicas)
    if corrupt:
        incoming["tables"]["context_review_targets"][0]["target_sha256"] = "0" * 64
        reseal(incoming)
    dest = replicas["b"]
    if corrupt:
        with pytest.raises(ReplicaError, match="Review target binding"):
            apply_content(dest["path"], dest["config"], incoming)
        assert dest["conn"].execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
    else:
        apply_content(dest["path"], dest["config"], incoming)
        row = (
            dest["conn"]
            .execute(
                "SELECT target_sha256 FROM context_review_targets WHERE observation_id=?",
                (review,),
            )
            .fetchone()
        )
        assert (
            row[0] == incoming["tables"]["context_review_targets"][0]["target_sha256"]
        )


def test_review_payload_cannot_claim_an_undeclared_captured_input(replicas):
    from agent_session_tools.context.public import AgentContext
    from agent_session_tools.context.reviews import ReviewStore

    ids = seed(replicas)
    conn = replicas["a"]["conn"]
    extra = ContextStore(conn).capture(
        NativeSource(
            session_id="personal",
            native_key="extra",
            harness="codex",
            native_kind="message",
            native_locator="fixture.jsonl:2",
            parser_version="fixture",
            machine_id="a",
            body="Additional fixture source",
            origin=Origin.CONVERSATION,
        )
    )
    ctx = AgentContext(conn)
    review = ReviewStore(ctx).append(
        target_kind="assertion",
        target_id=ids["assertion"],
        verdict="uncertain",
        rationale="Both sources were inspected.",
        citations=[
            {"evidence_id": extra, "start": 0, "end": 10, "quote": "Additional"}
        ],
        producer="fixture-reviewer",
    )
    conn.commit()
    incoming = snapshot(replicas)
    # A self-consistent but invalid report claims an input in its payload while
    # omitting that input from the authoritative dependency list.
    tables = incoming["tables"]
    tables["context_observation_sources"] = [
        r
        for r in tables["context_observation_sources"]
        if not (r["observation_id"] == review and r["evidence_id"] == extra)
    ]
    row = next(r for r in tables["context_observations"] if r["id"] == review)
    binding = {
        k: row[k]
        for k in ("kind", "subject", "payload", "producer", "authority", "recorded_at")
    }
    binding["sources"] = [ids["sources"]["personal"]]
    binding["supersedes"] = []
    row["binding_sha256"] = _hash(_json(binding))
    reseal(incoming)
    dest = replicas["b"]
    with pytest.raises(ReplicaError, match="not a declared captured input"):
        apply_content(dest["path"], dest["config"], incoming)
    assert dest["conn"].execute("SELECT count(*) FROM sessions").fetchone()[0] == 0


def test_source_refuses_undeclared_review_input_before_reading_any_body(
    replicas, monkeypatch
):
    from agent_session_tools.context.public import AgentContext
    from agent_session_tools.context.reviews import ReviewStore

    ids = seed(replicas)
    conn = replicas["a"]["conn"]
    ctx = AgentContext(conn)
    review = ReviewStore(ctx).append(
        target_kind="assertion",
        target_id=ids["assertion"],
        verdict="uncertain",
        rationale="Fixture report.",
        citations=[
            {
                "evidence_id": ids["sources"]["personal"],
                "start": 0,
                "end": 8,
                "quote": "Observed",
            }
        ],
        producer="fixture-reviewer",
    )
    conn.commit()
    row = dict(
        conn.execute(
            "SELECT * FROM context_observations WHERE id=?", (review,)
        ).fetchone()
    )
    payload = json.loads(row["payload"])
    payload["citations"] = [
        {
            "evidence_id": ids["sources"]["work"],
            "start": 0,
            "end": 13,
            "quote": "EXCLUDED_WORK",
        }
    ]
    row["payload"] = _json(payload)
    binding = {
        k: row[k]
        for k in ("kind", "subject", "payload", "producer", "authority", "recorded_at")
    }
    binding.update(sources=[ids["sources"]["personal"]], supersedes=[])
    conn.execute("DROP TRIGGER context_observations_immutable")
    conn.execute(
        "UPDATE context_observations SET payload=?,binding_sha256=? WHERE id=?",
        (row["payload"], _hash(_json(binding)), review),
    )
    conn.commit()

    def forbidden(*args, **kwargs):
        pytest.fail("Body materialized before invalid input dependency was rejected")

    monkeypatch.setattr(projection.Projection, "read", forbidden)
    with pytest.raises(ReplicaError, match="undeclared captured inputs"):
        snapshot(replicas)


def test_learner_body_native_reference_is_filtered_before_materialization(
    replicas, monkeypatch
):
    seed(replicas)
    item = replicas["a"]
    conn = item["conn"]
    # Explicit project ownership does not erase a row's separate native FK.
    with ContextStore(conn)._atomic(), records.policy_guard(conn):
        row = conn.execute(
            "INSERT INTO teach_back_scores(concept,topic,review_type,session_id,notes) "
            "VALUES ('fixture','fixture','fixture','work','EXCLUDED_WORK_LEARNER')"
        )
        records.bind(
            conn,
            "teach_back_scores",
            row.lastrowid,
            owner_path=Path(item["config"]["memory"]["projects"]["p"]["roots"][0]),
        )
    original = projection.Projection.read

    def checked(self, *args, **kwargs):
        rows = original(self, *args, **kwargs)
        assert "EXCLUDED_WORK_LEARNER" not in _json(rows)
        return rows

    monkeypatch.setattr(projection.Projection, "read", checked)
    result = snapshot(replicas)
    assert result["tables"]["teach_back_scores"] == []


def test_encoded_budget_includes_the_final_binding_field(replicas, monkeypatch):
    seed(replicas)
    actual_bytes = len(_json(snapshot(replicas)).encode())
    monkeypatch.setattr(projection, "MAX_BYTES", actual_bytes - 1)
    with pytest.raises(ReplicaError, match="Encoded snapshot exceeds"):
        snapshot(replicas)


def seed_learner_tables(replicas):
    """Populate each owned table, including generated scores and study children."""
    conn = replicas["a"]["conn"]
    statements = {
        "study_sessions": (
            "INSERT INTO study_sessions(id,session_id,started_at) VALUES ('study','personal','2026-09-06T00:00:00Z')",
            "study",
        ),
        "teach_back_scores": (
            "INSERT INTO teach_back_scores(concept,topic,review_type,session_id,score_accuracy,score_depth) VALUES ('fixture','fixture','fixture','personal',3,4)",
            None,
        ),
        "knowledge_bridges": (
            "INSERT INTO knowledge_bridges(source_concept,source_domain,target_concept,target_domain) VALUES ('new','network','new','data')",
            None,
        ),
        "parked_topics": (
            "INSERT INTO parked_topics(study_session_id,session_id,question) VALUES ('study','personal','Fixture question?')",
            None,
        ),
        "study_notes": (
            "INSERT INTO study_notes(study_session_id,session_id,title,body) VALUES ('study','personal','Fixture title','Fixture body')",
            None,
        ),
        "practice_attempts": (
            "INSERT INTO practice_attempts(id,practice_path,task_index,task_prompt,verification_kind,passed) VALUES ('practice','fictional.py',0,'Fixture task','manual',1)",
            "practice",
        ),
    }
    owners = {}
    with ContextStore(conn)._atomic(), records.policy_guard(conn):
        for table, (statement, identity) in statements.items():
            inserted = conn.execute(statement)
            identity = identity or inserted.lastrowid
            owners[table] = records.bind(
                conn,
                table,
                identity,
                session_id="personal",
                study_session_id="study"
                if table in ("parked_topics", "study_notes")
                else None,
            )
    return owners


def test_all_learner_tables_roundtrip_with_generated_score_and_study_links(replicas):
    seed(replicas)
    owners = seed_learner_tables(replicas)
    incoming = snapshot(replicas)
    assert "total_score" not in incoming["tables"]["teach_back_scores"][0]
    dest = replicas["b"]
    apply_content(dest["path"], dest["config"], incoming)
    for table, owner_id in owners.items():
        owner = (
            dest["conn"]
            .execute(
                "SELECT row_id FROM context_record_owners WHERE id=? AND table_name=?",
                (owner_id, table),
            )
            .fetchone()
        )
        assert owner is not None
        original_owner = (
            replicas["a"]["conn"]
            .execute("SELECT row_id FROM context_record_owners WHERE id=?", (owner_id,))
            .fetchone()
        )
        original = dict(
            replicas["a"]["conn"]
            .execute(f"SELECT * FROM {table} WHERE id=?", (original_owner[0],))
            .fetchone()
        )
        received = dict(
            dest["conn"]
            .execute(f"SELECT * FROM {table} WHERE id=?", (owner[0],))
            .fetchone()
        )
        original.pop("id")
        received.pop("id")
        assert original == received
    assert (
        dest["conn"].execute("SELECT total_score FROM teach_back_scores").fetchone()[0]
        == 7
    )
    assert (
        dest["conn"]
        .execute("SELECT count(*) FROM context_record_study_links")
        .fetchone()[0]
        == 2
    )
    apply_content(dest["path"], dest["config"], snapshot(replicas))
    assert (
        dest["conn"].execute("SELECT count(*) FROM practice_attempts").fetchone()[0]
        == 1
    )
    assert dest["conn"].execute("PRAGMA foreign_key_check").fetchall() == []


def test_peer_cannot_assign_ownership_to_an_identical_unowned_learner_row(replicas):
    seed(replicas)
    seed_learner_tables(replicas)
    incoming = snapshot(replicas)
    row = incoming["tables"]["practice_attempts"][0]
    dest = replicas["b"]
    dest["conn"].execute(
        "INSERT INTO practice_attempts ("
        + ",".join(row)
        + ") VALUES ("
        + ",".join("?" for _ in row)
        + ")",
        list(row.values()),
    )
    dest["conn"].commit()
    with pytest.raises(ReplicaConflict, match="lacks the incoming owner"):
        apply_content(dest["path"], dest["config"], snapshot(replicas))
    assert dest["conn"].execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
    assert (
        dest["conn"].execute("SELECT count(*) FROM context_record_owners").fetchone()[0]
        == 0
    )


@pytest.mark.parametrize("corrupt", [False, True])
def test_native_rendering_link_survives_transfer_with_its_binding(replicas, corrupt):
    ids = seed(replicas)
    source = replicas["a"]["conn"]
    source.execute(
        "INSERT INTO context_native_message_sources VALUES (?,?,?)",
        ("personal-m", ids["sources"]["personal"], _hash("Observed fixture result")),
    )
    source.commit()
    incoming = snapshot(replicas)
    assert len(incoming["tables"]["context_native_message_sources"]) == 1
    dest = replicas["b"]
    if corrupt:
        incoming["tables"]["context_native_message_sources"][0][
            "rendered_body_sha256"
        ] = "0" * 64
        reseal(incoming)
        with pytest.raises(ReplicaError, match="Native rendering link"):
            apply_content(dest["path"], dest["config"], incoming)
        assert dest["conn"].execute("SELECT count(*) FROM messages").fetchone()[0] == 0
    else:
        apply_content(dest["path"], dest["config"], incoming)
        assert dest["conn"].execute(
            "SELECT rendered_body_sha256 FROM context_native_message_sources"
        ).fetchone()[0] == _hash("Observed fixture result")
