"""D1/D2 guards: THIRD-PARTY-NOTICES.md's claims must match reality.

D1: the notices file said `vendor/` "ships 26 third-party files" -- but four
of the 26 `vendor/MANIFEST` entries are first-party CSS `@font-face` glue
sheets the repo wrote itself (marked `local` in the MANIFEST, not fetched
from anywhere). "Third-party" should count only the genuinely third-party
(non-`local`) entries, and the four first-party files should be named, not
silently folded into that count.

D2: Apache-2.0 and MPL-2.0 (DOMPurify, Fuse.js) were linked but never
reproduced -- Apache-2.0 §4 and MPL-2.0 §3.1 both require the licence text
(and any upstream NOTICE) to accompany redistribution. See
test_every_named_licence_family_has_its_full_text_present below.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
NOTICES = REPO_ROOT / "THIRD-PARTY-NOTICES.md"
MANIFEST = (
    REPO_ROOT
    / "packages"
    / "studyloop"
    / "src"
    / "studyloop"
    / "web"
    / "static"
    / "vendor"
    / "MANIFEST"
)


def _manifest_entries() -> list[tuple[str, str]]:
    """(path, source_url_or_'local') for every non-comment MANIFEST line."""
    entries = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        path, _version, _sha256, source_url = line.split("\t")
        entries.append((path, source_url))
    return entries


def test_manifest_has_both_local_and_non_local_entries() -> None:
    """Sanity check: this file's split only means something if both exist."""
    entries = _manifest_entries()
    sources = {source for _path, source in entries}
    assert "local" in sources, "expected at least one 'local' (first-party) MANIFEST entry"
    assert any(source != "local" for source in sources), (
        "expected at least one non-local (third-party) MANIFEST entry"
    )


def test_notices_third_party_count_matches_non_local_manifest_entries() -> None:
    entries = _manifest_entries()
    third_party_count = sum(1 for _path, source in entries if source != "local")
    text = NOTICES.read_text(encoding="utf-8")
    match = re.search(r"\*\*(\d+) are third-party\*\*", text)
    assert match, "expected a '**N are third-party**' sentence in THIRD-PARTY-NOTICES.md"
    claimed = int(match.group(1))
    assert claimed == third_party_count, (
        f"THIRD-PARTY-NOTICES.md claims {claimed} third-party files; "
        f"vendor/MANIFEST has {third_party_count} non-local (genuinely third-party) entries"
    )


def test_notices_names_every_first_party_glue_file() -> None:
    entries = _manifest_entries()
    local_paths = [path for path, source in entries if source == "local"]
    assert local_paths, "expected some local/first-party entries in the MANIFEST"
    text = NOTICES.read_text(encoding="utf-8")
    missing = [Path(path).name for path in local_paths if Path(path).name not in text]
    assert not missing, (
        f"first-party glue file(s) not named/acknowledged in THIRD-PARTY-NOTICES.md: {missing}"
    )


# ---------------------------------------------------------------------------
# D2: every licence family named in the JS-libraries table has its full text
# reproduced somewhere in the file (Apache-2.0 §4, MPL-2.0 §3.1 both require
# the licence text to accompany redistribution -- a link is not enough).
# ---------------------------------------------------------------------------

#: licence identifier (as it appears in the "Licence" column of the
#: JavaScript-libraries table, after splitting a cell like "Apache-2.0 OR
#: MPL-2.0" on " OR ") -> a distinctive phrase that only appears inside that
#: licence's own full text.
_LICENCE_FULL_TEXT_MARKERS: dict[str, str] = {
    "MIT": ("Permission is hereby granted, free of charge, to any person obtaining a copy"),
    "Zero-Clause BSD (0BSD)": (
        "Permission to use, copy, modify, and/or distribute this software for"
    ),
    "BSD-3-Clause": "Redistributions of source code must retain the above copyright notice",
    "Apache-2.0": "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION",
    "MPL-2.0": "Exhibit A - Source Code Form License Notice",
}


def _js_library_licence_cells() -> list[str]:
    """Every "Licence" column value from the JavaScript-libraries table."""
    text = NOTICES.read_text(encoding="utf-8")
    lines = text.splitlines()
    header_idx = next(
        i for i, line in enumerate(lines) if line.startswith("| Library | Version | Licence")
    )
    cells = []
    for line in lines[header_idx + 2 :]:  # +2 skips the header and the |---| separator row
        if not line.startswith("|"):
            break
        columns = [c.strip() for c in line.split("|")]
        # columns[0] is '' (before the leading |); Licence is the 3rd cell.
        cells.append(columns[3])
    return cells


def test_js_library_table_parses_to_real_rows() -> None:
    """Sanity check the table parser found rows, not zero."""
    cells = _js_library_licence_cells()
    assert len(cells) >= 8, f"expected >=8 JS-library rows, parsed {len(cells)}: {cells}"


def test_every_named_licence_family_has_its_full_text_present() -> None:
    text = NOTICES.read_text(encoding="utf-8")
    named: set[str] = set()
    for cell in _js_library_licence_cells():
        # "Apache-2.0 OR MPL-2.0 (recipient's choice)" -> {"Apache-2.0", "MPL-2.0"}
        for token in re.split(r"\s+OR\s+", cell):
            token = re.sub(r"\s*\(.*\)$", "", token).strip()
            if token in _LICENCE_FULL_TEXT_MARKERS:
                named.add(token)

    assert named, "parsed zero recognised licence identifiers from the JS-libraries table"

    missing = [family for family in named if _LICENCE_FULL_TEXT_MARKERS[family] not in text]
    assert not missing, (
        f"licence family named in the JS-libraries table with no full text "
        f"present in THIRD-PARTY-NOTICES.md: {missing}"
    )


def test_notices_reproduces_apache_and_mpl_text_not_just_a_link() -> None:
    """D2's specific complaint: Apache-2.0/MPL-2.0 were only linked."""
    text = NOTICES.read_text(encoding="utf-8")
    assert _LICENCE_FULL_TEXT_MARKERS["Apache-2.0"] in text
    assert _LICENCE_FULL_TEXT_MARKERS["MPL-2.0"] in text
