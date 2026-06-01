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


def test_smoke_uv_tool_install_uses_isolated_tool_home_and_runs_cli_smoke() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "scripts" / "smoke-uv-tool-install.sh"
    script_text = script.read_text()

    assert 'ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in script_text
    assert 'export HOME="$tmp/home"' in script_text
    assert 'export XDG_CONFIG_HOME="$tmp/xdg-config"' in script_text
    assert 'export XDG_CACHE_HOME="$tmp/xdg-cache"' in script_text
    assert 'export XDG_DATA_HOME="$tmp/xdg-data"' in script_text
    assert 'TOOL_BIN="$tmp/bin"' in script_text
    assert (
        'uv tool install --force --editable "$ROOT_DIR/packages/studyloop[sessions,web,content]"'
        in script_text
    )
    assert '--with-editable "$ROOT_DIR/packages/agent-session-tools"' in script_text
    assert 'test -x "$TOOL_BIN/studyloop"' in script_text
    assert 'PATH="$TOOL_BIN:$PATH" "$ROOT_DIR/scripts/smoke-installed-cli.sh"' in script_text
