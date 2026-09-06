"""Schema39 upgrade preserves legacy content and rolls back all DDL on failure."""

import sqlite3
from importlib.resources import files

import pytest

from agent_session_tools import migrations


def test_schema39_upgrade_failure_retry_and_existing_retirement(tmp_path, monkeypatch):
    conn = sqlite3.connect(tmp_path / "upgrade.db")
    conn.executescript(files("agent_session_tools").joinpath("schema.sql").read_text())
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "CURRENT_VERSION", 38)
        migrations.migrate(conn)
    conn.execute(
        "INSERT INTO sessions(id,source) VALUES ('retained','fixture'),('retired','fixture')"
    )
    conn.execute(
        "INSERT INTO session_notes(session_id,notes) VALUES ('retained','keep'),('retired','purge')"
    )
    conn.execute(
        "INSERT INTO session_tags(session_id,tag) VALUES ('retained','keep'),('retired','purge')"
    )
    conn.execute(
        "INSERT INTO context_tombstones VALUES ('retired','forget','2026-09-06')"
    )
    conn.commit()
    description, install = migrations.MIGRATIONS[39]

    def fail_after_ddl(c):
        install(c)
        raise RuntimeError("injected after schema39 DDL and purge")

    with monkeypatch.context() as patch:
        patch.setitem(migrations.MIGRATIONS, 39, (description, fail_after_ddl))
        with pytest.raises(RuntimeError, match="injected"):
            migrations.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 38
    assert not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='context_observation_session_owners'"
    ).fetchone()
    assert conn.execute("SELECT count(*) FROM session_notes").fetchone()[0] == 2
    assert len(migrations.migrate(conn)) == migrations.CURRENT_VERSION - 38
    assert conn.execute("SELECT session_id,notes FROM session_notes").fetchall() == [
        ("retained", "keep")
    ]
    assert conn.execute("SELECT session_id,tag FROM session_tags").fetchall() == [
        ("retained", "keep")
    ]
    assert migrations.migrate(conn) == []
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.close()
