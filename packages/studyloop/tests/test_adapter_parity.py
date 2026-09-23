"""Parity guard: the six supported adapters agree at every layer.

Andy's 2026-09-10 ruling fixes the supported set at exactly kiro, claude,
codex, opencode, pi and grok (Grok Build) -- see
``docs/architecture/session-memory/receipts/adapter-scope-2026-09-10.md``.

Before this guard, the set lived in six places that could each drift alone:
the harness contract, the doctor table, the installer links, the exporter
registry, the export CLI's ``--sources`` choices, and the extractor's source
filter. ``80d24e48`` dropped grok from the launch layers while the exporter
kept it, and nothing failed. This file holds the ONE literal; every layer
must equal it, so the next drift fails here with the layer named.
"""

from __future__ import annotations

import re
from pathlib import Path

from agent_session_tools.export_sessions import SOURCE_CHOICES
from agent_session_tools.exporters import EXPORTERS
from studyloop import installers
from studyloop.doctor.agents import TOOL_AGENTS
from studyloop.extractors.pipeline import STUDY_SOURCES
from studyloop.harnesses import HARNESSES, RELEASE_HARNESSES, SESSION_SOURCE_BY_HARNESS
from studyloop.web.services.session_start import ACP_CAPABLE_AGENTS

#: The ruling. Harness ids as used by ``harnesses.py`` and the exporter registry.
EXPECTED_HARNESSES = frozenset({"kiro", "claude", "codex", "opencode", "pi", "grok"})

#: The ``sessions.source`` labels those six harnesses write. Two differ from
#: the harness id (``kiro_cli``, ``claude_code``); the rest coincide.
EXPECTED_SOURCES = frozenset({"kiro_cli", "claude_code", "codex", "opencode", "pi", "grok"})

REPO_ROOT = Path(__file__).resolve().parents[3]


def _layer_diff(name: str, actual: set[str]) -> str:
    return (
        f"{name} disagrees with the six-adapter ruling: "
        f"missing {sorted(EXPECTED_HARNESSES - actual)}, "
        f"unexpected {sorted(actual - EXPECTED_HARNESSES)}"
    )


def test_release_contract_is_exactly_the_six() -> None:
    assert len(RELEASE_HARNESSES) == len(set(RELEASE_HARNESSES)), "duplicate harness id"
    assert set(RELEASE_HARNESSES) == EXPECTED_HARNESSES, _layer_diff(
        "RELEASE_HARNESSES", set(RELEASE_HARNESSES)
    )


def test_launch_layers_enumerate_the_same_six() -> None:
    layers = {
        "harnesses.HARNESSES": set(HARNESSES),
        "harnesses.SESSION_SOURCE_BY_HARNESS": set(SESSION_SOURCE_BY_HARNESS),
        "doctor.agents.TOOL_AGENTS": set(TOOL_AGENTS),
        "installers._TOOL_LINKS": set(installers._TOOL_LINKS),
    }
    for name, actual in layers.items():
        assert actual == EXPECTED_HARNESSES, _layer_diff(name, actual)


def test_session_export_layers_enumerate_the_same_six() -> None:
    assert set(EXPORTERS) == EXPECTED_HARNESSES, _layer_diff("exporters.EXPORTERS", set(EXPORTERS))
    assert set(SOURCE_CHOICES) == EXPECTED_HARNESSES, _layer_diff(
        "export_sessions.SOURCE_CHOICES", set(SOURCE_CHOICES)
    )


def test_source_labels_agree_between_contract_and_extractor() -> None:
    assert set(SESSION_SOURCE_BY_HARNESS.values()) == EXPECTED_SOURCES
    assert STUDY_SOURCES == EXPECTED_SOURCES, (
        "extractors.pipeline.STUDY_SOURCES must be derived from the harness contract: "
        f"missing {sorted(EXPECTED_SOURCES - STUDY_SOURCES)}, "
        f"unexpected {sorted(STUDY_SOURCES - EXPECTED_SOURCES)}"
    )


def test_acp_capable_set_is_a_subset_of_the_six() -> None:
    assert ACP_CAPABLE_AGENTS <= EXPECTED_HARNESSES, sorted(ACP_CAPABLE_AGENTS - EXPECTED_HARNESSES)


def test_readme_names_every_supported_harness_by_its_label() -> None:
    """The README is the first thing a new user reads; it must name all six."""
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    missing = [
        harness.label
        for harness in HARNESSES.values()
        if not re.search(rf"\b{re.escape(harness.label)}\b", text)
    ]
    assert not missing, f"README.md does not name these supported harnesses: {missing}"


# ---------------------------------------------------------------------------
# Learning tier, item 1 (S1-RED): the writers are NAMED everywhere, GRANTED nowhere new
# ---------------------------------------------------------------------------
#
# Owner decision 2 (docs/architecture/learning-tier/plan-2026-09-19.md §7): the
# additive writers are named in every harness definition and stay prompt-per-call;
# no harness gains a pre-approval on this branch. Parity is of the instruction,
# never of approval -- codex, pi and grok cannot express approval in this repo.
# The S1-0 receipt (docs/architecture/learning-tier/receipts/s1-0-capability-lock.md)
# records the cells these tests pin.

#: The additive, learner-agreed writers (``record_teachback`` is the new one).
W_AUTO = ("log_topic", "log_struggle", "record_teachback", "record_plan_learning")

#: The mentor definition each harness actually loads. Grok Build reads the same
#: canonical file as Codex (its header says so; ``adapters/grok.py`` projects it).
MENTOR_DEFINITIONS = {
    "kiro": "agents/kiro/study-mentor/persona.md",
    "claude": "agents/claude/socratic-mentor.md",
    "opencode": "agents/opencode/study-mentor.md",
    "codex": "agents/codex/AGENTS.md",
    "pi": "agents/pi/AGENTS.md",
    "grok": "agents/codex/AGENTS.md",
}


def _definition(harness: str) -> str:
    return (REPO_ROOT / MENTOR_DEFINITIONS[harness]).read_text(encoding="utf-8")


def test_mentor_definitions_cover_exactly_the_six() -> None:
    assert set(MENTOR_DEFINITIONS) == EXPECTED_HARNESSES


def test_every_mentor_definition_names_each_w_auto_writer() -> None:
    """A writer the definition never names is a writer the mentor never calls."""
    missing = {
        harness: [w for w in W_AUTO if not re.search(rf"\b{w}\b", _definition(harness))]
        for harness in sorted(MENTOR_DEFINITIONS)
    }
    missing = {h: ws for h, ws in missing.items() if ws}
    assert not missing, f"W_auto writers not named: {missing}"


def test_claude_mentor_tools_line_names_each_writer() -> None:
    """Claude's sub-agent frontmatter restricts tools to the ``tools:`` line;
    an unnamed MCP tool is unreachable there, whatever the permissions say."""
    text = _definition("claude")
    match = re.search(r"^tools:\s*(.+)$", text, flags=re.MULTILINE)
    assert match, "socratic-mentor.md has no frontmatter tools: line"
    named = {item.strip() for item in match.group(1).split(",")}
    missing = [w for w in W_AUTO if f"mcp__studyloop__{w}" not in named]
    assert not missing, f"tools: line does not name {missing}; it names {sorted(named)}"


def test_kiro_gains_no_pre_approval() -> None:
    """The one recorded asymmetry stays exactly one: ``log_topic``."""
    import json

    spec = json.loads((REPO_ROOT / "agents/kiro/study-mentor.json").read_text(encoding="utf-8"))
    allowed = set(spec["allowedTools"])
    assert allowed & {f"@studyloop/{w}" for w in W_AUTO} == {"@studyloop/log_topic"}


def test_claude_settings_grant_nothing() -> None:
    import json

    settings = json.loads((REPO_ROOT / "agents/claude/settings.json").read_text(encoding="utf-8"))
    assert "permissions" not in settings, "decision 2: no permissions block on Claude"


def test_opencode_permission_block_is_exactly_as_recorded() -> None:
    """Recorded as known and not least-privilege in the S1-0 receipt; unchanged here."""
    text = _definition("opencode")
    for line in (
        '"studyloop *": allow',
        '"session-* *": allow',
        '"uv run tutor-*": allow',
        '"*": ask',
    ):
        assert line in text, f"opencode permission block changed: {line!r} missing"
