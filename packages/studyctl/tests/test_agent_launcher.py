"""Tests for studyctl.agent_launcher — agent detection and launch."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

# Inline fixtures only (no conftest.py — pluggy conflict)


class TestDetectAgents:
    def test_detect_claude_installed(self):
        from studyctl.agent_launcher import detect_agents

        with patch("studyctl.agent_launcher.shutil.which") as mock_which:
            mock_which.return_value = "/usr/local/bin/claude"
            agents = detect_agents()
            assert "claude" in agents

    def test_detect_no_agents(self):
        from studyctl.agent_launcher import detect_agents

        with patch("studyctl.agent_launcher.shutil.which") as mock_which:
            mock_which.return_value = None
            agents = detect_agents()
            assert agents == []

    def test_get_default_agent(self):
        from studyctl.agent_launcher import get_default_agent

        with patch("studyctl.agent_launcher.shutil.which") as mock_which:
            mock_which.return_value = "/usr/local/bin/claude"
            assert get_default_agent() == "claude"

    def test_get_default_agent_none_available(self):
        from studyctl.agent_launcher import get_default_agent

        with patch("studyctl.agent_launcher.shutil.which") as mock_which:
            mock_which.return_value = None
            assert get_default_agent() is None


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

    def test_unknown_agent_raises(self, tmp_path):
        from studyctl.agent_launcher import get_launch_command

        persona = tmp_path / "persona.md"
        with pytest.raises(KeyError):
            get_launch_command("unknown-agent", persona)
