"""Scope rejection through existing CLI, MCP, semantic and metadata interfaces."""

import json
import sqlite3

import pytest
from typer.testing import CliRunner

from agent_session_tools.context.scope import ScopePolicy, apply_policy


@pytest.fixture
def scoped_db(migrated_db, tmp_path, monkeypatch):
    conn, path = migrated_db
    settings = {
        "database": {"path": str(path)},
        "memory": {
            "default_scope": "personal",
            "projects": {
                "personal": {"scope": "personal", "roots": ["/scope/personal"]},
                "work": {"scope": "work", "roots": ["/scope/work"]},
            },
        },
    }
    config = tmp_path / "scopes.yaml"
    config.write_text(json.dumps(settings))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    for sid, root, marker in [
        ("shared-personal", "/scope/personal", "PERSONAL_VISIBLE"),
        ("shared-work", "/scope/work", "WORK_HIDDEN"),
        ("unknown", "/scope/unknown", "UNCLASSIFIED_HIDDEN"),
    ]:
        conn.execute(
            "INSERT INTO sessions(id,source,project_path,created_at,updated_at) VALUES (?,?,?,?,?)",
            (sid, "kiro_cli", root, "2026-09-05", "2026-09-05"),
        )
        conn.execute(
            "INSERT INTO messages(id,session_id,role,content,seq) VALUES (?,?,?,?,?)",
            (sid + "-msg", sid, "assistant", "common " + marker, 1),
        )
        conn.execute(
            "INSERT INTO file_references(session_id,message_id,file_path,tool_name,timestamp) VALUES (?,?,?,?,?)",
            (sid, sid + "-msg", marker + ".py", "Read", "2026-09-05"),
        )
        conn.execute(
            "INSERT INTO session_notes(session_id,notes) VALUES (?,?)",
            (sid, marker + " note"),
        )
        conn.execute(
            "INSERT INTO session_tags(session_id,tag) VALUES (?,?)",
            (sid, marker + " tag"),
        )
    conn.commit()
    apply_policy(
        conn, ScopePolicy.from_config(settings), actor="fixture", dry_run=False
    )
    monkeypatch.setattr("agent_session_tools.mcp_server._get_db_path", lambda: path)
    return conn, path, config, settings


def tools():
    import asyncio

    from agent_session_tools.mcp_server import mcp

    # This SDK annotates the metadata base type although its internal registry
    # returns callable Tool instances. Exercise the registered runtime function.
    return {tool.name: getattr(tool, "fn") for tool in asyncio.run(mcp._list_tools())}


def assert_private_absent(output):
    value = json.dumps(output) if not isinstance(output, str) else output
    assert "WORK_HIDDEN" not in value
    assert "UNCLASSIFIED_HIDDEN" not in value
    assert "/scope/work" not in value
    assert "/scope/unknown" not in value


def test_all_mcp_reads_and_clean_scan_obey_scope(scoped_db):
    mcp = tools()
    search = mcp["session_search"](query="common")["rows"]
    assert len(search) == 1 and search[0]["session_id"] == "shared-personal"
    assert mcp["session_search"](query="common", project="/scope/work")["rows"] == []
    assert len(mcp["session_list"]()) == 1
    assert (
        mcp["session_show"](session_id="shared")["session"]["id"] == "shared-personal"
    )
    for name in ("session_show", "session_context"):
        assert_private_absent(mcp[name](session_id="shared-work"))
        assert_private_absent(mcp[name](session_id="unknown"))
        assert "PERSONAL_VISIBLE" in json.dumps(mcp[name](session_id="shared-personal"))
    stats = mcp["session_stats"]()
    assert stats["total_sessions"] == stats["total_messages"] == 1
    assert mcp["session_clean"](dry_run=True)["messages_scanned"] == 1
    hotspots = mcp["session_hotspots"](days=0)
    assert len(hotspots) == 1 and hotspots[0]["file_path"] == "PERSONAL_VISIBLE.py"
    assert_private_absent([search, stats, hotspots])


@pytest.mark.parametrize(
    "command",
    [
        ["search", "common", "--output-format", "json"],
        ["list", "--output-format", "json"],
        ["show", "shared-work"],
        ["context", "shared-work"],
        ["continue", "shared-work"],
        ["stats-cmd"],
        ["note", "shared-work"],
        ["tag", "shared-work"],
    ],
)
def test_cli_routes_do_not_return_hidden_content(scoped_db, command):
    from agent_session_tools.query_sessions import app

    _, path, _, _ = scoped_db
    result = CliRunner().invoke(app, [*command, "--db", str(path)])
    assert_private_absent(result.output)
    assert result.exit_code == (1 if command[0] in ("note", "tag") else 0), repr(
        result.exception
    )
    assert "No such command" not in result.output


def test_retrieval_service_and_file_hotspots_obey_scope(scoped_db):
    from agent_session_tools.file_hotspots import get_hotspots
    from agent_session_tools.retrieval import search

    conn, *_ = scoped_db
    result = search(conn, "common")
    assert len(result.hits) == 1 and result.hits[0].session_id == "shared-personal"
    assert search(conn, "common", project="/scope/work").hits == ()
    assert_private_absent(result.to_payload())
    assert_private_absent(get_hotspots(conn))


def test_next_mcp_request_observes_reclassification(scoped_db):
    conn, _, config, settings = scoped_db
    mcp = tools()
    assert len(mcp["session_search"](query="common")["rows"]) == 1
    settings["memory"]["projects"]["personal"]["scope"] = "work"
    config.write_text(json.dumps(settings))
    from agent_session_tools.context.scope import ScopeError

    with pytest.raises(ScopeError, match="changed"):
        mcp["session_search"](query="common")
    apply_policy(
        conn, ScopePolicy.from_config(settings), actor="fixture", dry_run=False
    )
    assert mcp["session_search"](query="common")["rows"] == []


def test_explicit_unknown_scope_can_inspect_only_unclassified(scoped_db, monkeypatch):
    monkeypatch.setenv("SESSION_CONTEXT_SCOPE", "unclassified")
    mcp = tools()
    result = mcp["session_search"](query="common")["rows"]
    assert len(result) == 1 and result[0]["session_id"] == "unknown"
    assert mcp["session_show"](session_id="shared-work").get("error")


def test_federated_read_checks_full_database_policy(
    scoped_db, tmp_path, capsys, monkeypatch
):
    from agent_session_tools.query_logic import search
    from agent_session_tools.context.scope import ScopeError

    conn, _, config, settings = scoped_db
    full = tmp_path / "full.db"
    other = sqlite3.connect(full)
    try:
        conn.backup(other)
        for sid, root, marker in [
            ("historical-personal", "/scope/personal", "HISTORY_VISIBLE"),
            ("historical-work", "/scope/work", "WORK_HIDDEN"),
        ]:
            other.execute(
                "INSERT INTO sessions(id,source,project_path) VALUES (?,?,?)",
                (sid, "claude_code", root),
            )
            other.execute(
                "INSERT INTO messages(id,session_id,role,content) VALUES (?,?,?,?)",
                (sid + "-m", sid, "assistant", "common " + marker),
            )
        other.commit()
        other.execute("PRAGMA foreign_keys=ON")
        apply_policy(
            other, ScopePolicy.from_config(settings), actor="fixture", dry_run=False
        )
        settings["database"]["full_db_path"] = str(full)
        config.write_text(json.dumps(settings))
        monkeypatch.setattr("agent_session_tools.query_db._config", None)
        search(conn, "common", output_format="json")
        output = capsys.readouterr().out
        result = json.loads(output)
        assert {r["session_id"] for r in result["rows"]} == {
            "shared-personal",
            "historical-personal",
        }
        assert_private_absent(output)
        conn.rollback()  # End this request's read snapshot before starting another.
        conn.execute("DETACH DATABASE full_db")
        other.execute("UPDATE context_policy_state SET digest='stale'")
        other.commit()
        with pytest.raises(ScopeError, match="changed"):
            search(conn, "common", output_format="json")
        assert capsys.readouterr().out == ""
    finally:
        other.close()


def test_mcp_stdio_protocol_returns_only_configured_scope(scoped_db):
    import asyncio
    import os
    import sys
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    _, _, config, _ = scoped_db

    async def check():
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "agent_session_tools.mcp_server"],
            env={**os.environ, "STUDYLOOP_CONFIG": str(config)},
        )
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("session_search", {"query": "common"})
                assert not result.isError
                output = "\n".join(c.text for c in result.content if c.type == "text")
                assert "PERSONAL_VISIBLE" in output
                assert_private_absent(output)
                hidden = await session.call_tool(
                    "session_context", {"session_id": "shared-work"}
                )
                assert_private_absent(
                    "\n".join(c.text for c in hidden.content if c.type == "text")
                )

    asyncio.run(check())
