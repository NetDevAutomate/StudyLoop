from __future__ import annotations

import os
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


def run_release_check(
    repo_root: Path, *, pre_tag: bool = False
) -> subprocess.CompletedProcess[str]:
    argv = [sys.executable, str(SCRIPT), "--repo-root", str(repo_root), "--skip-wheel", "--release"]
    if pre_tag:
        argv.append("--pre-tag")
    return subprocess.run(argv, check=False, text=True, capture_output=True)


def init_git_repo_with_tag(
    repo_root: Path, *, tag: str | None, tag_date: str, commit_message: str = "init"
) -> None:
    """A minimal git repo containing every file already written under

    *repo_root*, committed on *tag_date* and optionally tagged *tag* on that
    same commit -- the fixture W41's release-tag check tests need.
    """

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=repo_root, check=True, capture_output=True, text=True
        )

    env_date = f"{tag_date}T12:00:00"
    run("init", "-q")
    run("config", "user.email", "test@example.com")
    run("config", "user.name", "Test")
    run("add", "-A")
    subprocess.run(
        ["git", "commit", "-q", "-m", commit_message],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_AUTHOR_DATE": env_date,
            "GIT_COMMITTER_DATE": env_date,
        },
    )
    if tag is not None:
        run("tag", tag)


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


# ---------------------------------------------------------------------------
# W41: --release mode must also assert a git tag exists and that the
# CHANGELOG's dated heading for the version is on or after the tag's own
# commit date.
# ---------------------------------------------------------------------------


def _write_release_fixture(tmp_path: Path, version: str, changelog_date: str) -> None:
    write_package_version(tmp_path, version)
    write_root_version(tmp_path, version)
    releases_dir = tmp_path / "releases"
    releases_dir.mkdir()
    (releases_dir / f"v{version}.md").write_text(f"# v{version}\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## [{version}] - {changelog_date}\n\n- stuff\n",
        encoding="utf-8",
    )


def test_release_tag_check_fails_when_tag_missing(tmp_path: Path) -> None:
    _write_release_fixture(tmp_path, "1.2.3", "2026-09-06")
    init_git_repo_with_tag(tmp_path, tag=None, tag_date="2026-09-06")

    result = run_release_check(tmp_path)

    assert result.returncode == 1
    assert "no git tag" in result.stderr
    assert "v1.2.3" in result.stderr


def test_release_tag_check_passes_when_tag_exists_and_changelog_date_on_or_after(
    tmp_path: Path,
) -> None:
    _write_release_fixture(tmp_path, "1.2.3", "2026-09-06")
    init_git_repo_with_tag(tmp_path, tag="v1.2.3", tag_date="2026-09-06")

    result = run_release_check(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "release consistency passed" in result.stdout


def test_release_tag_check_fails_when_changelog_date_before_tag_commit_date(
    tmp_path: Path,
) -> None:
    """The bug this check exists to catch (W41): CHANGELOG dates a version

    earlier than the commit its own tag actually sits on.
    """
    _write_release_fixture(tmp_path, "1.2.3", "2026-09-05")
    init_git_repo_with_tag(tmp_path, tag="v1.2.3", tag_date="2026-09-06")

    result = run_release_check(tmp_path)

    assert result.returncode == 1
    assert "2026-09-05" in result.stderr
    assert "2026-09-06" in result.stderr


# ---------------------------------------------------------------------------
# The tag assertion above made `just release-check` (which runs --release)
# impossible to pass BEFORE the tag it demands exists. --pre-tag is the
# pre-cut mode: every other release check runs, the tag/date assertion is
# deferred and named, and `just release-verify` runs the strict form after
# the tag is cut.
# ---------------------------------------------------------------------------


def test_pre_tag_mode_passes_without_a_tag_and_names_the_pending_tag(tmp_path: Path) -> None:
    _write_release_fixture(tmp_path, "1.2.3", "2026-09-06")
    init_git_repo_with_tag(tmp_path, tag=None, tag_date="2026-09-06")

    result = run_release_check(tmp_path, pre_tag=True)

    assert result.returncode == 0, result.stderr
    assert "v1.2.3" in result.stdout and "pending" in result.stdout


def test_pre_tag_mode_still_runs_the_other_release_checks(tmp_path: Path) -> None:
    """--pre-tag defers ONLY the tag/date assertion; a missing release note
    must still fail in pre-tag mode."""
    write_package_version(tmp_path, "1.2.3")
    write_root_version(tmp_path, "1.2.3")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [1.2.3] - 2026-09-06\n", encoding="utf-8"
    )
    init_git_repo_with_tag(tmp_path, tag=None, tag_date="2026-09-06")

    result = run_release_check(tmp_path, pre_tag=True)

    assert result.returncode == 1
    assert "release" in result.stderr.lower()


def test_justfile_release_check_uses_pre_tag_mode_and_release_verify_is_strict() -> None:
    justfile = (Path(__file__).resolve().parents[3] / "Justfile").read_text(encoding="utf-8")
    recipes: dict[str, str] = {}
    current = None
    for line in justfile.splitlines():
        if line and not line[0].isspace() and ":" in line and not line.startswith("#"):
            current = line.split(":", 1)[0].split()[0]
            recipes[current] = line
        elif current and line.startswith((" ", "\t")):
            recipes[current] += "\n" + line
    shipped = recipes["release-consistency-shipped"]
    assert "--release" in shipped and "--pre-tag" in shipped, shipped
    verify = recipes["release-verify"]
    assert "--release" in verify and "--pre-tag" not in verify, verify
    assert "release-consistency-shipped" in recipes["release-check"]


def test_release_note_that_is_still_the_prepare_release_skeleton_fails(tmp_path: Path) -> None:
    """Council (grok F16): validate_release_note() checked only that the file
    exists and its title names the version, so the skeleton
    `scripts/prepare-release.py` writes ("- Release summary.") would pass a
    release gate with no release notes at all."""
    write_package_version(tmp_path, "1.2.3")
    write_root_version(tmp_path, "1.2.3")
    releases_dir = tmp_path / "releases"
    releases_dir.mkdir()
    skeleton = (
        "# v1.2.3\n\n## Changes\n\n- Release summary.\n\n"
        "## Verification\n\n- `just release-check`\n"
    )
    (releases_dir / "v1.2.3.md").write_text(skeleton, encoding="utf-8")

    # Mid-cycle the skeleton is a legitimate intermediate state (prepare-release
    # writes it; the notes come later), so the ordinary check accepts it ...
    assert run_check(tmp_path).returncode == 0

    # ... but no release mode does, pre-tag or strict.
    init_git_repo_with_tag(tmp_path, tag=None, tag_date="2026-09-06")
    result = run_release_check(tmp_path, pre_tag=True)

    assert result.returncode == 1
    assert "skeleton" in result.stderr.lower() or "release summary" in result.stderr.lower()


# ---------------------------------------------------------------------------
# The openspec-shipped guard: a change with commits since the last tag must be
# archived or carry an EXPLAINED `deferred:`. `.openspec.yaml` writes the reason
# as a YAML folded scalar (`deferred: >-` + indented lines), and the guard's
# line-match read the fold marker `>-` as the reason -- so an empty fold passed
# and the printed reason was `>-`, defeating the "unexplained deferral is
# indistinguishable from a forgotten one" rule the guard exists for.
# ---------------------------------------------------------------------------


def _write_changes_fixture(tmp_path: Path, openspec_yaml: str | None) -> None:
    """A tagged repo, then a post-tag commit touching one openspec change."""
    _write_release_fixture(tmp_path, "1.2.3", "2026-09-06")
    init_git_repo_with_tag(tmp_path, tag="v1.2.3", tag_date="2026-09-06")
    change_dir = tmp_path / "openspec" / "changes" / "some-change"
    change_dir.mkdir(parents=True)
    (change_dir / "proposal.md").write_text("# proposal\n", encoding="utf-8")
    if openspec_yaml is not None:
        (change_dir / ".openspec.yaml").write_text(openspec_yaml, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "touch change"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )


def test_release_mode_names_an_undeferred_change_with_commits_since_the_tag(
    tmp_path: Path,
) -> None:
    _write_changes_fixture(tmp_path, openspec_yaml="schema: spec-driven\n")

    result = run_release_check(tmp_path)

    assert result.returncode == 1
    assert "neither archived nor deferred" in result.stderr
    assert "some-change" in result.stderr


def test_release_mode_accepts_a_folded_deferral_and_prints_its_text_not_the_fold_marker(
    tmp_path: Path,
) -> None:
    _write_changes_fixture(
        tmp_path,
        openspec_yaml=(
            "schema: spec-driven\n\n"
            "deferred: >-\n"
            "  Follow-on programme; archived when the owner\n"
            "  scores the last rubric row.\n"
        ),
    )

    result = run_release_check(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "deferred: Follow-on programme; archived when the owner scores the last rubric row." in (
        result.stdout
    )
    assert "deferred: >-" not in result.stdout


def test_release_mode_refuses_an_empty_folded_deferral(tmp_path: Path) -> None:
    """`deferred: >-` with nothing under it is the forgotten-deferral case."""
    _write_changes_fixture(
        tmp_path, openspec_yaml="schema: spec-driven\n\ndeferred: >-\n\ncreated: 2026-09-16\n"
    )

    result = run_release_check(tmp_path)

    assert result.returncode == 1
    assert "neither archived nor deferred" in result.stderr
    assert "some-change" in result.stderr
