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
            "studyloop doctor --json",
            "fix_hint",
            "fix_auto",
            "max 3 iterations",
            "uname",
            "python3 --version",
        ]
        for term in required:
            assert term.lower() in content.lower(), f"Missing required term: {term}"

    def test_python_minimum_is_312_not_stale_310(self):
        """W29: the repo-wide minimum is >=3.12 (packages/studyloop/pyproject.toml);
        install-mentor.md must not still gate on the old 3.10 floor."""
        prompt = REPO_ROOT / "agents" / "shared" / "install-mentor.md"
        content = prompt.read_text()
        assert "3.12" in content
        assert "3.10" not in content

    def test_valid_markdown(self):
        prompt = REPO_ROOT / "agents" / "shared" / "install-mentor.md"
        content = prompt.read_text()
        assert content.startswith("#"), "Should start with markdown heading"
        assert len(content) > 500, "Prompt seems too short"
