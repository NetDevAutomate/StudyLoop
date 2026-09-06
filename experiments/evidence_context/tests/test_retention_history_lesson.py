"""Preserve the retention history walkthrough as an independent lesson."""

import json
import os
import subprocess
import sys


def test_retention_history_lesson(tmp_path):
    output = tmp_path / "lesson"
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        not in {
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "OPENROUTER_API_KEY",
            "GEMINI_API_KEY",
            "AWS_BEARER_TOKEN_BEDROCK",
        }
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "experiments.evidence_context.retention_history.runner",
            "--output",
            str(output),
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads((output / "results.json").read_text())
    assert len(data["checks"]) == 15 and all(data["checks"].values())
    assert data["committed_delivery"]["retention_authorized"] == "not_evaluated"
    assert (output / "walkthrough.html").read_text().count("<section>") == 5
