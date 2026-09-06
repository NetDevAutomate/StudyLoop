"""Review lineage works through the actual CLI and MCP transport."""

import json
import os
import sqlite3
import subprocess
import sys


def test_review_lesson_real_cli_and_mcp(tmp_path):
    output = tmp_path / "lesson"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "experiments.evidence_context.interpretation_reviews.runner",
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=45,
    )
    result = json.loads((output / "results.json").read_text())
    assert len(result["checks"]) == 8 and all(result["checks"].values())
    assert result["disputed"]["assessment"]["status"] == "disputed_reviews"
    assert result["revoked"]["assessment"]["status"] == "review_needed"


def test_pilot_rejects_fenced_and_partially_invalid_batches_without_mutating_environment(tmp_path):
    from experiments.evidence_context.interpretation_reviews.live import run

    keys = ("STUDYLOOP_CONFIG", "SESSION_CONTEXT_SCOPE")
    previous = {key: os.environ.get(key) for key in keys}

    def gateway(messages, model):
        cases = json.loads(messages[1]["content"])
        items = [
            {
                "case_id": case["case_id"],
                "verdict": "uncertain",
                "rationale": "Fixture assessment.",
                "citations": [case["sources"][0]["citation"]],
                "limitations": [],
            }
            for case in cases
        ]
        if model == "mistral-large-3":
            # Valid first two rows must roll back when the last row invents evidence.
            items[-1]["citations"][0]["evidence_id"] = "invented-source"
        text = json.dumps({"reviews": items})
        if model == "llama4-maverick":
            text = "```json\n" + text + "\n```"
        return {"finish_reason": "stop", "text": text}

    report = run(tmp_path, gateway=gateway)
    assert {key: os.environ.get(key) for key in keys} == previous
    assert [r["status"] for r in report["records"]] == ["failed", "accepted", "failed"]
    with sqlite3.connect(tmp_path / "sessions.db") as conn:
        assert conn.execute("SELECT count(*) FROM context_review_targets").fetchone()[0] == 3
