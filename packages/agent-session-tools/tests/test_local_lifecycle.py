"""Production local forgetting: actual native capture, cascades, replay and bytes."""

import json
import sqlite3
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from agent_session_tools.context import annotations, records
from agent_session_tools.context.cli import app
from agent_session_tools.context.lifecycle import (
    compact,
    eviction,
    forget_session,
    purge_session,
)
from agent_session_tools.context.observations import ObservationStore
from agent_session_tools.context.provenance import ExecutionState, Scope
from agent_session_tools.context.scope import ScopeError, ScopePolicy, apply_policy
from agent_session_tools.context.store import Access, Citation, ContextStore
from agent_session_tools.exporters.codex import CodexExporter


@pytest.fixture
def memory(tmp_path, monkeypatch):
    config = {
        "memory": {
            "default_scope": "personal",
            "projects": {
                "p": {"scope": "personal", "roots": [str(tmp_path / "personal")]},
                "w": {"scope": "work", "roots": [str(tmp_path / "work")]},
            },
        }
    }
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(cfg))
    path = tmp_path / "sessions.db"
    conn = records.connect(path)
    apply_policy(conn, ScopePolicy.from_config(config), actor="fixture", dry_run=False)
    archives = tmp_path / "archives"
    archives.mkdir()
    for name in ("personal", "work"):
        rows = [
            {
                "type": "session_meta",
                "payload": {"id": name, "cwd": str(tmp_path / name)},
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": f"UNIQUE_{name.upper()}_BODY"}
                    ],
                },
            },
        ]
        (archives / f"rollout-{name}.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows)
        )
    exporter = CodexExporter(archives)
    stats = exporter.export_all(conn, incremental=False)
    assert not stats.errors
    ids = {
        name: conn.execute(
            "SELECT id FROM sessions WHERE project_path=?", (str(tmp_path / name),)
        ).fetchone()[0]
        for name in ("personal", "work")
    }
    yield {
        "conn": conn,
        "path": path,
        "config": config,
        "cfg": cfg,
        "exporter": exporter,
        "ids": ids,
    }
    conn.close()


def enrich(memory):
    c = memory["conn"]
    sid = memory["ids"]["personal"]
    store = ContextStore(c)
    source = dict(
        c.execute(
            "SELECT * FROM context_evidence WHERE session_id=?", (sid,)
        ).fetchone()
    )
    message = c.execute(
        "SELECT id FROM messages WHERE session_id=?", (sid,)
    ).fetchone()[0]
    assertion = store.propose(
        statement="UNIQUE_PERSONAL_ASSERTION",
        state=ExecutionState.UNKNOWN,
        target=None,
        generator="fixture",
        citations=[
            Citation(evidence_id=source["id"], start=0, end=8, quote=source["body"][:8])
        ],
        access=Access(scope=Scope.PERSONAL),
    )
    with store._atomic(), records.policy_guard(c):
        c.execute(
            "INSERT INTO study_sessions(id,session_id,started_at,notes) VALUES ('study',?,'fixture','UNIQUE_PERSONAL_STUDY')",
            (sid,),
        )
        owner = records.bind(c, "study_sessions", "study", session_id=sid)
        # Older children without owner records must not escape via SET NULL.
        c.execute(
            "INSERT INTO study_notes(study_session_id,title,body) VALUES ('study','old note','UNIQUE_PERSONAL_NOTE')"
        )
        c.execute(
            "INSERT INTO parked_topics(study_session_id,question) VALUES ('study','UNIQUE_PERSONAL_PARKED')"
        )
        observation = ObservationStore(c).append(
            kind="fixture.report",
            subject="fixture",
            payload={"text": "UNIQUE_PERSONAL_REPORT"},
            producer="fixture",
            authority="model_interpretation",
            evidence_ids=[source["id"]],
        )
        records.link_observation(c, owner, observation)
        first = annotations.write(c, sid, "note", {"notes": "UNIQUE_PERSONAL_FIRST"})
        second = annotations.write(
            c, sid, "note", {"notes": "UNIQUE_PERSONAL_CORRECTION"}
        )
        # Migration 48 shape: chunked, hashed, dimensioned; no session vectors exist.
        c.execute(
            "INSERT INTO message_embeddings"
            "(message_id,chunk_ix,model,dim,content_sha256,embedding) VALUES (?,?,?,?,?,?)",
            (message, 0, "fixture-model", 4, "0" * 64, b"UNIQUE_PERSONAL_VECTOR"),
        )
    return {
        "assertion": assertion,
        "source": source["id"],
        "owner": owner,
        "observation": observation,
        "notes": [first, second],
    }


def test_preview_is_body_free_and_preserves_database(memory):
    enrich(memory)
    c = memory["conn"]
    before = list(c.iterdump())
    result = forget_session(c, memory["ids"]["personal"])
    assert not result["applied"] and "UNIQUE_" not in json.dumps(result)
    assert result["selected_counts"]["learner_records"] == 3
    assert list(c.iterdump()) == before


def test_forget_purges_native_and_detached_legacy_derivatives(memory):
    ids = enrich(memory)
    c = memory["conn"]
    result = forget_session(c, memory["ids"]["personal"], apply=True)
    assert result["applied"] and result["replica_reconciliation"] == "not_performed"
    for table in (
        "study_sessions",
        "study_notes",
        "parked_topics",
        "context_assertions",
        "context_observations",
        "context_record_owners",
        "message_embeddings",
    ):
        assert c.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert c.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1
    assert (
        c.execute(
            "SELECT count(*) FROM messages_fts WHERE messages_fts MATCH ? ",
            ("UNIQUE_PERSONAL_BODY",),
        ).fetchone()[0]
        == 0
    )
    assert (
        c.execute(
            "SELECT count(*) FROM context_evidence_fts WHERE context_evidence_fts MATCH ?",
            ("UNIQUE_PERSONAL_BODY",),
        ).fetchone()[0]
        == 0
    )
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    for kind, key in [
        ("session", memory["ids"]["personal"]),
        ("source", ids["source"]),
        ("assertion", ids["assertion"]),
        ("record", ids["owner"]),
        ("observation", ids["observation"]),
    ]:
        assert c.execute(
            "SELECT 1 FROM context_retirements WHERE kind=? AND object_id=?",
            ("evidence" if kind == "source" else kind, key),
        ).fetchone()
    assert (
        c.execute(
            "SELECT previous_id FROM context_observation_supersedes WHERE observation_id=?",
            (ids["notes"][1],),
        ).fetchone()[0]
        == ids["notes"][0]
    )


def test_actual_exporter_cannot_reimport_forgotten_native_source(memory):
    enrich(memory)
    c = memory["conn"]
    sid = memory["ids"]["personal"]
    forget_session(c, sid, apply=True)
    stats = memory["exporter"].export_all(c, incremental=False)
    assert stats.forgotten == 1 and not stats.errors
    assert not c.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone()
    assert not c.execute(
        "SELECT 1 FROM context_evidence WHERE session_id=?", (sid,)
    ).fetchone()


def test_compaction_removes_unique_markers_from_canonical_files(memory):
    enrich(memory)
    c = memory["conn"]
    path = memory["path"]
    forget_session(c, memory["ids"]["personal"], apply=True)
    assert compact(path)["complete"]
    for file in path.parent.glob(path.name + "*"):
        assert b"UNIQUE_PERSONAL_" not in file.read_bytes()
    assert b"UNIQUE_WORK_BODY" in path.read_bytes()
    assert not c.execute("SELECT 1 FROM context_erasure_pending").fetchone()


def test_excluded_scope_cannot_be_forgotten_or_previewed(memory):
    c = memory["conn"]
    before = list(c.iterdump())
    for apply in (False, True):
        with pytest.raises(ScopeError, match="unavailable"):
            forget_session(c, memory["ids"]["work"], apply=apply)
    assert list(c.iterdump()) == before


def test_mid_purge_failure_rolls_back_bodies_and_retirement(memory):
    enrich(memory)
    c = memory["conn"]
    c.execute(
        "CREATE TRIGGER fixture_fail BEFORE DELETE ON messages BEGIN SELECT RAISE(ABORT,'fixture interruption'); END"
    )
    c.commit()
    before = list(c.iterdump())
    with pytest.raises(sqlite3.IntegrityError, match="fixture interruption"):
        forget_session(c, memory["ids"]["personal"], apply=True)
    assert list(c.iterdump()) == before
    c.execute("DROP TRIGGER fixture_fail")
    c.commit()
    assert forget_session(c, memory["ids"]["personal"], apply=True)["applied"]


def test_eviction_purges_without_permanent_retirement(memory):
    enrich(memory)
    c = memory["conn"]
    sid = memory["ids"]["personal"]
    with ContextStore(c)._atomic(), eviction(c):
        purge_session(c, sid, permanent=False)
    for table in (
        "context_retirements",
        "context_tombstones",
        "context_observation_tombstones",
        "context_observation_retired_subjects",
        "context_annotation_retirements",
    ):
        assert c.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert (
        c.execute("SELECT mode FROM context_lifecycle_mode").fetchone()[0] == "ordinary"
    )
    assert not c.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone()
    # This tests the low-level reversible purge only, not peer permission/regrant.
    stats = memory["exporter"].export_all(c, incremental=False)
    assert not stats.errors
    assert c.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone()


def test_eviction_exception_restores_mode_and_state(memory):
    enrich(memory)
    c = memory["conn"]
    before = list(c.iterdump())
    with pytest.raises(RuntimeError, match="interrupt"):
        with ContextStore(c)._atomic(), eviction(c):
            purge_session(c, memory["ids"]["personal"], permanent=False)
            raise RuntimeError("interrupt")
    assert list(c.iterdump()) == before


def test_permanent_retirement_cannot_be_deleted(memory):
    c = memory["conn"]
    forget_session(c, memory["ids"]["personal"], apply=True)
    for table in ("context_retirements", "context_tombstones"):
        with pytest.raises(sqlite3.IntegrityError, match="Permanent retirement"):
            c.execute(f"DELETE FROM {table}")
        c.rollback()


def test_actual_cli_preview_apply_and_canonical_cleanup(memory):
    enrich(memory)
    runner = CliRunner()
    args = ["forget", memory["ids"]["personal"], "--db", str(memory["path"])]
    preview = runner.invoke(app, args)
    assert preview.exit_code == 0, preview.output
    assert not json.loads(preview.output)["applied"]
    applied = runner.invoke(app, [*args, "--apply"])
    assert applied.exit_code == 0, applied.output
    result = json.loads(applied.output)
    assert result["applied"] and result["canonical_file_cleanup"]["complete"]
    assert result["managed_restore_reconciled"] is False


def test_busy_reader_leaves_durable_cleanup_pending(memory):
    enrich(memory)
    reader = sqlite3.connect(memory["path"])
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM messages").fetchone()
    forget_session(memory["conn"], memory["ids"]["personal"], apply=True)
    assert compact(memory["path"])["complete"] is False
    assert memory["conn"].execute("SELECT 1 FROM context_erasure_pending").fetchone()
    reader.close()
    assert compact(memory["path"])["complete"] is True


@pytest.mark.parametrize("permanent", [True, False])
def test_process_death_rolls_back_purge_and_mode(memory, permanent):
    enrich(memory)
    c = memory["conn"]
    before = list(c.iterdump())
    code = """
import os,sys
from contextlib import nullcontext
from pathlib import Path
from agent_session_tools.context import records
from agent_session_tools.context.store import ContextStore
from agent_session_tools.context.lifecycle import eviction,purge_session
c=records.connect(Path(sys.argv[1]))
c.create_function('fixture_exit',0,lambda:os._exit(17))
c.execute("CREATE TEMP TRIGGER fixture_death BEFORE DELETE ON sessions BEGIN SELECT fixture_exit(); END")
permanent=sys.argv[3]=='True'
with ContextStore(c)._atomic(), (nullcontext() if permanent else eviction(c)):
    purge_session(c,sys.argv[2],permanent=permanent)
"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            code,
            str(memory["path"]),
            memory["ids"]["personal"],
            str(permanent),
        ],
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 17, result.stderr
    assert list(c.iterdump()) == before
    assert forget_session(c, memory["ids"]["personal"], apply=True)["applied"]


def test_policy_change_during_forget_rolls_back(memory, monkeypatch):
    from agent_session_tools.context import lifecycle

    enrich(memory)
    c = memory["conn"]
    before = list(c.iterdump())
    original = lifecycle.purge_session

    def change(*args, **kwargs):
        original(*args, **kwargs)
        config = memory["config"]
        config["memory"]["default_scope"] = "work"
        memory["cfg"].write_text(json.dumps(config))

    monkeypatch.setattr(lifecycle, "purge_session", change)
    with pytest.raises(ScopeError, match="Scope changed"):
        forget_session(c, memory["ids"]["personal"], apply=True)
    assert list(c.iterdump()) == before


def test_old_tombstone_body_is_reconciled_before_compaction(memory):
    c = memory["conn"]
    sid = memory["ids"]["personal"]
    # Earlier schemas could hold a suppressed source body beside its tombstone.
    c.execute(
        "INSERT INTO context_tombstones VALUES (?,'legacy-delete','fixture')", (sid,)
    )
    c.commit()
    assert c.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone()
    assert compact(memory["path"])["complete"]
    assert not c.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone()
    assert b"UNIQUE_PERSONAL_BODY" not in memory["path"].read_bytes()


@pytest.mark.parametrize("new_annotation", [False, True, "legacy_note", "metadata"])
def test_hot_pruning_is_verified_eviction_not_permanent_forgetting(
    memory, new_annotation
):
    from agent_session_tools.tiering import prune_hot

    enrich(memory)
    c = memory["conn"]
    c.execute("UPDATE sessions SET updated_at='2000-01-01T00:00:00Z'")
    c.commit()
    archive = memory["path"].with_name("full.db")
    with sqlite3.connect(archive) as full:
        c.backup(full)
    if new_annotation == "legacy_note":
        c.execute(
            "INSERT INTO session_notes(session_id,notes) VALUES (?,'Unarchived legacy edit')",
            (memory["ids"]["personal"],),
        )
        c.commit()
    elif new_annotation == "metadata":
        c.execute("UPDATE sessions SET metadata='Unarchived metadata'")
        c.commit()
    elif new_annotation:
        with ContextStore(c)._atomic(), records.policy_guard(c):
            annotations.write(
                c,
                memory["ids"]["personal"],
                "note",
                {"notes": "New report after archival"},
            )
    result = prune_hot(
        hot=memory["path"], full=archive, dry_run=False, vacuum=False, config={}
    )
    if new_annotation:
        assert result.sessions_deleted == 0 and result.skipped_unverified == 1
        assert result.skipped_anchored == 1
        assert c.execute("SELECT count(*) FROM sessions").fetchone()[0] == 2
    else:
        # enrich() binds study_sessions('study') to 'personal', which anchors it:
        # invariant 3 keeps the conversation so its learner rows survive in hot.
        assert result.sessions_deleted == 1 and result.skipped_anchored == 1
        assert result.anchored_ids == [memory["ids"]["personal"]]
        assert {r[0] for r in c.execute("SELECT id FROM sessions")} == {
            memory["ids"]["personal"]
        }
        assert c.execute("SELECT count(*) FROM study_notes").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM parked_topics").fetchone()[0] == 1
        assert not c.execute("SELECT 1 FROM context_retirements").fetchone()
        assert not c.execute("SELECT 1 FROM context_observation_tombstones").fetchone()
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
        with sqlite3.connect(archive) as full:
            assert (
                full.execute("SELECT count(*) FROM context_observations").fetchone()[0]
                == 3
            )
            assert full.execute("SELECT count(*) FROM study_notes").fetchone()[0] == 1


@pytest.mark.parametrize(
    "anchor",
    ["study_session", "teach_back_score", "parked_topic", "study_note", "owner_only"],
)
def test_hot_pruning_retains_sessions_that_own_learner_records(memory, anchor):
    """Invariant 3 (docs/session-db-tiering.md): learning tables are never pruned.

    Eviction sweeps ``study_sessions``, ``teach_back_scores``, ``parked_topics``
    and ``study_notes`` by ``session_id``, owner binding and ``study_session_id``
    (``lifecycle.selected_records``), so the only way to keep the promise is to
    keep the conversation those rows hang off. A session that owns a learner
    record must stay in hot with every record intact, and prune must say so
    separately from "not yet archived" so the operator is not sent to sync.
    """
    from agent_session_tools.tiering import prune_hot

    c = memory["conn"]
    anchored, evictable = memory["ids"]["personal"], memory["ids"]["work"]
    with ContextStore(c)._atomic(), records.policy_guard(c):
        if anchor == "owner_only":
            # Bound through context_record_owners with no session_id column set.
            c.execute(
                "INSERT INTO study_sessions(id,started_at) VALUES ('study','fixture')"
            )
            records.bind(c, "study_sessions", "study", session_id=anchored)
        elif anchor == "study_session":
            c.execute(
                "INSERT INTO study_sessions(id,session_id,started_at) VALUES ('study',?,'fixture')",
                (anchored,),
            )
        elif anchor == "teach_back_score":
            c.execute(
                "INSERT INTO teach_back_scores(concept,topic,session_id,review_type,created_at) "
                "VALUES ('decorators','python',?,'teach_back','fixture')",
                (anchored,),
            )
        elif anchor == "parked_topic":
            c.execute(
                "INSERT INTO parked_topics(session_id,question) VALUES (?,'UNIQUE_PARKED')",
                (anchored,),
            )
        else:
            c.execute(
                "INSERT INTO study_notes(session_id,title,body) VALUES (?,'t','UNIQUE_NOTE')",
                (anchored,),
            )
    c.execute("UPDATE sessions SET updated_at='2000-01-01T00:00:00Z'")
    c.commit()
    archive = memory["path"].with_name("full.db")
    with sqlite3.connect(archive) as full:
        c.backup(full)
    learner_rows = {
        table: c.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in (
            "study_sessions",
            "teach_back_scores",
            "parked_topics",
            "study_notes",
        )
    }

    result = prune_hot(
        hot=memory["path"], full=archive, dry_run=False, vacuum=False, config={}
    )

    assert result.sessions_deleted == 1
    assert result.skipped_anchored == 1 and result.anchored_ids == [anchored]
    assert result.skipped_unverified == 0 and result.skipped_ids == []
    remaining = {r[0] for r in c.execute("SELECT id FROM sessions")}
    assert remaining == {anchored}, (
        f"{evictable} should be evicted, {anchored} retained"
    )
    for table, count in learner_rows.items():
        assert c.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == count, table
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []


def test_schema40_upgrade_preserves_rows_and_rolls_back_failure(tmp_path, monkeypatch):
    from agent_session_tools import migrations
    from agent_session_tools.context import lifecycle_schema

    monkeypatch.setattr(migrations, "CURRENT_VERSION", 40)
    conn = records.connect(tmp_path / "old.db")
    conn.execute("INSERT INTO sessions(id,source) VALUES ('keep','fixture')")
    conn.execute(
        "INSERT INTO context_tombstones VALUES ('gone','deletion','original-time')"
    )
    conn.commit()
    before = list(conn.iterdump())
    original = lifecycle_schema.install

    def fail(c):
        original(c)
        raise RuntimeError("migration interruption")

    monkeypatch.setattr(migrations, "CURRENT_VERSION", 41)
    monkeypatch.setattr(lifecycle_schema, "install", fail)
    with pytest.raises(RuntimeError, match="migration interruption"):
        migrations.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 40
    assert list(conn.iterdump()) == before
    monkeypatch.setattr(lifecycle_schema, "install", original)
    migrations.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 41
    assert (
        conn.execute("SELECT source FROM sessions WHERE id='keep'").fetchone()[0]
        == "fixture"
    )
    assert (
        conn.execute(
            "SELECT retired_at FROM context_retirements WHERE object_id='gone'"
        ).fetchone()[0]
        == "original-time"
    )
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_compaction_rebuilds_stale_fts_from_live_rows(memory):
    c = memory["conn"]
    c.execute(
        "INSERT INTO messages_fts(content,session_id,role) VALUES ('UNIQUE_PERSONAL_ORPHAN','missing-session','user')"
    )
    c.commit()
    forget_session(c, memory["ids"]["personal"], apply=True)
    assert (
        c.execute(
            "SELECT count(*) FROM messages_fts WHERE session_id='missing-session'"
        ).fetchone()[0]
        == 1
    )
    assert compact(memory["path"])["complete"]
    assert (
        c.execute(
            "SELECT count(*) FROM messages_fts WHERE session_id='missing-session'"
        ).fetchone()[0]
        == 0
    )
    for file in memory["path"].parent.glob(memory["path"].name + "*"):
        assert b"UNIQUE_PERSONAL_" not in file.read_bytes()


def test_control_after_reconciled_snapshot_cannot_be_acknowledged(memory, monkeypatch):
    from agent_session_tools.context import lifecycle

    c = memory["conn"]
    sid = memory["ids"]["personal"]
    real_connect = sqlite3.connect
    events = []

    class InterleavedConnection(sqlite3.Connection):
        def commit(self):
            super().commit()
            if not events:
                events.append("control after reconciled snapshot committed")
                with real_connect(memory["path"]) as writer:
                    writer.execute("PRAGMA foreign_keys=ON")
                    writer.execute(
                        "INSERT INTO context_tombstones VALUES (?,'concurrent-control','fixture')",
                        (sid,),
                    )

    def connect(*args, **kwargs):
        return real_connect(*args, **kwargs, factory=InterleavedConnection)

    with monkeypatch.context() as race:
        race.setattr(lifecycle.sqlite3, "connect", connect)
        result = compact(memory["path"])
    assert events
    assert result == {"complete": False, "reason": "state_changed_during_cleanup"}
    assert c.execute("SELECT 1 FROM context_erasure_pending").fetchone()
    assert c.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone()
    assert compact(memory["path"])["complete"]
    assert not c.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone()
    assert b"UNIQUE_PERSONAL_BODY" not in memory["path"].read_bytes()


def test_process_death_before_vacuum_leaves_durable_pending_job(memory):
    forget_session(memory["conn"], memory["ids"]["personal"], apply=True)
    code = """
import os,sys,sqlite3
from pathlib import Path
from agent_session_tools.context import lifecycle
real_connect=sqlite3.connect
def connect(*args,**kwargs):
    conn=real_connect(*args,**kwargs)
    conn.set_trace_callback(lambda sql: os._exit(23) if sql=='VACUUM' else None)
    return conn
lifecycle.sqlite3.connect=connect
lifecycle.compact(Path(sys.argv[1]))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(memory["path"])],
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 23, result.stderr
    assert memory["conn"].execute("SELECT 1 FROM context_erasure_pending").fetchone()
    assert compact(memory["path"])["complete"]
    assert (
        not memory["conn"].execute("SELECT 1 FROM context_erasure_pending").fetchone()
    )


def test_other_writer_cannot_observe_eviction_mode_as_its_own(memory):
    c = memory["conn"]
    other = sqlite3.connect(memory["path"], timeout=0)
    try:
        other.execute("PRAGMA foreign_keys=ON")
        with ContextStore(c)._atomic(), eviction(c):
            assert (
                other.execute("SELECT mode FROM context_lifecycle_mode").fetchone()[0]
                == "ordinary"
            )
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("DELETE FROM context_evidence")
            other.rollback()
        other.execute("DELETE FROM context_evidence")
        other.commit()
        assert (
            c.execute(
                "SELECT count(*) FROM context_retirements WHERE kind='evidence'"
            ).fetchone()[0]
            == 2
        )
    finally:
        other.close()


def test_source_forget_preserves_independent_project_record_linked_to_report(memory):
    refs = enrich(memory)
    c = memory["conn"]
    with ContextStore(c)._atomic(), records.policy_guard(c):
        row = c.execute(
            "INSERT INTO knowledge_bridges(source_concept,source_domain,target_concept,target_domain) VALUES ('INDEPENDENT_PROJECT_BODY','fixture','query','fixture')"
        )
        owner = records.bind(
            c,
            "knowledge_bridges",
            row.lastrowid,
            owner_path=memory["path"].parent / "personal",
        )
        # This edge means the report depends on the record; it does not claim
        # that this independently owned record derives from the report.
        records.link_observation(c, owner, refs["observation"])
    identity = row.lastrowid
    assert records.is_visible(c, "knowledge_bridges", identity)
    c.rollback()
    forget_session(c, memory["ids"]["personal"], apply=True)
    assert c.execute(
        "SELECT 1 FROM knowledge_bridges WHERE id=?", (identity,)
    ).fetchone()
    assert c.execute(
        "SELECT 1 FROM context_record_owners WHERE id=?", (owner,)
    ).fetchone()
    assert not c.execute(
        "SELECT 1 FROM context_observations WHERE id=?", (refs["observation"],)
    ).fetchone()
    assert records.is_visible(c, "knowledge_bridges", identity)
