"""Actual two-database lifecycle tests with serialized exchange; no sync mock."""

import json
import os
import subprocess
import sys

import pytest

from experiments.evidence_context.lifecycle import Replica

EARLY = "2026-01-01T00:00:00Z"
LATE = "2026-01-02T00:00:00Z"
SCOPES = {"personal", "work", "unclassified"}


@pytest.fixture
def pair(tmp_path):
    a = Replica.create(tmp_path / "a.db")
    b = Replica.create(tmp_path / "b.db")
    yield a, b
    a.close()
    b.close()


def exchange(a, b):
    b.receive(a.export(SCOPES), SCOPES)
    a.receive(b.export(SCOPES), SCOPES)


def test_correction_keeps_history_and_old_replay_does_not_become_current(pair):
    a, b = pair
    old = a.add("decision", "personal", "proposal", EARLY)
    stale = a.export(SCOPES)
    new = a.add("decision", "personal", "corrected", LATE, old, "Original omitted a constraint")
    a.receive(stale, SCOPES)
    assert [r["id"] for r in a.heads("decision")] == [new]
    assert [r["id"] for r in a.heads("decision", EARLY)] == [old]
    assert a.lookup(old)["body"] == "proposal"
    exchange(a, b)
    assert a.heads("decision") == b.heads("decision")


def test_concurrent_corrections_remain_conflicting_heads(pair):
    a, b = pair
    old = a.add("decision", "personal", "initial", EARLY)
    exchange(a, b)
    left = a.add("decision", "personal", "alternative a", LATE, old, "A observed failure")
    right = b.add("decision", "personal", "alternative b", LATE, old, "B observed success")
    exchange(a, b)
    assert {r["id"] for r in a.heads("decision")} == {left, right}
    assert a.heads("decision") == b.heads("decision")


@pytest.mark.parametrize("reverse", [False, True])
def test_delete_wins_both_exchange_orders_replay_reimport_and_rebuild(pair, reverse):
    a, b = pair
    first = a.add("decision", "personal", "SECRET_TOKEN old", EARLY)
    a.add("decision", "personal", "SECRET_TOKEN corrected", LATE, first, "SECRET_TOKEN reason")
    survivor = a.add("unrelated", "personal", "keepme", EARLY)
    exchange(a, b)
    stale = b.export(SCOPES)
    for replica in pair:
        for kind in ("summary", "edge", "context-cache"):
            replica.derive(kind, kind, "SECRET_TOKEN derived", ["decision", "unrelated"])
        replica.derive("safe", "summary", "safe", ["unrelated"])
    a.forget("decision", "personal")
    exchange(b, a) if reverse else exchange(a, b)
    for replica in pair:
        replica.receive(stale, SCOPES)
        replica.receive(stale, SCOPES)
        assert replica.add("decision", "personal", "SECRET_TOKEN reimport", LATE) is None
        replica.rebuild()
        assert replica.lookup(first) is None
        assert replica.heads("decision", EARLY) == []
        assert replica.search("SECRET_TOKEN") == []
        assert replica.search("keepme") == [survivor]
        assert "SECRET_TOKEN" not in replica.export(SCOPES)
        assert [r[0] for r in replica.conn.execute("SELECT id FROM artifacts")] == ["safe"]
        assert replica.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert a.export(SCOPES) == b.export(SCOPES)


def test_delete_before_first_import_suppresses_future_replay(pair):
    a, b = pair
    a.forget("decision", "personal")
    b.add("decision", "personal", "secret", EARLY)
    exchange(a, b)
    assert not a.heads("decision") and not b.heads("decision")


def test_correction_invalidates_derived_content(pair):
    a, _ = pair
    old = a.add("decision", "personal", "old", EARLY)
    a.derive("summary", "summary", "old interpretation", ["decision"])
    a.add("decision", "personal", "new", LATE, old, "Correction")
    assert a.conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0


def test_export_filters_before_serialization_and_receiver_rejects_wrong_scope(pair):
    a, b = pair
    a.add("public", "personal", "publicbody", EARLY)
    a.add("restricted", "work", "WORK_SECRET", EARLY)
    allowed = a.export({"personal"})
    assert "WORK_SECRET" not in allowed and "restricted" not in allowed
    b.receive(allowed, {"personal"})
    before = b.export(SCOPES)
    with pytest.raises(ValueError, match="scope"):
        b.receive(a.export(SCOPES), {"personal"})
    assert b.export(SCOPES) == before


def test_corrupt_transfer_rolls_back_including_tombstones(pair):
    a, b = pair
    b.add("decision", "personal", "keep until valid transfer", EARLY)
    a.forget("decision", "personal")
    a.add("other", "personal", "new", EARLY)
    payload = json.loads(a.export(SCOPES))
    payload["versions"][0]["id"] = "corrupt"
    before = b.export(SCOPES)
    with pytest.raises(ValueError, match="identity"):
        b.receive(json.dumps(payload), SCOPES)
    assert b.export(SCOPES) == before


def test_interrupted_delete_rolls_back_then_retry_completes(pair):
    a, _ = pair
    version = a.add("decision", "personal", "secret", EARLY)
    a.derive("summary", "summary", "secret", ["decision"])
    # A genuine process exit after tombstone insertion, before content purge.
    script = """
import os
from pathlib import Path
from experiments.evidence_context.lifecycle import Replica
r = Replica(Path(os.environ['LAB_DB_PATH']))
r._invalidate = lambda source: os._exit(17)
r.forget('decision', 'personal')
"""
    result = subprocess.run(
        [sys.executable, "-c", script], env={**os.environ, "LAB_DB_PATH": str(a.path)}, check=False
    )
    assert result.returncode == 17
    assert not a.forgotten("decision")
    assert a.lookup(version) is not None
    assert a.conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 1
    a.forget("decision", "personal")
    a.forget("decision", "personal")
    assert a.lookup(version) is None
    assert not a.search("secret")
    assert a.conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0


def test_reclassification_is_explicitly_rejected_not_silently_merged(pair):
    a, _ = pair
    a.add("decision", "personal", "first", EARLY)
    with pytest.raises(ValueError, match="reclassification"):
        a.add("decision", "work", "second", LATE)
    assert a.heads("decision")[0]["body"] == "first"


def test_invalid_cross_source_correction_is_rejected(pair):
    a, _ = pair
    old = a.add("one", "personal", "first", EARLY)
    with pytest.raises(ValueError, match="same-source"):
        a.add("two", "personal", "second", LATE, old, "invalid")
    assert not a.heads("two")


def test_forgetting_prevents_new_derived_content(pair):
    a, _ = pair
    a.add("decision", "personal", "secret", EARLY)
    a.forget("decision", "personal")
    with pytest.raises(ValueError, match="forgotten"):
        a.derive("summary", "summary", "secret", ["decision"])
