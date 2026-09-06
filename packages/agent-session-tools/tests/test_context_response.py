"""Read completion observes config, durable revocation, threads and independent tasks."""

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from agent_session_tools.context.records import connect
from agent_session_tools.context.response import (
    ScopeConflict,
    consistent_read,
    read_boundary,
)
from agent_session_tools.context.scope import (
    ScopePolicy,
    active_policy,
    apply_policy,
    visibility_sql,
)
from agent_session_tools.context.store import ContextStore


@pytest.fixture
def response_db(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    settings = {
        "memory": {
            "default_scope": "personal",
            "projects": {
                "p": {"scope": "personal", "roots": [str(tmp_path / "personal")]},
                "w": {"scope": "work", "roots": [str(tmp_path / "work")]},
            },
        }
    }
    config.write_text(json.dumps(settings))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "personal")
    path = tmp_path / "sessions.db"
    conn = connect(path)
    for sid, project in [("personal", "personal"), ("work", "work")]:
        conn.execute(
            "INSERT INTO sessions(id,source,project_path,created_at,updated_at) VALUES (?,?,?,?,?)",
            (sid, "codex", str(tmp_path / project), "2026-09-06", "2026-09-06"),
        )
    conn.commit()
    apply_policy(
        conn, ScopePolicy.from_config(settings), actor="fixture", dry_run=False
    )
    conn.close()
    return path, config, settings


def read_ids(path):
    conn = connect(path)
    try:
        clause, values = visibility_sql(conn)
        return [
            r[0]
            for r in conn.execute("SELECT s.id FROM sessions s WHERE " + clause, values)
        ]
    finally:
        conn.close()


@pytest.mark.parametrize("mutation", ["reassign", "away_and_back", "forget", "project"])
def test_read_response_rejects_committed_access_changes(response_db, mutation):
    path, _, _ = response_db
    with pytest.raises(ScopeConflict):
        with read_boundary():
            assert read_ids(path) == ["personal"]
            conn = connect(path)
            try:
                if mutation == "forget":
                    conn.execute(
                        "INSERT INTO context_tombstones VALUES ('personal','test','2026-09-06')"
                    )
                    conn.commit()
                elif mutation == "project":
                    conn.execute(
                        "UPDATE context_projects SET scope='work' WHERE id='p'"
                    )
                    conn.commit()
                else:
                    ContextStore(conn).assign_session("personal", "w")
                    if mutation == "away_and_back":
                        ContextStore(conn).assign_session("personal", "p")
            finally:
                conn.close()


def test_read_response_allows_ordinary_data_write_and_rolled_back_revocation(
    response_db,
):
    path, _, _ = response_db
    with read_boundary():
        assert read_ids(path) == ["personal"]
        conn = connect(path)
        conn.execute("UPDATE sessions SET updated_at='2026-09-07' WHERE id='personal'")
        conn.commit()
        conn.execute("UPDATE context_projects SET scope='work' WHERE id='p'")
        conn.rollback()
        conn.close()
        assert read_ids(path) == ["personal"]


def test_swallowed_scope_conflict_stays_failed_after_scope_restored(
    response_db, monkeypatch
):
    path, _, _ = response_db
    with pytest.raises(ScopeConflict):
        with read_boundary():
            read_ids(path)
            monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "work")
            with pytest.raises(ScopeConflict):
                read_ids(path)
            monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "personal")


def test_config_change_after_final_query_is_checked_before_return(response_db):
    path, config, settings = response_db
    with pytest.raises(ScopeConflict):
        with read_boundary():
            read_ids(path)
            settings["memory"]["projects"]["p"]["scope"] = "work"
            config.write_text(json.dumps(settings))


def test_worker_thread_contribution_reaches_parent_frame(response_db, monkeypatch):
    path, _, _ = response_db

    async def work():
        with pytest.raises(ScopeConflict):
            with read_boundary():
                assert await asyncio.to_thread(read_ids, path) == ["personal"]
                monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "work")

    asyncio.run(work())


def test_independent_async_requests_do_not_share_scope_frames(response_db):
    path, _, _ = response_db

    @consistent_read
    async def request(scope):
        policy = active_policy()
        resolved = policy.request_scope(override=scope)
        conn = connect(path)
        try:
            clause, values = visibility_sql(conn, policy=policy, scope=resolved)
            await asyncio.sleep(0)
            return [
                r[0]
                for r in conn.execute(
                    "SELECT s.id FROM sessions s WHERE " + clause, values
                )
            ]
        finally:
            conn.close()

    # Explicit override here is an internal query test, not a remote tool argument.
    # A different override from the process boundary must be rejected at release.
    async def work():
        results = await asyncio.gather(
            request("personal"), request("work"), return_exceptions=True
        )
        assert results[0] == ["personal"]
        assert isinstance(results[1], ScopeConflict)

    asyncio.run(work())


def test_public_read_without_scope_use_does_not_require_configuration(
    tmp_path, monkeypatch
):
    config = tmp_path / "empty.json"
    config.write_text("{}")
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    monkeypatch.delenv("SESSION_CONTEXT_SCOPE", raising=False)
    with read_boundary():
        assert 1 + 1 == 2


def test_replaced_database_is_not_released(response_db, tmp_path):
    path, _, _ = response_db
    replacement = tmp_path / "replacement.db"
    with pytest.raises(ScopeConflict):
        with read_boundary():
            read_ids(path)
            with (
                sqlite3.connect(path) as source,
                sqlite3.connect(replacement) as target,
            ):
                source.backup(target)
            Path(replacement).replace(path)


def test_native_write_rechecks_resolved_scope_before_commit(response_db, monkeypatch):
    from agent_session_tools.context.public import open_context
    from agent_session_tools.context.scope import ScopeError

    path, _, _ = response_db
    with pytest.raises(ScopeError, match="changed"):
        with open_context(path, write=True) as context:
            context.conn.execute("UPDATE sessions SET updated_at='SHOULD_ROLL_BACK'")
            monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "work")
    with sqlite3.connect(path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE updated_at='SHOULD_ROLL_BACK'"
            ).fetchone()[0]
            == 0
        )


def test_access_generation_migration_rolls_back_and_retries(tmp_path, monkeypatch):
    from agent_session_tools import migrations
    from agent_session_tools.context import response_schema

    with monkeypatch.context() as old:
        old.setattr(migrations, "CURRENT_VERSION", 37)
        conn = connect(tmp_path / "old.db")
    original = response_schema.install

    def fail_after_install(database):
        original(database)
        raise RuntimeError("injected migration failure")

    with monkeypatch.context() as failure:
        failure.setattr(response_schema, "install", fail_after_install)
        with pytest.raises(RuntimeError, match="injected"):
            migrations.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 37
    assert not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name LIKE 'access_generation_%' "
        "OR name='context_access_state'"
    ).fetchall()
    migrations.migrate(conn)
    assert (
        conn.execute("PRAGMA user_version").fetchone()[0] == migrations.CURRENT_VERSION
    )
    assert conn.execute("SELECT revision FROM context_access_state").fetchone()[0] == 0
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_legacy_database_requires_generation_migration_before_response(
    tmp_path, monkeypatch
):
    from agent_session_tools import migrations
    from agent_session_tools.context.scope import ScopeError

    config = tmp_path / "legacy-config.json"
    settings = {"memory": {"default_scope": "unclassified", "projects": {}}}
    config.write_text(json.dumps(settings))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "unclassified")
    with monkeypatch.context() as old:
        old.setattr(migrations, "CURRENT_VERSION", 37)
        conn = connect(tmp_path / "legacy.db")
    apply_policy(
        conn, ScopePolicy.from_config(settings), actor="fixture", dry_run=False
    )
    with pytest.raises(ScopeError, match="access-generation migration"):
        with read_boundary():
            visibility_sql(conn)
    conn.close()


def test_cancelled_read_closes_monitors_and_rejects_delayed_reuse(response_db):
    path, _, _ = response_db

    async def run():
        ready = asyncio.Event()
        frames = []
        connections = []

        async def pending():
            with read_boundary() as frame:
                read_ids(path)
                frames.append(frame)
                connections.append(next(iter(frame.monitors.values()))[0])
                ready.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(pending())
        await ready.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert frames[0].closed and not frames[0].monitors
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connections[0].execute("SELECT 1")
        with pytest.raises(ScopeConflict):
            frames[0].observe_policy(active_policy())
        with read_boundary():
            assert read_ids(path) == ["personal"]

    asyncio.run(run())


def test_sixteen_threaded_requests_observe_intervening_revocation(response_db):
    path, _, _ = response_db

    async def batch(change):
        ready = asyncio.Event()
        release = asyncio.Event()
        arrivals = []

        @consistent_read
        async def request():
            result = await asyncio.to_thread(read_ids, path)
            arrivals.append(True)
            if len(arrivals) == 16:
                ready.set()
            await release.wait()
            return result

        tasks = [asyncio.create_task(request()) for _ in range(16)]
        await asyncio.wait_for(ready.wait(), timeout=10)
        if change:
            conn = connect(path)
            ContextStore(conn).assign_session("personal", "w")
            ContextStore(conn).assign_session("personal", "p")
            conn.close()
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        if change:
            assert all(isinstance(result, ScopeConflict) for result in results)
        else:
            assert results == [["personal"]] * 16

    async def run():
        await batch(change=True)
        await batch(change=False)

    asyncio.run(run())
