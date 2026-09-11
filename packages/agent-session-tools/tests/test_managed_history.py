"""Managed historical copies must obey the active canonical lifecycle state."""

from contextlib import closing
import json
import sqlite3
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from agent_session_tools import query_logic
from agent_session_tools.context import records
from agent_session_tools.context import managed_history as managed
from agent_session_tools.context.cli import app
from agent_session_tools.context.lifecycle import (
    eviction,
    forget_session,
    purge_session,
)
from agent_session_tools.context.scope import ScopePolicy, apply_policy
from agent_session_tools.context.observations import ObservationStore


@pytest.fixture
def history(tmp_path, monkeypatch):
    hot, full = tmp_path / "sessions.db", tmp_path / "full.db"
    config = {
        "database": {"path": str(hot), "full_db_path": str(full)},
        "logging": {"path": str(tmp_path / "session.log"), "level": "WARNING"},
        "memory": {
            "default_scope": "personal",
            "projects": {
                "study": {"scope": "personal", "roots": [str(tmp_path / "study")]},
                "work": {"scope": "work", "roots": [str(tmp_path / "work")]},
            },
        },
    }
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(cfg))
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "personal")
    with closing(records.connect(hot)) as conn:
        apply_policy(
            conn, ScopePolicy.from_config(config), actor="fixture", dry_run=False
        )
        for name in ("study", "work"):
            conn.execute(
                "INSERT INTO sessions(id,source,project_path) VALUES (?,'codex',?)",
                (name, str(tmp_path / name)),
            )
            conn.execute(
                "INSERT INTO context_session_projects VALUES (?,?,'explicit')",
                (name, name),
            )
            conn.execute(
                "INSERT INTO messages(id,session_id,role,content) VALUES (?,?,'user',?)",
                (name + "-message", name, "ORCHID_PRIVATE_" + name),
            )
        conn.commit()
        with closing(sqlite3.connect(full)) as archive:
            conn.backup(archive)
    return {"hot": hot, "full": full, "config": config, "cfg": cfg}


def test_forgotten_source_cannot_return_through_stale_full_history(history, capsys):
    with closing(records.connect(history["hot"])) as conn:
        forget_session(conn, "study", apply=True)
        query_logic.search(conn, "ORCHID", output_format="json")
    assert json.loads(capsys.readouterr().out)["rows"] == []


def test_unforgotten_scoped_archive_remains_useful(history, capsys):
    with closing(records.connect(history["hot"])) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with eviction(conn):
            purge_session(conn, "study", permanent=False)
        conn.commit()
        query_logic.search(conn, "ORCHID", output_format="json")
    result = json.loads(capsys.readouterr().out)
    assert len(result["rows"]) == 1
    assert result["rows"][0]["session_id"] == "study"
    assert result["rows"][0]["tier"] == "full"
    assert "ORCHID_PRIVATE_work" not in json.dumps(result)


@pytest.mark.parametrize("status", ["withdrawn", "awaiting_content", "released"])
def test_current_withdrawal_hides_stale_archive(history, capsys, status):
    with closing(records.connect(history["hot"])) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with eviction(conn):
            purge_session(conn, "study", permanent=False)
        conn.execute(
            "INSERT INTO context_replica_peers VALUES ('peer','remote','local','instance','now')"
        )
        conn.execute(
            "INSERT INTO context_replica_denials VALUES ('peer','personal','session','study',1,?)",
            (status,),
        )
        conn.commit()
        query_logic.search(conn, "ORCHID", output_format="json")
    assert json.loads(capsys.readouterr().out)["rows"] == []
    # Denial blocks body reads, but the scoped owner can still permanently forget
    # this archive-only source. A regrant does not undo that permanent intent.
    assert managed.forget_with_history("study", apply=True)["applied"]
    assert managed.reconcile_full()["complete"]
    with closing(records.connect(history["full"])) as conn:
        assert not conn.execute("SELECT 1 FROM sessions WHERE id='study'").fetchone()
        assert conn.execute("SELECT 1 FROM sessions WHERE id='work'").fetchone()


def test_permanent_cleanup_removes_both_copies_and_managed_indexes(history):
    with closing(records.connect(history["hot"])) as conn:
        forget_session(conn, "study", apply=True)
    result = managed.reconcile_full()
    assert result["complete"] and result["controls_stable"]
    assert result["managed_restore_reconciled"] is False
    assert result["withdrawal_reconciliation"] == "not_performed"
    for path in (history["hot"], history["full"]):
        with closing(records.connect(path)) as conn:
            assert conn.execute("SELECT id FROM sessions").fetchall()[0][0] == "work"
            assert conn.execute("SELECT count(*) FROM messages_fts").fetchone()[0] == 1
            assert conn.execute(
                "SELECT 1 FROM context_tombstones WHERE session_id='study'"
            ).fetchone()
            assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        assert b"ORCHID_PRIVATE_study" not in path.read_bytes()
    assert managed.reconcile_full()["complete"]


def test_archive_only_forget_preview_and_cli_apply(history):
    with closing(records.connect(history["hot"])) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with eviction(conn):
            purge_session(conn, "study", permanent=False)
        conn.commit()
    preview = managed.forget_with_history("study")
    assert preview["selected_from"] == "configured_full_history"
    assert preview["selected_counts"]["messages"] == 1
    with closing(records.connect(history["hot"])) as conn:
        assert not conn.execute("SELECT 1 FROM context_tombstones").fetchone()
    result = CliRunner().invoke(app, ["forget", "study", "--apply"])
    assert result.exit_code == 0, result.output
    outcome = json.loads(result.stdout)
    assert outcome["configured_full_cleanup"]["complete"]
    assert "ORCHID_PRIVATE" not in result.stdout
    with closing(records.connect(history["full"])) as conn:
        assert not conn.execute("SELECT 1 FROM sessions WHERE id='study'").fetchone()


def test_archive_cannot_override_existing_canonical_scope(history, capsys):
    with closing(records.connect(history["hot"])) as conn:
        conn.execute(
            "UPDATE context_session_projects SET project_id='work' WHERE session_id='study'"
        )
        conn.commit()
        query_logic.search(conn, "ORCHID", output_format="json")
    assert json.loads(capsys.readouterr().out)["rows"] == []
    with pytest.raises(ValueError, match="unavailable"):
        managed.forget_with_history("study", apply=True)
    with closing(records.connect(history["hot"])) as conn:
        assert not conn.execute("SELECT 1 FROM context_tombstones").fetchone()


def test_offline_full_reports_pending_then_retries_without_resurrection(
    history, capsys
):
    offline = history["full"].with_suffix(".offline")
    history["full"].rename(offline)
    result = CliRunner().invoke(app, ["forget", "study", "--apply"])
    assert result.exit_code == 2
    assert (
        json.loads(result.stdout)["configured_full_cleanup"]["reason"]
        == "full_store_unavailable"
    )
    offline.rename(history["full"])
    with closing(records.connect(history["hot"])) as conn:
        query_logic.search(conn, "ORCHID", output_format="json")
    assert json.loads(capsys.readouterr().out)["rows"] == []
    result = CliRunner().invoke(app, ["cleanup"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["complete"]


def test_full_retirement_is_not_lost_when_canonical_copy_is_older(history):
    with closing(records.connect(history["full"])) as conn:
        forget_session(conn, "study", apply=True)
    assert managed.reconcile_full()["complete"]
    with closing(records.connect(history["hot"])) as conn:
        assert not conn.execute("SELECT 1 FROM sessions WHERE id='study'").fetchone()


@pytest.mark.parametrize(
    "phase", ["before_authority", "after_authority", "after_archive"]
)
def test_actual_process_death_retains_intent_and_retry_completes(history, phase):
    with closing(records.connect(history["hot"])) as conn:
        forget_session(conn, "study", apply=True)
    script = """
import os, sys
from agent_session_tools.context import managed_history as m
phase=sys.argv[1]
original_authority=m._commit_authority
original_archive=m._commit_archive
def authority(c):
    if phase=='before_authority': os._exit(41)
    original_authority(c)
    if phase=='after_authority': os._exit(41)
def archive(c):
    original_archive(c)
    if phase=='after_archive': os._exit(41)
m._commit_authority=authority
m._commit_archive=archive
m.reconcile_full()
"""
    child = subprocess.run(
        [sys.executable, "-c", script, phase], capture_output=True, timeout=30
    )
    assert child.returncode == 41, child.stderr.decode()
    with closing(records.connect(history["hot"])) as conn:
        assert conn.execute(
            "SELECT 1 FROM context_tombstones WHERE session_id='study'"
        ).fetchone()
    assert managed.reconcile_full()["complete"]
    with closing(records.connect(history["full"])) as conn:
        assert not conn.execute("SELECT 1 FROM sessions WHERE id='study'").fetchone()


def test_canonical_intent_survives_archive_commit_failure(history, monkeypatch):
    with closing(records.connect(history["full"])) as conn:
        forget_session(conn, "study", apply=True)
    original = managed._commit_archive
    monkeypatch.setattr(
        managed,
        "_commit_archive",
        lambda conn: (_ for _ in ()).throw(sqlite3.OperationalError("busy")),
    )
    assert not managed.reconcile_full()["complete"]
    with closing(records.connect(history["hot"])) as conn:
        assert conn.execute(
            "SELECT 1 FROM context_tombstones WHERE session_id='study'"
        ).fetchone()
    monkeypatch.setattr(managed, "_commit_archive", original)
    assert managed.reconcile_full()["complete"]


def test_same_file_and_noncanonical_override_are_refused(history):
    assert (
        managed.reconcile_full(hot=history["full"])["reason"] == "noncanonical_override"
    )
    history["config"]["database"]["full_db_path"] = str(history["hot"])
    history["cfg"].write_text(json.dumps(history["config"]))
    with pytest.raises(ValueError, match="different files"):
        managed.forget_with_history("study", apply=True)
    with pytest.raises(ValueError, match="different files"):
        managed.reconcile_full()


@pytest.mark.parametrize("whole_session", [False, True])
def test_forget_preserves_the_requested_unit_across_archive_versions(
    history, whole_session
):
    with closing(records.connect(history["hot"])) as conn:
        store = ObservationStore(conn)
        first = store.append(
            kind="fixture.report",
            subject="same-subject",
            payload={"text": "ORCHID_OLD_REPORT"},
            producer="fixture",
            authority="reported",
            owner_session_id="study",
        )
        with closing(sqlite3.connect(history["full"])) as full:
            conn.backup(full)
        # The full copy has another version that is absent from canonical.
    with closing(records.connect(history["full"])) as full:
        second = ObservationStore(full).append(
            kind="fixture.report",
            subject="same-subject",
            payload={"text": "ORCHID_FULL_REPORT"},
            producer="fixture",
            authority="reported",
            owner_session_id="study",
        )
    with closing(records.connect(history["hot"])) as conn:
        if whole_session:
            forget_session(conn, "study", apply=True)
        else:
            conn.execute("DELETE FROM context_observations WHERE id=?", (first,))
            conn.commit()
    assert managed.reconcile_full()["complete"]
    for path in (history["hot"], history["full"]):
        with closing(records.connect(path)) as conn:
            assert not conn.execute(
                "SELECT 1 FROM context_observations WHERE id=?", (first,)
            ).fetchone()
            retired = conn.execute(
                "SELECT 1 FROM context_retirements WHERE kind='observation' AND object_id=?",
                (second,),
            ).fetchone()
            assert bool(retired) is whole_session
        assert b"ORCHID_OLD_REPORT" not in path.read_bytes()
    with closing(records.connect(history["full"])) as conn:
        remaining = conn.execute(
            "SELECT 1 FROM context_observations WHERE id=?", (second,)
        ).fetchone()
        assert bool(remaining) is not whole_session
    assert (b"ORCHID_FULL_REPORT" in history["full"].read_bytes()) is not whole_session


def test_control_overflow_rolls_back_archive_and_remains_retryable(
    history, monkeypatch
):
    with closing(records.connect(history["hot"])) as conn:
        forget_session(conn, "study", apply=True)
    monkeypatch.setattr(managed, "MAX_CONTROL_ROWS", 0)
    with pytest.raises(ValueError, match="row budget"):
        managed.reconcile_full()
    with closing(records.connect(history["full"])) as conn:
        assert conn.execute("SELECT 1 FROM sessions WHERE id='study'").fetchone()
        assert not conn.execute("SELECT 1 FROM context_tombstones").fetchone()
    monkeypatch.setattr(managed, "MAX_CONTROL_ROWS", 1_000_000)
    assert managed.reconcile_full()["complete"]


def test_new_control_after_archive_commit_is_pending_until_retry(history, monkeypatch):
    original = managed._commit_archive

    def commit(conn):
        original(conn)
        with closing(records.connect(history["hot"])) as other:
            other.execute("BEGIN IMMEDIATE")
            purge_session(other, "study")
            other.commit()

    monkeypatch.setattr(managed, "_commit_archive", commit)
    result = managed.reconcile_full()
    assert not result["complete"] and not result["controls_stable"]
    monkeypatch.setattr(managed, "_commit_archive", original)
    assert managed.reconcile_full()["complete"]


def test_pinned_archive_reader_prevents_physical_cleanup_ack(history):
    with closing(records.connect(history["hot"])) as conn:
        forget_session(conn, "study", apply=True)
    with closing(sqlite3.connect(history["full"])) as reader:
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM messages").fetchall()
        result = managed.reconcile_full()
        assert not result["complete"]
    assert managed.reconcile_full()["complete"]


def test_config_change_before_commit_rolls_back_both_cleanup_phases(
    history, monkeypatch
):
    with closing(records.connect(history["full"])) as conn:
        forget_session(conn, "study", apply=True)
    original = managed._converge

    def converge(authority, archive):
        result = original(authority, archive)
        history["config"]["database"]["full_db_path"] = str(
            history["full"].with_suffix(".other")
        )
        history["cfg"].write_text(json.dumps(history["config"]))
        return result

    monkeypatch.setattr(managed, "_converge", converge)
    with pytest.raises(ValueError, match="configuration changed"):
        managed.reconcile_full()
    with closing(records.connect(history["hot"])) as conn:
        assert conn.execute("SELECT 1 FROM sessions WHERE id='study'").fetchone()
        assert not conn.execute("SELECT 1 FROM context_tombstones").fetchone()


def test_incompatible_full_schema_is_not_mutated(history):
    with closing(sqlite3.connect(history["full"])) as conn:
        conn.execute("PRAGMA user_version=45")
        conn.commit()
    with pytest.raises(ValueError, match="current schema"):
        managed.reconcile_full()
    with closing(sqlite3.connect(history["full"])) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 45
        assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 2


@pytest.mark.parametrize("operation", ["sync", "refocus"])
def test_legacy_full_writer_cannot_drop_modern_lineage(history, operation):
    from agent_session_tools import tiering
    from agent_session_tools.replication.legacy import LegacySyncRefused

    before = {key: history[key].read_bytes() for key in ("hot", "full")}
    with pytest.raises(LegacySyncRefused):
        if operation == "sync":
            tiering.sync_to_full()
        else:
            tiering.refocus(["ORCHID"])
    assert before == {key: history[key].read_bytes() for key in ("hot", "full")}


@pytest.mark.parametrize("entry", ["legacy", "native", "mcp", "direct_search"])
def test_direct_full_override_cannot_bypass_canonical_controls(history, entry):
    from agent_session_tools.context.public import open_context
    from agent_session_tools.mcp_server import _get_connection
    from agent_session_tools.query_db import get_connection

    with pytest.raises(ValueError, match="canonical database"):
        if entry == "native":
            with open_context(history["full"]):
                pass
        elif entry == "legacy":
            get_connection(history["full"])
        elif entry == "mcp":
            _get_connection(history["full"])
        else:
            with closing(records.connect(history["full"])) as conn:
                query_logic.search(conn, "ORCHID", output_format="json")


def test_removed_archive_is_not_retained_by_config_cache(history, capsys):
    from agent_session_tools import query_db

    assert query_db._get_config()["database"]["full_db_path"]
    history["config"]["database"].pop("full_db_path")
    history["cfg"].write_text(json.dumps(history["config"]))
    with closing(records.connect(history["hot"])) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with eviction(conn):
            purge_session(conn, "study", permanent=False)
        conn.commit()
        query_logic.search(conn, "ORCHID", output_format="json")
    assert json.loads(capsys.readouterr().out)["rows"] == []


@pytest.mark.parametrize(
    "change", ["config", "canonical_retirement", "archive_retirement"]
)
def test_change_during_search_rendering_releases_no_body(
    history, capsys, monkeypatch, change
):
    from agent_session_tools.context.response import ScopeConflict

    with closing(records.connect(history["hot"])) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with eviction(conn):
            purge_session(conn, "study", permanent=False)
        conn.commit()
        original = query_logic._render_search

        def render(*args):
            output = original(*args)
            if change == "config":
                history["config"]["database"].pop("full_db_path")
                history["cfg"].write_text(json.dumps(history["config"]))
            else:
                path = (
                    history["hot"]
                    if change == "canonical_retirement"
                    else history["full"]
                )
                with closing(records.connect(path)) as writer:
                    writer.execute("BEGIN IMMEDIATE")
                    purge_session(writer, "study")
                    writer.commit()
            return output

        monkeypatch.setattr(query_logic, "_render_search", render)
        with pytest.raises(ScopeConflict):
            query_logic.search(conn, "ORCHID", output_format="json")
    assert capsys.readouterr().out == ""


def test_full_attachment_is_read_only(history):
    from agent_session_tools.query_db import attach_full_db, get_connection

    with closing(get_connection()) as conn:
        assert attach_full_db(conn)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM full_db.messages")


def test_literal_database_path_does_not_enable_uri_parameters(tmp_path):
    path = tmp_path / "file:literal?mode=memory"
    with closing(records.connect(path)) as conn:
        conn.execute("INSERT INTO sessions(id,source) VALUES ('persisted','codex')")
        conn.commit()
    assert path.is_file()
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT id FROM sessions").fetchone()[0] == "persisted"
