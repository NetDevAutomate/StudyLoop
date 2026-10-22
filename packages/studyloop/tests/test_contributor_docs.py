"""Keep the public contributor handbook connected to maintained examples."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "name", ["contributor-code-map.md", "contributor-testing.md", "contributor-modules.md"]
)
def test_handbook_page_is_published_and_linked(name: str) -> None:
    config = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    allowlist, _, navigation = config.partition("nav:")
    assert (ROOT / "docs" / name).is_file()
    assert f"!/{name}" in allowlist
    assert name in navigation
    assert name in (ROOT / "docs/contributing.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "relative_path",
    [
        "packages/studyloop/tests/test_contributor_examples.py",
        "packages/studyloop/tests/e2e/test_contributor_browser_example.py",
    ],
)
def test_cookbook_links_to_real_collected_examples(relative_path: str) -> None:
    cookbook = (ROOT / "docs/contributor-testing.md").read_text(encoding="utf-8")
    assert (ROOT / relative_path).is_file()
    assert f"/blob/main/{relative_path}" in cookbook


def test_module_guide_preserves_proposal_and_execution_boundaries() -> None:
    """module-contract v1 shipped (W-review finding 9): the page now says so and names the
    contract page as the authority; the two execution boundaries it states are unchanged."""
    guide = (ROOT / "docs/contributor-modules.md").read_text(encoding="utf-8")
    assert "shipped" in guide and "no registry" in guide
    assert "not a shipped plugin API or registry" not in guide
    assert "(module-contract.md)" in guide
    assert "not an automatically executed setup hook" in guide
    assert "Catalogue inclusion should never silently authorize execution" in guide


# --- Changelog guide vs CHANGELOG.md (ADR-0016; plan 4, lane N, G#1) -------------------------

#: Keep a Changelog's six section names, which the guide cites as its authority.
_KEEP_A_CHANGELOG_SECTIONS = frozenset(
    {"Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"}
)
_GUIDE_SECTION_LIST_RE = re.compile(r"`### (\w+)`")
_H2_RE = re.compile(r"^## (.+?)\s*$", re.MULTILINE)
_H3_RE = re.compile(r"^### (.+?)\s*$", re.MULTILINE)


def _guide_section_order() -> list[str]:
    """The section names the guide's step 2 lists, in the order it gives them."""
    guide = (ROOT / "docs/contributor-changelog.md").read_text(encoding="utf-8")
    step_two = guide.split("2. Pick the section", 1)[1].split("\n3.", 1)[0]
    return _GUIDE_SECTION_LIST_RE.findall(step_two)


def _unreleased_sections() -> list[str]:
    """The ``###`` headings under ``## [Unreleased]`` in CHANGELOG.md, in order."""
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    h2_starts = [m.start() for m in _H2_RE.finditer(changelog)]
    start = changelog.index("## [Unreleased]")
    end = next((s for s in h2_starts if s > start), len(changelog))
    return _H3_RE.findall(changelog[start:end])


def test_changelog_guide_permits_every_keep_a_changelog_section() -> None:
    """The guide lists exactly the Keep a Changelog sections it cites as its authority;
    ADR-0016 required a ``Deprecated`` entry, which a five-section list told reviewers
    to strike."""
    order = _guide_section_order()
    assert set(order) == _KEEP_A_CHANGELOG_SECTIONS, order
    assert len(order) == len(set(order)), order
    guide = (ROOT / "docs/contributor-changelog.md").read_text(encoding="utf-8")
    assert "outside the five" not in guide
    table_sections = set(re.findall(r"^\| [^|]+ \| (\w+) \|", guide, re.MULTILINE))
    assert table_sections >= _KEEP_A_CHANGELOG_SECTIONS, table_sections


def test_unreleased_changelog_sections_follow_the_guide() -> None:
    """Every ``###`` under ``[Unreleased]`` is one the guide permits, and they appear in
    the guide's order, so a reviewer applying the guide never strikes a valid section."""
    order = _guide_section_order()
    used = _unreleased_sections()
    assert used, "CHANGELOG.md has no sections under [Unreleased]"
    unknown = [name for name in used if name not in order]
    assert not unknown, f"sections the guide does not permit: {unknown}"
    assert used == sorted(used, key=order.index), f"out of the guide's order: {used}"
    assert len(used) == len(set(used)), f"duplicate section under [Unreleased]: {used}"
