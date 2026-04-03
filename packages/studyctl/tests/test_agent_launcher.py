"""Tests for studyctl.agent_launcher — agent detection and launch."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

# Inline fixtures only (no conftest.py — pluggy conflict)


# ---------------------------------------------------------------------------
# Agent registry and adapter dataclass
# ---------------------------------------------------------------------------


class TestAgentRegistry:
    def test_four_agents_registered(self):
        from studyctl.agent_launcher import AGENTS

        assert set(AGENTS.keys()) == {"claude", "gemini", "kiro", "opencode"}

    def test_adapters_have_required_fields(self):
        from studyctl.agent_launcher import AGENTS

        for name, adapter in AGENTS.items():
            assert adapter.name == name
            assert adapter.binary, f"{name} has no binary"
            assert callable(adapter.setup), f"{name}.setup not callable"
            assert callable(adapter.launch_cmd), f"{name}.launch_cmd not callable"

    def test_claude_adapter_is_wired(self):
        from studyctl.agent_launcher import AGENTS

        claude = AGENTS["claude"]
        assert claude.binary == "claude"
        assert claude.teardown is None  # Claude has no global state to clean up

    def test_kiro_binary_is_kiro_cli(self):
        from studyctl.agent_launcher import AGENTS

        assert AGENTS["kiro"].binary == "kiro-cli"

    def test_all_agents_are_wired(self, tmp_path):
        from studyctl.agent_launcher import AGENTS

        for name in ("gemini", "opencode"):
            # These write to session_dir — should not raise
            path = AGENTS[name].setup("# test content", tmp_path)
            assert path.exists()

    def test_kiro_has_teardown(self):
        from studyctl.agent_launcher import AGENTS

        assert AGENTS["kiro"].teardown is not None
        assert AGENTS["claude"].teardown is None

    def test_gemini_has_mcp_setup(self):
        from studyctl.agent_launcher import AGENTS

        assert AGENTS["gemini"].mcp_setup is not None
        assert AGENTS["opencode"].mcp_setup is not None
        assert AGENTS["claude"].mcp_setup is None

    def test_get_adapter(self):
        from studyctl.agent_launcher import get_adapter

        adapter = get_adapter("claude")
        assert adapter.name == "claude"

    def test_get_adapter_unknown_raises(self):
        from studyctl.agent_launcher import get_adapter

        with pytest.raises(KeyError):
            get_adapter("nonexistent")


# ---------------------------------------------------------------------------
# Agent detection
# ---------------------------------------------------------------------------


class TestDetectAgents:
    def test_detect_claude_installed(self):
        from studyctl.agent_launcher import detect_agents

        with patch("studyctl.agent_launcher.shutil.which") as mock_which:
            mock_which.side_effect = lambda b: "/usr/local/bin/claude" if b == "claude" else None
            agents = detect_agents()
            assert agents == ["claude"]

    def test_detect_no_agents(self):
        from studyctl.agent_launcher import detect_agents

        with patch("studyctl.agent_launcher.shutil.which") as mock_which:
            mock_which.return_value = None
            agents = detect_agents()
            assert agents == []

    def test_detect_multiple_agents(self):
        from studyctl.agent_launcher import detect_agents

        installed = {"claude", "gemini"}
        with patch("studyctl.agent_launcher.shutil.which") as mock_which:
            mock_which.side_effect = lambda b: f"/usr/bin/{b}" if b in installed else None
            agents = detect_agents()
            assert "claude" in agents
            assert "gemini" in agents
            assert "kiro" not in agents

    def test_detect_respects_env_var_override(self):
        from studyctl.agent_launcher import detect_agents

        with (
            patch("studyctl.agent_launcher.shutil.which", return_value="/usr/bin/gemini"),
            patch.dict(os.environ, {"STUDYCTL_AGENT": "gemini"}),
        ):
            agents = detect_agents()
            assert agents == ["gemini"]

    def test_detect_env_var_not_installed_returns_empty(self):
        from studyctl.agent_launcher import detect_agents

        with (
            patch("studyctl.agent_launcher.shutil.which", return_value=None),
            patch.dict(os.environ, {"STUDYCTL_AGENT": "gemini"}),
        ):
            agents = detect_agents()
            assert agents == []

    def test_get_default_agent(self):
        from studyctl.agent_launcher import get_default_agent

        with patch("studyctl.agent_launcher.shutil.which") as mock_which:
            mock_which.side_effect = lambda b: "/usr/local/bin/claude" if b == "claude" else None
            assert get_default_agent() == "claude"

    def test_get_default_agent_none_available(self):
        from studyctl.agent_launcher import get_default_agent

        with patch("studyctl.agent_launcher.shutil.which") as mock_which:
            mock_which.return_value = None
            assert get_default_agent() is None


# ---------------------------------------------------------------------------
# Canonical persona builder
# ---------------------------------------------------------------------------


class TestBuildCanonicalPersona:
    def test_includes_topic_and_energy(self):
        from studyctl.agent_launcher import build_canonical_persona

        content = build_canonical_persona("study", "Python Decorators", 7)
        assert "Python Decorators" in content
        assert "7/10" in content
        assert "study" in content.lower()

    def test_includes_resume_notes(self):
        from studyctl.agent_launcher import build_canonical_persona

        content = build_canonical_persona("study", "SQL", 5, previous_notes="Covered JOINs")
        assert "Resuming Previous Session" in content
        assert "Covered JOINs" in content

    def test_co_study_mode(self):
        from studyctl.agent_launcher import build_canonical_persona

        content = build_canonical_persona("co-study", "Spark", 3)
        assert "co-study" in content.lower() or "companion" in content.lower()


# ---------------------------------------------------------------------------
# Backward-compatible wrappers
# ---------------------------------------------------------------------------


class TestBuildPersonaFile:
    def test_creates_temp_file(self):
        from studyctl.agent_launcher import build_persona_file

        path = build_persona_file("study", "Python Decorators", 7)
        try:
            assert path.exists()
            assert path.suffix == ".md"
            content = path.read_text()
            assert "Python Decorators" in content
            assert "7/10" in content
            assert "study" in content.lower()
        finally:
            path.unlink(missing_ok=True)

    def test_file_permissions_0600(self):
        from studyctl.agent_launcher import build_persona_file

        path = build_persona_file("study", "Test Topic", 5)
        try:
            mode = oct(os.stat(path).st_mode & 0o777)
            assert mode == "0o600"
        finally:
            path.unlink(missing_ok=True)

    def test_co_study_persona(self):
        from studyctl.agent_launcher import build_persona_file

        path = build_persona_file("co-study", "Spark Internals", 3)
        try:
            content = path.read_text()
            assert "co-study" in content.lower() or "companion" in content.lower()
        finally:
            path.unlink(missing_ok=True)

    def test_uses_persona_file_when_available(self, tmp_path):
        from studyctl.agent_launcher import build_persona_file

        # Create a test persona file
        persona_content = "# Test Persona\nThis is a test."
        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "read_text", return_value=persona_content),
        ):
            path = build_persona_file("study", "Test", 5)
            try:
                content = path.read_text()
                assert "Test Persona" in content
            finally:
                path.unlink(missing_ok=True)


class TestGetLaunchCommand:
    def test_claude_command(self, tmp_path):
        from studyctl.agent_launcher import get_launch_command

        persona = tmp_path / "persona.md"
        persona.touch()

        cmd = get_launch_command("claude", persona)
        assert "claude" in cmd
        assert "--append-system-prompt-file" in cmd
        assert str(persona) in cmd

    def test_claude_resume_command(self, tmp_path):
        from studyctl.agent_launcher import get_launch_command

        persona = tmp_path / "persona.md"
        persona.touch()

        cmd = get_launch_command("claude", persona, resume=True)
        assert "-r" in cmd
        assert "--append-system-prompt-file" in cmd

    def test_unknown_agent_raises(self, tmp_path):
        from studyctl.agent_launcher import get_launch_command

        persona = tmp_path / "persona.md"
        with pytest.raises(KeyError):
            get_launch_command("unknown-agent", persona)


# ---------------------------------------------------------------------------
# Claude adapter functions directly
# ---------------------------------------------------------------------------


class TestClaudeAdapter:
    def test_setup_writes_temp_file(self, tmp_path):
        from studyctl.agent_launcher import _claude_setup

        path = _claude_setup("# Test Content\nHello", tmp_path)
        try:
            assert path.exists()
            assert path.read_text() == "# Test Content\nHello"
            assert oct(os.stat(path).st_mode & 0o777) == "0o600"
        finally:
            path.unlink(missing_ok=True)

    def test_launch_new_session(self):
        from studyctl.agent_launcher import _claude_launch

        cmd = _claude_launch(Path("/tmp/persona.md"), resume=False)
        assert "--append-system-prompt-file" in cmd
        assert "/tmp/persona.md" in cmd
        assert "-r" not in cmd.split("--")[0]  # no -r before the flag

    def test_launch_resume_session(self):
        from studyctl.agent_launcher import _claude_launch

        cmd = _claude_launch(Path("/tmp/persona.md"), resume=True)
        assert "-r" in cmd
        assert "--append-system-prompt-file" in cmd


# ---------------------------------------------------------------------------
# Kiro adapter
# ---------------------------------------------------------------------------


class TestKiroAdapter:
    def test_setup_writes_persona_temp_file(self, tmp_path, monkeypatch):
        from studyctl.agent_launcher import _kiro_setup

        # Redirect Kiro agents dir to tmp_path
        fake_kiro = tmp_path / ".kiro" / "agents"
        fake_kiro.mkdir(parents=True)
        monkeypatch.setattr("studyctl.agent_launcher.KIRO_AGENTS_DIR", fake_kiro)

        path = _kiro_setup("# Kiro Test", tmp_path)
        try:
            assert path.exists()
            assert path.read_text() == "# Kiro Test"
        finally:
            path.unlink(missing_ok=True)

    def test_setup_writes_agent_json(self, tmp_path, monkeypatch):
        import json

        from studyctl.agent_launcher import KIRO_AGENT_NAME, _kiro_setup

        fake_kiro = tmp_path / ".kiro" / "agents"
        fake_kiro.mkdir(parents=True)
        monkeypatch.setattr("studyctl.agent_launcher.KIRO_AGENTS_DIR", fake_kiro)

        persona_path = _kiro_setup("# Test Content", tmp_path)
        try:
            agent_json = fake_kiro / f"{KIRO_AGENT_NAME}.json"
            assert agent_json.exists()
            data = json.loads(agent_json.read_text())
            assert data["prompt"] == f"file://{persona_path}"
            assert data["name"] == KIRO_AGENT_NAME
        finally:
            persona_path.unlink(missing_ok=True)

    def test_setup_creates_backup(self, tmp_path, monkeypatch):
        from studyctl.agent_launcher import KIRO_AGENT_NAME, _kiro_setup

        fake_kiro = tmp_path / ".kiro" / "agents"
        fake_kiro.mkdir(parents=True)
        # Pre-existing agent JSON
        existing = fake_kiro / f"{KIRO_AGENT_NAME}.json"
        existing.write_text('{"name": "study-mentor", "prompt": "original"}')
        monkeypatch.setattr("studyctl.agent_launcher.KIRO_AGENTS_DIR", fake_kiro)

        persona_path = _kiro_setup("# New Content", tmp_path)
        try:
            backup = fake_kiro / f"{KIRO_AGENT_NAME}.json.studyctl-backup"
            assert backup.exists()
            assert '"original"' in backup.read_text()
        finally:
            persona_path.unlink(missing_ok=True)

    def test_teardown_restores_backup(self, tmp_path, monkeypatch):
        from studyctl.agent_launcher import KIRO_AGENT_NAME, _kiro_teardown

        fake_kiro = tmp_path / ".kiro" / "agents"
        fake_kiro.mkdir(parents=True)
        target = fake_kiro / f"{KIRO_AGENT_NAME}.json"
        target.write_text('{"prompt": "modified"}')
        backup = target.with_suffix(target.suffix + ".studyctl-backup")
        backup.write_text('{"prompt": "original"}')
        monkeypatch.setattr("studyctl.agent_launcher.KIRO_AGENTS_DIR", fake_kiro)

        _kiro_teardown(tmp_path)

        assert target.read_text() == '{"prompt": "original"}'
        assert not backup.exists()

    def test_teardown_noop_without_backup(self, tmp_path, monkeypatch):
        from studyctl.agent_launcher import _kiro_teardown

        fake_kiro = tmp_path / ".kiro" / "agents"
        fake_kiro.mkdir(parents=True)
        monkeypatch.setattr("studyctl.agent_launcher.KIRO_AGENTS_DIR", fake_kiro)

        # Should not raise
        _kiro_teardown(tmp_path)

    def test_launch_new_session(self):
        from studyctl.agent_launcher import _kiro_launch

        cmd = _kiro_launch(Path("/tmp/persona.md"), resume=False)
        assert "chat" in cmd
        assert "--agent" in cmd
        assert "study-mentor" in cmd
        assert "--resume" not in cmd

    def test_launch_resume(self):
        from studyctl.agent_launcher import _kiro_launch

        cmd = _kiro_launch(Path("/tmp/persona.md"), resume=True)
        assert "--resume" in cmd
        assert "study-mentor" in cmd


# ---------------------------------------------------------------------------
# Gemini adapter
# ---------------------------------------------------------------------------


class TestGeminiAdapter:
    def test_setup_writes_gemini_md(self, tmp_path):
        from studyctl.agent_launcher import _gemini_setup

        path = _gemini_setup("# Gemini Persona", tmp_path)
        assert path == tmp_path / "GEMINI.md"
        assert path.exists()
        assert path.read_text() == "# Gemini Persona"

    def test_mcp_writes_settings_json(self, tmp_path):
        import json

        from studyctl.agent_launcher import _gemini_mcp

        _gemini_mcp(tmp_path)
        settings_path = tmp_path / ".gemini" / "settings.json"
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert "studyctl-mcp" in data["mcpServers"]
        assert data["mcpServers"]["studyctl-mcp"]["command"] == "uv"

    def test_launch_new_session(self):
        from studyctl.agent_launcher import _gemini_launch

        cmd = _gemini_launch(Path("/tmp/GEMINI.md"), resume=False)
        assert "gemini" in cmd
        assert "-r" not in cmd

    def test_launch_resume(self):
        from studyctl.agent_launcher import _gemini_launch

        cmd = _gemini_launch(Path("/tmp/GEMINI.md"), resume=True)
        assert "-r" in cmd


# ---------------------------------------------------------------------------
# OpenCode adapter
# ---------------------------------------------------------------------------


class TestOpenCodeAdapter:
    def test_setup_writes_md_with_frontmatter(self, tmp_path):
        from studyctl.agent_launcher import _opencode_setup

        path = _opencode_setup("# OpenCode Persona", tmp_path)
        assert path.exists()
        content = path.read_text()
        # YAML frontmatter
        assert content.startswith("---\n")
        assert "mode: primary" in content
        assert "temperature: 0.3" in content
        # Canonical content after frontmatter
        assert "# OpenCode Persona" in content

    def test_setup_creates_correct_directory(self, tmp_path):
        from studyctl.agent_launcher import _opencode_setup

        path = _opencode_setup("# test", tmp_path)
        assert ".opencode/agents/study-mentor.md" in str(path)

    def test_mcp_writes_opencode_json_with_correct_schema(self, tmp_path):
        import json

        from studyctl.agent_launcher import _opencode_mcp

        _opencode_mcp(tmp_path)
        config_path = tmp_path / ".opencode" / "opencode.json"
        assert config_path.exists()
        data = json.loads(config_path.read_text())

        # OpenCode schema: command is array, enabled (not disabled), environment (not env)
        mcp = data["mcp"]["studyctl-mcp"]
        assert isinstance(mcp["command"], list), "OpenCode command must be array"
        assert mcp["enabled"] is True
        assert mcp["type"] == "local"
        assert "environment" in mcp
        assert "env" not in mcp  # NOT "env"

    def test_launch_new_session(self):
        from studyctl.agent_launcher import _opencode_launch

        cmd = _opencode_launch(Path("/tmp/persona.md"), resume=False)
        assert "opencode" in cmd
        assert "--agent study-mentor" in cmd
        assert "-c" not in cmd

    def test_launch_resume(self):
        from studyctl.agent_launcher import _opencode_launch

        cmd = _opencode_launch(Path("/tmp/persona.md"), resume=True)
        assert "-c" in cmd
        assert "--agent study-mentor" in cmd
