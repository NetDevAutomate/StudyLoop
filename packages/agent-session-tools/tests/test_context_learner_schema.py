"""Historical upgrade preserves ownership, old notes and board names atomically."""

import json
import sqlite3
from importlib.resources import files

import pytest

from agent_session_tools import migrations
from agent_session_tools.context import learner_schema, records


def test_schema37_rebuild_preserves_records_and_retries_after_interruption(
    tmp_path, monkeypatch
):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"memory": {"default_scope": "unclassified", "projects": {}}})
    )
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "unclassified")
    monkeypatch.setattr(migrations, "CURRENT_VERSION", 37)
    database = tmp_path / "migration.db"
    conn = sqlite3.connect(database)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(files("agent_session_tools").joinpath("schema.sql").read_text())
    with monkeypatch.context() as old:
        old.setattr(migrations, "CURRENT_VERSION", 36)
        migrations.migrate(conn)
    conn.execute(learner_schema.NOTES_DDL)
    conn.execute(
        "CREATE TABLE board_columns(key TEXT PRIMARY KEY,name TEXT NOT NULL,position INTEGER NOT NULL)"
    )
    conn.execute("INSERT INTO board_columns VALUES ('old','OLD_BOARD',0)")
    conn.execute("INSERT INTO study_notes(title,body) VALUES ('OLD_NOTE','OLD_BODY')")
    conn.execute(
        "INSERT INTO study_sessions(id,started_at,notes) VALUES ('old-study','2026-09-01','OLD_STUDY')"
    )
    owner = records.bind(conn, "study_sessions", "old-study")
    conn.commit()
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    before = {
        table: conn.execute('SELECT * FROM "' + table + '"').fetchall()
        for table in tables
    }
    original = learner_schema.install

    def interrupted(db):
        original(db)
        # Another connection sees only the committed schema, never half a rebuild.
        with sqlite3.connect(database, timeout=0.05) as other:
            assert other.execute("PRAGMA user_version").fetchone()[0] == 36
            assert other.execute(
                "SELECT 1 FROM sqlite_master WHERE type='trigger' "
                "AND name='context_record_owners_immutable'"
            ).fetchone()
            assert (
                other.execute("SELECT id FROM context_record_owners").fetchone()[0]
                == owner
            )
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("UPDATE context_record_owners SET scope='work'")
        raise RuntimeError("injected after schema37 installation")

    with monkeypatch.context() as failure:
        failure.setattr(learner_schema, "install", interrupted)
        with pytest.raises(RuntimeError, match="injected"):
            migrations.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 36
    assert {
        table: conn.execute('SELECT * FROM "' + table + '"').fetchall()
        for table in tables
    } == before
    migrations.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 37
    assert conn.execute("SELECT id FROM context_record_owners").fetchone()[0] == owner
    assert conn.execute("SELECT notes FROM study_sessions").fetchone()[0] == "OLD_STUDY"
    assert conn.execute("SELECT title,body FROM study_notes").fetchall() == [
        ("OLD_NOTE", "OLD_BODY")
    ]
    assert conn.execute(
        "SELECT scope,key,name,position FROM context_board_columns"
    ).fetchall() == [("unclassified", "old", "OLD_BOARD", 0)]
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
