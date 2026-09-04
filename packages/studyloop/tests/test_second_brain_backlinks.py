"""T2 C11: backlinks reuse the export sink's matcher, and degrade quietly.

Two decisions are under test.

*Reuse, not reimplementation.* Two matchers would produce two different link sets
from one vault, so a learner would see study notes linking to one note and session
notes to another for the same term. The test asserts the real functions are
called, not that some links came back.

*Optional, not required.* The matcher lives in a separate package with its own
wheel. When it is absent, publishing continues without links — losing a
convenience is not a reason to refuse to write a note.
"""

from __future__ import annotations

import builtins
import logging

import pytest
from test_second_brain_templates import full_plan

from studyloop.second_brain import backlinks


def test_link_candidates_are_topics_then_concepts() -> None:
    plan = full_plan()
    plan.topics = ["python", "decorators"]
    plan.milestones[0].concepts = ["closures", "cell-vars"]
    assert backlinks.link_candidates(plan) == [
        "python",
        "decorators",
        "closures",
        "cell-vars",
    ]


def test_link_candidates_dedupe_case_insensitively_keeping_first_spelling() -> None:
    """``SQL`` and ``sql`` are one term; the learner's first spelling wins."""
    plan = full_plan()
    plan.topics = ["SQL"]
    plan.milestones[0].concepts = ["sql", "Window Functions"]
    assert backlinks.link_candidates(plan) == ["SQL", "Window Functions"]


def test_backlinks_use_lazy_agent_session_tools_matcher(tmp_path, monkeypatch) -> None:
    seen: dict[str, object] = {}

    def _index(vault_path):
        seen["vault"] = vault_path
        return {"python": "Python", "closures": "Closures"}

    def _inject(topics, index):
        seen["topics"] = list(topics)
        return [f"[[{index[t.lower()]}]]" for t in topics if t.lower() in index]

    monkeypatch.setattr(
        "agent_session_tools.obsidian_writer.build_topic_index", _index, raising=True
    )
    monkeypatch.setattr(
        "agent_session_tools.obsidian_writer.inject_backlinks", _inject, raising=True
    )

    plan = full_plan()
    plan.topics = ["python"]
    plan.milestones[0].concepts = ["closures", "not-a-note"]
    links = backlinks.wikilinks_for(plan, tmp_path)

    assert links == ["[[Python]]", "[[Closures]]"]
    assert seen["vault"] == tmp_path
    assert seen["topics"] == ["python", "closures", "not-a-note"]


def test_missing_matcher_warns_once_and_publishes_without_backlinks(
    tmp_path, monkeypatch, caplog
) -> None:
    real_import = builtins.__import__

    def _no_matcher(name, *args, **kwargs):
        if name == "agent_session_tools.obsidian_writer":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_matcher)
    backlinks.reset_warning_state()

    with caplog.at_level(logging.WARNING, logger="studyloop.second_brain.backlinks"):
        assert backlinks.wikilinks_for(full_plan(), tmp_path) == []
        assert backlinks.wikilinks_for(full_plan(), tmp_path) == []

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert "without wikilinks" in warnings[0].getMessage()


def test_disabled_backlinks_never_scan_the_vault(tmp_path, monkeypatch) -> None:
    """``backlinks: false`` must not cost a vault walk on every publish."""

    def _explode(*args: object, **kwargs: object):
        raise AssertionError("the vault was scanned with backlinks disabled")

    monkeypatch.setattr(
        "agent_session_tools.obsidian_writer.build_topic_index", _explode, raising=True
    )
    assert backlinks.wikilinks_for(full_plan(), tmp_path, enabled=False) == []


def test_a_plan_with_no_terms_does_not_scan(tmp_path, monkeypatch) -> None:
    def _explode(*args: object, **kwargs: object):
        raise AssertionError("the vault was scanned with nothing to match")

    monkeypatch.setattr(
        "agent_session_tools.obsidian_writer.build_topic_index", _explode, raising=True
    )
    plan = full_plan()
    plan.topics = []
    plan.milestones = []
    assert backlinks.wikilinks_for(plan, tmp_path) == []


def test_a_failing_vault_scan_does_not_break_a_publish(tmp_path, monkeypatch) -> None:
    def _raise(vault_path):
        raise OSError("permission denied")

    monkeypatch.setattr(
        "agent_session_tools.obsidian_writer.build_topic_index", _raise, raising=True
    )
    assert backlinks.wikilinks_for(full_plan(), tmp_path) == []


@pytest.mark.parametrize("module", ["studyloop.second_brain.backlinks"])
def test_the_matcher_is_not_imported_at_module_level(module) -> None:
    """A top-level import would make StudyLoop's wheel depend on the sibling package."""
    from pathlib import Path

    import studyloop.second_brain.backlinks as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    top_level = [
        line
        for line in source.splitlines()
        if line.startswith(("import agent_session_tools", "from agent_session_tools"))
    ]
    assert top_level == []
