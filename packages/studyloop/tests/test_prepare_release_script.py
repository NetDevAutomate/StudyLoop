from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "prepare-release.py"


def _write_repo(repo: Path, version: str = "1.2.3") -> None:
    package_dir = repo / "packages" / "studyloop"
    package_dir.mkdir(parents=True)
    (package_dir / "pyproject.toml").write_text(
        f'[project]\nname = "studyloop"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    # A real checkout always has a root pyproject too, and the release gate
    # compares the two versions (R-39). Omitting it here let the fixture pass
    # while the release it modelled could not.
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "studyloop-workspace"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    (repo / "releases").mkdir()


def test_prepare_release_updates_version_and_creates_release_note(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "1.2.4", "--repo-root", str(repo)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    pyproject = repo / "packages" / "studyloop" / "pyproject.toml"
    assert 'version = "1.2.4"' in pyproject.read_text(encoding="utf-8")
    release_note = repo / "releases" / "v1.2.4.md"
    assert release_note.is_file()
    assert release_note.read_text(encoding="utf-8").startswith("# v1.2.4\n")


def test_prepare_release_refuses_existing_release_note_without_force(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo)
    (repo / "releases" / "v1.2.4.md").write_text("# v1.2.4\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "1.2.4", "--repo-root", str(repo)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "already exists" in result.stderr


def test_prepare_release_dry_run_does_not_write_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "1.2.4", "--repo-root", str(repo), "--dry-run"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert 'version = "1.2.3"' in (repo / "packages" / "studyloop" / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert 'version = "1.2.3"' in (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert not (repo / "releases" / "v1.2.4.md").exists()
    assert "would update" in result.stdout


def test_prepare_release_leaves_the_consistency_check_passing(tmp_path: Path) -> None:
    """The two release scripts have to agree, or `prepare-release` is a trap.

    R-39 added a root-versus-package version check to
    `check-release-consistency.py` after the root `pyproject.toml` drifted to
    1.0.0 while the package sat at 0.1.0. But `prepare-release.py` only ever
    bumped the package, so running it produced exactly the drift the other
    script now refuses: `just preflight` failed on the commit that prepared the
    release, and the only way forward was to know about the second file.

    This test is the pair, checked end to end rather than by reading both
    scripts: prepare, then run the gate the release actually has to pass.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo)
    (repo / "scripts").mkdir()

    prepared = subprocess.run(
        [sys.executable, str(SCRIPT), "1.2.4", "--repo-root", str(repo)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert prepared.returncode == 0, prepared.stderr

    consistency = subprocess.run(
        [
            sys.executable,
            str(SCRIPT.with_name("check-release-consistency.py")),
            "--repo-root",
            str(repo),
            "--skip-wheel",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert consistency.returncode == 0, consistency.stderr + consistency.stdout
