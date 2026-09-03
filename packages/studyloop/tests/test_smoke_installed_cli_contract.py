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
    assert 'python3 -m json.tool "$self_test_output"' in script_text


def test_smoke_installed_cli_checks_expected_bin_dir_and_session_export() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "scripts" / "smoke-installed-cli.sh"
    script_text = script.read_text()

    assert "STUDYLOOP_EXPECT_BIN_DIR" in script_text
    assert 'require_on_path "studyloop"' in script_text
    assert 'require_on_path "session-export"' in script_text


def test_smoke_installed_cli_isolates_the_session_database_and_state_dir() -> None:
    """STUDYLOOP_CONFIG alone does not move session_db or state_dir off the

    machine's real ``~/.config/studyloop/sessions.db`` /
    ``~/.local/share/studyloop`` -- both are resolved independently of which
    config file is active (settings.py's ``_default_session_db``/
    ``_default_state_dir``), so every doctor/self-test check in this script
    reads real session history regardless of the isolated config. A machine
    whose real session DB has accumulated FTS index drift makes `doctor`
    report a "fail" status, which this script's own allowed-status check then
    rejects -- breaking the smoke test for a reason that has nothing to do
    with the release under test. STUDYLOOP_DB and STUDYLOOP_STATE_DIR must be
    isolated the same way STUDYLOOP_CONFIG already is.
    """
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "scripts" / "smoke-installed-cli.sh"
    script_text = script.read_text()

    assert 'export STUDYLOOP_DB="${STUDYLOOP_DB:-$(mktemp -d)/sessions.db}"' in script_text
    assert 'export STUDYLOOP_STATE_DIR="${STUDYLOOP_STATE_DIR:-$(mktemp -d)/state}"' in script_text


def test_smoke_uv_tool_install_uses_isolated_tool_home_and_runs_cli_smoke() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "scripts" / "smoke-uv-tool-install.sh"
    script_text = script.read_text()

    assert 'ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in script_text
    assert 'export HOME="$tmp/home"' in script_text
    assert 'export XDG_CONFIG_HOME="$tmp/xdg-config"' in script_text
    assert 'export XDG_CACHE_HOME="$tmp/xdg-cache"' in script_text
    assert 'export XDG_DATA_HOME="$tmp/xdg-data"' in script_text
    assert 'export UV_TOOL_BIN_DIR="$tmp/bin"' in script_text
    assert 'TOOL_BIN="$UV_TOOL_BIN_DIR"' in script_text
    assert 'uv tool install --force --editable "$ROOT_DIR/packages/studyloop[all]"' in script_text
    assert '--with-editable "$ROOT_DIR/packages/agent-session-tools"' in script_text
    assert (
        'uv tool install --force --editable "$ROOT_DIR/packages/agent-session-tools[all]"'
        in script_text
    )
    assert 'test -x "$TOOL_BIN/studyloop"' in script_text
    assert 'test -x "$TOOL_BIN/session-export"' in script_text
    assert (
        'STUDYLOOP_EXPECT_BIN_DIR="$TOOL_BIN" PATH="$TOOL_BIN:$PATH" '
        '"$ROOT_DIR/scripts/smoke-installed-cli.sh"'
    ) in script_text


def test_justfile_smoke_installed_installs_local_session_export() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    justfile = repo_root / "Justfile"
    justfile_text = justfile.read_text()

    assert "smoke-installed:" in justfile_text
    assert (
        '"$tmp/venv/bin/python" dist/studyloop-*.whl packages/agent-session-tools' in justfile_text
    )
    assert 'STUDYLOOP_EXPECT_BIN_DIR="$tmp/venv/bin"' in justfile_text
