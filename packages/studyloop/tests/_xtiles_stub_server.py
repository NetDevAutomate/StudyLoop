"""A stub ``xtiles`` MCP server — Layer 2 of the acceptance harness.

Its only job is to make "an ``xtiles`` connector is attached" REAL for the
transcript acceptance tests (WD-5/WD-6) without a network, an account or an
OAuth flow: a harness pointed at this server sees a server named ``xtiles``
exposing the three write tools the prompts select between, and every call is
appended to a JSON file the test reads afterwards.

Deliberately dumb. No validation, no state, no fidelity to xTiles' real
responses beyond the one thing the prompts check for (the planner-tile tool
returns a URL). Anything smarter would be a second implementation of xTiles
for tests to accidentally depend on.

NO NETWORK — enforced, not aspirational: the transport is stdio, and this
module must import nothing that can open a socket. WD-4 scans this file's
imports; adding ``socket``, ``http``, ``urllib.request``, ``requests`` or
similar here turns that test red.

Environment:
    XTILES_STUB_CALL_LOG   Path of the JSON call log (required). Each call is
                           appended as {"tool": ..., "arguments": {...}}.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("xtiles")


def _log_path() -> Path:
    raw = os.environ.get("XTILES_STUB_CALL_LOG", "").strip()
    if not raw:
        print("XTILES_STUB_CALL_LOG is not set; refusing to run unlogged", file=sys.stderr)
        raise SystemExit(2)
    return Path(raw)


def _log_call(tool: str, arguments: dict) -> None:
    """Append one call. Read-modify-write is fine: one server, one client."""
    path = _log_path()
    calls = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    calls.append({"tool": tool, "arguments": arguments})
    path.write_text(json.dumps(calls, indent=2), encoding="utf-8")


@mcp.tool()
def xtiles_create_tasks(tasks: list[dict], projectId: str = "") -> dict:  # noqa: N803 — xTiles' own casing
    """Create one or more tasks (stub: logs and returns fake ids)."""
    _log_call("xtiles_create_tasks", {"tasks": tasks, "projectId": projectId})
    return {"tasks": [{"id": f"stub-task-{i}"} for i, _ in enumerate(tasks)]}


@mcp.tool()
def xtiles_create_tiles_from_markdown_in_my_planner(period: str, date: str, markdown: str) -> dict:
    """Append tiles to the personal planner (stub: logs and returns fake URLs)."""
    _log_call(
        "xtiles_create_tiles_from_markdown_in_my_planner",
        {"period": period, "date": date, "markdown": markdown},
    )
    return {
        "view_id": "stub-view-planner",
        "tiles": [{"id": "stub-tile-1", "resource_url": "https://xtiles.app/stub-view-planner"}],
        "parent_resource_url": "https://xtiles.app/stub-view-planner",
    }


@mcp.tool()
def xtiles_create_view_from_markdown(projectId: str, markdown: str) -> dict:  # noqa: N803
    """Create a new page in a project (stub: logs and returns a fake URL)."""
    _log_call("xtiles_create_view_from_markdown", {"projectId": projectId, "markdown": markdown})
    return {
        "view_id": "stub-view-page",
        "resource_url": "https://xtiles.app/stub-view-page",
    }


if __name__ == "__main__":
    _log_path()  # fail before the handshake when unconfigured, not on first call
    mcp.run()  # stdio transport — the default, and the point
