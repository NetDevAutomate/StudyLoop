"""design.md's normative two-copy matrix for concept-event replication.

Every scenario runs the real content protocol (``export_snapshot`` ->
``apply_content``) on two real-schema databases, in both replication orders,
and computes every expected standing independently from the frozen triple
``(lamport, machine_id, event_id)`` -- never from which side "should" win by
narrative. Timestamps never participate.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing

import pytest

from agent_session_tools.context import records
from agent_session_tools.context.concepts import ConceptService
from agent_session_tools.context.provenance import Origin
from agent_session_tools.context.scope import ScopePolicy, apply_policy
from agent_session_tools.context.store import ContextStore, NativeSource
from agent_session_tools.replication.content import apply_content
from agent_session_tools.replication.policy import (
    PeerPolicy,
    ReplicaError,
    hello,
    negotiate,
)
from agent_session_tools.replication.snapshot import export_snapshot

_NOW = "2026-09-08T12:00:00+00:00"


@pytest.fixture
def replicas(tmp_path, monkeypatch):
    """Two real-schema replicas with reciprocal peer configs and seeded evidence."""
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
                },
                "sync": {
                    "node_id": node,
                    "peers": {other: {"allowed_scopes": ["personal"]}},
                },
            }
        }
        path = tmp_path / f"{node}.db"
        config_path = tmp_path / f"config-{node}.json"
        config_path.write_text(json.dumps(config))
        conn = records.connect(path)
        apply_policy(
            conn, ScopePolicy.from_config(config), actor="fixture", dry_run=False
        )
        result[node] = {
            "conn": conn,
            "path": path,
            "config": config,
            "config_path": config_path,
        }
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "personal")
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(result["a"]["config_path"]))
    for node in ("a", "b"):
        _seed_node(result[node], node)
    yield result
    for row in result.values():
        row["conn"].close()


def _seed_node(item, node):
    """One personal-scope session with quotable captured evidence."""
    conn, config = item["conn"], item["config"]
    root = config["memory"]["projects"]["p"]["roots"][0]
    session_id = f"{node}-session"
    conn.execute(
        "INSERT INTO sessions(id,source,project_path) VALUES (?,?,?)",
        (session_id, "codex", root),
    )
    conn.execute(
        "INSERT INTO messages(id,session_id,role,content) VALUES (?,?,?,?)",
        (
            f"{session_id}-m",
            session_id,
            "assistant",
            f"Replica {node} observed fact-{node}.",
        ),
    )
    conn.commit()
    apply_policy(conn, ScopePolicy.from_config(config), actor="fixture", dry_run=False)
    store = ContextStore(conn)
    store.capture(
        NativeSource(
            session_id=session_id,
            native_key=f"{session_id}-m",
            harness="codex",
            native_kind="message",
            native_locator="fixture.jsonl:1",
            parser_version="fixture",
            machine_id=node,
            body=f"Replica {node} observed fact-{node}.",
            origin=Origin.CONVERSATION,
        )
    )
    conn.commit()


def _use_config(monkeypatch, item):
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(item["config_path"]))


def _service(item):
    return ConceptService(item["path"], now=lambda: _NOW, prepare_schema=False)


def _winddown(monkeypatch, item, node, title, quote):
    _use_config(monkeypatch, item)
    result = _service(item).winddown(
        f"{node}-session",
        {
            "concepts": [
                {
                    "type": "Finding",
                    "title": title,
                    "description": f"{title} description.",
                    "tags": ["fixture", "replication"],
                    "confidence": 0.9,
                    "quotes": [{"quote": quote}],
                }
            ]
        },
        actor="fixture-author",
    )
    assert result.errors == (), result.errors
    assert result.writes == 1
    return result.concept_ids[0]


def _transition(monkeypatch, item, concept_id, standing, reason):
    _use_config(monkeypatch, item)
    result = _service(item).transition(
        concept_id, standing, actor="fixture-operator", reason=reason
    )
    assert result.errors == (), result.errors
    return result.event_id


def _plan(replicas, sender, receiver):
    hellos = []
    for node, other in ((sender, receiver), (receiver, sender)):
        item = replicas[node]
        item["conn"].rollback()
        hellos.append(
            hello(item["conn"], PeerPolicy.from_config(item["config"], other))
        )
    return negotiate(*hellos)


def _sync(replicas, sender, receiver):
    """One content-phase exchange sender -> receiver on the personal scope."""
    plan = _plan(replicas, sender, receiver)
    snapshot = export_snapshot(
        replicas[sender]["path"], replicas[sender]["config"], plan, "personal"
    )
    return apply_content(
        replicas[receiver]["path"], replicas[receiver]["config"], snapshot
    )


def _copy_pair(replicas, tmp_path, tag):
    """Two Online Backup copies forming one parallel-universe replica pair."""
    result = {}
    for node in ("a", "b"):
        item = replicas[node]
        item["conn"].commit()
        path = tmp_path / f"{node}-{tag}.db"
        with closing(sqlite3.connect(path)) as destination:
            item["conn"].backup(destination)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        result[node] = {
            "conn": conn,
            "path": path,
            "config": item["config"],
            "config_path": item["config_path"],
        }
    return result


def _close_pair(pair):
    for row in pair.values():
        row["conn"].close()


def _events(item):
    item["conn"].rollback()
    rows = (
        item["conn"]
        .execute("SELECT * FROM context_concept_events ORDER BY id")
        .fetchall()
    )
    return [dict(row) for row in rows]


def _digest(events):
    canonical = json.dumps(
        sorted(events, key=lambda row: row["id"]),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _standing_key(event):
    """The frozen order: (lamport, machine_id, event_id); nothing else."""
    return (event["logical_time"], event["origin_instance"], event["id"])


def _computed_standings(events):
    """Recompute standing per concept from full history, in Python, by the triple."""
    by_concept: dict[str, list[dict]] = {}
    for event in events:
        by_concept.setdefault(event["concept_id"], []).append(event)
    return {
        concept_id: max(history, key=_standing_key)["standing"]
        for concept_id, history in by_concept.items()
    }


def _sql_standings(item):
    """The production read model's answer for every concept."""
    item["conn"].rollback()
    return {
        row[0]: row[1]
        for row in item["conn"].execute(
            """WITH ranked AS (
                 SELECT concept_id,standing,
                   row_number() OVER (
                     PARTITION BY concept_id
                     ORDER BY logical_time DESC,origin_instance DESC,origin_seq DESC,id DESC
                   ) AS position
                 FROM context_concept_events
               )
               SELECT concept_id,standing FROM ranked WHERE position=1"""
        )
    }


def _assert_converged(pair):
    """Event sets, ordered digests, and computed standings agree on both copies."""
    events_a, events_b = _events(pair["a"]), _events(pair["b"])
    assert {e["id"] for e in events_a} == {e["id"] for e in events_b}
    assert _digest(events_a) == _digest(events_b)
    assert _computed_standings(events_a) == _computed_standings(events_b)
    # The production read model agrees with the from-history recomputation.
    assert _sql_standings(pair["a"]) == _computed_standings(events_a)
    assert _sql_standings(pair["b"]) == _computed_standings(events_b)
    return events_a


class TestTwoCopyMatrix:
    def test_1_opposite_replication_orders_converge_identically(
        self, replicas, tmp_path, monkeypatch
    ):
        """Matrix 1+2: A->B then B->A equals B->A then A->B, byte for byte."""
        _winddown(monkeypatch, replicas["a"], "a", "Alpha finding", "fact-a")
        _winddown(monkeypatch, replicas["b"], "b", "Beta finding", "fact-b")

        first = _copy_pair(replicas, tmp_path, "order-ab")
        second = _copy_pair(replicas, tmp_path, "order-ba")
        try:
            _sync(first, "a", "b")
            _sync(first, "b", "a")
            _sync(second, "b", "a")
            _sync(second, "a", "b")

            events_first = _assert_converged(first)
            events_second = _assert_converged(second)
            assert _digest(events_first) == _digest(events_second)
            assert _computed_standings(events_first) == _computed_standings(
                events_second
            )
        finally:
            _close_pair(first)
            _close_pair(second)

    def test_3_replay_is_idempotent(self, replicas, tmp_path, monkeypatch):
        """Matrix 3: re-running either direction with nothing new adds zero rows."""
        _winddown(monkeypatch, replicas["a"], "a", "Alpha finding", "fact-a")
        _winddown(monkeypatch, replicas["b"], "b", "Beta finding", "fact-b")
        pair = _copy_pair(replicas, tmp_path, "replay")
        try:
            _sync(pair, "a", "b")
            _sync(pair, "b", "a")
            before_a, before_b = _events(pair["a"]), _events(pair["b"])

            _sync(pair, "a", "b")
            _sync(pair, "b", "a")

            assert _events(pair["a"]) == before_a
            assert _events(pair["b"]) == before_b
        finally:
            _close_pair(pair)

    def test_4_causally_later_local_event_outranks_prior_concurrent_ones(
        self, replicas, tmp_path, monkeypatch
    ):
        """Matrix 4: post-convergence, a new local event gets a strictly greater
        lamport than both concurrent events and becomes standing on both copies.

        Run against the unmodified reference allocator first (design.md B3
        verification note): ``_allocate`` already takes a table-wide
        ``MAX(logical_time)`` over imported and local events alike.
        """
        concept = _winddown(monkeypatch, replicas["a"], "a", "Alpha finding", "fact-a")
        _sync(replicas, "a", "b")
        # Concurrent divergence on the same concept.
        _transition(
            monkeypatch, replicas["a"], concept, "accepted", "concurrent accept"
        )
        _winddown(monkeypatch, replicas["b"], "b", "Beta finding", "fact-b")
        pair = _copy_pair(replicas, tmp_path, "advance")
        try:
            _sync(pair, "a", "b")
            _sync(pair, "b", "a")
            converged = _events(pair["b"])
            highest = max(event["logical_time"] for event in converged)

            # New local event on B (the copy that only imported the accept).
            _use_config(monkeypatch, pair["b"])
            result = _service(pair["b"]).transition(
                concept, "retired", actor="fixture-operator", reason="post-convergence"
            )
            assert result.errors == (), result.errors
            new_event = next(
                event for event in _events(pair["b"]) if event["id"] == result.event_id
            )
            assert new_event["logical_time"] > highest

            _sync(pair, "b", "a")
            events = _assert_converged(pair)
            standings = _computed_standings(events)
            assert standings[concept] == "retired"
            winner = max(
                (event for event in events if event["concept_id"] == concept),
                key=_standing_key,
            )
            assert winner["id"] == result.event_id
        finally:
            _close_pair(pair)

    def test_5_read_model_rebuild_is_hash_equivalent(
        self, replicas, tmp_path, monkeypatch
    ):
        """Matrix 5: standing recomputed from full history digests identically."""
        concept = _winddown(monkeypatch, replicas["a"], "a", "Alpha finding", "fact-a")
        _transition(monkeypatch, replicas["a"], concept, "accepted", "history depth")
        _winddown(monkeypatch, replicas["b"], "b", "Beta finding", "fact-b")
        pair = _copy_pair(replicas, tmp_path, "hash")
        try:
            _sync(pair, "a", "b")
            _sync(pair, "b", "a")

            digests = []
            for node in ("a", "b"):
                standings = _computed_standings(_events(pair[node]))
                digests.append(
                    hashlib.sha256(
                        json.dumps(
                            standings, sort_keys=True, separators=(",", ":")
                        ).encode("utf-8")
                    ).hexdigest()
                )
                assert standings == _sql_standings(pair[node])
            assert digests[0] == digests[1]

            # The derived FTS read model is consistent on both copies too.
            from agent_session_tools.context.concept_schema import (
                _inspect_fts_consistency,
            )

            for node in ("a", "b"):
                pair[node]["conn"].rollback()
                receipt = _inspect_fts_consistency(pair[node]["conn"])
                assert receipt.consistent
        finally:
            _close_pair(pair)

    @pytest.mark.parametrize("first_direction", ["ab", "ba"])
    def test_6_concurrent_accept_and_retire_resolve_to_the_computed_winner(
        self, replicas, tmp_path, monkeypatch, first_direction
    ):
        """Matrix 6: the winner is computed from the triple, in either order."""
        concept = _winddown(monkeypatch, replicas["a"], "a", "Alpha finding", "fact-a")
        _sync(replicas, "a", "b")
        accept_id = _transition(
            monkeypatch, replicas["a"], concept, "accepted", "concurrent accept"
        )
        retire_id = _transition(
            monkeypatch, replicas["b"], concept, "retired", "concurrent retire"
        )
        pair = _copy_pair(replicas, tmp_path, f"concurrent-{first_direction}")
        try:
            order = (
                (("a", "b"), ("b", "a"))
                if first_direction == "ab"
                else (("b", "a"), ("a", "b"))
            )
            for sender, receiver in order:
                _sync(pair, sender, receiver)

            events = _assert_converged(pair)
            concurrent = [
                event for event in events if event["id"] in (accept_id, retire_id)
            ]
            assert len(concurrent) == 2
            expected_winner = max(concurrent, key=_standing_key)
            standings = _computed_standings(events)
            assert standings[concept] == expected_winner["standing"]
            assert _sql_standings(pair["a"])[concept] == expected_winner["standing"]
            assert _sql_standings(pair["b"])[concept] == expected_winner["standing"]
        finally:
            _close_pair(pair)

    def test_7_causal_accept_then_retire_resolves_to_retired_on_both(
        self, replicas, tmp_path, monkeypatch
    ):
        """Matrix 7: the retire chains from the synced accept, by construction."""
        concept = _winddown(monkeypatch, replicas["a"], "a", "Alpha finding", "fact-a")
        accept_id = _transition(
            monkeypatch, replicas["a"], concept, "accepted", "causal accept"
        )
        _sync(replicas, "a", "b")
        retire_id = _transition(
            monkeypatch, replicas["b"], concept, "retired", "causal retire"
        )
        _sync(replicas, "b", "a")

        events = _assert_converged(replicas)
        retire = next(event for event in events if event["id"] == retire_id)
        assert retire["parent_event_id"] == accept_id
        standings = _computed_standings(events)
        assert standings[concept] == "retired"


class TestDuplicateMachineIdentity:
    def test_negotiate_refuses_two_peers_with_one_instance(
        self, replicas, tmp_path, monkeypatch
    ):
        """A cloned database presented as a second replica is refused up front."""
        clone_path = tmp_path / "a-clone.db"
        replicas["a"]["conn"].commit()
        with closing(sqlite3.connect(clone_path)) as destination:
            replicas["a"]["conn"].backup(destination)
        clone_conn = sqlite3.connect(clone_path)
        clone_conn.row_factory = sqlite3.Row
        try:
            clone_config = {
                "memory": {
                    **replicas["a"]["config"]["memory"],
                    "sync": {
                        "node_id": "b",
                        "peers": {"a": {"allowed_scopes": ["personal"]}},
                    },
                }
            }
            sender = hello(
                replicas["a"]["conn"],
                PeerPolicy.from_config(replicas["a"]["config"], "b"),
            )
            receiver = hello(clone_conn, PeerPolicy.from_config(clone_config, "a"))
            with pytest.raises(ReplicaError, match="identity is duplicated"):
                negotiate(sender, receiver)
        finally:
            clone_conn.close()

    def test_apply_refuses_foreign_events_claiming_the_local_instance(
        self, replicas, tmp_path, monkeypatch
    ):
        """A clone's events routed through a third replica are refused, never merged.

        Clone A, create an event on the clone (it still carries A's
        ``origin_instance``), sync clone -> B (B cannot tell), then B -> A:
        A must refuse the event that claims to be its own history.
        """
        _winddown(monkeypatch, replicas["a"], "a", "Alpha finding", "fact-a")
        replicas["a"]["conn"].commit()
        clone_path = tmp_path / "a-clone.db"
        with closing(sqlite3.connect(clone_path)) as destination:
            replicas["a"]["conn"].backup(destination)
        clone = {
            "conn": sqlite3.connect(clone_path),
            "path": clone_path,
            "config": replicas["a"]["config"],
            "config_path": replicas["a"]["config_path"],
        }
        clone["conn"].row_factory = sqlite3.Row
        try:
            # Divergent histories under one instance: an event on the clone...
            clone_concept = _winddown(
                monkeypatch, clone, "a", "Clone finding", "fact-a"
            )
            # ...reaches B, which cannot distinguish the clone from A.
            _sync({"a": clone, "b": replicas["b"]}, "a", "b")
            assert clone_concept in _sql_standings(replicas["b"])

            # B -> A: the incoming event claims A's own origin_instance.
            with pytest.raises(ReplicaError, match="[Cc]lone"):
                _sync(replicas, "b", "a")

            # A retained its pre-transfer state.
            assert clone_concept not in _sql_standings(replicas["a"])
        finally:
            clone["conn"].close()

    def test_apply_refuses_interleaved_origin_sequences(
        self, replicas, tmp_path, monkeypatch
    ):
        """Two histories under one (origin_instance, origin_seq) never merge.

        The clone and A each allocate their own seq 2 with different events;
        after A's own event reaches B... the clone's conflicting seq is refused
        at B with a diagnostic, not interleaved.
        """
        _winddown(monkeypatch, replicas["a"], "a", "Alpha finding", "fact-a")
        replicas["a"]["conn"].commit()
        clone_path = tmp_path / "a-clone.db"
        with closing(sqlite3.connect(clone_path)) as destination:
            replicas["a"]["conn"].backup(destination)
        clone = {
            "conn": sqlite3.connect(clone_path),
            "path": clone_path,
            "config": replicas["a"]["config"],
            "config_path": replicas["a"]["config_path"],
        }
        clone["conn"].row_factory = sqlite3.Row
        try:
            # A and the clone both allocate the same origin_seq divergently.
            _winddown(monkeypatch, replicas["a"], "a", "Real second", "fact-a")
            _winddown(monkeypatch, clone, "a", "Clone second", "fact-a")

            _sync(replicas, "a", "b")
            with pytest.raises(ReplicaError, match="[Cc]lone"):
                _sync({"a": clone, "b": replicas["b"]}, "a", "b")
        finally:
            clone["conn"].close()
