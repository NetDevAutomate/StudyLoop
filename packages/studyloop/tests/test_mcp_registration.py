"""Temp-HOME contracts for cross-harness MCP registration and doctor state."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

import studyloop.doctor.agents as doctor_agents
import studyloop.installers as installers


def _repo_root() -> Path:
    root = Path(__file__).resolve()
    while root != root.parent and not (root / "agents" / "manifest.json").exists():
        root = root.parent
    assert (root / "agents" / "manifest.json").exists()
    return root


def _isolate_install_surfaces(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    """Keep install-agents on its real orchestration path without real-home links."""
    monkeypatch.setattr(installers, "_HOME", home)
    monkeypatch.setattr(installers, "_SHARED_LINKS", ())
    monkeypatch.setattr(
        installers,
        "_TOOL_LINKS",
        dict.fromkeys(installers._AGENT_CHOICES, ()),
    )
    monkeypatch.setattr(installers, "XTILES_SKILL_LINKS", {})
    monkeypatch.setattr(installers, "SESSION_MEMORY_SKILL_LINKS", {})
    monkeypatch.setattr(installers, "_HARNESS_EXPORT", {})
    monkeypatch.setattr(installers, "_configure_claude", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(installers, "install_session_db_mandate", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(installers, "install_claude_stop_hook", lambda: 0)
    monkeypatch.setattr(installers, "install_codex_session_end_hook", lambda: 0)
    # Deterministic, no-real-binary isolation for Grok Build: a bare PATH means
    # shutil.which("grok") can never resolve the developer's real install, and
    # deleting GROK_HOME means _grok_home() falls back to the isolated `home`
    # above rather than a real machine's $GROK_HOME.
    monkeypatch.setenv("PATH", str(home / "empty-bin"))
    monkeypatch.delenv("GROK_HOME", raising=False)


def _fake_grok_bin_dir(tmp_path: Path, script: str) -> Path:
    """Create a directory on PATH containing an executable ``grok`` script.

    The binding rule for this lane: subprocess calls to `grok` are asserted
    by argv via this kind of fake binary, never the developer's real CLI.
    """
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir(exist_ok=True)
    grok = bin_dir / "grok"
    grok.write_text(script, encoding="utf-8")
    grok.chmod(0o755)
    return bin_dir


def _write_unrelated_configs(home: Path) -> dict[Path, str]:
    paths = {
        home / ".claude.json": (
            '{\n  "theme": {"keep": true},\n  "mcpServers": {\n'
            '    "unrelated": {"command": "other", "args": ["--x"]}\n'
            "  }\n}\n"
        ),
        home / ".kiro/settings/mcp.json": (
            '{\n  "ui": {"keep": "kiro"},\n  "mcpServers": {\n'
            '    "unrelated": {"command": "other", "args": ["--y"]}\n'
            "  }\n}\n"
        ),
        home / ".codex/config.toml": (
            'model = "keep"\n\n[mcp_servers.unrelated]\ncommand = "other"\nargs = ["--z"]\n'
        ),
    }
    for path, content in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return paths


def _assert_both_servers_registered(home: Path, *, expect_unrelated: bool = True) -> None:
    expected = {
        "session-db": {"command": "session-db-mcp", "args": []},
        "studyloop": {"command": "studyloop-mcp", "args": []},
    }
    claude = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    kiro = json.loads((home / ".kiro/settings/mcp.json").read_text(encoding="utf-8"))
    codex = tomllib.loads((home / ".codex/config.toml").read_text(encoding="utf-8"))
    for payload in (claude["mcpServers"], kiro["mcpServers"]):
        assert {name: payload[name] for name in expected} == expected
        if expect_unrelated:
            assert payload["unrelated"]["command"] == "other"
    assert {name: codex["mcp_servers"][name] for name in expected} == expected
    if expect_unrelated:
        assert codex["mcp_servers"]["unrelated"]["command"] == "other"


def test_install_agents_registers_both_servers_idempotently_for_three_harnesses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _isolate_install_surfaces(monkeypatch, home)
    original = _write_unrelated_configs(home)

    installers.install_agent_definitions(_repo_root(), tools=["claude", "kiro", "codex"])

    _assert_both_servers_registered(home)
    first_bytes = {path: path.read_bytes() for path in original}
    assert '"theme": {"keep": true}' in (home / ".claude.json").read_text()
    assert '"ui": {"keep": "kiro"}' in (home / ".kiro/settings/mcp.json").read_text()
    assert '[mcp_servers.unrelated]\ncommand = "other"' in (home / ".codex/config.toml").read_text()

    installers.install_agent_definitions(_repo_root(), tools=["claude", "kiro", "codex"])

    assert {path: path.read_bytes() for path in original} == first_bytes


def test_mcp_registration_creates_missing_parent_configs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _isolate_install_surfaces(monkeypatch, home)

    installers.install_agent_definitions(_repo_root(), tools=["claude", "kiro", "codex"])

    _assert_both_servers_registered(home, expect_unrelated=False)


def test_doctor_reports_each_harness_mcp_registration_without_mutating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _isolate_install_surfaces(monkeypatch, home)
    _write_unrelated_configs(home)
    bin_dir = _fake_grok_bin_dir(
        tmp_path,
        "#!/bin/sh\n"
        'if [ "$1 $2" = "mcp add" ]; then exit 0; fi\n'
        'if [ "$1 $2 $3" = "mcp list --json" ]; then\n'
        '  echo \'[{"command": "session-db-mcp", "args": [], "enabled": true,'
        ' "name": "session-db", "scope": "user"},'
        ' {"command": "studyloop-mcp", "args": [], "enabled": true,'
        ' "name": "studyloop", "scope": "user"}]\'\n'
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
    )
    monkeypatch.setenv("PATH", str(bin_dir))
    installers.install_agent_definitions(
        _repo_root(), tools=["claude", "kiro", "codex", "opencode", "grok"]
    )
    before = {
        path: path.read_bytes()
        for path in (
            home / ".claude.json",
            home / ".kiro/settings/mcp.json",
            home / ".codex/config.toml",
            home / ".config/opencode/opencode.json",
        )
    }

    results = doctor_agents.check_mcp_registration()

    assert [(result.name, result.status) for result in results] == [
        ("mcp_claude", "pass"),
        ("mcp_kiro", "pass"),
        ("mcp_codex", "pass"),
        ("mcp_opencode", "pass"),
        ("mcp_grok", "pass"),
    ]
    assert {path: path.read_bytes() for path in before} == before


def test_doctor_check_mcp_registration_yields_entry_for_every_mcp_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(d) check_mcp_registration() names every installers._MCP_HARNESSES entry,

    by set equality, whether or not that harness is actually registered.
    """
    home = tmp_path / "home"
    home.mkdir()
    _isolate_install_surfaces(monkeypatch, home)

    results = doctor_agents.check_mcp_registration()

    assert {result.name for result in results} == {
        f"mcp_{tool}" for tool in installers._MCP_HARNESSES
    }
    assert all(result.status in {"pass", "warn"} for result in results)


# ---------------------------------------------------------------------------
# OpenCode global registration (L8-mcp-opencode-grok)
# ---------------------------------------------------------------------------

_OPENCODE_EXPECTED = {
    "session-db": {
        "command": ["session-db-mcp"],
        "enabled": True,
        "type": "local",
    },
    "studyloop": {
        "command": ["studyloop-mcp"],
        "enabled": True,
        "type": "local",
    },
}


def test_opencode_global_merge_registers_both_servers_preserving_unrelated_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _isolate_install_surfaces(monkeypatch, home)
    config_path = home / ".config/opencode/opencode.json"
    config_path.parent.mkdir(parents=True)
    unrelated = '    "other": {"command": ["echo"], "enabled": true, "type": "local"}'
    config_path.write_text(
        '{\n  "theme": "keep",\n  "mcp": {\n' + unrelated + "\n  }\n}\n",
        encoding="utf-8",
    )

    assert installers.register_mcp_servers(["opencode"]) == {"opencode": 1}

    text = config_path.read_text(encoding="utf-8")
    data = json.loads(text)
    assert {name: data["mcp"][name] for name in _OPENCODE_EXPECTED} == _OPENCODE_EXPECTED
    assert data["theme"] == "keep"
    assert unrelated in text, "unrelated mcp.other entry must survive byte-for-byte"

    # Idempotent re-run: no further write once both servers are correct.
    first_bytes = config_path.read_bytes()
    assert installers.register_mcp_servers(["opencode"]) == {"opencode": 0}
    assert config_path.read_bytes() == first_bytes


def test_opencode_global_merge_creates_missing_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _isolate_install_surfaces(monkeypatch, home)

    assert installers.register_mcp_servers(["opencode"]) == {"opencode": 1}

    config_path = home / ".config/opencode/opencode.json"
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["mcp"] == _OPENCODE_EXPECTED


def test_opencode_uninstall_removes_only_studyloop_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _isolate_install_surfaces(monkeypatch, home)
    config_path = home / ".config/opencode/opencode.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "theme": "keep",
                "mcp": {"other": {"command": ["echo"], "enabled": True, "type": "local"}},
            }
        ),
        encoding="utf-8",
    )
    installers.register_mcp_servers(["opencode"])

    assert installers.unregister_mcp_servers(["opencode"]) == {"opencode": 2}

    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert set(data["mcp"]) == {"other"}
    assert data["theme"] == "keep"
    # Idempotent: nothing left to remove.
    assert installers.unregister_mcp_servers(["opencode"]) == {"opencode": 0}


def test_opencode_status_matches_registered_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _isolate_install_surfaces(monkeypatch, home)

    assert installers.mcp_registration_status(["opencode"]) == {"opencode": False}
    installers.register_mcp_servers(["opencode"])
    assert installers.mcp_registration_status(["opencode"]) == {"opencode": True}


# ---------------------------------------------------------------------------
# Grok Build registration via its own CLI (L8-mcp-opencode-grok)
# ---------------------------------------------------------------------------

_GROK_ADD_RECORDING_SCRIPT = '#!/bin/sh\necho "$@" >> "{log}"\nexit 0\n'


def test_grok_registration_issues_exactly_two_mcp_add_argv_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _isolate_install_surfaces(monkeypatch, home)
    log = tmp_path / "argv.log"
    bin_dir = _fake_grok_bin_dir(tmp_path, _GROK_ADD_RECORDING_SCRIPT.format(log=log))
    monkeypatch.setenv("PATH", str(bin_dir))

    assert installers.register_mcp_servers(["grok"]) == {"grok": 2}

    lines = log.read_text(encoding="utf-8").splitlines()
    assert lines == [
        "mcp add --scope user --transport stdio session-db session-db-mcp",
        "mcp add --scope user --transport stdio studyloop studyloop-mcp",
    ]


def test_grok_registration_skips_cleanly_when_binary_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No `grok` on PATH: registration reports "skipped" (0, no exception) --

    the installer's overall run still completes (the CLI's exit 0), not a
    hard failure for a preview harness merely being absent.
    """
    home = tmp_path / "home"
    home.mkdir()
    _isolate_install_surfaces(monkeypatch, home)

    assert installers.register_mcp_servers(["grok"]) == {"grok": 0}
    # The wider install run (links, mandate, hook) still completes normally;
    # it does not raise merely because grok's MCP registration was skipped.
    installers.install_agent_definitions(_repo_root(), tools=["grok"])


_GROK_LIST_FIXTURE_SCRIPT = (
    "#!/bin/sh\n"
    'if [ "$1 $2 $3" = "mcp list --json" ]; then\n'
    "  echo '{fixture}'\n"
    "  exit 0\n"
    "fi\n"
    "exit 1\n"
)

#: Council grok F7: `grok mcp list --json` on grok 1.0.13 is a JSON array of
#: objects shaped {command, args, enabled, name, scope}.
_GROK_LIST_FIXTURE_BOTH_REGISTERED = json.dumps(
    [
        {
            "command": "session-db-mcp",
            "args": [],
            "enabled": True,
            "name": "session-db",
            "scope": "user",
        },
        {
            "command": "studyloop-mcp",
            "args": [],
            "enabled": True,
            "name": "studyloop",
            "scope": "user",
        },
    ]
)


def test_grok_status_parses_grok_mcp_list_json_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _isolate_install_surfaces(monkeypatch, home)
    bin_dir = _fake_grok_bin_dir(
        tmp_path,
        _GROK_LIST_FIXTURE_SCRIPT.format(fixture=_GROK_LIST_FIXTURE_BOTH_REGISTERED),
    )
    monkeypatch.setenv("PATH", str(bin_dir))

    assert installers.mcp_registration_status(["grok"]) == {"grok": True}


def test_grok_status_false_when_list_reports_only_one_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _isolate_install_surfaces(monkeypatch, home)
    partial_fixture = json.dumps(
        [
            {
                "command": "session-db-mcp",
                "args": [],
                "enabled": True,
                "name": "session-db",
                "scope": "user",
            }
        ]
    )
    bin_dir = _fake_grok_bin_dir(
        tmp_path, _GROK_LIST_FIXTURE_SCRIPT.format(fixture=partial_fixture)
    )
    monkeypatch.setenv("PATH", str(bin_dir))

    assert installers.mcp_registration_status(["grok"]) == {"grok": False}


def test_grok_status_false_when_binary_absent_and_no_legacy_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _isolate_install_surfaces(monkeypatch, home)

    assert installers.mcp_registration_status(["grok"]) == {"grok": False}


def test_grok_legacy_user_settings_entry_counts_as_registered_without_duplicating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """council kimi F13: an older $GROK_HOME/user-settings.json mcpServers map

    counts as registered read-only; registration must not create a duplicate
    entry for a name already present there.
    """
    home = tmp_path / "home"
    home.mkdir()
    _isolate_install_surfaces(monkeypatch, home)
    grok_home = home / ".grok"
    grok_home.mkdir(parents=True)
    (grok_home / "user-settings.json").write_text(
        json.dumps({"mcpServers": {"session-db": {"command": "session-db-mcp"}}}),
        encoding="utf-8",
    )
    log = tmp_path / "argv.log"
    bin_dir = _fake_grok_bin_dir(tmp_path, _GROK_ADD_RECORDING_SCRIPT.format(log=log))
    monkeypatch.setenv("PATH", str(bin_dir))

    # Only the name NOT already in user-settings.json is registered via the CLI.
    assert installers.register_mcp_servers(["grok"]) == {"grok": 1}
    lines = log.read_text(encoding="utf-8").splitlines()
    assert lines == ["mcp add --scope user --transport stdio studyloop studyloop-mcp"]

    # And status is True from the legacy file alone, with no `grok mcp list` call
    # needed once every name is covered there plus the one just registered.
    fixture = json.dumps(
        [{"command": "studyloop-mcp", "args": [], "enabled": True, "name": "studyloop"}]
    )
    list_bin_dir = _fake_grok_bin_dir(tmp_path, _GROK_LIST_FIXTURE_SCRIPT.format(fixture=fixture))
    monkeypatch.setenv("PATH", str(list_bin_dir))
    assert installers.mcp_registration_status(["grok"]) == {"grok": True}


def test_doctor_grok_message_names_the_legacy_user_settings_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding (major, agents.py:247): doctor's grok message must name which

    file satisfied registration. When both server names are covered by the
    legacy ``user-settings.json`` map (council kimi F13), the message names
    that file, not the generic ``config.toml``.
    """
    home = tmp_path / "home"
    home.mkdir()
    _isolate_install_surfaces(monkeypatch, home)
    grok_home = home / ".grok"
    grok_home.mkdir(parents=True)
    legacy_path = grok_home / "user-settings.json"
    legacy_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "session-db": {"command": "session-db-mcp"},
                    "studyloop": {"command": "studyloop-mcp"},
                }
            }
        ),
        encoding="utf-8",
    )

    results = doctor_agents.check_mcp_registration()

    grok_result = next(result for result in results if result.name == "mcp_grok")
    assert grok_result.status == "pass"
    assert str(legacy_path) in grok_result.message
    assert "config.toml" not in grok_result.message


def test_doctor_grok_message_names_the_config_toml_when_cli_registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same finding: when registration is satisfied via `grok mcp list`

    (i.e. `grok mcp add`/config.toml, not the legacy file), the message
    names config.toml instead.
    """
    home = tmp_path / "home"
    home.mkdir()
    _isolate_install_surfaces(monkeypatch, home)
    bin_dir = _fake_grok_bin_dir(
        tmp_path, _GROK_LIST_FIXTURE_SCRIPT.format(fixture=_GROK_LIST_FIXTURE_BOTH_REGISTERED)
    )
    monkeypatch.setenv("PATH", str(bin_dir))

    results = doctor_agents.check_mcp_registration()

    grok_result = next(result for result in results if result.name == "mcp_grok")
    assert grok_result.status == "pass"
    assert str(home / ".grok/config.toml") in grok_result.message
    assert "user-settings.json" not in grok_result.message


def test_doctor_grok_message_is_generic_when_not_registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Neither source registered: no file name to report, generic warn message."""
    home = tmp_path / "home"
    home.mkdir()
    _isolate_install_surfaces(monkeypatch, home)

    results = doctor_agents.check_mcp_registration()

    grok_result = next(result for result in results if result.name == "mcp_grok")
    assert grok_result.status == "warn"
    assert "config.toml" not in grok_result.message
    assert "user-settings.json" not in grok_result.message
    assert grok_result.message == "grok MCP registration is missing or incomplete"


def test_grok_uninstall_removes_both_servers_via_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _isolate_install_surfaces(monkeypatch, home)
    log = tmp_path / "remove.log"
    script = f'#!/bin/sh\necho "$@" >> "{log}"\nexit 0\n'
    bin_dir = _fake_grok_bin_dir(tmp_path, script)
    monkeypatch.setenv("PATH", str(bin_dir))

    assert installers.unregister_mcp_servers(["grok"]) == {"grok": 2}

    lines = log.read_text(encoding="utf-8").splitlines()
    assert lines == ["mcp remove session-db", "mcp remove studyloop"]


@pytest.mark.integration
def test_grok_add_list_remove_lifecycle_with_real_binary(tmp_path: Path) -> None:
    """Opt-in: exercises the REAL `grok` CLI end to end in a temp GROK_HOME.

    Skipped unless `grok` is genuinely on PATH (this is the one place in this
    file that is allowed to invoke it -- everywhere else uses a fake binary).
    """
    import os
    import shutil

    binary = shutil.which("grok")
    if binary is None:
        pytest.skip("grok is not installed on PATH")

    grok_home = tmp_path / "grok-home"
    grok_home.mkdir()
    env = {**os.environ, "GROK_HOME": str(grok_home)}
    import subprocess

    add_session_db = subprocess.run(
        [
            binary,
            "mcp",
            "add",
            "--scope",
            "user",
            "--transport",
            "stdio",
            "session-db",
            "session-db-mcp",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    add_studyloop = subprocess.run(
        [
            binary,
            "mcp",
            "add",
            "--scope",
            "user",
            "--transport",
            "stdio",
            "studyloop",
            "studyloop-mcp",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert add_session_db.returncode == 0, add_session_db.stderr
    assert add_studyloop.returncode == 0, add_studyloop.stderr

    listed = subprocess.run(
        [binary, "mcp", "list", "--json"], env=env, capture_output=True, text=True
    )
    assert listed.returncode == 0, listed.stderr
    names = {entry["name"] for entry in json.loads(listed.stdout)}
    assert {"session-db", "studyloop"} <= names

    for name in ("session-db", "studyloop"):
        removed = subprocess.run(
            [binary, "mcp", "remove", name], env=env, capture_output=True, text=True
        )
        assert removed.returncode == 0, removed.stderr


def test_registration_repairs_owned_json_entry_without_reformatting_unrelated_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(installers, "_HOME", home)
    path = home / ".claude.json"
    unrelated = '    "unrelated": {"command": "other", "args": ["--x"]}'
    path.write_text(
        '{\n  "mcpServers": {\n'
        + unrelated
        + ",\n"
        + '    "session-db": {"command": "wrong", "args": ["--bad"]}\n'
        + "  }\n}\n",
        encoding="utf-8",
    )

    installers.register_mcp_servers(["claude"])

    assert unrelated in path.read_text(encoding="utf-8")
    payload = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]
    assert payload["session-db"] == {"command": "session-db-mcp", "args": []}
    assert payload["studyloop"] == {"command": "studyloop-mcp", "args": []}


@pytest.mark.parametrize(
    "owned_header",
    (
        '[mcp_servers."session-db"]',
        '["mcp_servers".session-db]',
        "['mcp_servers'.'session-db']",
    ),
)
def test_codex_repair_replaces_quoted_owned_table_without_duplication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owned_header: str,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(installers, "_HOME", home)
    path = home / ".codex/config.toml"
    path.parent.mkdir(parents=True)
    unrelated = '[mcp_servers.unrelated]\ncommand = "other"\n# keep unrelated comment\n'
    path.write_text(
        "# keep top comment\n"
        + owned_header
        + '\ncommand = "wrong"\nargs = ["--bad"]\n\n'
        + unrelated,
        encoding="utf-8",
    )

    assert installers.register_mcp_servers(["codex"]) == {"codex": 1}

    repaired = path.read_text(encoding="utf-8")
    parsed = tomllib.loads(repaired)
    assert parsed["mcp_servers"]["session-db"] == {
        "command": "session-db-mcp",
        "args": [],
    }
    assert parsed["mcp_servers"]["studyloop"] == {
        "command": "studyloop-mcp",
        "args": [],
    }
    assert unrelated in repaired
    assert repaired.count("session-db-mcp") == 1
    first_bytes = path.read_bytes()
    assert installers.register_mcp_servers(["codex"]) == {"codex": 0}
    assert path.read_bytes() == first_bytes


def test_codex_repair_removes_complete_owned_subtree_and_preserves_crlf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(installers, "_HOME", home)
    path = home / ".codex/config.toml"
    path.parent.mkdir(parents=True)
    unrelated = (
        '[mcp_servers.unrelated]\r\ncommand = "other"\r\n'
        'args = ["--keep"]\r\n# keep unrelated comment\r\n'
    )
    path.write_bytes(
        (
            "# keep top comment\r\n[mcp_servers]\r\n\r\n"
            '[mcp_servers.session-db]\r\ncommand = "wrong"\r\nargs = []\r\n\r\n'
            '[mcp_servers.session-db.env]\r\nTOKEN = "remove"\r\n\r\n'
            '[mcp_servers.studyloop]\r\ncommand = "wrong"\r\nargs = []\r\n\r\n'
            '[mcp_servers.studyloop.env]\r\nMODE = "remove"\r\n\r\n' + unrelated
        ).encode()
    )

    assert installers.register_mcp_servers(["codex"]) == {"codex": 1}

    repaired_bytes = path.read_bytes()
    repaired = repaired_bytes.decode()
    parsed = tomllib.loads(repaired)
    assert parsed["mcp_servers"]["session-db"] == {
        "command": "session-db-mcp",
        "args": [],
    }
    assert parsed["mcp_servers"]["studyloop"] == {
        "command": "studyloop-mcp",
        "args": [],
    }
    assert "TOKEN" not in repaired
    assert "MODE" not in repaired
    assert unrelated.encode() in repaired_bytes
    assert b"\r\n" in repaired_bytes
    assert b"\n" not in repaired_bytes.replace(b"\r\n", b"")
    assert installers.register_mcp_servers(["codex"]) == {"codex": 0}
    assert path.read_bytes() == repaired_bytes


def test_codex_repair_replaces_owned_values_declared_in_parent_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(installers, "_HOME", home)
    path = home / ".codex/config.toml"
    path.parent.mkdir(parents=True)
    unrelated = 'unrelated = { command = "other", args = ["--keep"] }\n'
    path.write_text(
        "[mcp_servers]\n"
        + unrelated
        + '"session-db" = { command = "wrong", args = ["--bad"] }\n'
        + 'studyloop.command = "wrong"\n'
        + 'studyloop.args = ["--bad"]\n\n'
        + '[ui]\n# keep ui comment\ntheme = "dark"\n',
        encoding="utf-8",
    )

    assert installers.register_mcp_servers(["codex"]) == {"codex": 1}

    repaired = path.read_text(encoding="utf-8")
    parsed = tomllib.loads(repaired)
    assert parsed["mcp_servers"]["session-db"] == {
        "command": "session-db-mcp",
        "args": [],
    }
    assert parsed["mcp_servers"]["studyloop"] == {
        "command": "studyloop-mcp",
        "args": [],
    }
    assert unrelated in repaired
    assert '[ui]\n# keep ui comment\ntheme = "dark"\n' in repaired
    first_bytes = path.read_bytes()
    assert installers.register_mcp_servers(["codex"]) == {"codex": 0}
    assert path.read_bytes() == first_bytes


def test_codex_repair_preserves_exact_multiline_notes_data_loss_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(installers, "_HOME", home)
    path = home / ".codex/config.toml"
    path.parent.mkdir(parents=True)
    unrelated_before = '[ui]\nnotes = """\n[mcp_servers.session-db]\ncommand = "fictional"\n"""\n'
    owned = '[mcp_servers.session-db]\ncommand = "wrong"\nargs = ["--bad"]\n'
    unrelated_after = '[mcp_servers.unrelated]\ncommand = "other"\n'
    original = unrelated_before + owned + unrelated_after
    original_notes = tomllib.loads(original)["ui"]["notes"]
    path.write_text(original, encoding="utf-8")

    assert installers.register_mcp_servers(["codex"]) == {"codex": 1}

    repaired_bytes = path.read_bytes()
    repaired = repaired_bytes.decode()
    parsed = tomllib.loads(repaired)
    assert parsed["ui"]["notes"] == original_notes
    assert repaired_bytes.startswith((unrelated_before + unrelated_after).encode())
    assert parsed["mcp_servers"]["session-db"] == {
        "command": "session-db-mcp",
        "args": [],
    }
    assert parsed["mcp_servers"]["studyloop"] == {
        "command": "studyloop-mcp",
        "args": [],
    }
    assert installers.register_mcp_servers(["codex"]) == {"codex": 0}
    assert path.read_bytes() == repaired_bytes


@pytest.mark.parametrize(
    ("newline", "unrelated_before"),
    (
        (
            "\n",
            '[ui]\n# keep outside comment\nnotes = """escaped quote: \\" still open\n'
            "escaped backslash: \\\\\n# string comment text\n"
            '[mcp_servers.studyloop]\ncommand = "fictional"\n"""\n',
        ),
        (
            "\r\n",
            "[ui]\r\n# keep outside comment\r\nnotes = '''literal text\r\n"
            "# string comment text\r\n[mcp_servers.session-db]\r\n"
            "command = 'fictional'\r\n'''\r\n",
        ),
    ),
)
def test_codex_repair_preserves_table_text_in_multiline_string_lexical_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    newline: str,
    unrelated_before: str,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(installers, "_HOME", home)
    path = home / ".codex/config.toml"
    path.parent.mkdir(parents=True)
    owned = f'[mcp_servers.studyloop]{newline}command = "wrong"{newline}args = ["--bad"]{newline}'
    unrelated_after = (
        f"[mcp_servers.unrelated]{newline}"
        f'command = "other"{newline}'
        f"# keep trailing comment{newline}"
    )
    original = unrelated_before + owned + unrelated_after
    original_notes = tomllib.loads(original)["ui"]["notes"]
    path.write_bytes(original.encode())

    assert installers.register_mcp_servers(["codex"]) == {"codex": 1}

    repaired_bytes = path.read_bytes()
    repaired = repaired_bytes.decode()
    parsed = tomllib.loads(repaired)
    assert parsed["ui"]["notes"] == original_notes
    assert repaired_bytes.startswith((unrelated_before + unrelated_after).encode())
    assert b"# keep outside comment" in repaired_bytes
    assert b"# keep trailing comment" in repaired_bytes
    if newline == "\r\n":
        assert b"\n" not in repaired_bytes.replace(b"\r\n", b"")
    assert installers.register_mcp_servers(["codex"]) == {"codex": 0}
    assert path.read_bytes() == repaired_bytes


def test_codex_repair_removes_owned_multiline_value_without_false_header_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(installers, "_HOME", home)
    path = home / ".codex/config.toml"
    path.parent.mkdir(parents=True)
    owned = (
        '[mcp_servers.session-db]\ncommand = """wrong \\" still open\n'
        '[mcp_servers.studyloop]\ncommand = "fictional"\n"""\nargs = ["--bad"]\n'
        '[mcp_servers.session-db.env]\nTOKEN = "remove"\n'
    )
    unrelated = (
        "[ui]\nnotes = '''[mcp_servers.session-db]\n"
        "command = 'keep as text'\n'''\n# keep final comment\n"
    )
    original_notes = tomllib.loads(owned + unrelated)["ui"]["notes"]
    path.write_text(owned + unrelated, encoding="utf-8")

    assert installers.register_mcp_servers(["codex"]) == {"codex": 1}

    repaired_bytes = path.read_bytes()
    repaired = repaired_bytes.decode()
    parsed = tomllib.loads(repaired)
    assert repaired_bytes.startswith(unrelated.encode())
    assert parsed["ui"]["notes"] == original_notes
    assert "TOKEN" not in repaired
    assert parsed["mcp_servers"]["session-db"] == {
        "command": "session-db-mcp",
        "args": [],
    }
    assert parsed["mcp_servers"]["studyloop"] == {
        "command": "studyloop-mcp",
        "args": [],
    }
    assert installers.register_mcp_servers(["codex"]) == {"codex": 0}
    assert path.read_bytes() == repaired_bytes


@pytest.mark.parametrize("owned_value", ('"wrong"', '["wrong"]', "null", "42", "false"))
def test_json_repair_replaces_every_valid_owned_value_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owned_value: str,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(installers, "_HOME", home)
    path = home / ".claude.json"
    unrelated = '    "unrelated": {"command": "other", "args": ["--keep"]}'
    path.write_text(
        '{\n  "theme": {"keep": true},\n  "mcpServers": {\n'
        + unrelated
        + ',\n    "session-db": '
        + owned_value
        + "\n  }\n}\n",
        encoding="utf-8",
    )

    assert installers.register_mcp_servers(["claude"]) == {"claude": 1}

    repaired = path.read_text(encoding="utf-8")
    parsed = json.loads(repaired)
    assert parsed["mcpServers"]["session-db"] == {
        "command": "session-db-mcp",
        "args": [],
    }
    assert parsed["mcpServers"]["studyloop"] == {
        "command": "studyloop-mcp",
        "args": [],
    }
    assert unrelated in repaired
    assert repaired.count('"session-db"') == 1
    first_bytes = path.read_bytes()
    assert installers.register_mcp_servers(["claude"]) == {"claude": 0}
    assert path.read_bytes() == first_bytes


@pytest.mark.parametrize("container", ("null", "[]", '"wrong"', "42", "false"))
def test_json_repair_replaces_non_object_mcp_servers_container_without_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    container: str,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(installers, "_HOME", home)
    path = home / ".kiro/settings/mcp.json"
    path.parent.mkdir(parents=True)
    unrelated = '  "ui": {"theme": "keep"},\r\n'
    path.write_bytes(("{\r\n" + unrelated + '  "mcpServers": ' + container + "\r\n}\r\n").encode())

    assert installers.register_mcp_servers(["kiro"]) == {"kiro": 1}

    repaired_bytes = path.read_bytes()
    repaired = repaired_bytes.decode()
    parsed = json.loads(repaired)
    assert parsed["mcpServers"] == {
        "session-db": {"command": "session-db-mcp", "args": []},
        "studyloop": {"command": "studyloop-mcp", "args": []},
    }
    assert repaired.count('"mcpServers"') == 1
    assert unrelated.encode() in repaired_bytes
    assert b"\n" not in repaired_bytes.replace(b"\r\n", b"")
    assert installers.register_mcp_servers(["kiro"]) == {"kiro": 0}
    assert path.read_bytes() == repaired_bytes


def test_json_repair_rejects_comments_without_mutating_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(installers, "_HOME", home)
    path = home / ".claude.json"
    original = b'{\n  // JSON comments are not supported\n  "mcpServers": null\n}\n'
    path.write_bytes(original)

    with pytest.raises(installers.InstallError, match="malformed"):
        installers.register_mcp_servers(["claude"])

    assert path.read_bytes() == original


# ---------------------------------------------------------------------------
# Docs congruence (L8-mcp-opencode-grok TESTS FIRST (e))
# ---------------------------------------------------------------------------


def _repo_text(relative: str) -> str:
    return (_repo_root() / relative).read_text(encoding="utf-8")


def test_mcp_readme_has_no_stale_not_registered_for_opencode_wording() -> None:
    text = _repo_text("agents/mcp/README.md")
    assert "not registered for OpenCode" not in text


def test_session_memory_skill_names_pi_as_cli_only_by_design() -> None:
    """pi's own README states "No MCP" by design; the skill documents that

    rather than a repo-side registration gap.
    """
    text = _repo_text("agents/skills/studyloop-session-memory/SKILL.md")
    assert "pi has no MCP by design" in text


def test_session_memory_skill_marks_opencode_and_grok_as_mcp_plus_fallback() -> None:
    text = _repo_text("agents/skills/studyloop-session-memory/SKILL.md")
    assert "MCP + fallback" in text


def test_topic_exercises_generic_mcp_example_uses_studyloop_as_server_name() -> None:
    """council grok F9: `studyloop-mcp` is the console-script COMMAND, never a

    server name -- the generic MCP config sample must key by `studyloop`.
    """
    text = _repo_text("docs/topic-exercises.md")
    assert '"studyloop": {' in text
    assert '"studyloop-mcp": {' not in text
