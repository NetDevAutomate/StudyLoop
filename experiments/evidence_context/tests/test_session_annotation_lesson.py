"""The preserved Stage30 lesson invokes actual commands and MCP."""

import json
import os
import subprocess
import sys


def test_session_annotation_walkthrough(tmp_path):
    output = tmp_path / "lesson"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "experiments.evidence_context.session_annotations.runner",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        env=dict(os.environ),
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads((output / "results.json").read_text())
    assert len(evidence["checks"]) == 10 and all(evidence["checks"].values())
    page = (output / "walkthrough.html").read_text()
    assert page.count("<section>") == 5
    assert "scoped sync or managed restore proof" in page
