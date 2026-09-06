"""Preserve the actual CLI recovery walkthrough."""

import json
import subprocess
import sys


def test_quarantine_recovery_lesson(tmp_path):
    output = tmp_path / "lesson"
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "experiments.evidence_context.quarantine_recovery.runner",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    data = json.loads((output / "results.json").read_text())
    assert len(data["checks"]) == 18 and all(data["checks"].values())
    assert data["recovery"]["operator_decisions"] == 1
    html = (output / "walkthrough.html").read_text()
    assert html.count("<section>") == 5
    assert "STAGE37_PRIVATE" not in html and "STAGE37_SHARED" not in html
