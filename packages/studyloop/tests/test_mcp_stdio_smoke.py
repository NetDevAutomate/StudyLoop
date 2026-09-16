"""Real stdio protocol smoke test for the studyloop-mcp server.

Spawns the actual server subprocess (``python -m studyloop.mcp.server``) and
drives it over stdio with the official ``mcp`` SDK client — the same
handshake a desktop app (Claude Desktop, Codex) performs. This proves the
server works over its real transport, not just that ``register_tools()``
attaches functions to a FastMCP instance in-process.

Marked ``integration`` (spawns a subprocess, deselected by default). Run with:
    uv run pytest packages/studyloop/tests/test_mcp_stdio_smoke.py -m integration
"""

from __future__ import annotations

import sys

import pytest

mcp_mod = pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

pytestmark = pytest.mark.integration

CORE_TOOLS = {"list_courses", "get_study_backlog", "end_session"}

#: The nine study-plan tools of design §4 (D-8/D-9): six from #11, three from #12.
PLAN_TOOLS = {
    "list_study_plans",
    "get_study_plan",
    "get_planning_interview",
    "create_study_plan",
    "update_study_plan",
    "set_study_plan_status",
    "set_study_plan_milestone",
    "evaluate_study_plan",
    "delete_study_plan",
}

#: The exact production inventory: 23 original tools at ``0a20a796`` —
#: ``record_plan_learning`` among them — plus the nine plan tools = 32
#: (council review 3, F13 — the design's "26 → 35" was arithmetic on a stale
#: count; review 4, F6 — an earlier form of this comment said "plus nine less
#: one", which is 31).
#: Exact, not a lower bound: an accidental registration is a failure here, and
#: the name assertions stop an unrelated addition masking a missing tool.
PRODUCTION_TOOL_COUNT = 32


@pytest.fixture
def isolated_config(tmp_path):
    """Point the server subprocess at an empty, throwaway config + DB."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"session_db: {tmp_path / 'sessions.db'}\n")
    return {"STUDYLOOP_CONFIG": str(config_path)}


@pytest.mark.asyncio
async def test_full_handshake_list_tools_and_call(isolated_config):
    """initialize -> initialized -> tools/list -> tools/call, end to end."""
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "studyloop.mcp.server"],
        env=isolated_config,
    )

    async with (
        stdio_client(server_params) as (read, write),
        ClientSession(read, write) as session,
    ):
        # initialize + notifications/initialized handshake handled by SDK.
        init_result = await session.initialize()
        assert init_result.serverInfo.name == "studyloop"

        tools_result = await session.list_tools()
        listed = [t.name for t in tools_result.tools]
        names = set(listed)
        assert len(listed) == len(names), f"duplicate tool names advertised: {sorted(listed)}"
        assert len(names) == PRODUCTION_TOOL_COUNT, (
            f"expected exactly {PRODUCTION_TOOL_COUNT} tools, got {len(names)}: {sorted(names)}"
        )
        assert names >= CORE_TOOLS, f"missing core tools: {CORE_TOOLS - names}"
        assert names >= PLAN_TOOLS, f"missing plan tools: {PLAN_TOOLS - names}"
        assert "record_plan_learning" in names

        call_result = await session.call_tool("list_courses", {})
        assert not call_result.isError
        assert len(call_result.content) == 1
        payload = call_result.content[0]
        assert payload.type == "text"
        assert "courses" in payload.text


@pytest.mark.asyncio
async def test_dev_flag_adds_exercise_tools_to_real_stdio_inventory(isolated_config):
    """The config-level `--dev` flag changes real protocol discovery.

    Production absence is asserted in test_mcp_exercises; this is the other
    side of the process boundary: the executable parses --dev and builds the
    developer registry before the stdio handshake.
    """
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "studyloop.mcp.server", "--dev"],
        env=isolated_config,
    )

    async with (
        stdio_client(server_params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        names = {tool.name for tool in (await session.list_tools()).tools}
        assert names >= {
            "exercise_list",
            "exercise_get",
            "exercise_create",
            "exercise_import",
            "exercise_review",
        }
