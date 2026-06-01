"""Tests for cross-harness session-export wiring (W4).

Covers the installer functions (steering mandate + Claude Stop-hook merge)
and the doctor ``harness`` category check. Everything is exercised against a
tmp HOME so the user's real ~/.claude / ~/.kiro are never touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import studyloop.installers as installers
from studyloop.installers import _HarnessExport


@pytest.fixture
def repo_root() -> Path:
    # The real repo root — we need the actual agents/shared template.
    root = Path(__file__).resolve()
    while root != root.parent and not (root / "agents/shared/session-db-mandate.md").exists():
        root = root.parent
    assert (root / "agents/shared/session-db-mandate.md").exists(), "template not found"
    return root


@pytest.fixture
def home(tmp_path: Path):
    """Patch the installer's harness map + HOME to a sandbox tmp dir."""
    claude_rules = tmp_path / ".claude/rules/session-db.md"
    kiro_steer = tmp_path / ".kiro/steering/session-db.md"
    harness_map = {
        "claude": _HarnessExport(claude_rules, "claude-only"),
        "kiro": _HarnessExport(kiro_steer, "kiro-only"),
    }
    with (
        patch.object(installers, "_HOME", tmp_path),
        patch.object(installers, "_HARNESS_EXPORT", harness_map),
    ):
        yield tmp_path


# ---------------------------------------------------------------------------
# install_session_db_mandate
# ---------------------------------------------------------------------------


class TestMandate:
    def test_writes_mandate_with_correct_flags(self, repo_root: Path, home: Path):
        result = installers.install_session_db_mandate(repo_root, tools=["claude", "kiro"])
        assert result == {"claude": 1, "kiro": 1}
        claude_text = (home / ".claude/rules/session-db.md").read_text()
        kiro_text = (home / ".kiro/steering/session-db.md").read_text()
        assert "session-export --claude-only" in claude_text
        assert "session-export --kiro-only" in kiro_text
        assert installers._MANDATE_SENTINEL in claude_text

    def test_idempotent(self, repo_root: Path, home: Path):
        installers.install_session_db_mandate(repo_root, tools=["claude"])
        again = installers.install_session_db_mandate(repo_root, tools=["claude"])
        assert again == {"claude": 0}  # sentinel present → not rewritten

    def test_skips_unknown_harness(self, repo_root: Path, home: Path):
        # codex has no exporter / no entry in the map.
        result = installers.install_session_db_mandate(repo_root, tools=["codex"])
        assert result == {}


# ---------------------------------------------------------------------------
# install_claude_stop_hook
# ---------------------------------------------------------------------------


class TestClaudeStopHook:
    def _write_settings(self, home: Path, hooks: dict) -> Path:
        p = home / ".claude/settings.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"hooks": hooks}))
        return p

    def test_adds_hook_preserving_existing(self, home: Path):
        p = self._write_settings(
            home,
            {"Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "claude-voice"}]}]},
        )
        assert installers.install_claude_stop_hook() == 1
        data = json.loads(p.read_text())
        cmds = [h["command"] for g in data["hooks"]["Stop"] for h in g["hooks"]]
        assert any("claude-voice" in c for c in cmds)  # preserved
        assert sum("session-export --claude-only" in c for c in cmds) == 1

    def test_idempotent(self, home: Path):
        self._write_settings(home, {"Stop": []})
        assert installers.install_claude_stop_hook() == 1
        assert installers.install_claude_stop_hook() == 0  # already present

    def test_noop_when_no_settings(self, home: Path):
        # No ~/.claude/settings.json → nothing to merge into.
        assert installers.install_claude_stop_hook() == 0

    def test_creates_stop_array_when_absent(self, home: Path):
        self._write_settings(home, {})  # hooks dict with no Stop key
        assert installers.install_claude_stop_hook() == 1
        data = json.loads((home / ".claude/settings.json").read_text())
        assert len(data["hooks"]["Stop"]) == 1


# ---------------------------------------------------------------------------
# doctor harness check
# ---------------------------------------------------------------------------


class TestHarnessDoctorCheck:
    def test_warns_when_unwired_then_passes_after_fix(self, repo_root: Path, home: Path):
        from studyloop.doctor.harness import check_harness_export

        # Settings with a Stop array but no export hook.
        sp = home / ".claude/settings.json"
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps({"hooks": {"Stop": []}}))

        with patch.object(
            installers, "detect_available_agent_tools", return_value=["claude", "kiro"]
        ):
            before = {r.name: r.status for r in check_harness_export()}
        # All warn before wiring.
        assert before["export_mandate_claude"] == "warn"
        assert before["export_mandate_kiro"] == "warn"
        assert before["claude_stop_hook"] == "warn"

        # Apply the fix.
        installers.install_session_db_mandate(repo_root, tools=["claude", "kiro"])
        installers.install_claude_stop_hook()

        with patch.object(
            installers, "detect_available_agent_tools", return_value=["claude", "kiro"]
        ):
            after = {r.name: r.status for r in check_harness_export()}
        assert after["export_mandate_claude"] == "pass"
        assert after["export_mandate_kiro"] == "pass"
        assert after["claude_stop_hook"] == "pass"

    def test_results_are_auto_fixable_warnings(self, home: Path):
        from studyloop.doctor.harness import check_harness_export

        # harness.py reads installers._HARNESS_EXPORT / detect_… through the
        # module, so the `home` fixture's patch of installers is seen here.
        with patch.object(installers, "detect_available_agent_tools", return_value=["kiro"]):
            results = check_harness_export()
        assert results, "expected at least one harness result"
        assert all(r.category == "harness" for r in results)
        warn = [r for r in results if r.status == "warn"]
        assert warn and all(r.fix_auto for r in warn)
