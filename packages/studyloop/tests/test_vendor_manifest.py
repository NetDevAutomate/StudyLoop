"""R-75 guard: `vendor/MANIFEST` must exactly match what is actually vendored.

Every non-``dev/`` file under
``packages/studyloop/src/studyloop/web/static/vendor/`` must have a line in
``vendor/MANIFEST`` recording its version, upstream source, and sha256 --
and that sha256 must match the file on disk right now. This catches three
distinct failure modes:

- a vendored file silently edited or corrupted (hash mismatch);
- a new file dropped into ``vendor/`` without a manifest entry (unlisted);
- a manifest entry left behind for a file that was deleted (stale).

``vendor/dev/`` is excluded on purpose -- it is git-tracked but wheel-excluded
dev-only assets covered by its own contract in
``test_dev_asset_packaging.py``, not this one.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = PACKAGE_ROOT / "src" / "studyloop" / "web" / "static" / "vendor"
MANIFEST_PATH = VENDOR_DIR / "MANIFEST"


def _parse_manifest() -> dict[str, tuple[str, str, str]]:
    """path -> (version, sha256, source_url), skipping comments/blank lines."""
    entries: dict[str, tuple[str, str, str]] = {}
    for line in MANIFEST_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        path, version, sha256, source_url = line.split("\t")
        entries[path] = (version, sha256, source_url)
    return entries


def _vendored_files_excluding_dev() -> set[str]:
    result = set()
    for path in VENDOR_DIR.rglob("*"):
        if not path.is_file() or path.name == "MANIFEST":
            continue
        relative = path.relative_to(VENDOR_DIR)
        if relative.parts[0] == "dev":
            continue
        result.add(str(relative))
    return result


def test_manifest_is_not_empty() -> None:
    assert _parse_manifest(), f"{MANIFEST_PATH} parsed to zero entries"


def test_every_vendored_file_outside_dev_is_listed() -> None:
    entries = _parse_manifest()
    on_disk = _vendored_files_excluding_dev()
    unlisted = on_disk - entries.keys()
    assert not unlisted, f"vendored file(s) with no MANIFEST entry: {sorted(unlisted)}"


def test_every_manifest_entry_points_at_a_real_file() -> None:
    entries = _parse_manifest()
    on_disk = _vendored_files_excluding_dev()
    stale = entries.keys() - on_disk
    assert not stale, f"MANIFEST entry/entries for file(s) that no longer exist: {sorted(stale)}"


def test_every_manifest_sha256_matches_the_file_on_disk() -> None:
    entries = _parse_manifest()
    mismatches = []
    for path, (_version, expected_sha256, _source_url) in entries.items():
        full_path = VENDOR_DIR / path
        if not full_path.is_file():
            continue  # covered by test_every_manifest_entry_points_at_a_real_file
        actual_sha256 = hashlib.sha256(full_path.read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            mismatches.append(f"{path}: manifest={expected_sha256} actual={actual_sha256}")
    joined = "\n".join(mismatches)
    assert not mismatches, f"sha256 mismatch (file changed since MANIFEST was written):\n{joined}"


def test_every_manifest_entry_has_a_source_url_or_is_explicitly_local() -> None:
    entries = _parse_manifest()
    bad = [
        path
        for path, (_version, _sha256, source_url) in entries.items()
        if not source_url or (source_url != "local" and not source_url.startswith("https://"))
    ]
    assert not bad, f"entry with no usable source_url: {bad}"
