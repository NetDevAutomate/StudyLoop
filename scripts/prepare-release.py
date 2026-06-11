#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare a StudyLoop release.")
    parser.add_argument("version", help="New version, for example 2.6.0")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root. Defaults to the parent of scripts/.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned writes.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow updating an existing release note.",
    )
    return parser.parse_args(argv)


def replace_version(pyproject_text: str, version: str) -> str:
    return re.sub(
        r'(?m)^version = "[^"]+"$',
        f'version = "{version}"',
        pyproject_text,
        count=1,
    )


def release_note_text(version: str) -> str:
    return (
        f"# v{version}\n\n"
        "## Changes\n\n"
        "- Release summary.\n\n"
        "## Verification\n\n"
        "- `just release-check`\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    version = args.version
    if not VERSION_RE.match(version):
        print(f"invalid version: {version}", file=sys.stderr)
        return 1

    repo_root = args.repo_root.resolve()
    pyproject_path = repo_root / "packages" / "studyloop" / "pyproject.toml"
    release_note_path = repo_root / "releases" / f"v{version}.md"

    pyproject_text = pyproject_path.read_text(encoding="utf-8")
    new_pyproject_text = replace_version(pyproject_text, version)
    if new_pyproject_text == pyproject_text:
        print(f"could not find project version in {pyproject_path}", file=sys.stderr)
        return 1

    if release_note_path.exists() and not args.force:
        print(f"release note already exists: {release_note_path}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"would update {pyproject_path}")
        print(f"would write {release_note_path}")
        return 0

    pyproject_path.write_text(new_pyproject_text, encoding="utf-8")
    release_note_path.write_text(release_note_text(version), encoding="utf-8")
    print(f"prepared StudyLoop {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
