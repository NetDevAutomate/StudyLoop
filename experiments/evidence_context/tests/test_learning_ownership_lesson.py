"""The ownership lesson exercises actual StudyLoop MCP transport."""

import json
import subprocess
import sys


def test_learning_ownership_walkthrough(tmp_path):
    output = tmp_path / "lesson"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "experiments.evidence_context.learning_ownership.runner",
            "--output",
            str(output),
        ],
        check=True,
        text=True,
        capture_output=True,
        timeout=60,
    )
    result = json.loads((output / "results.json").read_text())
    assert len(result["checks"]) == 8 and all(result["checks"].values())
    assert result["mcp_before"]["teachback_scores"][0]["notes"] == "PERSONAL_SCORE"
    assert result["mcp_after"]["teachback_scores"] == []
