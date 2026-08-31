"""Shipped mentor definitions must not trigger unconfigured extraction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _repo_root() -> Path:
    candidate = Path(__file__).resolve()
    for parent in candidate.parents:
        if (parent / "agents").is_dir() and (parent / "packages").is_dir():
            return parent
    raise RuntimeError("Could not locate repository root")


REPO = _repo_root()
TARGET = "extract-struggles"
SHIPPED_MENTOR_FILES = (
    REPO / "agents" / "claude" / "settings.json",
    REPO / "agents" / "kiro" / "skills" / "study-mentor" / "SKILL.md",
    REPO / "agents" / "codex" / "AGENTS.md",
    REPO / "agents" / "opencode" / "study-mentor.md",
    REPO / "agents" / "pi" / "AGENTS.md",
)


@pytest.mark.parametrize("path", SHIPPED_MENTOR_FILES, ids=lambda path: path.parent.name)
def test_shipped_mentor_does_not_run_unconfigured_extraction(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        assert json.loads(text) is not None
    assert TARGET not in text


def test_every_release_harness_has_a_real_session_export_route() -> None:
    from studyloop.installers import _HARNESS_EXPORT

    assert {name: spec.export_flag for name, spec in _HARNESS_EXPORT.items()} == {
        "kiro": "kiro-only",
        "claude": "claude-only",
        "opencode": "opencode-only",
        "pi": "pi-only",
    }
    assert "session-export --codex-only" in (REPO / "agents" / "codex" / "AGENTS.md").read_text(
        encoding="utf-8"
    )
    assert "session-export --opencode-only" in (
        REPO / "agents" / "opencode" / "study-mentor.md"
    ).read_text(encoding="utf-8")
