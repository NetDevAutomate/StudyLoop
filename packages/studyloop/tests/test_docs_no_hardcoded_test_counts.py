"""R-62 guard: no live public page or release note copies a test total.

CONTRIBUTING.md states the rule in the imperative: "Do not copy a test
total into a document or release note. The executing gate is the authority
and its current output belongs in machine-readable release evidence."
`releases/v0.1.0.md:54` broke its own sibling public page's rule by
hardcoding "502 tests" -- a number that drifts the moment the suite grows,
silently making the release note wrong with no signal.

Scope is the live public contract, not the whole repo: the 16 pages
`mkdocs.yml`'s `exclude_docs` allowlist actually publishes (parsed from that
file, not hardcoded, so this test tracks the nav contract), plus the
top-level `README.md`, `CHANGELOG.md`, and `releases/v0.1.0.md`.
`docs/archive/**`, `docs/handoffs/**`, `docs/plans/**`, and other
internal-by-default trees (CONTRIBUTING.md's own "keep these internal"
list) are point-in-time historical records -- freezing a real number from
the day they were written is honest, not the anti-pattern this guards
against.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MKDOCS_YML = REPO_ROOT / "mkdocs.yml"
DOCS_DIR = REPO_ROOT / "docs"

_HARDCODED_COUNT_RE = re.compile(r"\b\d{3,}\+?\s+tests?\b", re.IGNORECASE)

_EXTRA_LIVE_FILES = ("README.md", "CHANGELOG.md", "releases/v0.1.0.md")


def _public_doc_pages() -> list[Path]:
    """Every page mkdocs.yml's exclude_docs allowlist actually un-excludes.

    exclude_docs is ``**`` (exclude everything) followed by ``!/name.md``
    negation lines that re-include specific pages -- those negation lines
    are the public-page allowlist.
    """
    text = MKDOCS_YML.read_text(encoding="utf-8")
    exclude_block = text.split("exclude_docs:", 1)[1]
    pages = []
    for line in exclude_block.splitlines():
        stripped = line.strip()
        if not stripped.startswith("!/"):
            if stripped and not stripped.startswith("-") and ":" in stripped:
                break  # next top-level YAML key ends the block
            continue
        name = stripped.removeprefix("!/")
        if name.endswith("/**") or not name.endswith(".md"):
            continue  # asset directories (images/, stylesheets/, ...), not pages
        pages.append(DOCS_DIR / name)
    return pages


def _live_files() -> list[Path]:
    files = _public_doc_pages()
    files.extend(REPO_ROOT / name for name in _EXTRA_LIVE_FILES)
    return files


def test_public_doc_pages_parses_to_a_real_allowlist() -> None:
    """Sanity check the parser actually found pages, not zero."""
    pages = _public_doc_pages()
    assert len(pages) >= 10, f"expected >=10 public pages, parsed {len(pages)}: {pages}"
    for page in pages:
        assert page.is_file(), f"{page} is in mkdocs.yml's allowlist but does not exist"


def test_no_live_public_file_hardcodes_a_test_count() -> None:
    offenders = []
    for path in _live_files():
        if not path.is_file():
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _HARDCODED_COUNT_RE.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{line_no}: {line.strip()}")
    assert not offenders, (
        "hardcoded test count(s) in a live public page or release note "
        "(CONTRIBUTING.md's own rule):\n" + "\n".join(offenders)
    )
