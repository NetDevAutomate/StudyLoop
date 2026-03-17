"""Validate install-mentor agent prompt file."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class TestInstallMentorPrompt:
    def test_file_exists(self):
        prompt = REPO_ROOT / "agents" / "shared" / "install-mentor.md"
        assert prompt.exists(), f"Missing: {prompt}"

    def test_has_required_sections(self):
        prompt = REPO_ROOT / "agents" / "shared" / "install-mentor.md"
        content = prompt.read_text()
        required = [
            "studyctl doctor --json",
            "fix_hint",
            "fix_auto",
            "max 3 iterations",
            "uname",
            "python3 --version",
        ]
        for term in required:
            assert term.lower() in content.lower(), f"Missing required term: {term}"

    def test_valid_markdown(self):
        prompt = REPO_ROOT / "agents" / "shared" / "install-mentor.md"
        content = prompt.read_text()
        assert content.startswith("#"), "Should start with markdown heading"
        assert len(content) > 500, "Prompt seems too short"
