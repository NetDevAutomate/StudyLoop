"""Actual StudyLoop consumer lesson; all state and source fixtures are isolated."""

import json

from experiments.evidence_context.consumer_scope.runner import run


def test_consumer_lesson_shows_scoped_result_and_missing_lineage(tmp_path):
    result = run(tmp_path / "lesson")
    observed = result["observations"]
    assert observed["resume"]["session_id"] == "personal"
    assert observed["resume"]["concepts_scope_status"] == "withheld_missing_scope_lineage"
    assert observed["mcp_history"]["wins"] == []
    assert {row["session_id"] for row in observed["topic_matches"]} == {"personal"}
    assert result["after_unapplied_config_change"]["exit_code"] == 1
    assert "WORK_ONLY" not in json.dumps(result)
