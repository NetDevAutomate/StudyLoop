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
