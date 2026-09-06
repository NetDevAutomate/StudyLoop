"""The preserved lesson executes the real content-phase implementation."""

import json
import os
import subprocess
import sys


def test_replica_content_lesson_runs_independently(tmp_path):
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
            "experiments.evidence_context.replica_content.runner",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads((output / "results.json").read_text())
    assert len(data["checks"]) == 12 and all(data["checks"].values())
    assert data["import"]["sync_complete"] is False
    assert (output / "walkthrough.html").read_text().count("<section>") == 5
