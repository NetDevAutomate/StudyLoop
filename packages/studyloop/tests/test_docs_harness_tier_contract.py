"""The documented core/preview split must equal ``harnesses.CORE_HARNESSES``.

Issue #21's congruence review found the docs and code AGREEING that OpenCode,
pi and Grok Build were preview -- and required that when the tier changes,
every document stating the split changes in the same commit, pinned by a test
so docs can never again outrun (or lag) the code. This module is that pin:
each test PARSES a document's own statement of the split into a set of
harness names and compares it with the code, in the pattern of
``packages/agent-session-tools/tests/test_docs_semantic_layer_contract.py``
(derive from real symbols, parse rather than substring-sweep, no line
numbers, no copied prose).

Label -> name mapping comes from ``harnesses.HARNESSES`` itself, so a renamed
label fails here instead of silently matching nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

from studyloop.harnesses import CORE_HARNESSES, HARNESSES, PREVIEW_HARNESSES, RELEASE_HARNESSES

REPO_ROOT = Path(__file__).resolve().parents[3]

_LABEL_TO_NAME = {h.label: name for name, h in HARNESSES.items()}
_BINARY_TO_NAME = {h.binary: name for name, h in HARNESSES.items()}


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def _names_in(text: str) -> set[str]:
    """Every harness whose LABEL appears in ``text`` (longest labels first, so
    "Kiro CLI" is not also counted as a bare "Kiro")."""
    found: set[str] = set()
    remaining = text
    for label in sorted(_LABEL_TO_NAME, key=len, reverse=True):
        if re.search(rf"(?<![A-Za-z]){re.escape(label)}(?![A-Za-z])", remaining):
            found.add(_LABEL_TO_NAME[label])
            remaining = remaining.replace(label, " ")
    return found


class TestAgentInstallDoc:
    """docs/agent-install.md §"Supported in the initial pre-release"."""

    def _section(self) -> str:
        text = _read("docs/agent-install.md")
        match = re.search(
            r"^## Supported in the initial pre-release\n(.*?)(?=^## )", text, re.S | re.M
        )
        assert match, (
            "docs/agent-install.md lost its 'Supported in the initial pre-release' section"
        )
        return match.group(1)

    def test_core_bullets_equal_core_harnesses(self) -> None:
        section = self._section()
        intro = re.search(r"core release harnesses are:\n\n((?:- .*\n)+)", section)
        assert intro, "the section must introduce the core list with 'core release harnesses are:'"
        bullets = [line[2:] for line in intro.group(1).splitlines()]
        documented = set().union(*(_names_in(b) for b in bullets))
        assert documented == set(CORE_HARNESSES), (
            f"agent-install.md core bullets name {sorted(documented)}, "
            f"code CORE_HARNESSES is {sorted(CORE_HARNESSES)}"
        )
        assert len(bullets) == len(CORE_HARNESSES), "one bullet per core harness"

    def test_preview_sentence_equals_preview_harnesses(self) -> None:
        section = self._section()
        # The paragraph, not the sentence: the labels sit in one sentence and
        # the word "preview" in the next ("... **pi** ... . They are shown as
        # preview harnesses until ...").
        paragraphs = [p for p in re.split(r"\n\s*\n", section) if "preview" in p.lower()]
        assert paragraphs, "the section must say which harnesses are preview"
        documented = set().union(*(_names_in(p) for p in paragraphs))
        assert documented == set(PREVIEW_HARNESSES), (
            f"agent-install.md preview wording names {sorted(documented)}, "
            f"code PREVIEW_HARNESSES is {sorted(PREVIEW_HARNESSES)}"
        )


class TestContributingSplitSentence:
    """CONTRIBUTING.md and docs/contributing.md each carry one
    "<labels> are core; <labels> are preview" statement."""

    def _split(self, rel_path: str) -> tuple[set[str], set[str]]:
        text = re.sub(r"\s+", " ", _read(rel_path))
        match = re.search(r"\(?([^.;()]*?) are\s+core;\s*([^.;()]*?) are preview", text)
        assert match, f"{rel_path} lost its 'X are core; Y are preview' statement"
        return _names_in(match.group(1)), _names_in(match.group(2))

    def test_contributing_md(self) -> None:
        core, preview = self._split("CONTRIBUTING.md")
        assert core == set(CORE_HARNESSES)
        assert preview == set(PREVIEW_HARNESSES)

    def test_docs_contributing_md(self) -> None:
        core, preview = self._split("docs/contributing.md")
        assert core == set(CORE_HARNESSES)
        assert preview == set(PREVIEW_HARNESSES)

    def test_release_count_words_match(self) -> None:
        words = {3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}
        expected = words[len(RELEASE_HARNESSES)]
        for rel_path in ("CONTRIBUTING.md", "docs/contributing.md"):
            text = _read(rel_path).lower()
            assert re.search(
                rf"\b{expected}\b[^.]*mentor harnesses|\b{expected}\b first-party", text
            ), f"{rel_path} must state {expected} harnesses (len(RELEASE_HARNESSES))"


class TestInstallMentorDetectionBlock:
    """agents/shared/install-mentor.md annotates each `which <binary>` with its tier."""

    def test_tier_annotations_match_code(self) -> None:
        text = _read("agents/shared/install-mentor.md")
        tiers: dict[str, str] = {}
        for binary, tier in re.findall(r"^which (\S+) .*?#\s*.*?\((core|preview)\)", text, re.M):
            tiers[_BINARY_TO_NAME[binary]] = tier
        assert set(tiers) == set(RELEASE_HARNESSES), "every release binary must be annotated"
        assert {n for n, t in tiers.items() if t == "core"} == set(CORE_HARNESSES)
        assert {n for n, t in tiers.items() if t == "preview"} == set(PREVIEW_HARNESSES)


class TestAcceptanceCoverageTable:
    """docs/acceptance-testing.md's coverage inventory tags PREVIEW rows explicitly."""

    def test_preview_tags_match_code(self) -> None:
        text = _read("docs/acceptance-testing.md")
        rows = re.findall(r"^\| (\w+)( \(PREVIEW\))? \|", text, re.M)
        tagged = {name for name, tag in rows if tag}
        untagged = {name for name, tag in rows if not tag and name in RELEASE_HARNESSES}
        assert tagged == set(PREVIEW_HARNESSES), (
            f"coverage table tags {sorted(tagged)} as PREVIEW; "
            f"code says {sorted(PREVIEW_HARNESSES)}"
        )
        assert untagged == set(CORE_HARNESSES)


class TestArchitectureDiagram:
    """docs/architecture/current.md's agent-CLI subgraph marks preview nodes."""

    def test_preview_nodes_match_code(self) -> None:
        text = _read("docs/architecture/current.md")
        block = re.search(r'subgraph "AI agent CLIs.*?\n(.*?)\n\s*end', text, re.S)
        assert block, "current.md lost its 'AI agent CLIs' subgraph"
        preview: set[str] = set()
        core: set[str] = set()
        for line in block.group(1).splitlines():
            names = _names_in(line.split("<br/>")[0])
            if not names:
                continue
            (preview if "preview" in line.lower() else core).update(names)
        assert preview == set(PREVIEW_HARNESSES)
        assert core == set(CORE_HARNESSES)


class TestHarnessRecordsAgreeWithTiers:
    def test_core_flag_mirrors_the_tuples(self) -> None:
        assert {n for n, h in HARNESSES.items() if h.core} == set(CORE_HARNESSES)
        assert {n for n, h in HARNESSES.items() if not h.core} == set(PREVIEW_HARNESSES)
