"""Tests for config-driven custom agents."""

from __future__ import annotations

import stat
from unittest.mock import patch


class TestCustomAgentFromConfig:
    def test_cli_flag_strategy(self, tmp_path):
        from studyctl.adapters._custom import build_custom_adapter

        config = {"binary": "aider", "strategy": "cli-flag", "launch": "{binary} --read {persona}"}
        adapter = build_custom_adapter("aider", config)
        assert adapter.name == "aider"
        assert adapter.binary == "aider"
        path = adapter.setup("# content", tmp_path)
        assert path.exists()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_launch_cmd_interpolation(self, tmp_path):
        from studyctl.adapters._custom import build_custom_adapter

        config = {"binary": "aider", "strategy": "cli-flag", "launch": "{binary} --read {persona}"}
        adapter = build_custom_adapter("aider", config)
        persona = tmp_path / "persona.md"
        persona.touch()
        with patch("shutil.which", return_value="/usr/local/bin/aider"):
            cmd = adapter.launch_cmd(persona, resume=False)
        assert "/usr/local/bin/aider" in cmd
        assert str(persona) in cmd

    def test_resume_template(self, tmp_path):
        from studyctl.adapters._custom import build_custom_adapter

        config = {
            "binary": "aider",
            "strategy": "cli-flag",
            "launch": "{binary} --read {persona}",
            "resume": "{binary} --read {persona} --resume",
        }
        adapter = build_custom_adapter("aider", config)
        persona = tmp_path / "p.md"
        persona.touch()
        with patch("shutil.which", return_value="/usr/bin/aider"):
            cmd = adapter.launch_cmd(persona, resume=True)
        assert "--resume" in cmd

    def test_env_vars_prepended(self, tmp_path):
        from studyctl.adapters._custom import build_custom_adapter

        config = {
            "binary": "claude",
            "strategy": "cli-flag",
            "launch": "{binary} --prompt {persona}",
            "env": {"ANTHROPIC_BASE_URL": "http://localhost:4000", "MODEL": "qwen3"},
        }
        adapter = build_custom_adapter("my-llm", config)
        persona = tmp_path / "p.md"
        persona.touch()
        with patch("shutil.which", return_value="/usr/bin/claude"):
            cmd = adapter.launch_cmd(persona, resume=False)
        assert "ANTHROPIC_BASE_URL=http://localhost:4000" in cmd
        assert "MODEL=qwen3" in cmd

    def test_cwd_file_strategy(self, tmp_path):
        from studyctl.adapters._custom import build_custom_adapter

        config = {
            "binary": "my-agent",
            "strategy": "cwd-file",
            "filename": ".my-prompt.md",
            "launch": "{binary}",
        }
        adapter = build_custom_adapter("my-agent", config)
        path = adapter.setup("# persona", tmp_path)
        assert path == tmp_path / ".my-prompt.md"
        assert "persona" in path.read_text()

    def test_teardown_cmd(self, tmp_path):
        from studyctl.adapters._custom import build_custom_adapter

        marker = tmp_path / "teardown-ran"
        config = {
            "binary": "agent",
            "strategy": "cli-flag",
            "launch": "{binary}",
            "teardown": f"touch {marker}",
        }
        adapter = build_custom_adapter("agent", config)
        assert adapter.teardown is not None
        adapter.teardown(tmp_path)
        assert marker.exists()

    def test_teardown_idempotent(self, tmp_path):
        from studyctl.adapters._custom import build_custom_adapter

        config = {
            "binary": "agent",
            "strategy": "cli-flag",
            "launch": "{binary}",
            "teardown": "true",
        }
        adapter = build_custom_adapter("agent", config)
        adapter.teardown(tmp_path)
        adapter.teardown(tmp_path)  # Must not raise

    def test_mcp_generic(self, tmp_path):
        from studyctl.adapters._custom import build_custom_adapter

        config = {
            "binary": "agent",
            "strategy": "cli-flag",
            "launch": "{binary}",
            "mcp": {"format": "generic"},
        }
        adapter = build_custom_adapter("agent", config)
        assert adapter.mcp_setup is not None
        adapter.mcp_setup(tmp_path)
        assert (tmp_path / ".mcp.json").exists()

    def test_mcp_bool_true_means_generic(self, tmp_path):
        from studyctl.adapters._custom import build_custom_adapter

        config = {"binary": "agent", "strategy": "cli-flag", "launch": "{binary}", "mcp": True}
        adapter = build_custom_adapter("agent", config)
        assert adapter.mcp_setup is not None
        adapter.mcp_setup(tmp_path)
        assert (tmp_path / ".mcp.json").exists()

    def test_unknown_strategy_raises(self):
        import pytest

        from studyctl.adapters._custom import build_custom_adapter

        with pytest.raises(ValueError, match="Unknown strategy"):
            build_custom_adapter("bad", {"binary": "x", "strategy": "unknown", "launch": "x"})
