"""Disposable staging binds complete data without accumulating every body."""

import sqlite3
import json
import os
import subprocess
import sys

import pytest

from agent_session_tools.context.store import _hash, _json
from agent_session_tools.replication.policy import ReplicaError
from agent_session_tools.replication.snapshot import TABLES
from agent_session_tools.replication.staging import (
    Stage,
    StagedSnapshot,
    binding,
    canonical_parts,
)


def complete(stage, messages=()):
    return {
        table: stage.add(table, messages if table == "messages" else ())
        for table in TABLES
    }


def test_streamed_canonical_hash_matches_existing_json_for_unicode_and_escapes():
    rows = [{"id": "m2", "body": 'café\n雪\t"quoted"\\'}, {"id": "m1", "body": "next"}]
    with Stage() as stage:
        staged = complete(stage, rows)
        expected = {table: rows if table == "messages" else [] for table in TABLES}
        value = {"tables": staged, "other": [True, None, 1.25], "z": "last"}
        normal = {"tables": expected, "other": [True, None, 1.25], "z": "last"}
        assert "".join(canonical_parts(value)) == _json(normal)
        assert binding(value) == (_hash(_json(normal)), len(_json(normal).encode()))
        assert staged["messages"].indexed("id")["m1"]["body"] == "next"
        assert list(staged["messages"].indexed("id")) == ["m2", "m1"]


def test_incomplete_stage_and_duplicate_identity_never_seal():
    with Stage() as stage:
        with pytest.raises(ReplicaError, match="Incomplete"):
            stage.seal()
        with pytest.raises(ReplicaError, match="Duplicate"):
            stage.add("messages", [{"id": "same"}, {"id": "same"}])


def test_sealed_stage_is_read_only_and_closing_invalidates_rows():
    stage = Stage()
    tables = complete(stage, [{"id": "m", "body": "temporary"}])
    stage.seal()
    snapshot = StagedSnapshot(stage, {"tables": tables})
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        stage.conn.execute("DELETE FROM staged_rows")
    with pytest.raises(ReplicaError, match="Invalid"):
        stage.add("messages", [])
    snapshot.close()
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        list(tables["messages"])


def test_bounds_refuse_incomplete_rows(monkeypatch):
    from agent_session_tools.replication import staging

    monkeypatch.setattr(staging, "MAX_ENCODED_ROW_BYTES", 40)
    with Stage() as stage:
        with pytest.raises(ReplicaError, match="resource bounds"):
            stage.add("messages", [{"id": "m", "body": "x" * 100}])
        assert not stage.sealed
        assert stage.conn.execute("SELECT count(*) FROM staged_rows").fetchone()[0] == 0
        with pytest.raises(ReplicaError, match="Invalid"):
            stage.add("sessions", [])


def test_real_process_death_leaves_no_reusable_stage_file(tmp_path):
    scratch = tmp_path / "sqlite-scratch"
    scratch.mkdir()
    script = """
import json,os,resource
from agent_session_tools.replication.staging import Stage
s=Stage()
s.add('messages', ({'id':str(i),'body':'fictional stage bytes '*800} for i in range(4096)))
pages=s.conn.execute('PRAGMA page_count').fetchone()[0]
size=s.conn.execute('PRAGMA page_size').fetchone()[0]
os.write(1,json.dumps({'allocated_bytes':pages*size,'rss':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'visible_files':os.listdir(os.environ['SQLITE_TMPDIR'])}).encode())
os._exit(39)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        env={**os.environ, "SQLITE_TMPDIR": str(scratch), "TMPDIR": str(scratch)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 39, result.stderr
    report = json.loads(result.stdout)
    assert report["allocated_bytes"] > 64 * 1024 * 1024
    assert report["visible_files"] == []
    assert list(scratch.iterdir()) == []
