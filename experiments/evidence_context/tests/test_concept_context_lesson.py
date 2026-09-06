"""The graph lesson validates actual HTTP routes and MCP stdio."""

import json
import subprocess
import sys


def test_concept_context_lesson(tmp_path):
    output = tmp_path / "lesson"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "experiments.evidence_context.concept_context.runner",
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    result = json.loads((output / "results.json").read_text())
    assert len(result["checks"]) == 10 and all(result["checks"].values())
    assert result["mcp"]["contract"] == "studyloop.concept-context/v1"
    assert result["after_scope"]["edges"] == []
