"""Actual policy command preview/apply over an older disposable database."""

import json

from typer.testing import CliRunner

from agent_session_tools.context.cli import app
from agent_session_tools.context.scope import ScopePolicy, visibility_sql
from agent_session_tools.migrations import CURRENT_VERSION, migrate


def test_preview_keeps_old_schema_and_apply_upgrades_atomically(
    temp_db, tmp_path, monkeypatch
):
    import agent_session_tools.migrations as migrations

    conn, path = temp_db
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "CURRENT_VERSION", 31)
        migrate(conn)
    conn.execute(
        "INSERT INTO sessions(id,source,project_path) VALUES ('session','fixture','/fixtures/project')"
    )
    conn.execute(
        "INSERT INTO messages(id,session_id,role,content) VALUES ('message','session','user','BODY_MUST_NOT_APPEAR')"
    )
    conn.commit()
    settings = {
        "database": {"path": str(path)},
        "memory": {
            "default_scope": "personal",
            "projects": {
                "project": {"scope": "personal", "roots": ["/fixtures/project"]}
            },
        },
    }
    config = tmp_path / "scope-config.yaml"
    config.write_text(json.dumps(settings))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    runner = CliRunner()
    preview = runner.invoke(
        app, ["policy", "plan", "--db", str(path), "--actor", "test-owner"]
    )
    assert preview.exit_code == 0, repr(preview.exception)
    assert json.loads(preview.stdout)["dry_run"]
    assert "BODY_MUST_NOT_APPEAR" not in preview.stdout
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 31
    assert not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='context_scope_audit'"
    ).fetchone()
    result = runner.invoke(
        app, ["policy", "apply", "--db", str(path), "--actor", "test-owner"]
    )
    assert result.exit_code == 0, repr(result.exception)
    assert not json.loads(result.stdout)["dry_run"]
    assert conn.execute("PRAGMA user_version").fetchone()[0] == CURRENT_VERSION
    p = ScopePolicy.from_config(settings)
    clause, params = visibility_sql(conn, "s.id", policy=p)
    assert (
        conn.execute("SELECT s.id FROM sessions s WHERE " + clause, params).fetchone()[
            0
        ]
        == "session"
    )
    assert (
        conn.execute("SELECT DISTINCT actor FROM context_scope_audit").fetchone()[0]
        == "test-owner"
    )
    repeated = runner.invoke(
        app, ["policy", "apply", "--db", str(path), "--actor", "test-owner"]
    )
    assert repeated.exit_code == 0
    assert json.loads(repeated.stdout)["changes"] == []
