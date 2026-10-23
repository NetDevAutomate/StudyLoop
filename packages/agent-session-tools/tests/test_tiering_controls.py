"""Permanent controls are reconciled for the tier mirror without compacting.

``reconcile_full`` gates ``complete`` on ``lifecycle.compact`` of both files
(``wal_checkpoint(TRUNCATE)`` + ``VACUUM``), which reports ``database_in_use``
whenever another connection has the file open. ``maybe_spawn_sync`` runs
``sync-full`` after every export, so gating the mirror on that would VACUUM hot
after every export and refuse whenever the web app or MCP server is open
(council pass 7, A1). ``reconcile_full_controls`` is the convergence and the
two canonical-first commits only, and ``context_annotation_retirements`` --
permanent, but outside ``CONTROL_TABLES`` -- is reconciled with the rest
(council pass 7, C3; remediation plan 6, lane T unit T3).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from agent_session_tools import tiering_registry
from agent_session_tools.context import managed_history as managed
from agent_session_tools.export_sessions import init_db


@pytest.fixture
def pair(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    hot = config_dir / "sessions.db"
    full_dir = tmp_path / "external"
    full_dir.mkdir()
    full = full_dir / "sessions_full.db"
    cfg = config_dir / "config.yaml"
    cfg.write_text(
        f"database:\n  path: {hot}\n  backup_dir: {full_dir}\n  full_db_path: {full}\n"
    )
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(cfg))
    conn = init_db(str(hot))
    conn.execute("INSERT INTO sessions(id,source) VALUES ('s','codex')")
    conn.execute(
        "INSERT INTO session_notes(session_id,notes) VALUES ('s','RETIRED_NOTE_BODY')"
    )
    conn.commit()
    with closing(sqlite3.connect(full)) as archive:
        conn.backup(archive)
    conn.close()
    return {"hot": hot, "full": full}


def _count(path, sql):
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute(sql).fetchone()[0]


def test_annotation_retirements_are_a_managed_control():
    assert "context_annotation_retirements" in managed.CONTROL_TABLES
    assert managed.CONTROL_TABLES == tiering_registry.CONTROL_TABLES


@pytest.mark.parametrize("entry", ["reconcile_full", "reconcile_full_controls"])
def test_annotation_retirement_reaches_the_full_tier(pair, entry):
    with closing(sqlite3.connect(pair["hot"])) as hot:
        hot.execute("INSERT INTO context_annotation_retirements VALUES ('s','note')")
        hot.commit()
        assert not hot.execute("SELECT 1 FROM session_notes").fetchone()
    assert _count(pair["full"], "SELECT count(*) FROM session_notes") == 1

    result = getattr(managed, entry)()

    assert result["controls_stable"] is True
    assert (
        _count(pair["full"], "SELECT count(*) FROM context_annotation_retirements") == 1
    )
    assert _count(pair["full"], "SELECT count(*) FROM session_notes") == 0


def test_controls_reconcile_without_compacting(pair, monkeypatch):
    def no_compact(_path):
        raise AssertionError("reconcile_full_controls must not compact (VACUUM)")

    monkeypatch.setattr(managed, "compact", no_compact)
    with closing(sqlite3.connect(pair["hot"])) as hot:
        hot.execute(
            "INSERT INTO context_tombstones VALUES ('gone','deletion-1','2026-01-01')"
        )
        hot.commit()

    result = managed.reconcile_full_controls()

    assert result["complete"] is True and result["controls_stable"] is True
    assert result["physical_cleanup"] == "not_performed"
    assert _count(pair["full"], "SELECT count(*) FROM context_tombstones") == 1
    assert _count(pair["full"], "SELECT count(*) FROM context_retirements") == 1


def test_controls_reconcile_while_a_reader_holds_hot_open(pair):
    """The web app / MCP server keep sessions.db open; compact would refuse."""
    reader = sqlite3.connect(pair["hot"])
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM sessions").fetchone()
    try:
        assert managed.reconcile_full()["complete"] is False
        result = managed.reconcile_full_controls()
    finally:
        reader.rollback()
        reader.close()
    assert result["complete"] is True and result["controls_stable"] is True


def test_controls_report_the_managed_reasons(pair, tmp_path):
    assert (
        managed.reconcile_full_controls(hot=pair["full"])["reason"]
        == "noncanonical_override"
    )
    pair["full"].unlink()
    unavailable = managed.reconcile_full_controls()
    assert unavailable["complete"] is False
    assert unavailable["controls_stable"] is False
    assert unavailable["reason"] == "full_store_unavailable"


def test_reconcile_full_keeps_its_report_shape(pair):
    result = managed.reconcile_full()
    assert result["complete"] is True
    for key in (
        "canonical_cleanup",
        "full_cleanup",
        "controls_stable",
        "closure_rounds",
    ):
        assert key in result
