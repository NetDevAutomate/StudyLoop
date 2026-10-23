"""Validate install-mentor agent prompt file."""

from __future__ import annotations

import re
from pathlib import Path

from studyloop.doctor.models import VALID_STATUSES, CheckResult

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

    def test_install_commands_use_only_the_supported_source_installer(self):
        """F-OPS-04: there is no PyPI or Homebrew release of studyloop
        (docs/setup-guide.md "User Install"), and `agent-session-tools` is not
        published at all, so a registry install cannot produce a working tool.
        The only supported path is a source checkout plus ./scripts/install.sh.
        """
        content = (REPO_ROOT / "agents" / "shared" / "install-mentor.md").read_text()
        assert "./scripts/install.sh" in content
        forbidden = [
            r"""uv\s+tool\s+install\s+["']?studyloop""",
            r"""pip3?\s+install\s+["']?studyloop""",
            r"""brew\s+install\s+["']?studyloop""",
        ]
        hits = [p for p in forbidden if re.search(p, content)]
        assert hits == [], f"registry install commands still present: {hits}"

    def test_doctor_json_contract_matches_check_result(self):
        """F-OPS-04: the prompt parses `studyloop doctor --json`, so its schema
        must be the real CheckResult contract (doctor/models.py), not the stale
        `check` key and `ok|warn|error` statuses."""
        content = (REPO_ROOT / "agents" / "shared" / "install-mentor.md").read_text()
        for key in CheckResult("core", "n", "pass", "m").to_dict():
            assert f'"{key}"' in content, f"doctor JSON key {key!r} not documented"
        assert '"check":' not in content
        status_line = re.search(r'"status":\s*"([^"]+)"', content)
        assert status_line is not None
        assert set(status_line.group(1).split("|")) == set(VALID_STATUSES)
