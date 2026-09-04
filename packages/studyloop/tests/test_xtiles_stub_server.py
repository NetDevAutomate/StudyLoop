"""WD-4 — the stub ``xtiles`` MCP server speaks MCP, logs every call, no network.

The stub's one job is to make "a connector named ``xtiles`` is attached" real
for the transcript acceptance tests. So the properties pinned here are exactly
the ones those tests lean on: the server completes a real stdio handshake
under the name ``xtiles``, exposes the three write tools the prompts select
between, appends every call to the JSON artefact, and cannot reach a network.

Red when: a call is unlogged, a tool disappears, the server name drifts, or a
network-capable import creeps into the stub.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

STUB = Path(__file__).parent / "_xtiles_stub_server.py"

EXPECTED_TOOLS = {
    "xtiles_create_tasks",
    "xtiles_create_tiles_from_markdown_in_my_planner",
    "xtiles_create_view_from_markdown",
}

#: Modules that can open a connection. The stub's transport is stdio and its
#: whole value is being offline; one of these appearing in it is the defect.
_NETWORK_MODULES = {
    "socket",
    "ssl",
    "http",
    "urllib",
    "urllib3",
    "requests",
    "httpx",
    "aiohttp",
    "websockets",
}


def _server_params(tmp_path: Path) -> tuple[StdioServerParameters, Path]:
    log = tmp_path / "stub-calls.json"
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(STUB)],
        env={"XTILES_STUB_CALL_LOG": str(log)},
    )
    return params, log


@pytest.mark.asyncio
async def test_handshake_tools_and_call_log(tmp_path: Path) -> None:
    """initialize → tools/list → one call per tool → every call in the artefact."""
    params, log = _server_params(tmp_path)

    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        init = await session.initialize()
        # The NAME is the gate: the wind-down skill's second half is "an MCP
        # server named `xtiles` is connected", so a drifted name here would
        # make the whole harness test a connector the skill cannot see.
        assert init.serverInfo.name == "xtiles"

        tools = {t.name for t in (await session.list_tools()).tools}
        assert tools == EXPECTED_TOOLS

        task_call = await session.call_tool(
            "xtiles_create_tasks",
            {"tasks": [{"title": "Study: decorators"}]},
        )
        assert not task_call.isError

        tile_call = await session.call_tool(
            "xtiles_create_tiles_from_markdown_in_my_planner",
            {"period": "day", "date": "2026-09-04", "markdown": "### Study: decorators"},
        )
        assert not tile_call.isError
        # The one bit of response fidelity the prompts depend on: the planner
        # tile is the shape that returns a URL.
        tile_payload = tile_call.content[0]
        assert tile_payload.type == "text"
        assert "resource_url" in tile_payload.text

        page_call = await session.call_tool(
            "xtiles_create_view_from_markdown",
            {"projectId": "stub-project", "markdown": "## LR — page"},
        )
        assert not page_call.isError

    calls = json.loads(log.read_text(encoding="utf-8"))
    assert [c["tool"] for c in calls] == [
        "xtiles_create_tasks",
        "xtiles_create_tiles_from_markdown_in_my_planner",
        "xtiles_create_view_from_markdown",
    ], "a call was dropped from the log, or logged out of order"
    assert calls[0]["arguments"]["tasks"] == [{"title": "Study: decorators"}]
    assert calls[1]["arguments"]["markdown"] == "### Study: decorators"


@pytest.mark.asyncio
async def test_every_call_is_appended_not_overwritten(tmp_path: Path) -> None:
    """Two calls to the SAME tool → two log entries. A log that keeps only the
    last call would grade a multi-write transcript as a single write."""
    params, log = _server_params(tmp_path)

    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        for title in ("first", "second"):
            await session.call_tool("xtiles_create_tasks", {"tasks": [{"title": title}]})

    calls = json.loads(log.read_text(encoding="utf-8"))
    assert len(calls) == 2
    assert calls[0]["arguments"]["tasks"][0]["title"] == "first"
    assert calls[1]["arguments"]["tasks"][0]["title"] == "second"


def test_unconfigured_stub_refuses_to_run() -> None:
    """No log path → exit before the handshake. A stub that ran unlogged would
    pass WD-5's silence checks vacuously — the exact trap (D4) this suite is
    built to avoid."""
    import subprocess

    result = subprocess.run(
        [sys.executable, str(STUB)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
        timeout=30,
    )
    assert result.returncode == 2
    assert "XTILES_STUB_CALL_LOG" in result.stderr


def test_the_stub_imports_nothing_that_can_open_a_socket() -> None:
    """Structural half of "reaches no network": stdio transport by
    construction, plus no network-capable import in the stub itself."""
    tree = ast.parse(STUB.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    offenders = imported & _NETWORK_MODULES
    assert not offenders, f"the stub imports network-capable modules: {sorted(offenders)}"
