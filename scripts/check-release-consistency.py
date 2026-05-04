#!/usr/bin/env python3
"""Check release metadata consistency for studyctl.

The published package is ``packages/studyctl``. The workspace root package is
not released to PyPI and is intentionally ignored by this check.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
FORMULA_VERSION_RE = re.compile(r"studyctl-(\d+\.\d+\.\d+)\.tar\.gz")


@dataclass(frozen=True)
class ReleaseMetadata:
    package_version: str
    formula_version: str | None
    release_notes_path: Path
    release_notes_exists: bool


def read_package_version(repo_root: Path) -> str:
    """Read the version of the published studyctl package."""
    pyproject = repo_root / "packages" / "studyctl" / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    version = str(data["project"]["version"])
    if not VERSION_RE.match(version):
        msg = f"Invalid studyctl package version in {pyproject}: {version!r}"
        raise ValueError(msg)
    return version


def read_formula_version(repo_root: Path) -> str | None:
    """Read the studyctl tarball version from the Homebrew formula."""
    formula = repo_root / "Formula" / "studyctl.rb"
    if not formula.exists():
        return None
    match = FORMULA_VERSION_RE.search(formula.read_text())
    return match.group(1) if match else None


def collect_metadata(repo_root: Path) -> ReleaseMetadata:
    """Collect release metadata from the repository."""
    package_version = read_package_version(repo_root)
    notes_path = repo_root / "releases" / f"v{package_version}.md"
    return ReleaseMetadata(
        package_version=package_version,
        formula_version=read_formula_version(repo_root),
        release_notes_path=notes_path,
        release_notes_exists=notes_path.exists(),
    )


def normalize_tag(raw: str | None) -> str | None:
    """Normalize empty or ref-style tag input."""
    if not raw:
        return None
    tag = raw.removeprefix("refs/tags/")
    return tag if tag.startswith("v") else None


def check_release_consistency(
    repo_root: Path,
    *,
    tag: str | None = None,
    require_release_notes: bool = False,
    require_formula_current: bool = False,
    allow_formula_lag: bool = False,
) -> tuple[list[str], list[str], ReleaseMetadata]:
    """Return release consistency errors and warnings."""
    metadata = collect_metadata(repo_root)
    errors: list[str] = []
    warnings: list[str] = []

    expected_tag = f"v{metadata.package_version}"
    normalized_tag = normalize_tag(tag)
    if normalized_tag and normalized_tag != expected_tag:
        errors.append(
            f"Tag {normalized_tag!r} does not match package version; expected {expected_tag!r}."
        )

    if require_release_notes or normalized_tag:
        if not metadata.release_notes_exists:
            errors.append(f"Missing release notes: {metadata.release_notes_path}")
        else:
            notes = metadata.release_notes_path.read_text()
            if f"# {expected_tag}" not in notes:
                errors.append(
                    f"Release notes heading must include '# {expected_tag}': "
                    f"{metadata.release_notes_path}"
                )
            mentions_tag = f"studyctl {expected_tag}" in notes
            mentions_version = f"studyctl {metadata.package_version}" in notes
            if not mentions_tag and not mentions_version:
                errors.append(
                    f"Release notes must mention studyctl {metadata.package_version}: "
                    f"{metadata.release_notes_path}"
                )

    if metadata.formula_version is None:
        errors.append("Could not find a studyctl source tarball URL in Formula/studyctl.rb.")
    elif metadata.formula_version != metadata.package_version:
        message = (
            f"Homebrew formula points at studyctl {metadata.formula_version}, "
            f"but package version is {metadata.package_version}."
        )
        if require_formula_current:
            errors.append(message)
        elif allow_formula_lag:
            warnings.append(
                message
                + " This is allowed before PyPI publish; the update-formula job must fix it."
            )
        else:
            warnings.append(message)

    return errors, warnings, metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--tag", default=None, help="Release tag, for example v2.5.0.")
    parser.add_argument(
        "--require-release-notes",
        action="store_true",
        help="Fail unless releases/vX.Y.Z.md exists and mentions the package version.",
    )
    parser.add_argument(
        "--require-formula-current",
        action="store_true",
        help="Fail unless Formula/studyctl.rb points at the package version.",
    )
    parser.add_argument(
        "--allow-formula-lag",
        action="store_true",
        help="Warn instead of fail when the formula still points at the previous PyPI tarball.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    errors, warnings, metadata = check_release_consistency(
        args.repo_root.resolve(),
        tag=args.tag,
        require_release_notes=args.require_release_notes,
        require_formula_current=args.require_formula_current,
        allow_formula_lag=args.allow_formula_lag,
    )

    print(f"studyctl package version: {metadata.package_version}")
    if metadata.formula_version:
        print(f"Homebrew formula version: {metadata.formula_version}")
    print(f"Release notes path: {metadata.release_notes_path}")

    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
