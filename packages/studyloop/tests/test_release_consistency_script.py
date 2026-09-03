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


def write_root_version(repo_root: Path, version: str) -> None:
    """R-39: the workspace-root pyproject.toml must agree with the package's."""
    (repo_root / "pyproject.toml").write_text(
        f'[project]\nname = "studyloop-workspace"\nversion = "{version}"\n',
        encoding="utf-8",
    )


def run_check(repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(repo_root), "--skip-wheel"],
        check=False,
        text=True,
        capture_output=True,
    )


def run_check_with_artifacts(repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(repo_root)],
        check=False,
        text=True,
        capture_output=True,
    )


def test_release_consistency_passes_when_release_note_exists(tmp_path: Path) -> None:
    write_package_version(tmp_path, "1.2.3")
    write_root_version(tmp_path, "1.2.3")
    releases_dir = tmp_path / "releases"
    releases_dir.mkdir()
    (releases_dir / "v1.2.3.md").write_text("# v1.2.3\n", encoding="utf-8")

    result = run_check(tmp_path)

    assert result.returncode == 0
    assert "release consistency passed" in result.stdout


def test_release_consistency_fails_when_release_note_is_missing(tmp_path: Path) -> None:
    write_package_version(tmp_path, "1.2.3")
    write_root_version(tmp_path, "1.2.3")

    result = run_check(tmp_path)

    assert result.returncode == 1
    assert "missing release note" in result.stderr
    assert "releases/v1.2.3.md" in result.stderr


def test_release_consistency_fails_when_title_version_mismatches(tmp_path: Path) -> None:
    write_package_version(tmp_path, "1.2.3")
    write_root_version(tmp_path, "1.2.3")
    releases_dir = tmp_path / "releases"
    releases_dir.mkdir()
    (releases_dir / "v1.2.3.md").write_text("# v1.2.2\n", encoding="utf-8")

    result = run_check(tmp_path)

    assert result.returncode == 1
    assert "release note title" in result.stderr
    assert "v1.2.3" in result.stderr


def test_release_consistency_requires_sdist_when_not_skipping_artifacts(
    tmp_path: Path,
) -> None:
    write_package_version(tmp_path, "1.2.3")
    write_root_version(tmp_path, "1.2.3")
    releases_dir = tmp_path / "releases"
    releases_dir.mkdir()
    (releases_dir / "v1.2.3.md").write_text("# v1.2.3\n", encoding="utf-8")

    result = run_check_with_artifacts(tmp_path)

    assert result.returncode == 1
    assert "missing source distribution" in result.stderr
    assert "dist/studyloop-1.2.3.tar.gz" in result.stderr


def test_release_consistency_fails_when_root_version_mismatches_package(
    tmp_path: Path,
) -> None:
    """R-39: the root pyproject.toml version drifting from the package's is

    exactly the '1.0.0' vs '0.1.0' defect this check exists to catch.
    """
    write_package_version(tmp_path, "1.2.3")
    write_root_version(tmp_path, "9.9.9")
    releases_dir = tmp_path / "releases"
    releases_dir.mkdir()
    (releases_dir / "v1.2.3.md").write_text("# v1.2.3\n", encoding="utf-8")

    result = run_check(tmp_path)

    assert result.returncode == 1
    assert "root pyproject.toml version" in result.stderr
    assert "9.9.9" in result.stderr
    assert "1.2.3" in result.stderr


def test_release_consistency_fails_when_root_pyproject_is_missing(tmp_path: Path) -> None:
    write_package_version(tmp_path, "1.2.3")

    result = run_check(tmp_path)

    assert result.returncode == 1
    assert "pyproject.toml" in result.stderr
