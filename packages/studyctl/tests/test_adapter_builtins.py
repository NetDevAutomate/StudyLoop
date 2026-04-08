"""Tests for built-in adapter modules."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

BUILTIN_ADAPTERS = ["claude", "gemini", "kiro", "opencode", "ollama", "lmstudio"]


class TestBuiltinAdapters:
    @pytest.mark.parametrize("name", BUILTIN_ADAPTERS)
    def test_module_exports_adapter(self, name):
        import importlib

        mod = importlib.import_module(f"studyctl.adapters.{name}")
        adapter = getattr(mod, "ADAPTER", None)
        assert adapter is not None, f"adapters/{name}.py missing ADAPTER"
        assert adapter.name == name

    @pytest.mark.parametrize("name", BUILTIN_ADAPTERS)
    def test_adapter_has_required_fields(self, name):
        import importlib

        mod = importlib.import_module(f"studyctl.adapters.{name}")
        adapter = mod.ADAPTER
        assert adapter.binary, f"{name} has no binary"
        assert callable(adapter.setup)
        assert callable(adapter.launch_cmd)

    @pytest.mark.parametrize("name", ["gemini", "opencode"])
    def test_setup_creates_file_in_session_dir(self, name, tmp_path):
        import importlib

        mod = importlib.import_module(f"studyctl.adapters.{name}")
        path = mod.ADAPTER.setup("# test content", tmp_path)
        assert path.exists()
        assert "test content" in path.read_text()

    @pytest.mark.parametrize("name", ["claude", "ollama", "lmstudio"])
    def test_cli_flag_setup_creates_temp_file(self, name, tmp_path):
        import importlib

        mod = importlib.import_module(f"studyctl.adapters.{name}")
        path = mod.ADAPTER.setup("# test content", tmp_path)
        assert path.exists()
        assert "test content" in path.read_text()

    def test_kiro_has_teardown(self):
        from studyctl.adapters.kiro import ADAPTER

        assert ADAPTER.teardown is not None

    def test_gemini_has_mcp_setup(self):
        from studyctl.adapters.gemini import ADAPTER

        assert ADAPTER.mcp_setup is not None

    def test_opencode_has_mcp_setup(self):
        from studyctl.adapters.opencode import ADAPTER

        assert ADAPTER.mcp_setup is not None

    def test_claude_no_teardown(self):
        from studyctl.adapters.claude import ADAPTER

        assert ADAPTER.teardown is None
        assert ADAPTER.mcp_setup is None

    def test_registry_discovers_all_builtins(self):
        from studyctl.adapters.registry import get_all_adapters, reset_registry

        reset_registry()
        adapters = get_all_adapters()
        expected = {"claude", "gemini", "kiro", "opencode", "ollama", "lmstudio"}
        assert set(adapters.keys()) >= expected


class TestKiroAdapter:
    """Direct tests for studyctl.adapters.kiro functions."""

    def _patch_kiro_dir(self, monkeypatch, tmp_path):
        """Point KIRO_AGENTS_DIR at a temp directory for test isolation."""
        kiro_agents = tmp_path / "kiro-agents"
        import studyctl.adapters.kiro as kiro_mod

        monkeypatch.setattr(kiro_mod, "KIRO_AGENTS_DIR", kiro_agents)
        return kiro_agents

    def _patch_no_template(self, monkeypatch):
        """Make _KIRO_TEMPLATE point to a non-existent path so fallback is used."""
        import studyctl.adapters.kiro as kiro_mod

        monkeypatch.setattr(
            kiro_mod,
            "_KIRO_TEMPLATE",
            kiro_mod._KIRO_TEMPLATE.parent / "__nonexistent__.json",
        )

    # ------------------------------------------------------------------
    # _kiro_setup tests
    # ------------------------------------------------------------------

    def test_kiro_setup_creates_persona_file(self, monkeypatch, tmp_path):
        """_kiro_setup writes canonical_content to a temp persona .md file."""
        self._patch_kiro_dir(monkeypatch, tmp_path)
        self._patch_no_template(monkeypatch)

        from studyctl.adapters.kiro import _kiro_setup

        persona_path = _kiro_setup("# Hello World", tmp_path / "session")

        assert persona_path.exists()
        assert persona_path.suffix == ".md"
        assert "# Hello World" in persona_path.read_text()

    def test_kiro_setup_writes_agent_json(self, monkeypatch, tmp_path):
        """_kiro_setup creates the agent JSON with a file:// prompt reference."""
        kiro_agents = self._patch_kiro_dir(monkeypatch, tmp_path)
        self._patch_no_template(monkeypatch)

        from studyctl.adapters.kiro import KIRO_AGENT_NAME, _kiro_setup

        persona_path = _kiro_setup("# Mentor content", tmp_path / "session")

        target = kiro_agents / f"{KIRO_AGENT_NAME}.json"
        assert target.exists()

        data = json.loads(target.read_text())
        assert data["prompt"] == f"file://{persona_path}"
        assert data["name"] == KIRO_AGENT_NAME

    def test_kiro_setup_uses_fallback_template_when_missing(self, monkeypatch, tmp_path):
        """When _KIRO_TEMPLATE does not exist, fallback dict is used."""
        kiro_agents = self._patch_kiro_dir(monkeypatch, tmp_path)
        self._patch_no_template(monkeypatch)

        from studyctl.adapters.kiro import KIRO_AGENT_NAME, _kiro_setup

        _kiro_setup("content", tmp_path / "session")

        target = kiro_agents / f"{KIRO_AGENT_NAME}.json"
        data = json.loads(target.read_text())
        assert data["description"] == "Socratic study mentor"

    def test_kiro_setup_uses_real_template_when_present(self, monkeypatch, tmp_path):
        """When _KIRO_TEMPLATE exists, its content is used as the base dict."""
        kiro_agents = self._patch_kiro_dir(monkeypatch, tmp_path)

        # Write a fake template file
        fake_template = tmp_path / "study-mentor.json"
        fake_template.write_text(json.dumps({"name": "kiro-test", "extra": "value"}))

        import studyctl.adapters.kiro as kiro_mod

        monkeypatch.setattr(kiro_mod, "_KIRO_TEMPLATE", fake_template)

        from studyctl.adapters.kiro import KIRO_AGENT_NAME, _kiro_setup

        _kiro_setup("content", tmp_path / "session")

        target = kiro_agents / f"{KIRO_AGENT_NAME}.json"
        data = json.loads(target.read_text())
        # Template field preserved
        assert data["extra"] == "value"

    def test_kiro_setup_backs_up_existing_json(self, monkeypatch, tmp_path):
        """If agent JSON already exists, it is copied to a .studyctl-backup file."""
        kiro_agents = self._patch_kiro_dir(monkeypatch, tmp_path)
        self._patch_no_template(monkeypatch)

        from studyctl.adapters.kiro import _KIRO_BACKUP_SUFFIX, KIRO_AGENT_NAME, _kiro_setup

        # Pre-create an existing agent JSON
        kiro_agents.mkdir(parents=True, exist_ok=True)
        target = kiro_agents / f"{KIRO_AGENT_NAME}.json"
        original_data = {"name": KIRO_AGENT_NAME, "prompt": "original-prompt"}
        target.write_text(json.dumps(original_data))

        _kiro_setup("new content", tmp_path / "session")

        backup = target.with_suffix(target.suffix + _KIRO_BACKUP_SUFFIX)
        assert backup.exists()
        backed_up = json.loads(backup.read_text())
        assert backed_up["prompt"] == "original-prompt"

    def test_kiro_setup_crash_recovery_restores_stale_backup(self, monkeypatch, tmp_path):
        """If a stale backup exists (crashed session), it is restored before setup proceeds."""
        kiro_agents = self._patch_kiro_dir(monkeypatch, tmp_path)
        self._patch_no_template(monkeypatch)

        from studyctl.adapters.kiro import _KIRO_BACKUP_SUFFIX, KIRO_AGENT_NAME, _kiro_setup

        # Simulate a stale backup from a previous crashed session.
        # No current target JSON — backup exists alone.
        kiro_agents.mkdir(parents=True, exist_ok=True)
        target = kiro_agents / f"{KIRO_AGENT_NAME}.json"
        backup = target.with_suffix(target.suffix + _KIRO_BACKUP_SUFFIX)

        stale_original = {"name": KIRO_AGENT_NAME, "prompt": "user-original"}
        backup.write_text(json.dumps(stale_original))

        _kiro_setup("new content", tmp_path / "session")

        # After setup: backup is gone (it was consumed by crash-recovery then
        # re-created because the restored target was backed up again)
        # The new target must have the studyctl-managed file:// prompt
        assert target.exists()
        data = json.loads(target.read_text())
        assert data["prompt"].startswith("file://")

        # The stale backup should now hold the restored original (re-backed-up)
        assert backup.exists()
        re_backed = json.loads(backup.read_text())
        assert re_backed["prompt"] == "user-original"

    def test_kiro_setup_no_backup_when_no_existing_target(self, monkeypatch, tmp_path):
        """Fresh install: no existing agent JSON means no backup file is created."""
        kiro_agents = self._patch_kiro_dir(monkeypatch, tmp_path)
        self._patch_no_template(monkeypatch)

        from studyctl.adapters.kiro import _KIRO_BACKUP_SUFFIX, KIRO_AGENT_NAME, _kiro_setup

        _kiro_setup("content", tmp_path / "session")

        target = kiro_agents / f"{KIRO_AGENT_NAME}.json"
        backup = target.with_suffix(target.suffix + _KIRO_BACKUP_SUFFIX)
        # Target must exist; backup must NOT (nothing to back up)
        assert target.exists()
        assert not backup.exists()

    def test_kiro_setup_creates_agents_dir_if_missing(self, monkeypatch, tmp_path):
        """_kiro_setup creates KIRO_AGENTS_DIR if it doesn't exist."""
        kiro_agents = self._patch_kiro_dir(monkeypatch, tmp_path)
        self._patch_no_template(monkeypatch)

        from studyctl.adapters.kiro import _kiro_setup

        assert not kiro_agents.exists()
        _kiro_setup("content", tmp_path / "session")
        assert kiro_agents.exists()

    # ------------------------------------------------------------------
    # _kiro_teardown tests
    # ------------------------------------------------------------------

    def test_kiro_teardown_restores_backup(self, monkeypatch, tmp_path):
        """teardown() moves the backup file back over the target JSON."""
        kiro_agents = self._patch_kiro_dir(monkeypatch, tmp_path)
        self._patch_no_template(monkeypatch)

        from studyctl.adapters.kiro import _KIRO_BACKUP_SUFFIX, KIRO_AGENT_NAME, _kiro_teardown

        kiro_agents.mkdir(parents=True, exist_ok=True)
        target = kiro_agents / f"{KIRO_AGENT_NAME}.json"
        backup = target.with_suffix(target.suffix + _KIRO_BACKUP_SUFFIX)

        # Set up: current (studyctl) JSON + backup (user's original)
        target.write_text(json.dumps({"prompt": "file:///tmp/studyctl-persona.md"}))
        original_data = {"name": KIRO_AGENT_NAME, "prompt": "user-original"}
        backup.write_text(json.dumps(original_data))

        _kiro_teardown(tmp_path / "session")

        # Backup consumed, target restored to original
        assert not backup.exists()
        assert target.exists()
        restored = json.loads(target.read_text())
        assert restored["prompt"] == "user-original"

    def test_kiro_teardown_idempotent_no_backup(self, monkeypatch, tmp_path):
        """teardown() is safe when no backup exists — no error raised."""
        kiro_agents = self._patch_kiro_dir(monkeypatch, tmp_path)
        self._patch_no_template(monkeypatch)

        from studyctl.adapters.kiro import _kiro_teardown

        kiro_agents.mkdir(parents=True, exist_ok=True)
        # No backup and no target — should not raise
        _kiro_teardown(tmp_path / "session")

    def test_kiro_teardown_idempotent_with_target_no_backup(self, monkeypatch, tmp_path):
        """teardown() leaves existing target untouched when there's no backup."""
        kiro_agents = self._patch_kiro_dir(monkeypatch, tmp_path)
        self._patch_no_template(monkeypatch)

        from studyctl.adapters.kiro import KIRO_AGENT_NAME, _kiro_teardown

        kiro_agents.mkdir(parents=True, exist_ok=True)
        target = kiro_agents / f"{KIRO_AGENT_NAME}.json"
        target.write_text(json.dumps({"prompt": "file:///tmp/persona.md"}))

        _kiro_teardown(tmp_path / "session")

        # Target unchanged, no error
        assert target.exists()
        assert "file://" in target.read_text()

    # ------------------------------------------------------------------
    # _kiro_launch tests
    # ------------------------------------------------------------------

    def test_kiro_launch_cmd_no_resume(self, monkeypatch, tmp_path):
        """launch_cmd builds a kiro command without --resume by default."""
        import shutil as shutil_mod

        def _which(name):
            return f"/usr/local/bin/{name}" if name == "kiro-cli" else None

        monkeypatch.setattr(shutil_mod, "which", _which)

        from studyctl.adapters.kiro import KIRO_AGENT_NAME, _kiro_launch

        cmd = _kiro_launch(tmp_path / "persona.md", resume=False)

        assert cmd == f"/usr/local/bin/kiro-cli chat --agent {KIRO_AGENT_NAME}"
        assert "--resume" not in cmd

    def test_kiro_launch_cmd_with_resume(self, monkeypatch, tmp_path):
        """launch_cmd includes --resume when resume=True."""
        import shutil as shutil_mod

        def _which(name):
            return f"/usr/local/bin/{name}" if name == "kiro-cli" else None

        monkeypatch.setattr(shutil_mod, "which", _which)

        from studyctl.adapters.kiro import KIRO_AGENT_NAME, _kiro_launch

        cmd = _kiro_launch(tmp_path / "persona.md", resume=True)

        assert cmd == f"/usr/local/bin/kiro-cli chat --agent {KIRO_AGENT_NAME} --resume"

    def test_kiro_launch_cmd_falls_back_to_kiro(self, monkeypatch, tmp_path):
        """When kiro-cli is not found, falls back to kiro binary."""
        import shutil as shutil_mod

        def _which(name):
            return "/usr/local/bin/kiro" if name == "kiro" else None

        monkeypatch.setattr(shutil_mod, "which", _which)

        from studyctl.adapters.kiro import KIRO_AGENT_NAME, _kiro_launch

        cmd = _kiro_launch(tmp_path / "persona.md", resume=False)

        assert cmd.startswith("/usr/local/bin/kiro ")
        assert f"--agent {KIRO_AGENT_NAME}" in cmd

    def test_kiro_launch_cmd_falls_back_to_literal_kiro_cli(self, monkeypatch, tmp_path):
        """When neither kiro-cli nor kiro is on PATH, literal 'kiro-cli' is used."""
        import shutil as shutil_mod

        monkeypatch.setattr(shutil_mod, "which", lambda _name: None)

        from studyctl.adapters.kiro import KIRO_AGENT_NAME, _kiro_launch

        cmd = _kiro_launch(tmp_path / "persona.md", resume=False)

        assert cmd.startswith("kiro-cli ")
        assert f"--agent {KIRO_AGENT_NAME}" in cmd

    def test_kiro_adapter_setup_delegates_to_setup_fn(self, monkeypatch, tmp_path):
        """ADAPTER.setup() calls through to _kiro_setup correctly."""
        self._patch_kiro_dir(monkeypatch, tmp_path)
        self._patch_no_template(monkeypatch)

        from studyctl.adapters.kiro import ADAPTER

        persona_path = ADAPTER.setup("# Mentor", tmp_path / "session")
        assert persona_path.exists()
        assert "# Mentor" in persona_path.read_text()

    def test_kiro_adapter_teardown_delegates_to_teardown_fn(self, monkeypatch, tmp_path):
        """ADAPTER.teardown() calls through to _kiro_teardown correctly."""
        kiro_agents = self._patch_kiro_dir(monkeypatch, tmp_path)
        self._patch_no_template(monkeypatch)

        from studyctl.adapters.kiro import _KIRO_BACKUP_SUFFIX, ADAPTER, KIRO_AGENT_NAME

        kiro_agents.mkdir(parents=True, exist_ok=True)
        target = kiro_agents / f"{KIRO_AGENT_NAME}.json"
        backup = target.with_suffix(target.suffix + _KIRO_BACKUP_SUFFIX)
        backup.write_text(json.dumps({"prompt": "restored"}))
        target.write_text(json.dumps({"prompt": "studyctl-managed"}))

        ADAPTER.teardown(tmp_path / "session")

        assert not backup.exists()
        restored = json.loads(target.read_text())
        assert restored["prompt"] == "restored"


class TestLaunchCommands:
    """Verify launch_cmd output for all built-in adapters."""

    def test_ollama_launch_includes_env_vars(self, tmp_path):
        from studyctl.adapters.ollama import ADAPTER

        persona = tmp_path / "p.md"
        persona.touch()
        with patch("studyctl.adapters.ollama.shutil.which", return_value="/usr/bin/claude"):
            cmd = ADAPTER.launch_cmd(persona, resume=False)
        assert "ANTHROPIC_BASE_URL=" in cmd
        assert str(persona) in cmd

    def test_ollama_launch_resume(self, tmp_path):
        from studyctl.adapters.ollama import ADAPTER

        persona = tmp_path / "p.md"
        persona.touch()
        with patch("studyctl.adapters.ollama.shutil.which", return_value="/usr/bin/claude"):
            cmd = ADAPTER.launch_cmd(persona, resume=True)
        assert "-r" in cmd or "--resume" in cmd

    def test_ollama_launch_no_resume_no_r_flag(self, tmp_path):
        from studyctl.adapters.ollama import ADAPTER

        persona = tmp_path / "p.md"
        persona.touch()
        with patch("studyctl.adapters.ollama.shutil.which", return_value="/usr/bin/claude"):
            cmd = ADAPTER.launch_cmd(persona, resume=False)
        # -r should NOT appear in a non-resume launch
        parts = cmd.split()
        assert "-r" not in parts

    def test_ollama_launch_fallback_binary_when_not_on_path(self, tmp_path):
        from studyctl.adapters.ollama import ADAPTER

        persona = tmp_path / "p.md"
        persona.touch()
        with patch("studyctl.adapters.ollama.shutil.which", return_value=None):
            cmd = ADAPTER.launch_cmd(persona, resume=False)
        # Falls back to bare "claude" string
        assert "claude" in cmd

    def test_gemini_launch(self, tmp_path):
        from studyctl.adapters.gemini import ADAPTER

        persona = tmp_path / "p.md"
        persona.touch()
        with patch("studyctl.adapters.gemini.shutil.which", return_value="/usr/bin/gemini"):
            cmd = ADAPTER.launch_cmd(persona, resume=False)
        assert "/usr/bin/gemini" in cmd

    def test_gemini_launch_resume(self, tmp_path):
        from studyctl.adapters.gemini import ADAPTER

        persona = tmp_path / "p.md"
        persona.touch()
        with patch("studyctl.adapters.gemini.shutil.which", return_value="/usr/bin/gemini"):
            cmd = ADAPTER.launch_cmd(persona, resume=True)
        assert "-r" in cmd

    def test_gemini_launch_no_resume_no_r_flag(self, tmp_path):
        from studyctl.adapters.gemini import ADAPTER

        persona = tmp_path / "p.md"
        persona.touch()
        with patch("studyctl.adapters.gemini.shutil.which", return_value="/usr/bin/gemini"):
            cmd = ADAPTER.launch_cmd(persona, resume=False)
        assert "-r" not in cmd.split()

    def test_gemini_launch_fallback_binary(self, tmp_path):
        from studyctl.adapters.gemini import ADAPTER

        persona = tmp_path / "p.md"
        persona.touch()
        with patch("studyctl.adapters.gemini.shutil.which", return_value=None):
            cmd = ADAPTER.launch_cmd(persona, resume=False)
        assert "gemini" in cmd

    def test_opencode_launch(self, tmp_path):
        from studyctl.adapters.opencode import ADAPTER

        persona = tmp_path / "p.md"
        persona.touch()
        with patch("studyctl.adapters.opencode.shutil.which", return_value="/usr/bin/opencode"):
            cmd = ADAPTER.launch_cmd(persona, resume=False)
        assert "study-mentor" in cmd

    def test_opencode_launch_resume(self, tmp_path):
        from studyctl.adapters.opencode import ADAPTER

        persona = tmp_path / "p.md"
        persona.touch()
        with patch("studyctl.adapters.opencode.shutil.which", return_value="/usr/bin/opencode"):
            cmd = ADAPTER.launch_cmd(persona, resume=True)
        assert "-c" in cmd

    def test_opencode_launch_binary_in_cmd(self, tmp_path):
        from studyctl.adapters.opencode import ADAPTER

        persona = tmp_path / "p.md"
        persona.touch()
        with patch("studyctl.adapters.opencode.shutil.which", return_value="/usr/bin/opencode"):
            cmd = ADAPTER.launch_cmd(persona, resume=False)
        assert cmd.startswith("/usr/bin/opencode")

    def test_opencode_launch_fallback_binary(self, tmp_path):
        from studyctl.adapters.opencode import ADAPTER

        persona = tmp_path / "p.md"
        persona.touch()
        with patch("studyctl.adapters.opencode.shutil.which", return_value=None):
            cmd = ADAPTER.launch_cmd(persona, resume=False)
        assert "opencode" in cmd

    def test_lmstudio_launch_includes_env_vars(self, tmp_path):
        from studyctl.adapters.lmstudio import ADAPTER

        persona = tmp_path / "p.md"
        persona.touch()
        with patch("studyctl.adapters.lmstudio.shutil.which", return_value="/usr/bin/claude"):
            cmd = ADAPTER.launch_cmd(persona, resume=False)
        assert "ANTHROPIC_BASE_URL=" in cmd

    def test_lmstudio_launch_resume(self, tmp_path):
        from studyctl.adapters.lmstudio import ADAPTER

        persona = tmp_path / "p.md"
        persona.touch()
        with patch("studyctl.adapters.lmstudio.shutil.which", return_value="/usr/bin/claude"):
            cmd = ADAPTER.launch_cmd(persona, resume=True)
        assert "-r" in cmd

    def test_lmstudio_launch_includes_persona_path(self, tmp_path):
        from studyctl.adapters.lmstudio import ADAPTER

        persona = tmp_path / "p.md"
        persona.touch()
        with patch("studyctl.adapters.lmstudio.shutil.which", return_value="/usr/bin/claude"):
            cmd = ADAPTER.launch_cmd(persona, resume=False)
        assert str(persona) in cmd

    def test_claude_launch_absolute_path(self, tmp_path):
        from studyctl.adapters.claude import ADAPTER

        persona = tmp_path / "p.md"
        persona.touch()
        with patch("studyctl.adapters.claude.shutil.which", return_value="/usr/local/bin/claude"):
            cmd = ADAPTER.launch_cmd(persona, resume=False)
        assert cmd.startswith("/usr/local/bin/claude")
        assert "--append-system-prompt-file" in cmd

    def test_claude_launch_resume(self, tmp_path):
        from studyctl.adapters.claude import ADAPTER

        persona = tmp_path / "p.md"
        persona.touch()
        with patch("studyctl.adapters.claude.shutil.which", return_value="/usr/local/bin/claude"):
            cmd = ADAPTER.launch_cmd(persona, resume=True)
        assert "-r" in cmd

    def test_claude_launch_includes_persona_path(self, tmp_path):
        from studyctl.adapters.claude import ADAPTER

        persona = tmp_path / "p.md"
        persona.touch()
        with patch("studyctl.adapters.claude.shutil.which", return_value="/usr/local/bin/claude"):
            cmd = ADAPTER.launch_cmd(persona, resume=False)
        assert str(persona) in cmd

    def test_claude_launch_no_resume_no_r_flag(self, tmp_path):
        from studyctl.adapters.claude import ADAPTER

        persona = tmp_path / "p.md"
        persona.touch()
        with patch("studyctl.adapters.claude.shutil.which", return_value="/usr/local/bin/claude"):
            cmd = ADAPTER.launch_cmd(persona, resume=False)
        parts = cmd.split()
        assert "-r" not in parts

    def test_claude_launch_fallback_binary(self, tmp_path):
        from studyctl.adapters.claude import ADAPTER

        persona = tmp_path / "p.md"
        persona.touch()
        with patch("studyctl.adapters.claude.shutil.which", return_value=None):
            cmd = ADAPTER.launch_cmd(persona, resume=False)
        assert "claude" in cmd
