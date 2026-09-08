"""Temp-HOME contracts for cross-harness MCP registration and doctor state."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

import studyloop.doctor.agents as doctor_agents
import studyloop.installers as installers

if TYPE_CHECKING:
    import pytest


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
    installers.install_agent_definitions(_repo_root(), tools=["claude", "kiro", "codex"])
    before = {
        path: path.read_bytes()
        for path in (
            home / ".claude.json",
            home / ".kiro/settings/mcp.json",
            home / ".codex/config.toml",
        )
    }

    results = doctor_agents.check_mcp_registration()

    assert [(result.name, result.status) for result in results] == [
        ("mcp_claude", "pass"),
        ("mcp_kiro", "pass"),
        ("mcp_codex", "pass"),
    ]
    assert {path: path.read_bytes() for path in before} == before


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
