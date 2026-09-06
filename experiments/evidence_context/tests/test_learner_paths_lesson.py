"""The derived-record lesson exercises actual HTTP routes and MCP stdio."""

import json
import subprocess
import sys


def test_learner_paths_walkthrough(tmp_path):
    output = tmp_path / "lesson"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "experiments.evidence_context.learner_paths.runner",
            "--output",
            str(output),
        ],
        check=True,
        text=True,
        capture_output=True,
        timeout=60,
    )
    result = json.loads((output / "results.json").read_text())
    assert len(result["checks"]) == 10 and all(result["checks"].values())
    assert result["before"]["frequency"] == {"Shared question": 2}
    assert result["progress"][0]["record_dependencies"][0]["table"] == "practice_attempts"
    assert result["after"]["notes"] == []
    assert result["mcp_history"]["practice_attempts"][0]["authority"] == "application_report"
