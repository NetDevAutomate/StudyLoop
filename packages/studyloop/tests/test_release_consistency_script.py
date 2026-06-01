from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check-release-consistency.py"


def write_package_version(repo_root: Path, version: str) -> None:
    package_dir = repo_root / "packages" / "studyloop"
    package_dir.mkdir(parents=True)
    (package_dir / "pyproject.toml").write_text(
        f'[project]\nname = "studyloop"\nversion = "{version}"\n',
        encoding="utf-8",
    )


def run_check(repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(repo_root), "--skip-wheel"],
        check=False,
        text=True,
        capture_output=True,
    )


def test_release_consistency_passes_when_release_note_exists(tmp_path: Path) -> None:
    write_package_version(tmp_path, "1.2.3")
    releases_dir = tmp_path / "releases"
    releases_dir.mkdir()
    (releases_dir / "v1.2.3.md").write_text("# v1.2.3\n", encoding="utf-8")

    result = run_check(tmp_path)

    assert result.returncode == 0
    assert "release consistency passed" in result.stdout


def test_release_consistency_fails_when_release_note_is_missing(tmp_path: Path) -> None:
    write_package_version(tmp_path, "1.2.3")

    result = run_check(tmp_path)

    assert result.returncode == 1
    assert "missing release note" in result.stderr
    assert "releases/v1.2.3.md" in result.stderr
