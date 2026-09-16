"""Names of the study-plan tools the ``studyloop`` MCP server registers.

One tuple, importable without the ``mcp`` SDK (the ``studyloop[mcp]`` extra is
optional; the installer that prints these names runs without it), so the
public documentation, the installer's printed text and the persona can all be
pinned to the same list. ``tests/test_docs_plan_integration_contract.py``
grounds this tuple in the production ``FastMCP`` registry: it must name
exactly the registered tools whose name says *plan*, so a tool added to or
removed from ``studyloop.mcp.tools`` fails a test rather than leaving a stale
sentence in ``docs/agent-install.md``.
"""

from __future__ import annotations

from typing import Final

#: The nine plan lifecycle tools of design §4 (D-8, D-9), in lifecycle order:
#: discover → inspect → interview → create → revise → lifecycle → milestone →
#: evaluate → delete. Issues #11 (the first six) and #12 (the last three).
PLAN_TOOL_NAMES: Final[tuple[str, ...]] = (
    "list_study_plans",
    "get_study_plan",
    "get_planning_interview",
    "create_study_plan",
    "update_study_plan",
    "set_study_plan_status",
    "set_study_plan_milestone",
    "evaluate_study_plan",
    "delete_study_plan",
)

#: The plan-write tool that pre-dates the nine: appends a learning record to a
#: plan — the wind-down's first write (ADR-0010). Documented beside the nine,
#: not counted among them.
LEARNING_RECORD_TOOL: Final = "record_plan_learning"

__all__ = ["LEARNING_RECORD_TOOL", "PLAN_TOOL_NAMES"]
