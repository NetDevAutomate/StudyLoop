"""The Stage31 lesson traverses actual MCP pages from a real CLI cursor."""

import json
import subprocess
import sys


def test_bounded_history_walkthrough(tmp_path):
    output = tmp_path / "lesson"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "experiments.evidence_context.bounded_history.runner",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads((output / "results.json").read_text())
    assert len(data["checks"]) == 8 and all(data["checks"].values())
    assert data["pages_traversed"] > 1
    assert (output / "walkthrough.html").read_text().count("<section>") == 4
