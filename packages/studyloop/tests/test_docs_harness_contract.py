"""Doc-contract tests for the six-harness scope (L2-harness-scope).

``studyloop.harnesses`` is the single source of truth for which coding
harnesses StudyLoop supports and how they are split (core vs preview). These
tests compare SETS derived from that module (and the other code symbols that
mirror it) against what the in-scope docs actually say, so a docs/code drift
like "five harnesses" or a dangling "grok" gap fails a test instead of a
reviewer's eyeball.

No line numbers, no copied prose sentences, no "every command must appear as
a substring" sweeps -- every assertion here is set/symbol comparison or a
narrowly scoped regex the DECISIONS record calls for.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from studyloop.harnesses import HARNESSES, PREVIEW_HARNESSES, RELEASE_HARNESSES

REPO_ROOT = Path(__file__).resolve().parents[3]

# Files this lane (L2-harness-scope) owns. A doc's harness-count claim,
# harness roster, and stale-version wording are checked against these only --
# other docs with unrelated drift belong to other lanes.
_IN_SCOPE_DOC_FILES = (
    "CONTRIBUTING.md",
    "agents/shared/install-mentor.md",
    "docs/agent-install.md",
    "docs/architecture/current.md",
    "docs/architecture/pi-harness-integration.md",
    "docs/architecture/target.md",
    "docs/contributing.md",
    "docs/first-week.md",
    "docs/setup-guide.md",
    "packages/agent-session-tools/README.md",
)

# (a) files whose prose should name every harness by its product label.
_HARNESS_ROSTER_FILES = (
    "README.md",
    "CONTRIBUTING.md",
    "docs/contributing.md",
    "docs/agent-install.md",
    "agents/shared/install-mentor.md",
    "packages/agent-session-tools/README.md",
)

_NUMBER_WORDS = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
}
_CORRECT_COUNT_WORD = _NUMBER_WORDS[len(HARNESSES)]
assert _CORRECT_COUNT_WORD == "six"


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel_path", _HARNESS_ROSTER_FILES)
def test_every_harness_label_named(rel_path: str) -> None:
    text = _read(rel_path)
    missing = [h.label for h in HARNESSES.values() if h.label not in text]
    assert not missing, f"{rel_path} is missing harness label(s): {missing}"


@pytest.mark.parametrize("rel_path", _IN_SCOPE_DOC_FILES)
def test_five_does_not_appear_near_harness(rel_path: str) -> None:
    """DECISIONS (A6): 'five' must not appear within 80 chars of 'harness' --

    the release grew from five to six harnesses (Grok Build re-admitted), so a
    stray 'five' next to 'harness' is stale count wording, not a false alarm.
    """
    text = _read(rel_path)
    harness_positions = [m.start() for m in re.finditer(r"harness", text, re.IGNORECASE)]
    offenders = [
        text[max(0, m.start() - 40) : m.start() + 40]
        for m in re.finditer(r"\bfive\b", text, re.IGNORECASE)
        if any(abs(m.start() - hp) <= 80 for hp in harness_positions)
    ]
    assert not offenders, f"{rel_path}: 'five' found near 'harness': {offenders}"


@pytest.mark.parametrize(
    "rel_path",
    (
        "CONTRIBUTING.md",
        "docs/contributing.md",
    ),
)
def test_stated_harness_count_word_is_six(rel_path: str) -> None:
    """Where a doc states '<count-word> ... harness(es)' as a release-scope

    claim, that count word is 'six' -- the number-word for len(HARNESSES).
    """
    text = _read(rel_path)
    count_claims = re.findall(
        r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\b"
        r"[^.\n]{0,20}?harnesses?\b",
        text,
        re.IGNORECASE,
    )
    assert count_claims, f"{rel_path} should state a harness-count claim"
    assert all(word.lower() == _CORRECT_COUNT_WORD for word in count_claims), (
        f"{rel_path} states a harness count other than {_CORRECT_COUNT_WORD!r}: {count_claims}"
    )


@pytest.mark.parametrize("rel_path", ("CONTRIBUTING.md", "docs/contributing.md"))
def test_no_stale_version_pin(rel_path: str) -> None:
    """Version wording is version-independent (A6): no literal 0.<n>.x pin."""
    text = _read(rel_path)
    assert not re.search(r"0\.\d+\.x", text), f"{rel_path} still pins a literal 0.x.y version"


def test_grok_build_not_described_as_a_non_mentor() -> None:
    """packages/agent-session-tools/README.md must not call Grok a non-mentor.

    Grok Build ships an automatic SessionEnd hook (installers.py) and is a
    PREVIEW_HARNESSES member, so "Grok is ... not a StudyLoop mentor" is a
    stale claim.
    """
    assert "grok" in PREVIEW_HARNESSES
    text = _read("packages/agent-session-tools/README.md")
    assert "not a StudyLoop mentor" not in text


def test_install_mentor_detection_block_names_all_six_binaries() -> None:
    text = _read("agents/shared/install-mentor.md")
    missing = [h.binary for h in HARNESSES.values() if f"which {h.binary}" not in text]
    assert not missing, f"install-mentor.md detection block is missing: {missing}"


def test_session_export_docstrings_name_every_harness_source() -> None:
    """(b) The export module docstring and the export() command docstring --

    which is what ``session-export --help`` renders -- must name every value
    of SESSION_SOURCE_BY_HARNESS, not just the harnesses that shipped first.
    """
    import agent_session_tools.export_sessions as export_sessions_module
    from studyloop.harnesses import SESSION_SOURCE_BY_HARNESS

    module_doc = export_sessions_module.__doc__ or ""
    command_doc = export_sessions_module.export.__doc__ or ""
    assert "grok" in module_doc.lower(), "module docstring is missing a grok source line"
    for source in SESSION_SOURCE_BY_HARNESS.values():
        assert source in command_doc, f"export() docstring missing source {source!r}"


def test_session_export_help_names_every_harness_source() -> None:
    """(b) The rendered ``session-export --help`` text is a real CLI contract."""
    from typer.testing import CliRunner

    from agent_session_tools.export_sessions import app

    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "grok" in result.output


def test_first_week_extract_struggles_examples_pass_harness() -> None:
    """(c) Every fenced 'studyloop extract-struggles ...' example names --harness."""
    text = _read("docs/first-week.md")
    offenders = [
        line
        for line in text.splitlines()
        if "studyloop extract-struggles" in line and "--harness" not in line
    ]
    assert not offenders, f"extract-struggles example(s) missing --harness: {offenders}"


_LINK_RE = re.compile(r"\]\(([^)]+\.md(?:#[^)]*)?)\)")


@pytest.mark.parametrize("rel_path", tuple(f for f in _IN_SCOPE_DOC_FILES if f.endswith(".md")))
def test_relative_markdown_links_resolve(rel_path: str) -> None:
    """(d) Every relative '](path.md...)' link in an in-scope doc resolves."""
    path = REPO_ROOT / rel_path
    text = path.read_text(encoding="utf-8")
    broken = []
    for m in _LINK_RE.finditer(text):
        target = m.group(1)
        if target.startswith("http://") or target.startswith("https://"):
            continue
        target_path = target.split("#", 1)[0]
        resolved = (path.parent / target_path).resolve()
        if not resolved.exists():
            broken.append(target)
    assert not broken, f"{rel_path} has dead relative link(s): {broken}"


def test_current_architecture_mcp_claim_matches_installers() -> None:
    """(e) current.md must not claim MCP is Kiro-only when more harnesses register it."""
    from studyloop.installers import _MCP_HARNESSES

    assert len(_MCP_HARNESSES) > 1
    text = _read("docs/architecture/current.md")
    assert "only the Kiro adapter" not in text
    assert "Kiro only" not in text


def test_target_architecture_names_every_acp_capable_agent() -> None:
    """(e) target.md's 'ACP becomes the preferred transport' sentence names every

    harness in ACP_CAPABLE_AGENTS, not a hardcoded 'Kiro only'.
    """
    from studyloop.web.services.session_start import ACP_CAPABLE_AGENTS

    text = _read("docs/architecture/target.md")
    sentence_match = re.search(r"ACP becomes the preferred transport[^.]*\.", text)
    assert sentence_match, "target.md is missing the ACP transport sentence"
    sentence = sentence_match.group(0)
    missing = [
        HARNESSES[agent].label
        for agent in ACP_CAPABLE_AGENTS
        if agent in HARNESSES and HARNESSES[agent].label not in sentence
    ]
    assert not missing, f"ACP sentence is missing capable agent(s): {missing}"


def test_pi_harness_integration_grok_row_matches_installers() -> None:
    """(e) The Grok Build export-comparison row must match installers.py's

    live wiring (install_grok_session_end_hook + the grok steering mandate),
    not the 'none today' claim from before that wiring shipped.
    """
    from studyloop.installers import _HARNESS_EXPORT, _grok_hooks_path

    text = _read("docs/architecture/pi-harness-integration.md")
    row_match = re.search(r"\| Grok Build[^\n]*\|", text)
    assert row_match, "pi-harness-integration.md is missing a Grok Build row"
    row = row_match.group(0)
    assert "none today" not in row
    assert "GROK_HOME/hooks" in row
    assert "GROK_HOME/rules" in row
    assert "grok" in _HARNESS_EXPORT
    assert callable(_grok_hooks_path)


def test_pi_harness_integration_has_no_stale_line_number_citations() -> None:
    """(e)/(f) doctor/harness.py line-number citations go stale; use function

    names instead, per the DECISIONS record.
    """
    text = _read("docs/architecture/pi-harness-integration.md")
    offenders = re.findall(r"doctor/harness\.py:\d+", text)
    assert not offenders, f"stale doctor/harness.py line citation(s): {offenders}"


def test_no_kirocrew_token_anywhere_tracked() -> None:
    """(f) FORBIDDEN-TOKEN LOCK (A18): 'kirocrew' must never reappear."""
    import subprocess

    result = subprocess.run(
        ["git", "grep", "-i", "-l", "-E", "kirocrew|kiro[-_ ]?crew"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    hits = [
        line
        for line in result.stdout.splitlines()
        if line != "packages/studyloop/tests/test_docs_harness_contract.py"
    ]
    assert not hits, f"forbidden token 'kirocrew' reappeared in: {hits}"


def test_release_harnesses_still_has_no_gemini() -> None:
    """Sanity guard alongside the roster checks above."""
    assert "gemini" not in RELEASE_HARNESSES
