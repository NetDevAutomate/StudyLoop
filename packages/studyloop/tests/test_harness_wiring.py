"""
P5 smoke tests: verify that 'extract-struggles' is wired into all four
agent harness files.  These are pure file-content assertions — no execution,
no DB access, no network calls.
"""

import json
from pathlib import Path


def _repo_root() -> Path:
    """Walk up from this file until we find a directory that contains both
    'agents/' and 'packages/' subdirectories (repo root)."""
    candidate = Path(__file__).resolve()
    for parent in candidate.parents:
        if (parent / "agents").is_dir() and (parent / "packages").is_dir():
            return parent
    raise RuntimeError(
        f"Could not locate repo root (expected dir with agents/ and packages/) "
        f"starting from {__file__}"
    )


REPO = _repo_root()

CLAUDE_SETTINGS = REPO / "agents" / "claude" / "settings.json"
KIRO_SKILL = REPO / "agents" / "kiro" / "skills" / "study-mentor" / "SKILL.md"
GEMINI_MD = REPO / "agents" / "gemini" / "GEMINI.md"
OPENCODE_MD = REPO / "agents" / "opencode" / "study-mentor.md"

TARGET = "extract-struggles"


def test_claude_settings_has_extract_struggles() -> None:
    """agents/claude/settings.json must contain the extract-struggles hook
    and must be valid JSON."""
    assert CLAUDE_SETTINGS.exists(), f"File not found: {CLAUDE_SETTINGS}"
    raw = CLAUDE_SETTINGS.read_text()
    # Must parse as valid JSON
    parsed = json.loads(raw)
    assert parsed is not None, "settings.json is not valid JSON"
    # Must contain the substring
    assert TARGET in raw, (
        f"'{TARGET}' not found in {CLAUDE_SETTINGS}. "
        "Add the Stop hook block as described in the P5 task."
    )


def test_kiro_skill_has_extract_struggles() -> None:
    """agents/kiro/skills/study-mentor/SKILL.md must reference extract-struggles."""
    assert KIRO_SKILL.exists(), f"File not found: {KIRO_SKILL}"
    text = KIRO_SKILL.read_text()
    assert TARGET in text, (
        f"'{TARGET}' not found in {KIRO_SKILL}. "
        "Add a Session End step referencing studyloop extract-struggles."
    )


def test_gemini_has_extract_struggles() -> None:
    """agents/gemini/GEMINI.md must reference extract-struggles."""
    assert GEMINI_MD.exists(), f"File not found: {GEMINI_MD}"
    text = GEMINI_MD.read_text()
    assert TARGET in text, (
        f"'{TARGET}' not found in {GEMINI_MD}. "
        "Add studyloop extract-struggles to the Key Commands section."
    )


def test_opencode_has_extract_struggles() -> None:
    """agents/opencode/study-mentor.md must reference extract-struggles."""
    assert OPENCODE_MD.exists(), f"File not found: {OPENCODE_MD}"
    text = OPENCODE_MD.read_text()
    assert TARGET in text, (
        f"'{TARGET}' not found in {OPENCODE_MD}. "
        "Add studyloop extract-struggles to permissions and End-of-Session Protocol."
    )
