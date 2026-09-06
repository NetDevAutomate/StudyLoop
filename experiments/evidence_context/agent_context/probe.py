"""Isolated CLI and real MCP-stdio acceptance; imports only the memory package."""

import argparse
import asyncio
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import replace
from importlib.resources import files
from pathlib import Path

import agent_session_tools.context.public as public
from agent_session_tools.context.provenance import Origin
from agent_session_tools.context.scope import ScopePolicy, apply_policy
from agent_session_tools.context.store import ContextStore, NativeSource

REVISION = "a" * 40
TARGET = '["uv","run","pytest"]'


def prepare(output):
    settings = {
        "database": {"path": str(output / "sessions.db")},
        "memory": {
            "default_scope": "personal",
            "projects": {
                "studyloop": {"scope": "personal", "roots": ["/lesson/studyloop"]},
                "mailgraph": {"scope": "personal", "roots": ["/lesson/mailgraph"]},
                "work": {"scope": "work", "roots": ["/lesson/work"]},
            },
        },
    }
    config = output / "config.json"
    config.write_text(json.dumps(settings))
    os.environ["STUDYLOOP_CONFIG"] = str(config)
    os.environ["SESSION_CONTEXT_SCOPE"] = "personal"
    conn = sqlite3.connect(output / "sessions.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(files("agent_session_tools").joinpath("schema.sql").read_text())
    from agent_session_tools.migrations import migrate

    migrate(conn)
    for sid, project in [("s", "studyloop"), ("m", "mailgraph"), ("w", "work")]:
        conn.execute(
            "INSERT INTO sessions(id,source,project_path) VALUES (?,?,?)",
            (sid, "fixture", "/lesson/" + project),
        )
    conn.commit()
    apply_policy(conn, ScopePolicy.from_config(settings), actor="lesson", dry_run=False)
    store = ContextStore(conn)
    base = NativeSource(
        session_id="s",
        native_key="s-report",
        harness="codex",
        native_kind="message:assistant",
        native_locator="fixture.jsonl#line/1",
        parser_version="lesson",
        machine_id="fictional-laptop",
        origin=Origin.CONVERSATION,
        body="Cache history: SQLite keeps the writes atomic.",
        recorded_at="2026-09-01T12:00:00Z",
    )
    other = replace(
        base,
        session_id="m",
        native_key="m-report",
        harness="kiro_cli",
        machine_id="fictional-mini",
        body="A graph would help relationship traversal.",
    )
    private = replace(base, session_id="w", native_key="w-report", body="Cache WORK_EXCLUDED")
    check = replace(
        base,
        native_key="process",
        origin=Origin.PROCESS_EXIT,
        target=TARGET,
        revision=REVISION,
        exit_code=0,
        body="2 passed",
    )
    ids = {
        name: store.capture(source)
        for name, source in [
            ("base", base),
            ("other", other),
            ("private", private),
            ("check", check),
        ]
    }
    return conn, store, settings, ids, base, other, check


def cli(*arguments):
    command = Path(sys.executable).parent / "session-context"
    prefix = (
        [str(command)]
        if command.is_file()
        else [sys.executable, "-m", "agent_session_tools.context.cli"]
    )
    result = subprocess.run([*prefix, *arguments], check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


async def exercise(output, require_installed):
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    if require_installed:
        assert "site-packages" in public.__file__
        assert importlib.util.find_spec("studyloop") is None
        assert (Path(sys.executable).parent / "session-context").is_file()
    conn, store, settings, ids, base, other, check = prepare(output)
    requirements = [
        {
            "name": "unit tests",
            "project_id": "studyloop",
            "target": TARGET,
            "revision": REVISION,
            "expected_exit_code": 0,
        }
    ]
    request = output / "requirements.json"
    request.write_text(json.dumps(requirements))
    binary = Path(sys.executable).parent / "session-db-mcp"
    transport = StdioTransport(
        command=str(binary),
        args=[],
        env=dict(os.environ),
        cwd=str(output),
        log_file=output / "mcp-server.log",
    )
    async with Client(transport, timeout=30) as client:

        async def call(name, **arguments):
            response = await client.call_tool(name, arguments)
            assert not response.is_error
            return response.structured_content or response.data

        first = await call(
            "memory_propose",
            statement="Prefer SQLite",
            state="completed",
            citations=[
                {"evidence_id": ids["base"], "start": 0, "end": len(base.body), "quote": base.body}
            ],
        )
        second = await call(
            "memory_propose",
            statement="Consider a graph",
            state="completed",
            citations=[
                {
                    "evidence_id": ids["other"],
                    "start": 0,
                    "end": len(other.body),
                    "quote": other.body,
                }
            ],
        )
        await call(
            "memory_relate",
            from_id=second["assertion_id"],
            to_id=first["assertion_id"],
            relation="contradicts",
        )
        history = await call("memory_search", query="cache")
        assert {s["harness"] for s in history["sources"]} == {"codex", "kiro_cli"}
        assert {s["machine_id"] for s in history["sources"]} == {
            "fictional-laptop",
            "fictional-mini",
        }
        assert {s["project_id"] for s in history["sources"]} == {"studyloop", "mailgraph"}
        assert len(history["relationships"]) == 1
        assert "WORK_EXCLUDED" not in json.dumps(history)
        supported = cli("decide", "unit checks", str(request))
        assert supported["decision"]["sufficiency"] == "recorded_checks_satisfied"
        assert supported["decision"]["validation_of_change"] == "not_established"
        failed = store.capture(replace(check, native_key="failed", exit_code=1, body="1 failed"))
        conflicting = await call("memory_decide", query="unit checks", requirements=requirements)
        assert conflicting["decision"]["sufficiency"] == "conflicting_records"
        assert failed in conflicting["decision"]["checks"][0]["source_ids"]["different_exit"]
        missing = await call(
            "memory_decide",
            query="unit checks",
            requirements=[{**requirements[0], "revision": "b" * 40}],
        )
        assert missing["decision"]["sufficiency"] == "checks_not_established"
        bounded = await call("memory_search", query="cache", max_sources=1, budget_bytes=4096)
        assert public.size(bounded) <= 4096
        assert bounded["coverage"]["limits_reached"]
        hidden = await call("memory_source", evidence_id=ids["private"])
        assert hidden["status"] == "unavailable"
        settings["memory"]["projects"]["mailgraph"]["scope"] = "work"
        (output / "config.json").write_text(json.dumps(settings))
        apply_policy(conn, ScopePolicy.from_config(settings), actor="lesson", dry_run=False)
        narrowed = await call("memory_search", query="cache")
        assert narrowed["relationships"] == []
        assert "Consider a graph" not in json.dumps(narrowed)
    conn.close()
    return {
        "runtime": {
            "python": sys.executable,
            "package_file": public.__file__,
            "wheel_only_required": require_installed,
            "mcp_transport": "stdio",
        },
        "history": history,
        "matching_checks": supported,
        "conflicting_checks": conflicting,
        "different_revision": missing,
        "bounded_context": bounded,
        "reclassified_context": narrowed,
        "checks": {
            "cross_project_harness_machine_context": True,
            "exact_proposal_citations": True,
            "recorded_checks_not_semantic_validation": True,
            "conflicting_exit_records": True,
            "changed_revision_withheld": True,
            "whole_document_budget": True,
            "private_source_withheld": True,
            "reclassification_revokes_relationship": True,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-installed", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    result = asyncio.run(exercise(args.output, args.require_installed))
    (args.output / "results.json").write_text(json.dumps(result, indent=2))
    print(
        json.dumps(
            {"output": str(args.output), "checks": result["checks"], "runtime": result["runtime"]}
        )
    )


if __name__ == "__main__":
    main()
