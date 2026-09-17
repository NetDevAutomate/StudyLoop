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

from studyloop.mcp.inventory import LEARNING_RECORD_TOOL, PLAN_TOOL_NAMES
from studyloop.planning.boundaries import NOT_AUTOMATIC

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


def _prose(text: str) -> str:
    """Markdown soft-wraps lines, so a phrase can straddle a newline where a
    space belongs; collapse whitespace before any phrase-membership check."""
    return re.sub(r"\s+", " ", text)


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


def test_agent_install_doc_promises_exactly_what_update_study_plan_revises() -> None:
    """Review 5 (GPT F4) pinned the opposite: `update_study_plan` exposed no
    mission field, so the doc had to keep the mission out of what MCP revises.
    Item 3b (design §3b) added `why`, `success`, `constraints` and
    `out_of_scope` to the tool, so the pin flips with the schema it is
    grounded in: the 'no CLI command' sentence now names the mission among
    what MCP revises, and the table row names every schema property except
    the identifier — and no longer says the mission is *not* among them."""
    from studyloop.mcp.server import mcp

    schema = set(mcp._tool_manager._tools["update_study_plan"].parameters["properties"])
    assert {"why", "success", "constraints", "out_of_scope"} <= schema
    section = _prose(_section(_read("docs/agent-install.md"), "Study-plan tools over MCP"))
    sentence = re.search(r"[^.]*no CLI command[^.]*\.", section)
    assert sentence, "the install doc no longer states which operations have no CLI command"
    assert "mission" in sentence.group(0).lower()
    row = re.search(r"\| `update_study_plan\(plan_id, …\)` \|([^|]*)\|", section)
    assert row, "no update_study_plan row"
    cell = row.group(1).lower()
    for prop in sorted(schema - {"plan_id"}):
        word = prop.replace("_", " ").split(" ")[0]
        assert word in cell, f"update_study_plan row does not mention {prop!r}"
    assert "mission" in cell
    assert not re.search(r"mission[^.]*\bnot\b[^.]*fields", cell), (
        "the row still says the mission is not among the tool's fields"
    )


def test_agent_install_doc_names_the_planning_purpose_and_no_stale_phase_reference() -> None:
    """The install doc names the Web door (``purpose=planning``) and states the
    Kiro/Claude harness boundary as an owner decision, not as "tracked as
    Phase 6, T6.1" — T6.1 is the phase that closes here."""
    text = _read("docs/agent-install.md")
    section = _prose(_section(text, "Study-plan tools over MCP"))
    assert "purpose=planning" in section
    assert "study-plan-architect.json" in section and "study-plan-architect.md" in section
    assert "T6.1" not in text, "the install doc still points at the phase that just closed"
    assert "Phase 6" not in text


# ---------------------------------------------------------------------------
# agents/mcp/README.md — the capability matrix per-harness registration points at
# ---------------------------------------------------------------------------


def test_mcp_readme_lists_the_whole_production_inventory() -> None:
    registered = _registry()
    section = _section(_read("agents/mcp/README.md"), "studyloop-mcp (Study tools)")
    listed = _table_tool_names(section)
    assert len(listed) == len(set(listed)), f"duplicate rows: {listed}"
    assert set(listed) == registered, (
        f"README table vs registry — missing {sorted(registered - set(listed))}, "
        f"stale {sorted(set(listed) - registered)}"
    )


def test_mcp_readme_states_the_registry_count() -> None:
    section = _section(_read("agents/mcp/README.md"), "studyloop-mcp (Study tools)")
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
    """Six automation boundaries from issue #7's out-of-scope list — and only
    automation boundaries (review 5, GPT F7 / Grok F6: the manual form's brain
    dump is an input-path fact, stated beside the list, not in it)."""
    assert len(NOT_AUTOMATIC) == 6
    assert len(set(NOT_AUTOMATIC)) == len(NOT_AUTOMATIC)
    for phrase in NOT_AUTOMATIC:
        assert phrase == phrase.strip() and phrase and phrase[0].islower(), phrase
        assert "brain dump" not in phrase
    assert any("schedule" in phrase for phrase in NOT_AUTOMATIC), (
        "#7: no autonomous recurring planning sessions"
    )


def test_study_plans_doc_states_the_brain_dump_limit_beside_the_boundary_list() -> None:
    section = _prose(_section(_read("docs/study-plans.md"), "Deliberately not automatic"))
    assert "brain dump" in section
    assert "same single session slot" in section or "same session slot" in section


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
    text = _prose(_read("docs/study-plans.md"))
    assert "plan-aware guidance with tested ranking rules" in text
    assert "better learning" not in text.lower()
    assert "learn faster" not in text.lower()
    # Review 5 (GPT F3 / Grok F1) pinned the page to say the verdicts were
    # PENDING while they were. The owner scored the rubric on 2026-09-16
    # (receipt header: "owner verdicts RECORDED"), so the page now reports the
    # outcome — accepted rows and the two findings — and must not fall back to
    # "pending", nor round the two `no` verdicts up.
    now_section = _prose(_section(_read("docs/study-plans.md"), "Plan-aware now"))
    assert "recorded per scenario" not in now_section
    assert "pending" not in now_section.lower()
    assert "scored" in now_section.lower()
    assert "were not" in now_section, "the two `no` verdicts must be stated, not rounded up"
    receipt = _read("docs/architecture/plan-integration/receipts/now-rubric-2026-09-16.md")
    assert "owner verdicts RECORDED" in receipt, (
        "the rubric receipt no longer says it is scored — move the page's status sentence with it"
    )


def test_study_plans_doc_plan_aware_now_states_eligibility_and_optional_fields() -> None:
    """Review 5 (GPT F5): synthesis needs a READY plan whose next milestone is
    within the energy capability; an unready active plan is a warning and
    repair target; a fully checked plan is a completion action; the no-plan
    output is unchanged (not 'exactly what it was' in every failure case)."""
    section = _prose(_section(_read("docs/study-plans.md"), "Plan-aware now"))
    for phrase in ("ready", "energy", "not ready", "completion", "unchanged"):
        assert phrase in section, f"'Plan-aware now' lacks the qualification {phrase!r}"
    assert "exactly what it was" not in section


def test_architect_section_claims_the_brief_only_where_it_is_built() -> None:
    """Review 5 (GPT F2 / Grok F2-F3): the planning brief is injected on the
    Web door (`purpose=planning`); a CLI-started architect gathers the same
    material through `get_planning_interview` / `studyloop plan interview`;
    checkpoints are never fired from session events; the two operations with
    no CLI command are named."""
    section = _prose(
        _section(_read("docs/study-plans.md"), "Build a plan with the study-plan-architect")
    )
    lowered = section.lower()
    assert "whichever door" not in lowered
    assert "session run against" not in lowered
    assert "web" in lowered and "planning brief" in lowered
    assert "get_planning_interview" in section and "studyloop plan interview" in section
    assert "session events" in lowered
    assert "no cli command" in lowered.replace("-", " ")
    assert "revis" in lowered and "delet" in lowered


def test_study_plans_doc_plan_aware_now_section_names_every_consumer() -> None:
    """The four surfaces that consume the one recommendation result (#10)."""
    section = _prose(_section(_read("docs/study-plans.md"), "Plan-aware now"))
    for surface in ("studyloop now", "Today", "recap", "get_next_action"):
        assert surface in section, f"'Plan-aware now' does not name {surface!r}"


def test_study_plans_doc_states_recording_retry_and_deletion_semantics() -> None:
    """Review 5 (GPT F9): learner-visible behaviours the specs bind and the
    guide did not state — a recorded checkpoint reports each write; the CLI
    milestone flags are retry-safe while omitting them toggles; a hand-edited
    active plan that is no longer complete is paused or repaired before it is
    written to; Web deletes on the explicit action, MCP needs confirmed=true."""
    section = _prose(_section(_read("docs/study-plans.md"), "Recording, retries, and deletion"))
    lowered = section.lower()
    for phrase in ("each write", "--done", "--undone", "toggle", "pause", "confirmed=true"):
        assert phrase in lowered, f"missing {phrase!r}"


# ---------------------------------------------------------------------------
# The other public pages that described the pre-#7 gap
# ---------------------------------------------------------------------------

#: Public pages found during T6.1 still saying the gap #7 closed was open.
_PUBLIC_PLAN_PAGES = (
    "README.md",
    "docs/index.md",
    "docs/web-ui-guide.md",
    "docs/study-plans.md",
    "docs/cli-reference.md",
    "docs/roadmap.md",
)

#: Each pattern is a claim that was true before the change and is false now.
_STALE_GAP_CLAIMS = (
    r"planning interview is not integrated",
    r"do not yet influence",
    r"does not (?:yet )?(?:bias|influence|change) .{0,40}(?:now|Today|recommendation)",
    r"remains CLI-only",
    r"not available yet",
)


@pytest.mark.parametrize("rel_path", _PUBLIC_PLAN_PAGES)
def test_public_pages_no_longer_describe_the_closed_gap(rel_path: str) -> None:
    text = _prose(_read(rel_path))
    offenders = [
        pattern for pattern in _STALE_GAP_CLAIMS if re.search(pattern, text, re.IGNORECASE)
    ]
    assert not offenders, f"{rel_path} still carries a pre-#7 gap claim: {offenders}"


def test_web_ui_guide_today_and_plans_sections_state_the_shipped_behaviour() -> None:
    guide = _read("docs/web-ui-guide.md")
    today = _prose(_section(guide, "Today"))
    assert "plan-aware guidance with tested ranking rules" in today
    plans = _prose(_section(guide, "Study Plans"))
    assert "Plan with architect" in plans
    assert "creates no plan" in plans


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
    # Rich wraps the console at 80 columns under CliRunner; a phrase may straddle
    # a line break where a space belongs.
    return re.sub(r"\s+", " ", result.output)


def test_installer_output_names_the_nine_tools_and_the_planning_purpose(
    runner: CliRunner, tmp_path: Path
) -> None:
    output = _invoke_install_agents(runner, tmp_path)
    for name in PLAN_TOOL_NAMES:
        assert name in output, f"installer output does not name {name}"
    assert "planning" in output
    assert "docs/agent-install.md" in output
    # Review 5 (GPT F6 / Grok F7): nine LIFECYCLE tools plus record_plan_learning
    # (ten plan-named tools), reachable per harness — not by the install itself.
    assert "lifecycle" in output
    assert LEARNING_RECORD_TOOL in output
    assert "per-harness" in output or "per harness" in output


def test_installer_output_states_the_boundary_with_the_constant(
    runner: CliRunner, tmp_path: Path
) -> None:
    """The installer's boundary sentence is built from ``NOT_AUTOMATIC``, so
    it cannot claim more automation than the docs do (issue #7, Further
    Notes: stale installer language claiming an active plan already changes
    Now had to be corrected — the fix is to derive it)."""
    output = _invoke_install_agents(runner, tmp_path)
    for phrase in NOT_AUTOMATIC:
        assert phrase in output, f"installer output does not state the boundary {phrase!r}"


def test_uninstall_output_makes_no_capability_claims(runner: CliRunner, tmp_path: Path) -> None:
    output = _invoke_install_agents(runner, tmp_path, "--uninstall")
    assert "Removed agent definitions" in output
    for name in PLAN_TOOL_NAMES:
        assert name not in output
