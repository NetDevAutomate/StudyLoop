"""The response-boundary lesson invokes actual HTTP and MCP helpers."""

import json
import subprocess
import sys


def test_response_boundary_walkthrough(tmp_path):
    output = tmp_path / "lesson"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "experiments.evidence_context.response_boundary.runner",
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
    assert result["generation"]["after"] > result["generation"]["before"]
    assert result["withheld_http"]["code"] == "context_scope_unavailable"
    assert "PERSONAL_NOTE" not in json.dumps(result["withheld_http"])
