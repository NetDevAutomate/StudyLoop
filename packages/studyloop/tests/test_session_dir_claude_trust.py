"""``setup_session_dir`` and Claude Code's trust list: only for a Claude session.

The pre-trust write exists so a Claude Code mentor never blocks on the
workspace-trust prompt in an automated session. It was harness-agnostic: a
``studyloop study --agent pi`` also added its session dir to the developer's
real ``~/.claude/settings.json`` -- found 2026-09-16 when the first
real-harness-auth acceptance run for pi tripped the unit suite's real-home
write guard on exactly that file. A pi, OpenCode or Grok Build session gains
nothing from the entry, and every such session leaves a dead scratch path in
the learner's Claude settings for good.

No conftest.py (pluggy conflict with agent-session-tools). Fixtures inline.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from studyloop.session import orchestrator

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def claude_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    settings = tmp_path / "claude-home" / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"projects": {}}))
    monkeypatch.setattr(orchestrator, "_claude_settings_path", lambda: settings)
    return settings


def _trusted(settings: Path) -> set[str]:
    data = json.loads(settings.read_text())
    return {k for k, v in data.get("projects", {}).items() if v.get("hasTrustDialogAccepted")}


class TestClaudeTrustIsHarnessAware:
    def test_claude_session_pre_trusts_the_session_dir_and_its_parent(
        self, tmp_path: Path, claude_settings: Path
    ) -> None:
        session_dir = tmp_path / "sessions" / "study-topic-abcd1234"
        orchestrator.setup_session_dir(session_dir, "Topic", agent="claude")
        assert _trusted(claude_settings) == {str(session_dir), str(session_dir.parent)}

    @pytest.mark.parametrize("agent", ["pi", "opencode", "grok", "codex", "kiro"])
    def test_other_harness_sessions_never_touch_claude_settings(
        self, agent: str, tmp_path: Path, claude_settings: Path
    ) -> None:
        before = claude_settings.read_text()
        session_dir = tmp_path / "sessions" / f"study-topic-{agent}"
        orchestrator.setup_session_dir(session_dir, "Topic", agent=agent)
        assert claude_settings.read_text() == before
        # The rest of the directory setup is unchanged for every harness.
        assert (session_dir / "CLAUDE.md").exists()
        assert (session_dir / "studyloop").exists()

    def test_unknown_agent_keeps_the_historical_pre_trust(
        self, tmp_path: Path, claude_settings: Path
    ) -> None:
        """Callers that do not (yet) say which harness they launch -- the web
        session-start routes -- keep the behaviour they had, so nothing that
        depended on the trust entry silently loses it."""
        session_dir = tmp_path / "sessions" / "study-topic-web"
        orchestrator.setup_session_dir(session_dir, "Topic")
        assert str(session_dir) in _trusted(claude_settings)
