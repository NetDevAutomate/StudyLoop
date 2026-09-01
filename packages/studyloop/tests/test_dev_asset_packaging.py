"""Dev-only vendored assets: in git, out of the wheel.

The contract, per docs/adr/0007-dev-only-vendored-assets.md:

* ``static/vendor/dev/`` is **tracked** -- a developer checking out on another
  machine must get it, which is why a branch, a submodule or a
  download-at-setup step were all rejected.
* it is **excluded from the wheel** -- users never run ``--dev``, and shipping
  it added ~1.7 MB to every install.

Both halves are asserted. A one-sided "not in the wheel" test would also pass if
someone deleted the assets outright, and that is not a hypothetical failure mode
here: this repo shipped a broken SPA precisely because two source files existed
on disk but not in git.
"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEV_VENDOR = PACKAGE_ROOT / "src" / "studyloop" / "web" / "static" / "vendor" / "dev"

#: Path fragment the wheel must never contain.
WHEEL_FORBIDDEN_FRAGMENT = "web/static/vendor/dev/"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


class TestDevAssetsAreTrackedInGit:
    """The 'across machines' half of the contract."""

    def test_the_dev_vendor_directory_exists(self) -> None:
        assert DEV_VENDOR.is_dir(), f"{DEV_VENDOR} is missing"

    def test_dev_assets_are_tracked_not_merely_present_on_disk(self) -> None:
        """Tracked, not just present.

        ``git ls-files`` and not ``git status``: status lists only CHANGED files,
        so its silence proves nothing about whether a file is tracked. That exact
        mistake produced three false "file does not exist" findings during the
        0.1.0 review.
        """
        tracked = {
            line.strip()
            for line in _git(
                "ls-files",
                "packages/studyloop/src/studyloop/web/static/vendor/dev",
            ).splitlines()
            if line.strip()
        }
        assert tracked, (
            "no files under vendor/dev/ are tracked by git -- dev mode would not "
            "survive a fresh clone on another machine"
        )
        on_disk = {str(p.relative_to(REPO_ROOT)) for p in DEV_VENDOR.rglob("*") if p.is_file()}
        untracked = on_disk - tracked
        assert not untracked, f"dev assets present but untracked: {sorted(untracked)}"

    def test_the_engine_registry_points_at_assets_that_exist(self) -> None:
        from studyloop.web.dev_engines import DEV_ENGINES, missing_dev_assets

        for engine in DEV_ENGINES:
            assert missing_dev_assets(engine) == [], (
                f"dev engine {engine!r} references assets that are not on disk"
            )


class TestWheelExcludesDevAssets:
    """The 'not shipped' half of the contract."""

    @pytest.fixture(scope="class")
    def built_wheel(self, tmp_path_factory) -> Path:
        if shutil.which("uv") is None:
            pytest.skip("uv is not on PATH, so the wheel cannot be built here")
        out = tmp_path_factory.mktemp("wheel-contract")
        proc = subprocess.run(
            ["uv", "build", "--package", "studyloop", "--wheel", "-o", str(out)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode != 0:
            pytest.fail(f"wheel build failed:\n{proc.stdout}\n{proc.stderr}")
        wheels = list(out.glob("studyloop-*.whl"))
        assert len(wheels) == 1, f"expected one wheel, got {wheels}"
        return wheels[0]

    def test_wheel_contains_no_dev_vendor_files(self, built_wheel: Path) -> None:
        with zipfile.ZipFile(built_wheel) as zf:
            names = zf.namelist()
        offenders = [n for n in names if WHEEL_FORBIDDEN_FRAGMENT in n]
        assert not offenders, (
            f"the wheel ships {len(offenders)} dev-only asset(s): {offenders[:5]}. "
            "Check the exclude in packages/studyloop/pyproject.toml."
        )

    def test_wheel_still_contains_the_shipped_vendor_assets(self, built_wheel: Path) -> None:
        """Guard against the exclusion being too broad.

        An exclude that accidentally swallowed all of vendor/ would make the test
        above pass while shipping a wheel whose terminal cannot load at all.
        """
        with zipfile.ZipFile(built_wheel) as zf:
            names = zf.namelist()
        shipped = [n for n in names if "web/static/vendor/js/" in n]
        assert len(shipped) >= 5, (
            f"only {len(shipped)} shipped vendor/js files in the wheel; the "
            "exclusion looks too broad"
        )


class TestGitLfsIsNotUsed:
    """LFS was removed with the standalone wasm; keep it removed.

    LFS in this repo only ever managed a 423 KB file -- in a tree whose largest
    file is a 5.3 MB GIF that sits in plain git -- and it cost three red CI jobs
    plus two earlier cleanup commits. Its last justification went with the
    deprecated inline dev path.
    """

    def test_no_gitattributes_lfs_filters(self) -> None:
        attrs = REPO_ROOT / ".gitattributes"
        if not attrs.is_file():
            return
        offending = [
            line
            for line in attrs.read_text().splitlines()
            if "filter=lfs" in line and not line.lstrip().startswith("#")
        ]
        assert not offending, (
            "Git LFS filters are back in .gitattributes: "
            f"{offending}. See docs/adr/0007-dev-only-vendored-assets.md."
        )

    def test_no_lfs_checkout_in_workflows(self) -> None:
        workflows = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
        assert workflows, "no workflows found — this test would be vacuous"
        offending = [
            f"{wf.name}:{i}"
            for wf in workflows
            for i, line in enumerate(wf.read_text().splitlines(), 1)
            if line.strip().startswith("lfs:") and "true" in line
        ]
        assert not offending, f"workflows request an LFS checkout again: {offending}"
