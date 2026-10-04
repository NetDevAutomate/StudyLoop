"""Keep the public contributor handbook connected to maintained examples."""

from __future__ import annotations

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
    guide = (ROOT / "docs/contributor-modules.md").read_text(encoding="utf-8")
    assert "not a shipped plugin API or registry" in guide
    assert "not an automatically executed setup hook" in guide
    assert "Catalogue inclusion should never silently authorize execution" in guide
