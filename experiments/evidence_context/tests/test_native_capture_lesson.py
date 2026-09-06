"""The standalone lesson must exercise actual exporters in an isolated process."""

import json
import subprocess
import sys


def test_native_capture_lesson(tmp_path):
    output = tmp_path / "lesson"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "experiments.evidence_context.native_capture.runner",
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads((output / "results.json").read_text())
    assert result["checks"] == {
        "native_records": 7,
        "process_exit_records": 1,
        "revision_unknown": 7,
        "legacy_conversation_messages": 1,
        "replay_added_records": 0,
        "malformed_input_lost_records": 0,
    }
    assert len(result["health"]["harnesses"]) == 4
    assert result["health"]["harnesses"][0]["attempt_state"] == "partial"
    html = (output / "walkthrough.html").read_text()
    assert html.count("<section>") == 5
    assert "hook liveness" in html
