"""``sync-full``/``prune`` render a mirror refusal; the spawned sync stays quiet.

``maybe_spawn_sync`` runs ``python -m agent_session_tools.maintenance sync-full
--quiet`` with both streams on DEVNULL after every export and study-session
start. On the fast path that process must exit 0 without writing to hot; on a
refusal it must exit non-zero with the reason in the log, never a silent loop
(remediation plan 6, lane T unit T7 / §6; council pass 7, A1).
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from contextlib import closing

import pytest
from typer.testing import CliRunner

from agent_session_tools import tiering
from agent_session_tools.export_sessions import init_db
from agent_session_tools.maintenance import app
from agent_session_tools.tiering import TieringRefused

runner = CliRunner()


def _refuse(*_args, **_kwargs):
    raise TieringRefused("unbound_full", "/x/full.db holds rows and no mirror binding")


@pytest.mark.parametrize("command", [["sync-full"], ["prune", "--days", "30"]])
def test_handlers_print_the_reason_and_the_fix(monkeypatch, command):
    monkeypatch.setattr(tiering, "acquire_sync_lock", lambda: True)
    monkeypatch.setattr(tiering, "release_sync_lock", lambda: None)
    monkeypatch.setattr(tiering, "sync_to_full", _refuse)
    monkeypatch.setattr(tiering, "prune_hot", _refuse)

    result = runner.invoke(app, command)

    assert result.exit_code == 1, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "❌" in result.output and "unbound_full" in result.output
    assert "Fix: " + TieringRefused("unbound_full").fix in result.output
    assert "Traceback" not in result.output


@pytest.fixture
def spawned(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    hot = config_dir / "sessions.db"
    full_dir = tmp_path / "external" / "DB"
    full_dir.mkdir(parents=True)
    full = full_dir / "sessions_full.db"
    log = tmp_path / "session.log"
    cfg = config_dir / "config.yaml"
    cfg.write_text(
        f"database:\n  path: {hot}\n  backup_dir: {full_dir}\n  full_db_path: {full}\n"
        "  snapshot_interval_days: 0\n"
        f"logging:\n  path: {log}\n  level: INFO\n"
    )
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(cfg))
    monkeypatch.setenv("STUDYLOOP_DB", str(hot))
    conn = init_db(str(hot))
    conn.execute(
        "INSERT INTO sessions(id,source,updated_at) VALUES ('s','codex','2020-01-01')"
    )
    conn.execute(
        "INSERT INTO messages(id,session_id,role,content) VALUES ('m','s','user','hi')"
    )
    conn.commit()
    conn.close()
    return {"hot": hot, "full": full, "log": log}


def _spawn() -> subprocess.CompletedProcess:
    # The exact argv maybe_spawn_sync uses (tiering.maybe_spawn_sync).
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_session_tools.maintenance",
            "sync-full",
            "--quiet",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_spawned_sync_full_exits_zero_on_the_fast_path(spawned):
    first = _spawn()
    assert first.returncode == 0, first.stderr
    reader = sqlite3.connect(spawned["hot"])
    version = reader.execute("PRAGMA data_version").fetchone()[0]

    again = _spawn()

    assert again.returncode == 0, again.stderr
    assert again.stdout == ""
    assert reader.execute("PRAGMA data_version").fetchone()[0] == version, (
        "the fast path committed nothing to hot"
    )
    reader.close()
    assert "nothing changed" in spawned["log"].read_text()


def test_spawned_sync_full_refusal_exits_nonzero_and_logs_the_reason(spawned):
    conn = init_db(str(spawned["full"]))
    conn.execute("INSERT INTO sessions(id,source) VALUES ('other-history','codex')")
    conn.commit()
    conn.close()

    result = _spawn()

    assert result.returncode == 1
    assert result.stdout == ""
    logged = spawned["log"].read_text()
    assert "sync-full skipped" in logged and "unbound_full" in logged
    with closing(sqlite3.connect(spawned["full"])) as full:
        assert full.execute("SELECT id FROM sessions").fetchall() == [
            ("other-history",)
        ]
