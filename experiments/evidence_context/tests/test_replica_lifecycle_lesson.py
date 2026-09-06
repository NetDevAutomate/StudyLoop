"""Preserve the durable replica lifecycle walkthrough as an independent lesson."""

import json
import os
import subprocess
import sys


def test_replica_lifecycle_lesson(tmp_path):
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
            "experiments.evidence_context.replica_lifecycle.runner",
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
    assert len(data["checks"]) == 20 and all(data["checks"].values())
    assert data["replica_result"]["acknowledgement"]["sync_complete"] is False
    assert (output / "walkthrough.html").read_text().count("<section>") == 5
