"""Writer isolation (learning tier, item 1, plan §5 "Isolation").

Every ``W_auto`` writer is driven in a **child process** whose ``HOME`` and
``XDG_*`` point at a decoy tree while the four StudyLoop redirects point at a
sandbox. If any writer resolved a path through the home directory instead of
the redirect, a test run would reach the learner's real database or session
files -- the exact failure ``conftest.py`` documents from 2026-09-05. The
child writes through the real MCP tool functions, then the parent asserts:

* the decoy home tree holds no new file (including Markdown);
* each writer's row or line landed inside the sandbox.

Plan §5 says this test is a guard if it already passes on ``main`` and RED
only if it fails; it passed on first run, so it is the guard.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pytest.importorskip("mcp")

_CHILD = textwrap.dedent(
    """
    import json, os, sys
    from studyloop.mcp.server import mcp
    tools = mcp._tool_manager._tools

    def call(name, **kw):
        return tools[name].fn(**kw)

    out = {}
    out["log_topic"] = call("log_topic", topic="window frame", status="learning", note="iso")
    out["log_struggle"] = call("log_struggle", question="why ROWS not RANGE", topic_tag="sql")
    out["record_teachback"] = call(
        "record_teachback", concept="window frame", topic="sql",
        scores=[3, 3, 4, 3, 2], review_type="micro",
    )
    plan = call(
        "create_study_plan", title="Isolation plan",
        answers={"why": "prove the writers stay in the sandbox", "success": ["one row each"],
                 "topics": ["sql"], "milestones": [{"title": "Frames"}]},
        plan_id="isolation-plan",
    )
    out["record_plan_learning"] = call(
        "record_plan_learning", plan_id="isolation-plan", title="Frames are ROWS or RANGE",
        body="isolation body",
    )
    print(json.dumps(out, default=str))
    """
)


def _tree(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def test_every_w_auto_writer_stays_inside_the_sandbox(tmp_path: Path) -> None:
    decoy_home = tmp_path / "decoy-home"
    sandbox = tmp_path / "sandbox"
    for d in (decoy_home, sandbox / "state", sandbox / "session", sandbox / "plans"):
        d.mkdir(parents=True)
    # A decoy config dir that looks like a real one, so a writer that resolves
    # through HOME has somewhere plausible to land.
    (decoy_home / ".config" / "studyloop").mkdir(parents=True)
    (decoy_home / ".local" / "share" / "studyloop").mkdir(parents=True)
    before = _tree(decoy_home)

    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("STUDYLOOP_", "XDG_")) and k != "HOME"
    }
    env.update(
        {
            "HOME": str(decoy_home),
            "XDG_CONFIG_HOME": str(decoy_home / ".config"),
            "XDG_DATA_HOME": str(decoy_home / ".local" / "share"),
            "STUDYLOOP_DB": str(sandbox / "sessions.db"),
            "STUDYLOOP_STATE_DIR": str(sandbox / "state"),
            "STUDYLOOP_SESSION_DIR": str(sandbox / "session"),
            "STUDYLOOP_PLANS_DIR": str(sandbox / "plans"),
            "STUDYLOOP_CONFIG": str(sandbox / "config.yaml"),
        }
    )
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])

    # Nothing escaped to the decoy home -- not a database, not a Markdown file.
    escaped = _tree(decoy_home) - before
    assert escaped == set(), f"writers reached the home tree: {sorted(escaped)}"

    # Each writer landed inside the sandbox -- rows counted, not files stat'ed
    # (council review 9, astra Y4).
    assert out["record_teachback"]["recorded"] is True
    assert out["record_plan_learning"]["created"] is True
    assert out["log_struggle"]["status"] == "logged"
    topics = sandbox / "session" / "session-topics.md"
    assert topics.is_file() and "window frame" in topics.read_text(encoding="utf-8"), (
        "log_topic wrote no session line"
    )
    conn = sqlite3.connect(sandbox / "sessions.db")
    try:
        teachbacks = conn.execute("SELECT COUNT(*) FROM teach_back_scores").fetchone()[0]
        parked = conn.execute("SELECT COUNT(*) FROM parked_topics").fetchone()[0]
    finally:
        conn.close()
    assert teachbacks == 1, f"record_teachback rows in the sandbox: {teachbacks}"
    assert parked == 1, f"log_struggle rows in the sandbox: {parked}"
    plan_docs = list((sandbox / "plans").rglob("*.md"))
    assert plan_docs, "record_plan_learning wrote no plan document in the sandbox"
    assert any("Frames are ROWS or RANGE" in p.read_text(encoding="utf-8") for p in plan_docs)
