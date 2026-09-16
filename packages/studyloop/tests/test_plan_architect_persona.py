"""The study-plan architect persona prefers the MCP plan tools, CLI as fallback (T4.2, #13b).

The persona the ``planning`` purpose renders (``persona_mode_for("planning")`` →
``plan-architect``, design §5) must name the nine plan lifecycle tools of design
§4 — the six #11 registered and the three #12 lands — in a tooling section that
puts the MCP tools **before** the ``studyloop plan …`` CLI fallback, so an
architect running in a harness with the ``studyloop`` MCP server connected
reaches the plan application layer directly and one without it still has a
working recipe. The interview protocol itself (one question per turn) is not
under test here: these tests are about *which tools* the architect is told to
reach for and in what order of preference, never about the wording of a question.

Two guards ride along. The ``focus`` persona — what every default session
ships and hashes into ``persona_hash`` — is pinned by digest so this change
provably touched only the architect. And the per-harness projections (Claude
and OpenCode frontmatter files, Kiro's ``persona.md``) plus the manifest the
generator writes must still regenerate byte-identically from the canonical
body: there is no projection generator, only the copies and the hash manifest,
so drift is caught here rather than at install time.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest

from studyloop import session_state
from studyloop.agent_launcher import build_canonical_persona, persona_mode_for

_REPO_ROOT = Path(__file__).resolve()
while not (_REPO_ROOT / "agents/manifest.json").exists():
    _REPO_ROOT = _REPO_ROOT.parent
_AGENTS = _REPO_ROOT / "agents"
_CANONICAL = _AGENTS / "shared/personas/plan-architect.md"
_MANIFEST_GENERATOR = _REPO_ROOT / "scripts/update-agent-manifest.py"

# Design §4: the nine plan lifecycle tools, in lifecycle order.
PLAN_MCP_TOOLS: tuple[str, ...] = (
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

# #12 (T4.1) registers these three; the persona names them ahead of that landing
# so the two Phase-4 branches merge without a second persona edit.
_LANDING_WITH_12: frozenset[str] = frozenset(
    {"set_study_plan_milestone", "evaluate_study_plan", "delete_study_plan"}
)

# The CLI fallback must cover every lifecycle step that HAS a CLI command.
# ``delete`` is deliberately absent: there is no ``studyloop plan delete``
# (deletion is the Web UI or ``delete_study_plan`` with explicit confirmation),
# and the prompt-contract test rejects any invocation that does not resolve.
_CLI_FALLBACK_SUBCOMMANDS: tuple[str, ...] = (
    "interview",
    "list",
    "show",
    "new",
    "status",
    "milestone",
    "evaluate",
    "record",
)

_MCP_HEADING_RE = re.compile(r"^#{2,3} .*\bMCP\b.*$", re.MULTILINE)
_CLI_HEADING_RE = re.compile(r"^#{2,3} .*\bCLI fallback\b.*$", re.MULTILINE)

# ``build_canonical_persona("focus", "Python", 5)`` at 205819c7 (the tip
# feat/p4-13b branched from), with the three session paths fixed below so the
# digest does not depend on the machine's config directory. A change here is a
# change to what every default session ships — make it deliberately, in the same
# commit as the persona edit, never as a side effect of an architect change.
# A content digest of a public persona rendering, not a credential.
_FOCUS_SHA256_AT_205819C7 = (
    "2d35c22a99ed72fbc91e8a79ad05312b04af2e36bbb5a7bb4d7ac4a0e9ef11e0"  # pragma: allowlist secret
)


def _planning_persona() -> str:
    """The persona a ``planning``-purpose launch ships (design §5), brief and all."""
    mode = persona_mode_for("planning")
    return build_canonical_persona(mode, "Study plan", 5, brief="- interview item one")


def _section(content: str, heading_re: re.Pattern[str]) -> tuple[int, str]:
    """Return ``(start, text)`` of the section a heading opens, up to the next
    heading of the same or a higher level."""
    match = heading_re.search(content)
    assert match, f"no heading matches {heading_re.pattern!r}"
    level = len(match.group(0)) - len(match.group(0).lstrip("#"))
    closer = re.compile(rf"^#{{1,{level}}} ", re.MULTILINE)
    following = closer.search(content, match.end())
    end = following.start() if following else len(content)
    return match.start(), content[match.start() : end]


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    assert end != -1, "frontmatter opened with '---' but never closed"
    return text[end + len("\n---\n") :]


# ---------------------------------------------------------------------------
# RED for T4.2: the nine tools, the fallback, and the order of preference.
# ---------------------------------------------------------------------------


def test_plan_architect_persona_names_the_nine_mcp_tools_when_purpose_is_planning() -> None:
    content = _planning_persona()

    missing = [name for name in PLAN_MCP_TOOLS if f"`{name}" not in content]
    assert not missing, f"planning persona does not name {missing}"

    assert "CLI fallback" in content
    _, cli_section = _section(content, _CLI_HEADING_RE)
    absent = [
        sub
        for sub in _CLI_FALLBACK_SUBCOMMANDS
        if not re.search(rf"studyloop plan {sub}\b", cli_section)
    ]
    assert not absent, f"CLI fallback section names no `studyloop plan {absent}`"
    assert "studyloop plan delete" not in content, "there is no such command"


def test_plan_architect_persona_prefers_mcp_over_cli_ordering() -> None:
    content = _planning_persona()

    mcp_at, mcp_section = _section(content, _MCP_HEADING_RE)
    cli_at, _ = _section(content, _CLI_HEADING_RE)
    assert mcp_at < cli_at, "the MCP tools must be introduced before the CLI fallback"
    assert mcp_at + len(mcp_section) <= cli_at, "the MCP section must close before the fallback"
    assert not re.search(r"studyloop plan \w", mcp_section), "a CLI recipe inside the MCP section"

    # Every one of the nine is introduced in the MCP section itself, not only
    # mentioned in passing somewhere after the fallback.
    not_in_mcp = [name for name in PLAN_MCP_TOOLS if f"`{name}" not in mcp_section]
    assert not not_in_mcp, f"MCP section does not introduce {not_in_mcp}"

    # And the fallback is framed as the fallback: no `studyloop plan` recipe
    # appears before the MCP tools have been named.
    first_cli = re.search(r"studyloop plan \w", content)
    assert first_cli is not None
    assert first_cli.start() > mcp_at, "a CLI recipe precedes the MCP tools"


def test_mcp_section_states_the_lifecycle_guards() -> None:
    """The three behaviours the seam enforces and the persona must not talk the
    agent past: activate only when readiness says ready, delete only on explicit
    confirmation, evaluate as a preview unless recording is meant."""
    _, mcp_section = _section(_planning_persona(), _MCP_HEADING_RE)
    lowered = mcp_section.lower()

    assert "readiness" in lowered and "active" in lowered
    assert "confirm" in lowered and "`delete_study_plan" in mcp_section
    assert "record=false" in lowered.replace(" ", "") or "preview" in lowered
    assert "record=true" in lowered.replace(" ", "")


def test_the_nine_are_the_registry_plus_exactly_what_12_lands() -> None:
    """Ground the test's own constant in the real registry: six of the nine are
    registered today, and the ones that are not are exactly the three #12 adds.
    Holds before and after #12 merges."""
    from studyloop.mcp.server import mcp

    registered = set(mcp._tool_manager._tools)
    unregistered = {name for name in PLAN_MCP_TOOLS if name not in registered}
    assert unregistered <= _LANDING_WITH_12, f"unexpected unregistered names: {unregistered}"
    assert "record_plan_learning" in registered


# ---------------------------------------------------------------------------
# Guards: focus untouched, projections and manifest regenerate byte-identically.
# ---------------------------------------------------------------------------


def test_focus_persona_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_state, "STATE_FILE", Path("/fixed/session-state.json"))
    monkeypatch.setattr(session_state, "TOPICS_FILE", Path("/fixed/session-topics.md"))
    monkeypatch.setattr(session_state, "PARKING_FILE", Path("/fixed/session-parking.md"))

    content = build_canonical_persona("focus", "Python", 5)

    assert hashlib.sha256(content.encode("utf-8")).hexdigest() == _FOCUS_SHA256_AT_205819C7


@pytest.mark.parametrize(
    "relative",
    [
        "claude/study-plan-architect.md",
        "opencode/study-plan-architect.md",
        "kiro/study-plan-architect/persona.md",
    ],
)
def test_projected_personas_match_canonical(relative: str) -> None:
    canonical = _CANONICAL.read_text(encoding="utf-8").lstrip("\n")
    projected = _strip_frontmatter((_AGENTS / relative).read_text(encoding="utf-8")).lstrip("\n")
    assert projected == canonical, f"agents/{relative} has drifted from the canonical persona"


def test_manifest_hashes_regenerate_byte_identically_for_the_architect_projections() -> None:
    """Run the generator's own hash over the tracked projections and compare with
    the committed manifest — the check ``studyloop install agents`` and doctor
    rely on, without mutating the tracked manifest from a test."""
    spec = importlib.util.spec_from_file_location("update_agent_manifest", _MANIFEST_GENERATOR)
    assert spec is not None and spec.loader is not None
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)

    manifest = json.loads((_AGENTS / "manifest.json").read_text(encoding="utf-8"))["agents"]
    tracked = [
        rel
        for files in generator.TRACKED_FILES.values()
        for rel in files
        if "study-plan-architect" in rel
    ]
    assert tracked, "the generator tracks no architect projection at all"
    stale = {
        rel: (manifest.get(rel, {}).get("hash"), generator.hash_file(_AGENTS / rel))
        for rel in tracked
        if manifest.get(rel, {}).get("hash") != generator.hash_file(_AGENTS / rel)
    }
    assert not stale, f"re-run scripts/update-agent-manifest.py: {stale}"
