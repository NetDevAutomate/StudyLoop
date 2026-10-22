"""Tests for studyloop.agent_launcher — agent detection and launch."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    import pytest

# Inline fixtures only (no conftest.py — pluggy conflict)


# ---------------------------------------------------------------------------
# Agent registry and adapter dataclass
# ---------------------------------------------------------------------------


class TestAgentRegistry:
    def test_release_agents_registered(self):
        from studyloop.agent_launcher import AGENTS

        # RELEASE_HARNESSES order: core tier first (pi core since 2026-09-16).
        assert tuple(AGENTS) == ("kiro", "codex", "claude", "pi", "opencode", "grok")

    def test_adapters_have_required_fields(self):
        from studyloop.agent_launcher import AGENTS

        for name, adapter in AGENTS.items():
            assert adapter.name == name
            assert adapter.binary, f"{name} has no binary"
            assert callable(adapter.setup), f"{name}.setup not callable"
            assert callable(adapter.launch_cmd), f"{name}.launch_cmd not callable"

    def test_claude_adapter_is_wired(self):
        from studyloop.agent_launcher import AGENTS

        claude = AGENTS["claude"]
        assert claude.binary == "claude"
        assert claude.teardown is None  # Claude has no global state to clean up

    def test_kiro_binary_is_kiro_cli(self):
        from studyloop.agent_launcher import AGENTS

        assert AGENTS["kiro"].binary == "kiro-cli"

    def test_all_agents_are_wired(self, tmp_path):
        from studyloop.agent_launcher import AGENTS

        for name in ("codex", "opencode", "pi", "grok"):
            # These write to session_dir — should not raise
            path = AGENTS[name].setup("# test content", tmp_path)
            assert path.exists()

    def test_kiro_has_teardown(self):
        from studyloop.agent_launcher import AGENTS

        assert AGENTS["kiro"].teardown is not None
        assert AGENTS["claude"].teardown is None

    def test_opencode_has_mcp_setup(self):
        from studyloop.agent_launcher import AGENTS

        assert AGENTS["opencode"].mcp_setup is not None
        assert AGENTS["claude"].mcp_setup is None


# ---------------------------------------------------------------------------
# Agent detection
# ---------------------------------------------------------------------------


class TestDetectAgents:
    def test_detect_claude_installed(self):
        from studyloop.agent_launcher import detect_agents

        with patch("studyloop.agent_launcher.shutil.which") as mock_which:
            mock_which.side_effect = lambda b: "/usr/local/bin/claude" if b == "claude" else None
            agents = detect_agents()
            assert agents == ["claude"]

    def test_detect_no_agents(self):
        from studyloop.agent_launcher import detect_agents

        with patch("studyloop.agent_launcher.shutil.which") as mock_which:
            mock_which.return_value = None
            agents = detect_agents()
            assert agents == []

    def test_detect_multiple_agents(self):
        from studyloop.agent_launcher import detect_agents

        installed = {"claude", "pi"}
        with patch("studyloop.agent_launcher.shutil.which") as mock_which:
            mock_which.side_effect = lambda b: f"/usr/bin/{b}" if b in installed else None
            agents = detect_agents()
            assert "claude" in agents
            assert "pi" in agents
            assert "kiro" not in agents

    def test_detect_respects_env_var_override(self):
        from studyloop.agent_launcher import detect_agents

        with (
            patch("studyloop.agent_launcher.shutil.which", return_value="/usr/bin/pi"),
            patch.dict(os.environ, {"STUDYLOOP_AGENT": "pi"}),
        ):
            agents = detect_agents()
            assert agents == ["pi"]

    def test_detect_env_var_not_installed_returns_empty(self):
        from studyloop.agent_launcher import detect_agents

        # A registered harness named by STUDYLOOP_AGENT but absent from PATH:
        # explicit intent is honoured, nothing else is offered in its place.
        with (
            patch("studyloop.agent_launcher.shutil.which", return_value=None),
            patch.dict(os.environ, {"STUDYLOOP_AGENT": "grok"}),
        ):
            agents = detect_agents()
            assert agents == []

    def test_detect_env_var_unknown_name_returns_empty_not_a_fallback(self):
        """``STUDYLOOP_AGENT`` naming an unregistered harness yields nothing.

        The launcher used to fall through to ordinary detection here and launch
        whatever it found, silently ignoring a typo'd explicit choice. The
        registry's contract (pinned in ``test_adapter_registry.py``) returns
        ``[]`` so the caller reports the miss; the launcher now has one body
        with it.
        """
        from studyloop.agent_launcher import detect_agents

        with (
            patch("studyloop.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
            patch.dict(os.environ, {"STUDYLOOP_AGENT": "no-such-harness"}),
        ):
            assert detect_agents() == []

    def test_detects_a_harness_added_to_the_registry_after_import(self, monkeypatch):
        """A harness that enters the adapters registry is detected by the
        launcher without a second list.

        The launcher's ``AGENTS`` is the dict the registry handed it at import.
        A registry rebuild (``reset_registry()`` + first access, which is how a
        custom adapter module appears) produces a NEW dict; a ``detect_agents``
        that walks the import-time snapshot never sees the newcomer.
        """
        from studyloop.adapters import registry
        from studyloop.adapters._protocol import AgentAdapter
        from studyloop.agent_launcher import detect_agents

        fake = AgentAdapter(
            name="fakeharness",
            binary="fakeharness-bin",
            setup=lambda c, d: d / "p",
            launch_cmd=lambda p, r: "fakeharness",
        )
        rebuilt = {**registry.get_all_adapters(), "fakeharness": fake}
        monkeypatch.setattr(registry, "_registry", rebuilt)
        monkeypatch.delenv("STUDYLOOP_AGENT", raising=False)

        with patch("studyloop.agent_launcher.shutil.which") as mock_which:
            mock_which.side_effect = lambda b: (
                "/opt/bin/fakeharness-bin" if b == "fakeharness-bin" else None
            )
            assert detect_agents() == ["fakeharness"]


# ---------------------------------------------------------------------------
# Canonical persona builder
# ---------------------------------------------------------------------------


class TestBuildCanonicalPersona:
    def test_injects_runtime_session_paths_without_home_directory_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from studyloop import session_state
        from studyloop.agent_launcher import build_canonical_persona

        monkeypatch.setattr(session_state, "SESSION_DIR", tmp_path)
        monkeypatch.setattr(session_state, "STATE_FILE", tmp_path / "session-state.json")
        monkeypatch.setattr(session_state, "TOPICS_FILE", tmp_path / "session-topics.md")
        monkeypatch.setattr(session_state, "PARKING_FILE", tmp_path / "session-parking.md")

        content = build_canonical_persona("study", "Python Decorators", 6)

        assert str(tmp_path / "session-state.json") in content
        assert str(tmp_path / "session-topics.md") in content
        assert str(tmp_path / "session-parking.md") in content
        assert "~/.config/studyloop/session-state.json" not in content

    def test_includes_topic_and_energy(self):
        from studyloop.agent_launcher import build_canonical_persona

        content = build_canonical_persona("study", "Python Decorators", 7)
        assert "Python Decorators" in content
        assert "7/10" in content
        assert "study" in content.lower()

    def test_includes_resume_notes(self):
        from studyloop.agent_launcher import build_canonical_persona

        content = build_canonical_persona("study", "SQL", 5, previous_notes="Covered JOINs")
        assert "Resuming Previous Session" in content
        assert "Covered JOINs" in content

    def test_co_study_mode(self):
        from studyloop.agent_launcher import build_canonical_persona

        content = build_canonical_persona("co-study", "Spark", 3)
        assert "co-study" in content.lower() or "companion" in content.lower()

    def test_plan_architect_mode_carries_the_canonical_body_and_names_its_mode(self) -> None:
        from studyloop.agent_launcher import build_canonical_persona

        repo_root = Path(__file__).resolve()
        while not (repo_root / "agents/manifest.json").exists():
            repo_root = repo_root.parent
        canonical = (repo_root / "agents/shared/personas/plan-architect.md").read_text(
            encoding="utf-8"
        )

        content = build_canonical_persona("plan-architect", "Study plan", 5)

        assert "**Mode:** plan-architect" in content
        assert canonical.strip() in content

    def test_default_persona_handles_an_unrecognised_mode_without_raising(self) -> None:
        """Belt-and-braces: build_canonical_persona("plan-architect", ...) never
        reaches _default_persona today (agents/shared/personas/plan-architect.md
        exists), but the fallback must still degrade gracefully -- to the
        generic "study mode" default, not a KeyError -- if that file were ever
        missing."""
        from studyloop.agent_launcher import _default_persona

        content = _default_persona("plan-architect")
        assert isinstance(content, str)
        assert content.strip()


# ---------------------------------------------------------------------------
# Claude adapter functions directly
# ---------------------------------------------------------------------------


class TestClaudeAdapter:
    def test_setup_writes_temp_file(self, tmp_path):
        from studyloop.agent_launcher import _claude_setup

        path = _claude_setup("# Test Content\nHello", tmp_path)
        try:
            assert path.exists()
            assert path.read_text() == "# Test Content\nHello"
            assert oct(os.stat(path).st_mode & 0o777) == "0o600"
        finally:
            path.unlink(missing_ok=True)

    def test_launch_new_session(self):
        from studyloop.agent_launcher import _claude_launch

        cmd = _claude_launch(Path("/tmp/persona.md"), resume=False)
        assert "--append-system-prompt-file" in cmd
        assert "/tmp/persona.md" in cmd
        assert "-r" not in cmd.split("--")[0]  # no -r before the flag

    def test_launch_resume_session(self):
        from studyloop.agent_launcher import _claude_launch

        cmd = _claude_launch(Path("/tmp/persona.md"), resume=True)
        assert "-r" in cmd
        assert "--append-system-prompt-file" in cmd


# ---------------------------------------------------------------------------
# Kiro adapter — the compat re-export of the launch builder only. Setup and
# teardown (persona file, agent JSON swap, backup, stale-backup recovery) are
# covered against the one body in test_adapter_builtins.py::TestKiroAdapter;
# the launcher's wrappers that this file used to pin were test-only and gone.
# ---------------------------------------------------------------------------


class TestKiroAdapter:
    def test_launch_new_session(self):
        from studyloop.agent_launcher import _kiro_launch

        cmd = _kiro_launch(Path("/tmp/persona.md"), resume=False)
        assert "chat" in cmd
        assert "--agent" in cmd
        assert "study-mentor" in cmd
        assert "--resume" not in cmd

    def test_launch_resume(self):
        from studyloop.agent_launcher import _kiro_launch

        cmd = _kiro_launch(Path("/tmp/persona.md"), resume=True)
        assert "--resume" in cmd
        assert "study-mentor" in cmd


class TestCodexAdapter:
    def test_setup_writes_agents_md(self, tmp_path):
        from studyloop.agent_launcher import _codex_setup

        path = _codex_setup("# Codex Persona", tmp_path)
        assert path == tmp_path / "AGENTS.md"
        assert path.exists()
        assert path.read_text() == "# Codex Persona"

    def test_launch_new_session(self):
        from studyloop.agent_launcher import _codex_launch

        cmd = _codex_launch(Path("/tmp/AGENTS.md"), resume=False)
        assert cmd.endswith("codex")

    def test_launch_resume(self):
        from studyloop.agent_launcher import _codex_launch

        cmd = _codex_launch(Path("/tmp/AGENTS.md"), resume=True)
        assert cmd.endswith("codex resume --last")


# ---------------------------------------------------------------------------
# Grok Build adapter — the compat re-export, not the adapter module itself
# (adapters/grok.py is covered directly in test_adapter_builtins.py).
# ---------------------------------------------------------------------------


class TestGrokAdapter:
    def test_setup_writes_agents_md(self, tmp_path):
        from studyloop.agent_launcher import _grok_setup

        path = _grok_setup("# Grok Persona", tmp_path)
        assert path == tmp_path / "AGENTS.md"
        assert path.exists()
        assert path.read_text(encoding="utf-8") == "# Grok Persona"

    def test_launch_new_session(self):
        from studyloop.agent_launcher import _grok_launch

        cmd = _grok_launch(Path("/tmp/AGENTS.md"), resume=False)
        assert cmd.endswith("grok")

    def test_launch_resume(self):
        from studyloop.agent_launcher import _grok_launch

        cmd = _grok_launch(Path("/tmp/AGENTS.md"), resume=True)
        assert cmd.endswith("grok --resume")


# ---------------------------------------------------------------------------
# OpenCode adapter
# ---------------------------------------------------------------------------


class TestOpenCodeAdapter:
    def test_setup_writes_md_with_frontmatter(self, tmp_path):
        from studyloop.agent_launcher import _opencode_setup

        path = _opencode_setup("# OpenCode Persona", tmp_path)
        assert path.exists()
        content = path.read_text()
        # YAML frontmatter
        assert content.startswith("---\n")
        assert "mode: primary" in content
        assert "temperature: 0.3" in content
        # New permission format (not deprecated tools:)
        assert "permission:" in content
        assert "tools:" not in content
        # Canonical content after frontmatter
        assert "# OpenCode Persona" in content

    def test_setup_creates_correct_directory(self, tmp_path):
        from studyloop.agent_launcher import _opencode_setup

        path = _opencode_setup("# test", tmp_path)
        assert ".opencode/agents/study-mentor.md" in str(path)

    def test_launch_new_session(self):
        from studyloop.agent_launcher import _opencode_launch

        cmd = _opencode_launch(Path("/tmp/persona.md"), resume=False)
        assert "opencode" in cmd
        assert "--agent study-mentor" in cmd
        assert "-c" not in cmd

    def test_launch_resume(self):
        from studyloop.agent_launcher import _opencode_launch

        cmd = _opencode_launch(Path("/tmp/persona.md"), resume=True)
        assert "-c" in cmd
        assert "--agent study-mentor" in cmd
