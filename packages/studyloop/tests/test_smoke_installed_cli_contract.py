"""Contract tests for the installed CLI smoke script."""

from __future__ import annotations

from pathlib import Path


def test_smoke_installed_cli_runs_self_test_json() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "scripts" / "smoke-installed-cli.sh"
    script_text = script.read_text()

    assert 'studyloop self-test --json >"$self_test_output"' in script_text
    assert "self_test_status=$?" in script_text
    assert 'case "$self_test_status" in' in script_text
    assert "0|1) ;;" in script_text
    assert 'python -m json.tool "$self_test_output"' in script_text
