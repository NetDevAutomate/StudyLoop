#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    repo_root = args.repo_root.resolve()

    try:
        version = read_studyloop_version(repo_root)
        validate_root_version_matches_package(repo_root, version)
        validate_release_note(repo_root, version)
        if not args.skip_wheel:
            validate_sdist(repo_root, version)
            validate_wheel_metadata(repo_root, version)
    except (OSError, tomllib.TOMLDecodeError, ValueError, zipfile.BadZipFile) as exc:
        print(f"release consistency failed: {exc}", file=sys.stderr)
        return 1

    print(f"release consistency passed for studyloop {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
