"""Tests for doctor agent definition checks."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path


class TestAgentToolDetection:
    def test_detect_claude(self):
        from studyctl.doctor.agents import _detect_ai_tools

        with patch(
            "shutil.which", side_effect=lambda x: "/usr/local/bin/claude" if x == "claude" else None
        ):
            tools = _detect_ai_tools()
        assert "claude" in tools

    def test_detect_none(self):
        from studyctl.doctor.agents import _detect_ai_tools

        with patch("shutil.which", return_value=None):
            tools = _detect_ai_tools()
        assert tools == []


class TestAgentDefinitionCheck:
    @pytest.fixture()
    def agent_dir(self, tmp_path: Path) -> Path:
        agent_file = tmp_path / ".claude" / "commands" / "socratic-mentor.md"
        agent_file.parent.mkdir(parents=True)
        agent_file.write_text("# Socratic Mentor Agent\nTest content")
        return tmp_path

    def test_agent_installed_and_current(self, agent_dir: Path):
        import hashlib

        from studyctl.doctor.agents import check_agent_definitions

        content = (agent_dir / ".claude" / "commands" / "socratic-mentor.md").read_bytes()
        expected_hash = hashlib.sha256(content).hexdigest()[:16]

        manifest = {
            "version": 1,
            "agents": {
                "claude/socratic-mentor.md": {"hash": expected_hash, "updated": "2026-03-17"}
            },
        }

        with (
            patch("studyctl.doctor.agents._detect_ai_tools", return_value=["claude"]),
            patch(
                "studyctl.doctor.agents._get_agent_install_path",
                return_value=agent_dir / ".claude" / "commands" / "socratic-mentor.md",
            ),
            patch("studyctl.doctor.agents._fetch_manifest", return_value=manifest),
        ):
            results = check_agent_definitions()
        assert any(r.status == "pass" and "claude" in r.name for r in results)

    def test_agent_outdated(self, agent_dir: Path):
        from studyctl.doctor.agents import check_agent_definitions

        manifest = {
            "version": 1,
            "agents": {
                "claude/socratic-mentor.md": {"hash": "different_hash!", "updated": "2026-03-17"}
            },
        }

        with (
            patch("studyctl.doctor.agents._detect_ai_tools", return_value=["claude"]),
            patch(
                "studyctl.doctor.agents._get_agent_install_path",
                return_value=agent_dir / ".claude" / "commands" / "socratic-mentor.md",
            ),
            patch("studyctl.doctor.agents._fetch_manifest", return_value=manifest),
        ):
            results = check_agent_definitions()
        assert any(r.status == "warn" and r.fix_auto for r in results)

    def test_agent_not_installed(self, tmp_path: Path):
        from studyctl.doctor.agents import check_agent_definitions

        manifest = {
            "version": 1,
            "agents": {"claude/socratic-mentor.md": {"hash": "abc", "updated": "2026-03-17"}},
        }

        with (
            patch("studyctl.doctor.agents._detect_ai_tools", return_value=["claude"]),
            patch(
                "studyctl.doctor.agents._get_agent_install_path",
                return_value=tmp_path / "nonexistent.md",
            ),
            patch("studyctl.doctor.agents._fetch_manifest", return_value=manifest),
        ):
            results = check_agent_definitions()
        assert any(r.status == "warn" for r in results)

    def test_manifest_fetch_fails(self):
        from studyctl.doctor.agents import check_agent_definitions

        with (
            patch("studyctl.doctor.agents._detect_ai_tools", return_value=["claude"]),
            patch("studyctl.doctor.agents._fetch_manifest", return_value=None),
        ):
            results = check_agent_definitions()
        assert any(r.status == "info" for r in results)
