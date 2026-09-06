"""Actual CLI process journey on disposable sources and explicit scope policy."""

import json
import sqlite3

from experiments.evidence_context.scope_boundary.runner import run


def test_policy_journey_blocks_scope_drift_and_hidden_bodies(tmp_path):
    output = tmp_path / "scope-lesson"
    result = run(output)
    observations = result["observations"]
    assert len(observations) == 8
    assert [r["exit_code"] for r in observations] == [2, 0, 0, 0, 0, 2, 0, 0]
    assert "PERSONAL_DEMO_VISIBLE" in observations[3]["stdout"]
    assert "WORK_DEMO_HIDDEN" not in json.dumps(result)
    assert json.loads(observations[-1]["stdout"]) == []
    conn = sqlite3.connect(output / "sessions.db")
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == 3
        assert conn.execute("SELECT count(*) FROM context_scope_audit").fetchone()[0] == 6
    finally:
        conn.close()
    assert (output / "walkthrough.html").read_text().count("<details>") == 8
