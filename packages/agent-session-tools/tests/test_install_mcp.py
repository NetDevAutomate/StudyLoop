"""Idempotent per-harness session-db MCP registration (WP-2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_session_tools.install.mcp import (
    NAME,
    InstallError,
    merge_kiro_mcp,
    register_mcp,
)


def test_kiro_merge_creates_file_and_registers(tmp_path: Path) -> None:
    path = tmp_path / ".kiro" / "settings" / "mcp.json"
    assert merge_kiro_mcp(path) is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mcpServers"][NAME] == {"command": "session-db-mcp"}


def test_kiro_merge_preserves_unrelated_keys(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(
            {"mcpServers": {"other": {"command": "other-mcp"}}, "theme": "dark"}
        ),
        encoding="utf-8",
    )
    assert merge_kiro_mcp(path) is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["other"] == {"command": "other-mcp"}
    assert data["theme"] == "dark"
    assert data["mcpServers"][NAME] == {"command": "session-db-mcp"}


def test_kiro_merge_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    assert merge_kiro_mcp(path) is True
    before = path.read_text(encoding="utf-8")
    assert merge_kiro_mcp(path) is False
    assert path.read_text(encoding="utf-8") == before


def test_kiro_dry_run_reports_without_writing(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    assert merge_kiro_mcp(path, dry_run=True) is True
    assert not path.exists()


def test_merge_classifies_invalid_json_instead_of_crashing(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text('{"mcpServers": {broken', encoding="utf-8")
    with pytest.raises(InstallError, match="invalid JSON"):
        merge_kiro_mcp(path)


def test_merge_rejects_non_object_config(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(InstallError, match="not a JSON object"):
        merge_kiro_mcp(path)


def test_merge_rejects_non_object_section(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": "oops"}), encoding="utf-8")
    with pytest.raises(InstallError, match="not an object"):
        merge_kiro_mcp(path)


def test_register_mcp_uses_default_path_under_home(tmp_path: Path) -> None:
    assert register_mcp("kiro", home=tmp_path) is True
    installed = json.loads(
        (tmp_path / ".kiro" / "settings" / "mcp.json").read_text(encoding="utf-8")
    )
    assert NAME in installed["mcpServers"]


def test_register_mcp_fails_closed_for_toml_and_pi(tmp_path: Path) -> None:
    with pytest.raises(InstallError, match="tomlkit"):
        register_mcp("codex", home=tmp_path)
    with pytest.raises(InstallError, match="no verified user-editable MCP registry"):
        register_mcp("pi", home=tmp_path)
    with pytest.raises(InstallError, match="unknown harness"):
        register_mcp("emacs", home=tmp_path)
