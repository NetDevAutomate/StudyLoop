"""Contract tests for the source install script."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_justfile_has_shellcheck_recipe_for_install_and_release_scripts() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    justfile = repo_root / "Justfile"
    justfile_text = justfile.read_text()

    assert "shellcheck:" in justfile_text
    assert "shellcheck \\" in justfile_text
    assert "scripts/install.sh" in justfile_text
    assert "scripts/smoke-installed-cli.sh" in justfile_text
    assert "scripts/build-release.sh" in justfile_text
    assert "scripts/smoke-uv-tool-install.sh" in justfile_text


def test_install_script_smoke_checks_run_self_test_json() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "scripts" / "install.sh"
    script_text = script.read_text()

    assert "self_test_json=$(studyloop self-test --json)" in script_text
    assert "self_test_status=$?" in script_text
    assert 'case "$self_test_status" in' in script_text
    assert "0|1) ;;" in script_text
    assert "python3 -m json.tool" in script_text


def test_install_script_help_documents_supported_flags() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "scripts" / "install.sh"

    result = subprocess.run(
        ["bash", str(script), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--tools-only" in result.stdout
    assert "--agents-only" in result.stdout
    assert "--non-interactive" in result.stdout
    assert "--no-smoke" in result.stdout


def test_install_script_points_at_the_server_owned_browser_architect() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "scripts" / "install.sh").read_text()

    assert "Create with Architect" in script_text
    assert "Type or dictate one brain dump" in script_text
    assert "studyloop setup --planning-base-url URL --planning-model MODEL" in script_text
    assert "start the 'study-plan-architect' agent" not in script_text
    assert "studyloop plan new --title" not in script_text
