"""The final partial batch must be as failure-contained as every earlier batch.

Every exporter processes sources in batches of ``batch_size`` (default 50) and
commits each full batch inside its per-source ``try``. The leftover partial
batch was flushed *after* the loop, outside that guard, so a single bad session
in the last (< 50) batch propagated out of ``export_all`` — and
``export_sessions._run_export`` has no per-source guard either, so one source's
final batch could abort the whole multi-source export run. Any source with
fewer than ``batch_size`` sessions total has *only* a final batch, so for small
harnesses the guard covered nothing at all.

``commit_batch`` already rolls back and records ``stats.errors`` before
re-raising, so containment here loses no accounting — it only stops the raise
from escaping.
"""

from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path

import pytest

import agent_session_tools.exporters.opencode as opencode_mod
from agent_session_tools.exporters import (
    claude as claude_mod,
)
from agent_session_tools.exporters.base import ExportStats, flush_batch
from agent_session_tools.exporters.claude import ClaudeCodeExporter
from agent_session_tools.exporters.opencode import OpenCodeExporter

EXPORTER_MODULES = ("claude", "codex", "grok", "kiro", "opencode", "pi")


# ---------------------------------------------------------------------------
# The contract of the shared helper
# ---------------------------------------------------------------------------


def test_flush_batch_contains_failure_and_reports_it(migrated_db, monkeypatch):
    """A raising commit is contained, reported False, and leaves stats intact."""
    conn, _ = migrated_db
    stats = ExportStats()

    def _boom(_conn, sessions, _messages, stats_):
        # Mirror commit_batch's own accounting before it re-raises.
        stats_.errors += len(sessions)
        raise ValueError("Message ID collision across sessions: shared")

    monkeypatch.setattr("agent_session_tools.exporters.base.commit_batch", _boom)

    committed = flush_batch(
        conn,
        [{"id": "s1", "source": "opencode"}],
        [],
        stats,
        source="opencode",
    )

    assert committed is False
    # commit_batch's own errors accounting is preserved, not double-counted.
    assert stats.errors == 1
    assert stats.added == 0


def test_flush_batch_commits_on_the_happy_path(migrated_db):
    conn, _ = migrated_db
    stats = ExportStats()

    committed = flush_batch(
        conn,
        [{"id": "s-ok", "source": "opencode", "status": "added"}],
        [
            {
                "id": "m-ok",
                "session_id": "s-ok",
                "role": "user",
                "content": "hello",
                "seq": 1,
            }
        ],
        stats,
        source="opencode",
    )

    assert committed is True
    assert stats.added == 1
    assert stats.errors == 0
    assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == 1


def test_flush_batch_is_a_noop_for_an_empty_batch(migrated_db):
    conn, _ = migrated_db
    stats = ExportStats()
    assert flush_batch(conn, [], [], stats, source="opencode") is True
    assert stats == ExportStats()


# ---------------------------------------------------------------------------
# Real exporters: a failing final flush must not escape export_all
# ---------------------------------------------------------------------------


def _raise_on_commit(_conn, sessions, _messages, stats):
    """Stand in for commit_batch, including its own pre-raise accounting.

    The real commit_batch rolls back, adds ``len(sessions)`` to ``stats.errors``
    and re-raises (base.py:216-219). Mirroring that here keeps the assertions
    about ``stats.errors`` honest: the helper under test must contain the raise
    without inventing or duplicating the count.
    """
    stats.errors += len(sessions)
    raise ValueError("Cannot remove a stale message with evidence references: m-1")


@pytest.fixture()
def minimal_opencode_tree(tmp_path, monkeypatch):
    """Smallest OpenCode store that yields exactly one exportable session."""
    storage = tmp_path / "storage"
    (storage / "session" / "p1").mkdir(parents=True)
    (storage / "session" / "p1" / "s1.json").write_text(
        json.dumps(
            {
                "id": "s1",
                "title": "T",
                "version": "0.1",
                "directory": "/tmp/p1",
                "time": {"created": 1717236000000, "updated": 1717239600000},
            }
        )
    )
    (storage / "message" / "s1").mkdir(parents=True)
    (storage / "message" / "s1" / "m1.json").write_text(
        json.dumps({"id": "m1", "role": "user", "time": {"created": 1717236000000}})
    )
    (storage / "part" / "m1").mkdir(parents=True)
    (storage / "part" / "m1" / "p1.json").write_text(
        json.dumps({"type": "text", "text": "hello"})
    )
    monkeypatch.setattr(opencode_mod, "OPENCODE_DIR", storage)
    return storage


def test_opencode_final_flush_failure_does_not_escape(
    migrated_db, minimal_opencode_tree, monkeypatch
):
    """One session (< batch_size) means the ONLY commit is the final flush."""
    conn, _ = migrated_db
    monkeypatch.setattr(
        "agent_session_tools.exporters.base.commit_batch", _raise_on_commit
    )

    stats = OpenCodeExporter().export_all(conn, incremental=False)

    assert stats.errors >= 1
    assert stats.added == 0


def test_claude_final_flush_failure_does_not_escape(migrated_db, tmp_path, monkeypatch):
    conn, _ = migrated_db
    projects = tmp_path / "projects"
    projects.mkdir()
    entry = {
        "uuid": "msg-001",
        "timestamp": "2024-06-01T10:00:00Z",
        "message": {"role": "user", "content": "Hello"},
    }
    (projects / "sess-a.jsonl").write_text(json.dumps(entry) + "\n")
    monkeypatch.setattr(
        "agent_session_tools.exporters.base.commit_batch", _raise_on_commit
    )

    stats = ClaudeCodeExporter(projects_dir=projects).export_all(
        conn, incremental=False
    )

    assert stats.errors >= 1
    assert stats.added == 0


# ---------------------------------------------------------------------------
# Positive control: the unguarded pattern must not come back anywhere
# ---------------------------------------------------------------------------


def _commit_batch_calls(tree: ast.AST) -> list[ast.Call]:
    """Every ``commit_batch(...)`` and ``anything.commit_batch(...)`` call.

    Both spellings are matched so the guard below cannot be evaded by importing
    the module instead of the name.
    """
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Name) and func.id == "commit_batch") or (
            isinstance(func, ast.Attribute) and func.attr == "commit_batch"
        ):
            calls.append(node)
    return calls


def _unguarded_commit_batch_lines(source: str) -> list[int]:
    """Line numbers of commit_batch calls that sit outside any try block."""
    tree = ast.parse(source)
    guarded = {
        call.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Try)
        for call in _commit_batch_calls(node)
    }
    return sorted(
        call.lineno for call in _commit_batch_calls(tree) if call.lineno not in guarded
    )


@pytest.mark.parametrize("module_name", EXPORTER_MODULES)
def test_no_exporter_calls_commit_batch_outside_a_guard(module_name):
    path = Path(claude_mod.__file__).with_name(f"{module_name}.py")
    unguarded = _unguarded_commit_batch_lines(path.read_text())
    assert unguarded == [], (
        f"{module_name}.py calls commit_batch unguarded at lines {unguarded}; "
        "use flush_batch() so a bad final batch cannot abort the export run"
    )


def test_the_ast_guard_can_actually_fail():
    """A check that cannot fail proves nothing — prove this one can."""
    assert _unguarded_commit_batch_lines(
        "def f():\n    commit_batch(1, 2, 3, 4)\n"
    ) == [2]
    assert (
        _unguarded_commit_batch_lines(
            "def f():\n    try:\n        commit_batch(1, 2, 3, 4)\n    except Exception:\n        pass\n"
        )
        == []
    )
    # The attribute spelling must not slip past the guard either.
    assert _unguarded_commit_batch_lines(
        "def f():\n    base.commit_batch(1, 2, 3, 4)\n"
    ) == [2]


def test_every_exporter_reaches_commit_batch_through_base():
    """No exporter may bind a ``commit_batch`` other than the reviewed one.

    The guard above reads source text, so it only means something while every
    exporter's ``commit_batch`` really is base.py's — reached directly or via
    ``flush_batch``. OpenCode and Kiro now route every batch through
    ``flush_batch`` and no longer import the name at all.
    """
    from agent_session_tools.exporters import base as base_mod

    bound = {}
    for module_name in EXPORTER_MODULES:
        module = importlib.import_module(f"agent_session_tools.exporters.{module_name}")
        assert module.__dict__.get("commit_batch") in (None, base_mod.commit_batch), (
            f"{module_name}.py binds a commit_batch that is not base.commit_batch"
        )
        assert module.__dict__.get("flush_batch") in (None, base_mod.flush_batch)
        bound[module_name] = set(module.__dict__) & {"commit_batch", "flush_batch"}

    # Every exporter must reach the guarded path by one spelling or the other.
    assert all(names for names in bound.values()), bound
    assert bound["opencode"] == {"flush_batch"}
