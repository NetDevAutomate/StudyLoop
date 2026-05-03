"""Tests for the release consistency checker script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_checker():
    script = Path(__file__).parents[3] / "scripts" / "check-release-consistency.py"
    spec = importlib.util.spec_from_file_location("check_release_consistency", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load release consistency script")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_repo(tmp_path: Path, *, version: str, formula_version: str | None = None) -> Path:
    repo = tmp_path
    package_dir = repo / "packages" / "studyctl"
    formula_dir = repo / "Formula"
    release_dir = repo / "releases"
    package_dir.mkdir(parents=True)
    formula_dir.mkdir()
    release_dir.mkdir()

    (package_dir / "pyproject.toml").write_text(
        f'[project]\nname = "studyctl"\nversion = "{version}"\n'
    )
    if formula_version is not None:
        (formula_dir / "studyctl.rb").write_text(
            f'url "https://files.pythonhosted.org/packages/source/s/studyctl/studyctl-{formula_version}.tar.gz"\n'
        )
    else:
        (formula_dir / "studyctl.rb").write_text("class Studyctl < Formula\nend\n")
    (release_dir / f"v{version}.md").write_text(
        f"# v{version} Release Notes\n\n`studyctl v{version}` release.\n"
    )
    return repo


def test_release_consistency_accepts_matching_metadata(tmp_path: Path) -> None:
    checker = _load_checker()
    repo = _write_repo(tmp_path, version="2.5.0", formula_version="2.5.0")

    errors, warnings, metadata = checker.check_release_consistency(
        repo,
        tag="v2.5.0",
        require_release_notes=True,
        require_formula_current=True,
    )

    assert errors == []
    assert warnings == []
    assert metadata.package_version == "2.5.0"


def test_release_consistency_rejects_tag_mismatch(tmp_path: Path) -> None:
    checker = _load_checker()
    repo = _write_repo(tmp_path, version="2.5.0", formula_version="2.5.0")

    errors, _, _ = checker.check_release_consistency(repo, tag="v2.4.0")

    assert errors == ["Tag 'v2.4.0' does not match package version; expected 'v2.5.0'."]


def test_release_consistency_rejects_missing_release_notes(tmp_path: Path) -> None:
    checker = _load_checker()
    repo = _write_repo(tmp_path, version="2.5.0", formula_version="2.5.0")
    (repo / "releases" / "v2.5.0.md").unlink()

    errors, _, _ = checker.check_release_consistency(
        repo,
        tag="v2.5.0",
        require_release_notes=True,
    )

    assert any("Missing release notes" in error for error in errors)


def test_release_consistency_can_allow_formula_lag(tmp_path: Path) -> None:
    checker = _load_checker()
    repo = _write_repo(tmp_path, version="2.5.0", formula_version="2.4.0")

    errors, warnings, _ = checker.check_release_consistency(repo, allow_formula_lag=True)

    assert errors == []
    assert len(warnings) == 1
    assert "formula points at studyctl 2.4.0" in warnings[0]


def test_release_consistency_can_require_current_formula(tmp_path: Path) -> None:
    checker = _load_checker()
    repo = _write_repo(tmp_path, version="2.5.0", formula_version="2.4.0")

    errors, warnings, _ = checker.check_release_consistency(repo, require_formula_current=True)

    assert warnings == []
    assert len(errors) == 1
    assert "formula points at studyctl 2.4.0" in errors[0]
