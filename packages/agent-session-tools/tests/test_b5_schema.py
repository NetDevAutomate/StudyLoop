"""B5 migration contracts for sync durability and erasure hardening."""

from __future__ import annotations

import sqlite3

from agent_session_tools.export_sessions import init_db
from agent_session_tools.migrations import CURRENT_VERSION


def test_v50_installs_sync_and_capture_durability_tables(tmp_path) -> None:
    path = tmp_path / "fresh.db"
    conn = init_db(str(path))
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 50
    assert CURRENT_VERSION == 50
    assert {
        "sync_conflicts",
        "sync_machine_clocks",
        "sync_session_revisions",
        "session_export_runs",
        "context_concept_tombstones",
    } <= tables
    conn.close()


def test_v50_seeds_existing_sessions_with_stable_replica_versions(tmp_path) -> None:
    path = tmp_path / "upgrade.db"
    conn = sqlite3.connect(path)
    from pathlib import Path

    from agent_session_tools.migrations import MIGRATIONS, migrate, set_user_version

    schema = Path(__file__).resolve().parents[1] / "src/agent_session_tools/schema.sql"
    conn.executescript(schema.read_text(encoding="utf-8"))
    for version in range(1, 50):
        MIGRATIONS[version][1](conn)
        set_user_version(conn, version)
    conn.execute("INSERT INTO sessions(id,source) VALUES('b','test'),('a','test')")
    conn.commit()

    migrate(conn)

    instance = conn.execute(
        "SELECT instance FROM context_access_state WHERE id=1"
    ).fetchone()[0]
    assert conn.execute(
        "SELECT session_id,machine_id,seq FROM sync_session_revisions ORDER BY session_id"
    ).fetchall() == [("a", instance, 1), ("b", instance, 2)]
    assert conn.execute(
        "SELECT seq FROM sync_machine_clocks WHERE machine_id=?", (instance,)
    ).fetchone() == (2,)
    conn.close()


def test_concept_schema_pin_tracks_the_v50_host_migration() -> None:
    from agent_session_tools.context.concept_schema import UPSTREAM_SCHEMA_VERSION

    assert UPSTREAM_SCHEMA_VERSION == CURRENT_VERSION == 50
