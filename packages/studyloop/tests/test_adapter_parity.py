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
