"""Use real HTTP/MCP paths and deterministic between-helper access changes."""

import argparse
import asyncio
import inspect
import json
import os
import runpy
import statistics
import sys
import time
from pathlib import Path

import httpx
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

import agent_session_tools.context.response as response_guard
from agent_session_tools.context.scope import ScopePolicy, apply_policy
from agent_session_tools.context.store import ContextStore
from studyloop import notes
from studyloop.history import sessions
from studyloop.mcp.server import mcp
from studyloop.web.app import create_app
from studyloop.web.routes import notes as routes


async def exercise(output, require_installed):
    if require_installed:
        assert "site-packages" in notes.__file__
        assert "site-packages" in response_guard.__file__
    helper = runpy.run_path(str(Path(__file__).parents[1] / "agent_context/probe.py"))
    conn, _, settings, *_ = helper["prepare"](output)
    os.environ["STUDYLOOP_DB"] = str(output / "sessions.db")
    personal = sessions.start_study_session("python", "high", session_id="s")
    sessions.end_study_session(personal, "PERSONAL_SESSION", win_count=1)
    notes.add_note("PERSONAL_NOTE", session_id="s")
    os.environ["SESSION_CONTEXT_SCOPE"] = "work"
    work = sessions.start_study_session("python", "high", session_id="w")
    sessions.end_study_session(work, "WORK_SESSION", win_count=4)
    notes.add_note("WORK_NOTE", session_id="w")
    # Requests use the configured default; the child inherits the same file.
    os.environ.pop("SESSION_CONTEXT_SCOPE", None)
    original_count = routes.count_notes
    http_checks = {}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://lesson"
    ) as web:
        before = await web.get("/api/notes")
        http_checks["normal_http_returns_personal_only"] = before.status_code == 200 and [
            n["title"] for n in before.json()["notes"]
        ] == ["PERSONAL_NOTE"]

        def change_after_assembly(*args, **kwargs):
            value = original_count(*args, **kwargs)
            settings["memory"]["default_scope"] = "work"
            (output / "config.json").write_text(json.dumps(settings))
            return value

        routes.count_notes = change_after_assembly
        try:
            rejected = await web.get("/api/notes")
        finally:
            routes.count_notes = original_count
        http_checks["http_discards_assembled_body"] = (
            rejected.status_code == 409 and "PERSONAL_NOTE" not in rejected.text
        )
        work_response = await web.get("/api/notes")
        http_checks["next_http_request_reloads_scope"] = work_response.status_code == 200 and [
            n["title"] for n in work_response.json()["notes"]
        ] == ["WORK_NOTE"]
    settings["memory"]["default_scope"] = "personal"
    (output / "config.json").write_text(json.dumps(settings))
    before_revision = conn.execute("SELECT revision FROM context_access_state").fetchone()[0]
    try:
        with response_guard.read_boundary():
            notes.list_notes()
            store = ContextStore(conn)
            store.assign_session("s", "work")
            store.assign_session("s", "studyloop")
    except response_guard.ScopeConflict as exc:
        generation_error = str(exc)
    else:
        raise AssertionError("A changed-and-restored assignment was released")
    after_revision = conn.execute("SELECT revision FROM context_access_state").fetchone()[0]
    http_checks["away_and_back_changes_generation"] = after_revision > before_revision

    transport = StdioTransport(
        command=sys.executable,
        args=["-I", str(Path(__file__).with_name("mcp_probe_server.py"))],
        env={**os.environ, "STAGE28_TRIGGER": str(output / "inject-once")},
        cwd=str(output),
        log_file=output / "mcp.log",
    )
    async with Client(transport, timeout=30) as client:
        first = await client.call_tool("get_study_history", {"topic": "python"})
        (output / "inject-once").write_text("one controlled scope switch")
        failure = await client.call_tool(
            "get_study_history", {"topic": "python"}, raise_on_error=False
        )
        next_result = await client.call_tool("get_study_history", {"topic": "python"})
    first_data = first.structured_content or first.data
    next_data = next_result.structured_content or next_result.data
    error_text = "\n".join(item.text for item in failure.content if hasattr(item, "text"))
    http_checks["mcp_rejects_between_helper_switch"] = failure.is_error and "Retry" in error_text
    http_checks["mcp_error_excludes_partial_history"] = "session_stats" not in error_text
    http_checks["mcp_first_scope_has_one_win"] = first_data["session_stats"][0]["total_wins"] == 1
    http_checks["next_mcp_request_uses_new_scope"] = (
        next_data["session_stats"][0]["total_wins"] == 4
    )

    settings["memory"]["default_scope"] = "personal"
    (output / "config.json").write_text(json.dumps(settings))
    apply_policy(conn, ScopePolicy.from_config(settings), actor="lesson", dry_run=False)
    tool = mcp._tool_manager._tools["get_study_history"].fn
    baseline = inspect.unwrap(tool)
    timings = {"without_response_guard": [], "with_response_guard": []}
    variants = [("without_response_guard", baseline), ("with_response_guard", tool)]
    for iteration in range(20):
        for name, function in variants if iteration % 2 == 0 else reversed(variants):
            start = time.perf_counter()
            function(topic="python")
            timings[name].append((time.perf_counter() - start) * 1000)
    benchmark = {
        name + "_median_ms": round(statistics.median(samples), 3)
        for name, samples in timings.items()
    }
    benchmark["iterations_each"] = 20
    benchmark["order"] = "alternating paired order"
    benchmark["limits"] = (
        "Two fictional sessions, warm local direct MCP function; "
        "includes helper queries and policy reads; excludes transport/process startup. "
        "No production-scale, engine or concurrent-load comparison."
    )
    conn.close()
    assert all(http_checks.values()), http_checks
    return {
        "checks": http_checks,
        "normal_http": before.json(),
        "withheld_http": rejected.json(),
        "next_http": work_response.json(),
        "generation": {
            "before": before_revision,
            "after": after_revision,
            "error": generation_error,
        },
        "mcp": {"first": first_data, "withheld": error_text, "next": next_data},
        "benchmark": benchmark,
        "runtime": {
            "python": sys.executable,
            "studyloop_module": notes.__file__,
            "memory_module": response_guard.__file__,
            "require_installed": require_installed,
        },
        "limits": "Controlled injections into real installed helpers. HTTP ASGI omits lifespan; "
        "MCP uses actual stdio. This does not validate streaming/session-file ownership, "
        "complete sync/restore, historical fact consistency or whole-product acceptance.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-installed", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    result = asyncio.run(exercise(output, args.require_installed))
    (output / "results.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({"checks": result["checks"], "benchmark": result["benchmark"]}))


if __name__ == "__main__":
    main()
