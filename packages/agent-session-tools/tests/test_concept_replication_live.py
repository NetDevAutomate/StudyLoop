"""Opt-in two-copy matrix run against two real SQLite Online Backup copies.

design.md ("Two-copy test matrix"): every fixture scenario also has to hold
once on two real Online Backup copies of the owner's database. The live
database is only ever read through the Online Backup API (read-only source
connection, its own read transaction rolled back); every write happens on
disposable copies under a throwaway temp directory, deleted afterwards.

One of the two copies is deliberately re-identified (fresh
``context_access_state.instance`` and a matching, still-empty concept clock)
before any concept event exists on it: two byte-identical backups otherwise
share one replica identity, and the protocol refuses clones by design -- the
re-identification models restoring a backup onto a genuinely distinct second
machine, which is the only honest way two real copies can be peers.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest

from agent_session_tools.context.concepts import ConceptService
from agent_session_tools.context.concept_schema import _inspect_fts_consistency
from agent_session_tools.context.scope import ScopePolicy, apply_policy
from agent_session_tools.migrations import CURRENT_VERSION, migrate
from agent_session_tools.replication.content import apply_content
from agent_session_tools.replication.policy import PeerPolicy, hello, negotiate
from agent_session_tools.replication.snapshot import export_snapshot

LIVE_DB = Path.home() / ".config/studyloop/sessions.db"

pytestmark = [
    pytest.mark.live_concepts,
    pytest.mark.timeout(600),
    pytest.mark.skipif(not LIVE_DB.is_file(), reason="owner's live database absent"),
]

_NOW = "2026-09-08T12:00:00+00:00"


def _sentinels(path: Path) -> tuple[int, int, int]:
    with closing(
        sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    ) as conn:
        return (
            conn.execute("PRAGMA user_version").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
        )


def _online_backup(source: Path, destination: Path) -> None:
    with closing(
        sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    ) as src:
        src.execute("PRAGMA query_only = ON")
        src.execute("BEGIN")
        try:
            with closing(sqlite3.connect(destination)) as dst:
                src.backup(dst)
        finally:
            src.rollback()


def _reidentify(path: Path) -> None:
    """Give a restored backup its own honest replica identity, pre-events."""
    with closing(sqlite3.connect(path)) as conn:
        events = conn.execute("SELECT COUNT(*) FROM context_concept_events").fetchone()[
            0
        ]
        if events:
            raise RuntimeError("refusing to re-identify a copy with concept history")
        instance = uuid4().hex
        conn.execute(
            "UPDATE context_access_state SET instance=? WHERE id=1", (instance,)
        )
        # The clock identity trigger forbids UPDATE by design; a fresh row is
        # the re-identification path for a copy with zero allocated events.
        conn.execute("DELETE FROM context_concept_clock WHERE id=1")
        conn.execute("INSERT INTO context_concept_clock VALUES (1,?,0,0)", (instance,))
        conn.commit()


def _pick_project(path: Path) -> tuple[str, str, str]:
    """A small real project: (project_path, session_id, unique_quote)."""
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        candidates = conn.execute(
            """SELECT s.project_path AS root, COUNT(DISTINCT s.id) AS n,
                      SUM(COALESCE((SELECT SUM(length(m.content))
                                    FROM messages m WHERE m.session_id=s.id), 0)) AS msg_bytes,
                      SUM(COALESCE((SELECT SUM(length(e2.body))
                                    FROM context_evidence e2 WHERE e2.session_id=s.id), 0)) AS ev_bytes
               FROM sessions s
               WHERE s.project_path IS NOT NULL AND s.project_path LIKE '/%'
                 AND EXISTS (SELECT 1 FROM context_evidence e
                             WHERE e.session_id=s.id
                               AND length(e.body) BETWEEN 400 AND 50000)
               GROUP BY s.project_path
               HAVING n BETWEEN 1 AND 10
                  AND msg_bytes + ev_bytes < 4000000
               ORDER BY msg_bytes + ev_bytes, root LIMIT 20"""
        ).fetchall()
        for candidate in candidates:
            root = candidate["root"]
            rows = conn.execute(
                """SELECT e.session_id AS sid, e.body AS body
                   FROM context_evidence e JOIN sessions s ON s.id=e.session_id
                   WHERE s.project_path=? AND length(e.body) BETWEEN 400 AND 50000
                   ORDER BY e.id LIMIT 5""",
                (root,),
            ).fetchall()
            for row in rows:
                sid, body = row["sid"], row["body"]
                bodies = [
                    r[0]
                    for r in conn.execute(
                        "SELECT body FROM context_evidence WHERE session_id=?",
                        (sid,),
                    )
                ]
                if any(len(b) > 200_000 for b in bodies):
                    continue
                for start in range(0, max(1, len(body) - 200), 97):
                    quote = body[start : start + 160]
                    if len(quote) < 40 or not quote.strip():
                        continue
                    occurrences = sum(b.count(quote) for b in bodies)
                    if occurrences == 1:
                        return root, sid, quote
        raise RuntimeError("no suitable real project/session/quote found")


def _config(tmp_path: Path, node: str, other: str, root: str) -> tuple[dict, Path]:
    config = {
        "memory": {
            "default_scope": "personal",
            "projects": {"p": {"scope": "personal", "roots": [root]}},
            "sync": {
                "node_id": node,
                "peers": {other: {"allowed_scopes": ["personal"]}},
            },
        }
    }
    config_path = tmp_path / f"live-config-{node}-{uuid4().hex[:8]}.json"
    config_path.write_text(json.dumps(config))
    return config, config_path


def _apply_policy(path: Path, config: dict) -> None:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        apply_policy(
            conn, ScopePolicy.from_config(config), actor="live-matrix", dry_run=False
        )
        conn.commit()
    finally:
        conn.close()


def _sync(pair, sender, receiver):
    hellos = []
    for node, other in ((sender, receiver), (receiver, sender)):
        item = pair[node]
        with closing(sqlite3.connect(item["path"])) as conn:
            conn.row_factory = sqlite3.Row
            hellos.append(hello(conn, PeerPolicy.from_config(item["config"], other)))
    plan = negotiate(*hellos)
    snapshot = export_snapshot(
        pair[sender]["path"], pair[sender]["config"], plan, "personal"
    )
    return apply_content(pair[receiver]["path"], pair[receiver]["config"], snapshot)


def _events(path: Path):
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in conn.execute("SELECT * FROM context_concept_events ORDER BY id")
        ]


def _digest(events) -> str:
    canonical = json.dumps(
        sorted(events, key=lambda row: row["id"]),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _standing_key(event):
    return (event["logical_time"], event["origin_instance"], event["id"])


def _standings(events):
    by_concept: dict[str, list[dict]] = {}
    for event in events:
        by_concept.setdefault(event["concept_id"], []).append(event)
    return {
        concept: max(history, key=_standing_key)["standing"]
        for concept, history in by_concept.items()
    }


def _assert_converged(pair):
    events_a, events_b = _events(pair["a"]["path"]), _events(pair["b"]["path"])
    assert {e["id"] for e in events_a} == {e["id"] for e in events_b}
    assert _digest(events_a) == _digest(events_b)
    assert _standings(events_a) == _standings(events_b)
    return events_a


def _service(item):
    return ConceptService(item["path"], now=lambda: _NOW, prepare_schema=False)


def _winddown(monkeypatch, item, session_id, title, quote):
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(item["config_path"]))
    result = _service(item).winddown(
        session_id,
        {
            "concepts": [
                {
                    "type": "Finding",
                    "title": title,
                    "description": f"{title}: live matrix fixture concept.",
                    "tags": ["live-matrix", "replication"],
                    "confidence": 0.9,
                    "quotes": [{"quote": quote}],
                }
            ]
        },
        actor="live-matrix",
    )
    assert result.errors == (), result.errors
    return result.concept_ids[0]


def _transition(monkeypatch, item, concept_id, standing, reason):
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(item["config_path"]))
    result = _service(item).transition(
        concept_id, standing, actor="live-matrix", reason=reason
    )
    assert result.errors == (), result.errors
    return result.event_id


def test_two_copy_matrix_holds_on_two_real_online_backup_copies(tmp_path, monkeypatch):
    before = _sentinels(LIVE_DB)
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "personal")

    # Two real copies, migrated; copy B re-identified as a distinct machine.
    paths = {node: tmp_path / f"real-{node}.db" for node in ("a", "b")}
    for node in ("a", "b"):
        _online_backup(LIVE_DB, paths[node])
        with closing(sqlite3.connect(paths[node])) as conn:
            migrate(conn)
            assert conn.execute("PRAGMA user_version").fetchone()[0] == CURRENT_VERSION
    _reidentify(paths["b"])

    root, session_id, quote = _pick_project(paths["a"])
    pair = {}
    for node, other in (("a", "b"), ("b", "a")):
        config, config_path = _config(tmp_path, node, other, root)
        _apply_policy(paths[node], config)
        pair[node] = {
            "path": paths[node],
            "config": config,
            "config_path": config_path,
        }

    # Pre-sync divergence: one concept authored on each copy.
    concept_a = _winddown(monkeypatch, pair["a"], session_id, "Live alpha", quote)
    concept_b = _winddown(monkeypatch, pair["b"], session_id, "Live beta", quote)

    # Matrix 1+2: both orders from the same pre-sync state converge identically.
    second = {}
    for node in ("a", "b"):
        copy_path = tmp_path / f"real-{node}-order2.db"
        _online_backup(paths[node], copy_path)
        second[node] = {**pair[node], "path": copy_path}
    _sync(pair, "a", "b")
    _sync(pair, "b", "a")
    _sync(second, "b", "a")
    _sync(second, "a", "b")
    events_first = _assert_converged(pair)
    events_second = _assert_converged(second)
    assert _digest(events_first) == _digest(events_second)
    assert _standings(events_first) == _standings(events_second)

    # Matrix 3: replay adds zero rows in either direction.
    replayed = _sync(pair, "a", "b")
    assert replayed["content_phase_committed"] is True
    _sync(pair, "b", "a")
    assert _events(pair["a"]["path"]) == events_first
    assert _events(pair["b"]["path"]) == events_first

    # Matrix 6: concurrent accept-on-A / retire-on-B resolves to the winner
    # computed from the (lamport, machine_id, event_id) triple.
    accept_id = _transition(
        monkeypatch, pair["a"], concept_a, "accepted", "live concurrent accept"
    )
    retire_id = _transition(
        monkeypatch, pair["b"], concept_a, "retired", "live concurrent retire"
    )
    _sync(pair, "a", "b")
    _sync(pair, "b", "a")
    events = _assert_converged(pair)
    concurrent = [e for e in events if e["id"] in (accept_id, retire_id)]
    assert len(concurrent) == 2
    expected = max(concurrent, key=_standing_key)
    assert _standings(events)[concept_a] == expected["standing"]

    # Matrix 4: a causally-later local event outranks the prior concurrent
    # ones -- run against the unmodified allocator (design.md B3 note).
    highest = max(e["logical_time"] for e in events)
    later_id = _transition(
        monkeypatch, pair["b"], concept_b, "accepted", "live post-convergence"
    )
    later = next(e for e in _events(pair["b"]["path"]) if e["id"] == later_id)
    assert later["logical_time"] > highest
    _sync(pair, "b", "a")
    events = _assert_converged(pair)
    assert _standings(events)[concept_b] == "accepted"

    # Matrix 7: causal accept-then-retire chains and lands retired on both.
    retire_b = _transition(
        monkeypatch, pair["a"], concept_b, "retired", "live causal retire"
    )
    _sync(pair, "a", "b")
    events = _assert_converged(pair)
    retire_row = next(e for e in events if e["id"] == retire_b)
    assert retire_row["parent_event_id"] == later_id
    assert _standings(events)[concept_b] == "retired"

    # Matrix 5: read-model rebuild is hash-equivalent and FTS is consistent.
    digests = []
    for node in ("a", "b"):
        standings = _standings(_events(pair[node]["path"]))
        digests.append(
            hashlib.sha256(
                json.dumps(standings, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        with closing(sqlite3.connect(pair[node]["path"])) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            receipt = _inspect_fts_consistency(conn)
            assert receipt.consistent
    assert digests[0] == digests[1]

    # The live database was never touched.
    assert _sentinels(LIVE_DB) == before
