"""Tests for reusable persona injection strategies and MCP config writers."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest


class TestCliFlagStrategy:
    def test_creates_temp_file(self, tmp_path):
        from studyloop.adapters._strategies import cli_flag_setup

        result = cli_flag_setup("# Persona", tmp_path)
        assert result.exists()
        assert result.read_text() == "# Persona"

    def test_file_has_secure_permissions(self, tmp_path):
        from studyloop.adapters._strategies import cli_flag_setup

        result = cli_flag_setup("# Secure", tmp_path)
        mode = stat.S_IMODE(result.stat().st_mode)
        assert mode == 0o600

    def test_returns_path_object(self, tmp_path):
        from studyloop.adapters._strategies import cli_flag_setup

        result = cli_flag_setup("# Persona", tmp_path)
        assert isinstance(result, Path)


class TestCwdFileStrategy:
    def test_writes_to_session_dir(self, tmp_path):
        from studyloop.adapters._strategies import cwd_file_setup

        result = cwd_file_setup("# Persona", tmp_path, filename="CUSTOM.md")
        assert result == tmp_path / "CUSTOM.md"
        assert result.read_text() == "# Persona"

    def test_default_filename(self, tmp_path):
        from studyloop.adapters._strategies import cwd_file_setup

        result = cwd_file_setup("# Persona", tmp_path)
        assert result.name == "PERSONA.md"
        assert result.parent == tmp_path


class TestMcpConfigWriter:
    def test_generic_format(self, tmp_path):
        from studyloop.adapters._strategies import write_mcp_config

        write_mcp_config(tmp_path, fmt="generic")
        config_path = tmp_path / ".mcp.json"
        assert config_path.exists()
        data = json.loads(config_path.read_text())
        assert "mcpServers" in data
        assert "studyloop-mcp" in data["mcpServers"]
        entry = data["mcpServers"]["studyloop-mcp"]
        assert "command" in entry
        assert "args" in entry

    def test_opencode_format(self, tmp_path):
        from studyloop.adapters._strategies import write_mcp_config

        write_mcp_config(tmp_path, fmt="opencode")
        config_path = tmp_path / ".opencode" / "opencode.json"
        assert config_path.exists()
        data = json.loads(config_path.read_text())
        assert "mcp" in data
        assert "studyloop-mcp" in data["mcp"]
        entry = data["mcp"]["studyloop-mcp"]
        assert entry["enabled"] is True
        assert entry["type"] == "local"
        assert "command" in entry

    def test_dev_flag_is_explicit_in_generic_mcp_config(self, tmp_path, monkeypatch):
        from studyloop.adapters import _strategies

        monkeypatch.setattr(_strategies, "_mcp_command", lambda: ["studyloop-mcp"])
        _strategies.write_mcp_config(tmp_path, fmt="generic", dev=True)
        data = json.loads((tmp_path / ".mcp.json").read_text())
        assert data["mcpServers"]["studyloop-mcp"]["args"] == ["--dev"]

    def test_dev_flag_is_explicit_in_opencode_mcp_config(self, tmp_path, monkeypatch):
        from studyloop.adapters import _strategies

        monkeypatch.setattr(_strategies, "_mcp_command", lambda: ["studyloop-mcp"])
        _strategies.write_mcp_config(tmp_path, fmt="opencode", dev=True)
        data = json.loads((tmp_path / ".opencode" / "opencode.json").read_text())
        assert data["mcp"]["studyloop-mcp"]["command"] == ["studyloop-mcp", "--dev"]

    def test_custom_path_override(self, tmp_path):
        from studyloop.adapters._strategies import write_mcp_config

        write_mcp_config(tmp_path, fmt="generic", path="custom/mcp.json")
        config_path = tmp_path / "custom" / "mcp.json"
        assert config_path.exists()

    def test_unknown_format_raises(self, tmp_path):
        from studyloop.adapters._strategies import write_mcp_config

        with pytest.raises(ValueError, match="Unknown MCP config format"):
            write_mcp_config(tmp_path, fmt="bogus")
