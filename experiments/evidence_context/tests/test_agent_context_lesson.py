"""The Stage23 lesson crosses the real MCP transport and CLI boundaries."""

import json
import subprocess
import sys


def test_agent_context_stdio_lesson(tmp_path):
    output = tmp_path / "lesson"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "experiments.evidence_context.agent_context.runner",
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=45,
    )
    result = json.loads((output / "results.json").read_text())
    assert all(result["checks"].values())
    assert len(result["checks"]) == 8
    assert result["runtime"]["mcp_transport"] == "stdio"
    assert result["conflicting_checks"]["decision"]["sufficiency"] == "conflicting_records"
    assert (output / "walkthrough.html").read_text().count("<section>") == 6
