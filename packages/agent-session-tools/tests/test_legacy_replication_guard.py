"""Protected context must never fall through to old SQL or whole-file transport."""

import subprocess

import pytest
from typer.testing import CliRunner

from agent_session_tools import sync
from agent_session_tools.replication import legacy


def protect(conn):
    conn.execute(
        "INSERT INTO context_projects VALUES ('p','personal','fixture','fixture')"
    )
    conn.commit()


def no_process(*args, **kwargs):
    pytest.fail(
        "A legacy subprocess ran after the protection guard should have refused"
    )


@pytest.mark.parametrize("operation", ["push", "pull", "sync"])
def test_actual_cli_refuses_protected_database_before_remote_resolution(
    migrated_db, monkeypatch, operation
):
    conn, path = migrated_db
    protect(conn)
    monkeypatch.setattr(sync, "_resolve_remote", no_process)
    result = CliRunner().invoke(
        sync.app, [operation, "unknown-peer", "--db", str(path)]
    )
    assert result.exit_code != 0
    assert isinstance(result.exception, RuntimeError)
    assert "No legacy fallback" in str(result.exception)


@pytest.mark.parametrize("method", ["dump", "import", "seed"])
def test_low_level_legacy_paths_refuse_modern_context(migrated_db, monkeypatch, method):
    conn, path = migrated_db
    protect(conn)
    monkeypatch.setattr(sync.subprocess, "run", no_process)
    with pytest.raises(RuntimeError, match="Legacy SQL sync"):
        if method == "dump":
            sync._dump_delta_sql(path, {"fixture"})
        elif method == "import":
            sync._stream_sql_to_target("SELECT 1;", path)
        else:
            sync._seed_remote_db("host", "/fictional.db", path)


def test_whole_file_seed_refuses_even_an_empty_modern_schema(migrated_db, monkeypatch):
    _, path = migrated_db
    legacy.check_path(path)  # Empty modern tables are not populated context.
    monkeypatch.setattr(sync.subprocess, "run", no_process)
    with pytest.raises(RuntimeError, match="Legacy SQL sync"):
        sync._seed_remote_db("host", "/fictional.db", path)


@pytest.mark.parametrize(
    "memory",
    [
        {"default_scope": "personal"},
        {"default_scope": "work"},
        {"projects": {"p": {"scope": "personal", "roots": []}}},
        {"sync": {"node_id": "a", "peers": {"b": {"allowed_scopes": ["personal"]}}}},
    ],
)
def test_explicit_scope_configuration_refuses_legacy_before_db_read(
    memory, tmp_path, monkeypatch
):
    monkeypatch.setattr(legacy, "load_config", lambda: {"memory": memory})
    with pytest.raises(RuntimeError, match="Legacy SQL sync"):
        legacy.check_path(tmp_path / "not-created.db")
    assert not (tmp_path / "not-created.db").exists()


def test_retirement_without_remaining_bodies_still_refuses_legacy(migrated_db):
    conn, path = migrated_db
    conn.execute(
        "INSERT INTO context_tombstones VALUES ('forgotten','deletion','fixture')"
    )
    conn.commit()
    with pytest.raises(RuntimeError, match="Legacy SQL sync"):
        legacy.check_path(path)


def test_receiver_rechecks_protection_inside_sql_transaction(migrated_db, monkeypatch):
    conn, path = migrated_db
    real_run = subprocess.run

    def change_before_import(*args, **kwargs):
        protect(conn)
        return real_run(*args, **kwargs)

    monkeypatch.setattr(sync.subprocess, "run", change_before_import)
    assert (
        sync._stream_sql_to_target(
            "INSERT INTO sessions(id,source) VALUES ('must-not-arrive','fixture');",
            path,
        )
        is False
    )
    assert not conn.execute(
        "SELECT 1 FROM sessions WHERE id='must-not-arrive'"
    ).fetchone()
    assert not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='sync_row_archive'"
    ).fetchone()


def test_remote_guard_uses_only_metadata_before_refusing(migrated_db, monkeypatch):
    conn, _ = migrated_db
    protect(conn)
    queries = []

    def remote(_host, _path, query):
        queries.append(query)
        return "\n".join(str(r[0]) for r in conn.execute(query))

    monkeypatch.setattr(sync, "_remote_sql", remote)
    with pytest.raises(RuntimeError, match="Legacy SQL sync"):
        sync._remote_dump_queries("fictional", "fictional.db", {"fixture"})
    assert len(queries) == 2
    assert "sqlite_master" in queries[0] and queries[1].startswith(
        "SELECT CASE WHEN EXISTS"
    )


def test_remote_source_rechecks_protection_in_dump_transaction(
    migrated_db, monkeypatch
):
    conn, path = migrated_db
    conn.execute("INSERT INTO sessions(id,source) VALUES ('fixture','fixture')")
    conn.execute(
        "INSERT INTO messages(id,session_id,role,content) VALUES ('m','fixture','user','EXCLUDED_BODY_MARKER')"
    )
    conn.commit()

    def remote(_host, _path, query):
        return "\n".join(str(r[0]) for r in conn.execute(query))

    monkeypatch.setattr(sync, "_remote_sql", remote)
    commands = sync._remote_dump_queries("fictional", "fictional.db", {"fixture"})
    protect(conn)
    result = subprocess.run(
        ["sqlite3", "-bail", str(path)],
        input="BEGIN;\n" + "\n".join(commands) + "\nCOMMIT;",
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode != 0 and result.stdout == ""
    assert "EXCLUDED_BODY_MARKER" not in result.stdout + result.stderr
