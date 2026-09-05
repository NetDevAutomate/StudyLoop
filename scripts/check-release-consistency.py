#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path


def read_studyloop_version(repo_root: Path) -> str:
    pyproject_path = repo_root / "packages" / "studyloop" / "pyproject.toml"
    with pyproject_path.open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)
    version = pyproject.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError(f"missing project.version in {pyproject_path}")
    return version


def validate_root_version_matches_package(repo_root: Path, package_version: str) -> None:
    """R-39: the workspace-root pyproject.toml drifted to 1.0.0 while the

    package sat at 0.1.0, and nothing caught it. Read the same way
    ``read_studyloop_version`` reads the package version, then assert
    agreement.
    """
    root_pyproject_path = repo_root / "pyproject.toml"
    if not root_pyproject_path.is_file():
        raise ValueError(f"missing root pyproject.toml: {root_pyproject_path}")
    with root_pyproject_path.open("rb") as pyproject_file:
        root_pyproject = tomllib.load(pyproject_file)
    root_version = root_pyproject.get("project", {}).get("version")
    if not isinstance(root_version, str) or not root_version:
        raise ValueError(f"missing project.version in {root_pyproject_path}")
    if root_version != package_version:
        raise ValueError(
            f"root pyproject.toml version ({root_version}) does not match "
            f"packages/studyloop/pyproject.toml version ({package_version})"
        )


def validate_release_note(repo_root: Path, version: str) -> None:
    release_note_path = repo_root / "releases" / f"v{version}.md"
    if not release_note_path.is_file():
        raise ValueError(f"missing release note: releases/v{version}.md")
    first_heading = ""
    for line in release_note_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            first_heading = line.strip()
            break
    if f"v{version}" not in first_heading:
        raise ValueError(
            f"release note title must mention v{version}; got {first_heading or '<none>'}"
        )


def read_wheel_metadata_version(wheel_path: Path) -> str | None:
    with zipfile.ZipFile(wheel_path) as wheel:
        metadata_names = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
        for metadata_name in metadata_names:
            metadata = wheel.read(metadata_name).decode("utf-8")
            for line in metadata.splitlines():
                if line.startswith("Version: "):
                    return line.removeprefix("Version: ").strip()
    return None


def validate_wheel_metadata(repo_root: Path, version: str) -> None:
    wheel_paths = sorted((repo_root / "dist").glob("studyloop-*.whl"))
    if not wheel_paths:
        raise ValueError("missing built wheel: dist/studyloop-*.whl")

    wheel_versions = {
        str(wheel_path.relative_to(repo_root)): read_wheel_metadata_version(wheel_path)
        for wheel_path in wheel_paths
    }
    matching_wheels = [
        wheel_path
        for wheel_path, wheel_version in wheel_versions.items()
        if wheel_version == version
    ]
    if not matching_wheels:
        seen_versions = ", ".join(
            f"{wheel_path}={wheel_version or '<missing>'}"
            for wheel_path, wheel_version in wheel_versions.items()
        )
        raise ValueError(
            f"no built studyloop wheel has METADATA Version: {version}; saw {seen_versions}"
        )


def validate_sdist(repo_root: Path, version: str) -> None:
    sdist_path = repo_root / "dist" / f"studyloop-{version}.tar.gz"
    if not sdist_path.is_file():
        raise ValueError(f"missing source distribution: dist/studyloop-{version}.tar.gz")


def _git(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout.strip()


def _deferred_reason(change_dir: Path) -> str | None:
    """The change's explicit ``deferred:`` reason, or None.

    Read with a line match rather than a YAML parser so this script keeps its
    stdlib-only property. A bare ``deferred:`` with no reason does NOT count —
    an unexplained deferral is indistinguishable from a forgotten one, which is
    the state this guard exists to catch.
    """
    meta = change_dir / ".openspec.yaml"
    if not meta.is_file():
        return None
    for line in meta.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*deferred:\s*(\S.*)$", line)
        if match:
            return match.group(1).strip()
    return None


def validate_openspec_changes_shipped(repo_root: Path) -> None:
    """Release mode only: a change that shipped work must be archived.

    The 0.2.0 cut shipped the whole second-brain layer while its change sat at
    0/19 tasks, unarchived — nothing read change state, so nothing objected
    (2026-09-04 review, Q5). This fails the release gate when any directory
    under ``openspec/changes/`` (``archive/`` excluded) has commits since the
    last tag and is not archived, unless its ``.openspec.yaml`` carries an
    explicit ``deferred: <reason>``.

    Deliberately NOT part of preflight: open changes are legal during a cycle;
    only shipping one is not.
    """
    changes_dir = repo_root / "openspec" / "changes"
    if not changes_dir.is_dir():
        return
    try:
        last_tag = _git(repo_root, "describe", "--tags", "--abbrev=0")
    except subprocess.CalledProcessError:
        return  # no tag yet: the first release has nothing to compare against

    offenders: list[str] = []
    for change_dir in sorted(p for p in changes_dir.iterdir() if p.is_dir()):
        if change_dir.name == "archive":
            continue
        touched = _git(
            repo_root,
            "log",
            "--oneline",
            f"{last_tag}..HEAD",
            "--",
            str(change_dir.relative_to(repo_root)),
        )
        if not touched:
            continue
        reason = _deferred_reason(change_dir)
        if reason:
            print(f"openspec change {change_dir.name!r} deferred: {reason}")
            continue
        offenders.append(change_dir.name)

    if offenders:
        raise ValueError(
            "openspec change(s) with commits since "
            f"{last_tag} are neither archived nor deferred: {', '.join(offenders)}. "
            "Reconcile and run `openspec archive <name>`, or add "
            "`deferred: <reason>` to the change's .openspec.yaml."
        )


def validate_new_archives(repo_root: Path) -> None:
    """Archive entries added since the last tag must pass ``openspec validate``.

    Scoped to NEW archives, not ``--archived --all``: an archive from July
    predates this guard and has unticked tasks nobody has evidence to
    reconcile; re-failing every future release on it would teach people to
    ignore the gate. Soft-skips when the openspec CLI is absent — the same
    convention as ``just spec-check``.
    """
    import shutil

    if shutil.which("openspec") is None:
        print("openspec CLI not found — skipping archived-change validation")
        return
    try:
        last_tag = _git(repo_root, "describe", "--tags", "--abbrev=0")
    except subprocess.CalledProcessError:
        return

    changed = _git(
        repo_root, "diff", "--name-only", f"{last_tag}..HEAD", "--", "openspec/changes/archive/"
    )
    new_names = sorted(
        {parts[3] for line in changed.splitlines() if len(parts := line.split("/")) > 4}
    )
    if not new_names:
        return

    report = subprocess.run(
        ["openspec", "validate", "--archived", "--all", "--no-interactive"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    ).stdout
    failing = [name for name in new_names if f"✓ change/{name}" not in report]
    if failing:
        raise ValueError(
            f"newly archived openspec change(s) failed validation: {', '.join(failing)}. "
            "Run `openspec validate --archived --all` for the detail."
        )
    print(f"openspec archives validated: {', '.join(new_names)}")


def validate_adr_statuses(repo_root: Path) -> None:
    """An ADR that predates the latest tag must not still say Proposed.

    ADR-0010 shipped in 0.2.0 still marked Proposed — the decision was acted
    on, released, and its record claimed it was still being considered. Runs
    in every mode (always-on, per the Q5 ruling): an ADR's status is a
    statement of fact whenever it is read, not only at release time.
    """
    adr_dir = repo_root / "docs" / "adr"
    if not adr_dir.is_dir():
        return
    try:
        last_tag = _git(repo_root, "describe", "--tags", "--abbrev=0")
    except subprocess.CalledProcessError:
        return

    stale: list[str] = []
    for adr in sorted(adr_dir.glob("[0-9]*.md")):
        in_tag = subprocess.run(
            ["git", "cat-file", "-e", f"{last_tag}:{adr.relative_to(repo_root)}"],
            cwd=repo_root,
            capture_output=True,
            timeout=60,
            check=False,
        )
        if in_tag.returncode != 0:
            continue  # added after the tag; Proposed is honest for it
        head = adr.read_text(encoding="utf-8", errors="replace")[:600]
        if re.search(r"\*\*Status:\*\*\s*Proposed", head):
            stale.append(adr.name)
    if stale:
        raise ValueError(
            f"ADR(s) released in {last_tag} still say Status: Proposed: "
            f"{', '.join(stale)}. A shipped decision is Accepted (or Superseded) — "
            "update the ADR and its docs/adr/README.md row."
        )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check StudyLoop release notes and wheel metadata match pyproject version.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root to check. Defaults to the parent of scripts/.",
    )
    parser.add_argument(
        "--skip-wheel",
        action="store_true",
        help="Skip built wheel METADATA validation.",
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help=(
            "Also fail on unarchived, undeferred openspec changes with commits "
            "since the last tag (release-check mode; open changes are legal "
            "during a cycle, so preflight does not pass this)."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    repo_root = args.repo_root.resolve()

    try:
        version = read_studyloop_version(repo_root)
        validate_root_version_matches_package(repo_root, version)
        validate_release_note(repo_root, version)
        validate_adr_statuses(repo_root)
        if args.release:
            validate_openspec_changes_shipped(repo_root)
            validate_new_archives(repo_root)
        if not args.skip_wheel:
            validate_sdist(repo_root, version)
            validate_wheel_metadata(repo_root, version)
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        tomllib.TOMLDecodeError,
        ValueError,
        zipfile.BadZipFile,
    ) as exc:
        print(f"release consistency failed: {exc}", file=sys.stderr)
        return 1

    print(f"release consistency passed for studyloop {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
