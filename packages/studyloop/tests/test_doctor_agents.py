"""Tests for doctor agent definition checks."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


class TestAgentToolDetection:
    def test_detect_claude(self):
        from studyloop.doctor.agents import _detect_ai_tools

        with patch(
            "shutil.which", side_effect=lambda x: "/usr/local/bin/claude" if x == "claude" else None
        ):
            tools = _detect_ai_tools()
        assert "claude" in tools

    def test_detect_kiro_uses_kiro_cli_binary(self):
        from studyloop.doctor.agents import TOOL_AGENTS, _detect_ai_tools

        assert TOOL_AGENTS["kiro"][0] == "kiro-cli"

        with patch(
            "shutil.which",
            side_effect=lambda x: "/usr/local/bin/kiro-cli" if x == "kiro-cli" else None,
        ):
            tools = _detect_ai_tools()
        assert "kiro" in tools

    def test_detect_none(self):
        from studyloop.doctor.agents import _detect_ai_tools

        with patch("shutil.which", return_value=None):
            tools = _detect_ai_tools()
        assert tools == []

    def test_detect_codex(self):
        from studyloop.doctor.agents import _detect_ai_tools

        def _which(binary: str) -> str | None:
            return "/usr/local/bin/codex" if binary == "codex" else None

        with patch("shutil.which", side_effect=_which):
            tools = _detect_ai_tools()
        assert "codex" in tools

    def test_detect_pi(self):
        from studyloop.doctor.agents import _detect_ai_tools

        def _which(binary: str) -> str | None:
            return "/usr/local/bin/pi" if binary == "pi" else None

        with patch("shutil.which", side_effect=_which):
            tools = _detect_ai_tools()
        assert "pi" in tools

    def test_detect_grok(self):
        from studyloop.doctor.agents import _detect_ai_tools

        def _which(binary: str) -> str | None:
            return "/usr/local/bin/grok" if binary == "grok" else None

        with patch("shutil.which", side_effect=_which):
            tools = _detect_ai_tools()
        assert "grok" in tools


class TestAgentSmokeTests:
    def test_smoke_test_success(self):
        from unittest.mock import MagicMock

        from studyloop.doctor.agents import check_agent_smoke_tests

        mock_result = MagicMock(returncode=0, stdout="Claude Code v1.0.0\n")
        with (
            patch("studyloop.doctor.agents._detect_ai_tools", return_value=["claude"]),
            patch("studyloop.doctor.agents.shutil.which", return_value="/usr/bin/claude"),
            patch("studyloop.doctor.agents.subprocess.run", return_value=mock_result),
        ):
            results = check_agent_smoke_tests()
        assert len(results) == 1
        assert results[0].status == "pass"
        assert "Claude Code v1.0.0" in results[0].message

    def test_smoke_test_failure(self):
        from studyloop.doctor.agents import check_agent_smoke_tests

        with (
            patch("studyloop.doctor.agents._detect_ai_tools", return_value=["claude"]),
            patch("studyloop.doctor.agents.shutil.which", return_value="/usr/bin/claude"),
            patch("studyloop.doctor.agents.subprocess.run", side_effect=FileNotFoundError),
        ):
            results = check_agent_smoke_tests()
        assert len(results) == 1
        assert results[0].status == "warn"
        assert "failed" in results[0].message

    def test_smoke_test_timeout(self):
        import subprocess as sp

        from studyloop.doctor.agents import check_agent_smoke_tests

        with (
            patch("studyloop.doctor.agents._detect_ai_tools", return_value=["pi"]),
            patch("studyloop.doctor.agents.shutil.which", return_value="/usr/bin/pi"),
            patch(
                "studyloop.doctor.agents.subprocess.run", side_effect=sp.TimeoutExpired("cmd", 5)
            ),
        ):
            results = check_agent_smoke_tests()
        assert results[0].status == "warn"
        assert "timed out" in results[0].message

    def test_no_tools_returns_empty(self):
        from studyloop.doctor.agents import check_agent_smoke_tests

        with patch("studyloop.doctor.agents._detect_ai_tools", return_value=[]):
            results = check_agent_smoke_tests()
        assert results == []


class TestAgentDefinitionCheck:
    @pytest.fixture()
    def agent_dir(self, tmp_path: Path) -> Path:
        agent_file = tmp_path / ".claude" / "agents" / "socratic-mentor.md"
        agent_file.parent.mkdir(parents=True)
        agent_file.write_text("# Socratic Mentor Agent\nTest content")
        return tmp_path

    def test_pi_definition_uses_global_agents_md(self, tmp_path: Path):
        from studyloop.doctor.agents import _get_agent_install_path

        assert _get_agent_install_path("pi") == Path.home() / ".pi/agent/AGENTS.md"

    def test_agent_installed_and_current(self, agent_dir: Path):
        import hashlib

        from studyloop.doctor.agents import check_agent_definitions

        content = (agent_dir / ".claude" / "agents" / "socratic-mentor.md").read_bytes()
        expected_hash = hashlib.sha256(content).hexdigest()[:16]

        manifest = {
            "version": 1,
            "agents": {
                "claude/socratic-mentor.md": {"hash": expected_hash, "updated": "2026-03-17"}
            },
        }

        with (
            patch("studyloop.doctor.agents._detect_ai_tools", return_value=["claude"]),
            patch(
                "studyloop.doctor.agents._get_agent_install_path",
                return_value=agent_dir / ".claude" / "agents" / "socratic-mentor.md",
            ),
            patch(
                "studyloop.doctor.agents._fetch_manifest_with_reason",
                return_value=(manifest, ""),
            ),
        ):
            results = check_agent_definitions()
        assert any(r.status == "pass" and "claude" in r.name for r in results)

    def test_agent_outdated(self, agent_dir: Path):
        from studyloop.doctor.agents import check_agent_definitions

        manifest = {
            "version": 1,
            "agents": {
                "claude/socratic-mentor.md": {"hash": "different_hash!", "updated": "2026-03-17"}
            },
        }

        with (
            patch("studyloop.doctor.agents._detect_ai_tools", return_value=["claude"]),
            patch(
                "studyloop.doctor.agents._get_agent_install_path",
                return_value=agent_dir / ".claude" / "agents" / "socratic-mentor.md",
            ),
            patch(
                "studyloop.doctor.agents._fetch_manifest_with_reason",
                return_value=(manifest, ""),
            ),
        ):
            results = check_agent_definitions()
        assert any(r.status == "warn" and r.fix_auto for r in results)

    def test_agent_not_installed(self, tmp_path: Path):
        from studyloop.doctor.agents import check_agent_definitions

        manifest = {
            "version": 1,
            "agents": {"claude/socratic-mentor.md": {"hash": "abc", "updated": "2026-03-17"}},
        }

        with (
            patch("studyloop.doctor.agents._detect_ai_tools", return_value=["claude"]),
            patch(
                "studyloop.doctor.agents._get_agent_install_path",
                return_value=tmp_path / "nonexistent.md",
            ),
            patch(
                "studyloop.doctor.agents._fetch_manifest_with_reason",
                return_value=(manifest, ""),
            ),
        ):
            results = check_agent_definitions()
        assert any(r.status == "warn" for r in results)

    def test_codex_install_path_uses_repo_root(self, tmp_path: Path):
        from studyloop.doctor.agents import _get_agent_install_path

        with patch("studyloop.doctor.agents.find_repo_root", return_value=tmp_path):
            path = _get_agent_install_path("codex")

        assert path == tmp_path / "AGENTS.md"

    def test_grok_definition_uses_repo_agents_md(self, tmp_path: Path):
        """Grok Build reads the same repo-root AGENTS.md as Codex, by design.

        Asserted separately from the Codex case so that giving Grok Build its
        own definition file becomes a deliberate, visible change rather than a
        silent divergence between two harnesses that share one source file.
        """
        from studyloop.doctor.agents import _get_agent_install_path

        with patch("studyloop.doctor.agents.find_repo_root", return_value=tmp_path):
            assert _get_agent_install_path("grok") == tmp_path / "AGENTS.md"

    def test_manifest_fetch_fails(self):
        from studyloop.doctor.agents import check_agent_definitions

        with (
            patch("studyloop.doctor.agents._detect_ai_tools", return_value=["claude"]),
            patch(
                "studyloop.doctor.agents._fetch_manifest_with_reason",
                return_value=(None, "offline"),
            ),
        ):
            results = check_agent_definitions()
        assert any(r.status == "info" for r in results)


class TestPlanArchitectDefinitionCheck:
    """L7: doctor reports the new study-plan-architect files through the SAME
    check_agent_definitions loop that already reports study-mentor's, not a
    parallel check -- a harness with two native definitions in the manifest
    must have both checked, not just the first one found."""

    def test_checks_every_manifest_key_for_a_tool_not_just_the_first(self, tmp_path: Path):
        import hashlib

        import studyloop.installers as installers
        from studyloop.doctor.agents import check_agent_definitions

        architect_path = tmp_path / "study-plan-architect.md"
        architect_path.write_text("architect body")
        architect_hash = hashlib.sha256(architect_path.read_bytes()).hexdigest()[:16]

        manifest = {
            "version": 1,
            "agents": {
                "claude/socratic-mentor.md": {"hash": "not-installed", "updated": "2026-03-17"},
                "claude/study-plan-architect.md": {
                    "hash": architect_hash,
                    "updated": "2026-03-17",
                },
            },
        }
        fake_links = {
            "claude": (
                installers.LinkSpec(
                    "agents/claude/socratic-mentor.md",
                    str(tmp_path / "nonexistent-primary.md"),
                ),
                installers.LinkSpec(
                    "agents/claude/study-plan-architect.md",
                    str(architect_path),
                ),
            )
        }

        with (
            patch("studyloop.doctor.agents._detect_ai_tools", return_value=["claude"]),
            patch(
                "studyloop.doctor.agents._get_agent_install_path",
                return_value=tmp_path / "nonexistent-primary.md",
            ),
            patch(
                "studyloop.doctor.agents._fetch_manifest_with_reason",
                return_value=(manifest, ""),
            ),
            patch.object(installers, "_TOOL_LINKS", fake_links),
        ):
            results = check_agent_definitions()

        by_name = {r.name: r for r in results}
        assert by_name["agent_claude"].status == "warn"  # primary not installed
        secondary = [
            r
            for name, r in by_name.items()
            if name != "agent_claude" and name.startswith("agent_claude")
        ]
        assert secondary, f"no second check emitted for claude's second definition: {by_name}"
        assert secondary[0].status == "pass"
        assert "study-plan-architect" in secondary[0].message or "study-plan-architect" in (
            secondary[0].name
        )
