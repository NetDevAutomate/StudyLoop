"""Docs↔code contract for the plan integration's public claims (#15, T6.1).

Issue #15's first acceptance criterion is that "Study Plans, Now, Today, Web,
MCP, and installer language describe the implemented automatic boundaries
accurately". Prose cannot be proven accurate by reading it once — it drifts
the next time a tool is added or a boundary moves — so, like
``test_docs_harness_contract.py`` does for the six-harness scope, every claim
here is pinned to a code-side source of truth and compared as a SET or an
ordered tuple, never as a copied sentence:

* the nine plan tools + ``record_plan_learning`` — the constant
  :data:`studyloop.mcp.inventory.PLAN_TOOL_NAMES` (design §4, lifecycle order),
  itself grounded in the production ``FastMCP`` registry here so the constant
  can neither name a tool the server lacks nor omit one it has;
* the full ``studyloop-mcp`` inventory in ``agents/mcp/README.md`` — the
  registry, exactly (a stale "10 MCP tools" was found during T6.1);
* the learner-facing "Deliberately not automatic" list in
  ``docs/study-plans.md`` — :data:`studyloop.planning.boundaries.NOT_AUTOMATIC`,
  the one place issue #7's out-of-scope line is written down in code;
* the installer's printed text — the same two constants, so what
  ``studyloop install agents`` says matches what the docs say;
* the release language — D-16's bounded phrasing ("plan-aware guidance with
  tested ranking rules", never "better learning").
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from studyloop.mcp.inventory import (  # pyright: ignore[reportMissingImports]  # RED: lands in GREEN
    LEARNING_RECORD_TOOL,
    PLAN_TOOL_NAMES,
)
from studyloop.planning.boundaries import (  # pyright: ignore[reportMissingImports]  # RED: lands in GREEN
    NOT_AUTOMATIC,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

_TABLE_TOOL_ROW = re.compile(r"^\|\s*`([a-z_]+)(?:\(|`)", re.MULTILINE)
_BULLET_LEAD = re.compile(r"^- \*\*(.+?)\*\*")


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """The body of the ``## <heading>`` section, up to the next ``## `` heading.

    Level-two headings only: a ``### `` inside the section belongs to it.
    """
    match = re.search(
        rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
    )
    assert match, f"no '## {heading}' section found"
    return match.group(1)


def _table_tool_names(section: str) -> list[str]:
    """Tool names in a section's table, first column, in row order."""
    return _TABLE_TOOL_ROW.findall(section)


def _registry() -> set[str]:
    from studyloop.mcp.server import mcp

    return set(mcp._tool_manager._tools)


# ---------------------------------------------------------------------------
# The plan-tool constant is grounded in the production registry
# ---------------------------------------------------------------------------


def test_plan_tool_constant_is_exactly_the_registry_plan_tools() -> None:
    """The constant the docs and installer are pinned to must itself be true of
    the server: the nine design-§4 names plus ``record_plan_learning`` are
    exactly the registered tools whose name says ``plan`` — no invented tool,
    no unregistered tool, no registered plan tool the constant forgets."""
    registered = _registry()
    plan_named = {name for name in registered if "plan" in name}
    assert plan_named == set(PLAN_TOOL_NAMES) | {LEARNING_RECORD_TOOL}
    assert len(PLAN_TOOL_NAMES) == 9
    assert len(set(PLAN_TOOL_NAMES)) == len(PLAN_TOOL_NAMES), "duplicate names in the constant"
    assert LEARNING_RECORD_TOOL not in PLAN_TOOL_NAMES


# ---------------------------------------------------------------------------
# docs/agent-install.md
# ---------------------------------------------------------------------------


def test_agent_install_doc_table_is_the_nine_then_record_plan_learning() -> None:
    """The "Study-plan tools over MCP" table names every plan tool, in the
    constant's lifecycle order, with ``record_plan_learning`` last — and
    nothing else."""
    section = _section(_read("docs/agent-install.md"), "Study-plan tools over MCP")
    assert _table_tool_names(section) == [*PLAN_TOOL_NAMES, LEARNING_RECORD_TOOL]


def test_agent_install_doc_names_the_planning_purpose_and_no_stale_phase_reference() -> None:
    """The install doc names the Web door (``purpose=planning``) and states the
    Kiro/Claude harness boundary as an owner decision, not as "tracked as
    Phase 6, T6.1" — T6.1 is the phase that closes here."""
    text = _read("docs/agent-install.md")
    section = _section(text, "Study-plan tools over MCP")
    assert "purpose=planning" in section
    assert "study-plan-architect.json" in section and "study-plan-architect.md" in section
    assert "T6.1" not in text, "the install doc still points at the phase that just closed"
    assert "Phase 6" not in text


# ---------------------------------------------------------------------------
# agents/mcp/README.md — the capability matrix per-harness registration points at
# ---------------------------------------------------------------------------


def test_mcp_readme_lists_the_whole_production_inventory() -> None:
    registered = _registry()
    section = _section(_read("agents/mcp/README.md"), "studyloop-mcp (Session DB Tools)")
    listed = _table_tool_names(section)
    assert len(listed) == len(set(listed)), f"duplicate rows: {listed}"
    assert set(listed) == registered, (
        f"README table vs registry — missing {sorted(registered - set(listed))}, "
        f"stale {sorted(set(listed) - registered)}"
    )


def test_mcp_readme_states_the_registry_count() -> None:
    section = _section(_read("agents/mcp/README.md"), "studyloop-mcp (Session DB Tools)")
    match = re.search(r"exposes (\d+) MCP tools", section)
    assert match, "the README no longer states how many tools the server exposes"
    assert int(match.group(1)) == len(_registry())


# ---------------------------------------------------------------------------
# docs/study-plans.md
# ---------------------------------------------------------------------------


def test_study_plans_doc_boundary_list_is_the_constant_in_order() -> None:
    """Each bullet of "Deliberately not automatic" opens with a bold lead
    phrase; the tuple of lead phrases IS ``NOT_AUTOMATIC``. A boundary cannot
    be dropped from the doc, added to it, or reworded without the constant
    moving with it."""
    section = _section(_read("docs/study-plans.md"), "Deliberately not automatic")
    bullets = [line for line in section.splitlines() if line.startswith("- ")]
    leads = []
    for bullet in bullets:
        lead = _BULLET_LEAD.match(bullet)
        assert lead, f"bullet without a bold lead phrase: {bullet!r}"
        leads.append(lead.group(1))
    assert tuple(leads) == NOT_AUTOMATIC


def test_not_automatic_constant_is_well_formed() -> None:
    assert len(NOT_AUTOMATIC) >= 4, "issue #7 names at least four automatic boundaries"
    assert len(set(NOT_AUTOMATIC)) == len(NOT_AUTOMATIC)
    for phrase in NOT_AUTOMATIC:
        assert phrase == phrase.strip() and phrase and phrase[0].islower(), phrase


def test_study_plans_doc_has_no_stale_gap_claims() -> None:
    """The pre-#15 "What a plan does not do yet" list said broader plan
    management "remains CLI-only" and cited ``mcp/tools.py:129``; both are
    false now and neither may come back."""
    text = _read("docs/study-plans.md")
    assert "What a plan does not do yet" not in text
    assert "CLI-only" not in text
    assert not re.search(r"mcp/tools\.py:\d+", text), "a line-number citation goes stale"


def test_study_plans_doc_uses_the_bounded_release_language() -> None:
    """D-16: ranking tests prove ranking compliance, not learning. The doc
    says "plan-aware guidance with tested ranking rules" and never promises
    "better learning"."""
    text = _read("docs/study-plans.md")
    assert "plan-aware guidance with tested ranking rules" in text
    assert "better learning" not in text.lower()
    assert "learn faster" not in text.lower()


def test_study_plans_doc_plan_aware_now_section_names_every_consumer() -> None:
    """The four surfaces that consume the one recommendation result (#10)."""
    section = _section(_read("docs/study-plans.md"), "Plan-aware now")
    for surface in ("studyloop now", "Today", "recap", "get_next_action"):
        assert surface in section, f"'Plan-aware now' does not name {surface!r}"


# ---------------------------------------------------------------------------
# The installer's printed text
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _invoke_install_agents(runner: CliRunner, tmp_path: Path, *extra: str) -> str:
    from studyloop.cli import cli

    with (
        patch("studyloop.cli._install.require_repo_root", return_value=tmp_path),
        patch(
            "studyloop.cli._install.install_agent_definitions",
            return_value={"shared": 1, "kiro": 1},
        ),
    ):
        result = runner.invoke(
            cli, ["install", "agents", "--repo-root", str(tmp_path), "--tool", "kiro", *extra]
        )
    assert result.exit_code == 0, result.output
    return result.output


def test_installer_output_names_the_nine_tools_and_the_planning_purpose(
    runner: CliRunner, tmp_path: Path
) -> None:
    output = _invoke_install_agents(runner, tmp_path)
    for name in PLAN_TOOL_NAMES:
        assert name in output, f"installer output does not name {name}"
    assert "planning" in output
    assert "docs/agent-install.md" in output


def test_installer_output_states_the_boundary_with_the_constant(
    runner: CliRunner, tmp_path: Path
) -> None:
    """The installer's boundary sentence is built from ``NOT_AUTOMATIC``, so
    it cannot claim more automation than the docs do (issue #7, Further
    Notes: stale installer language claiming an active plan already changes
    Now had to be corrected — the fix is to derive it)."""
    output = _invoke_install_agents(runner, tmp_path)
    for phrase in NOT_AUTOMATIC[:4]:
        assert phrase in output, f"installer output does not state the boundary {phrase!r}"


def test_uninstall_output_makes_no_capability_claims(runner: CliRunner, tmp_path: Path) -> None:
    output = _invoke_install_agents(runner, tmp_path, "--uninstall")
    assert "Removed agent definitions" in output
    for name in PLAN_TOOL_NAMES:
        assert name not in output
