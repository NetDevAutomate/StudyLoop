"""Offline canonical-package lesson smoke test; no external conversations used."""

import json
import sqlite3

from experiments.evidence_context.canonical_sources.runner import run


def test_runnable_canonical_lesson_preserves_quotes_and_hides_scope(tmp_path):
    directory = tmp_path / "lesson"
    result = run(directory)
    assert result["work_source_hidden"]
    assert result["correction_hidden_after_reclassification"]
    assert result["relationships_after_reclassification"] == []
    assert len(result["proposed_relationship_before_reclassification"]) == 1
    assert (
        result["old_assertion_after_source_edit"]["semantic_status"] == "unverified_interpretation"
    )
    assert "WORK_ONLY_DEMO_MARKER" not in json.dumps(result)
    conn = sqlite3.connect(directory / "sessions.db")
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        assert conn.execute("SELECT count(*) FROM context_evidence").fetchone()[0] == 4
    finally:
        conn.close()
    assert (directory / "walkthrough.html").exists()
