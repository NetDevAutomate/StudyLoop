"""Exercise the fictional lesson through its real isolated child process."""

import json
import subprocess
import sys

from experiments.evidence_context.permission_withdrawal.runner import render


def test_permission_withdrawal_lesson(tmp_path):
    output = tmp_path / "lesson"
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "experiments.evidence_context.permission_withdrawal.runner",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 0, run.stderr
    result = json.loads((output / "results.json").read_text())
    assert len(result["checks"]) == 18 and all(result["checks"].values())
    assert result["quarantine"]["bytes_retained"] and result["quarantine"]["context_hidden"]
    html = render(result)
    assert html.count("<section>") == 6 and html.count("<details>") == 6
    assert "STAGE36_LOCAL" not in html and "STAGE36_SHARED" not in html
