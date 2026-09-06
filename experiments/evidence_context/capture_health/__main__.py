"""Run: python -m experiments.evidence_context.capture_health --output NEW_DIR."""

import argparse
import json
from pathlib import Path

from .lab import CaptureLab


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, mode=0o700, exist_ok=False)
    lab = CaptureLab(args.output / "capture.db")
    source = args.output / "synthetic.json"
    options = {
        "now": "2026-01-01T01:00:00Z",
        "max_age_seconds": 7200,
        "detected": True,
        "skill_installed": True,
        "hook_registered": True,
        "repair_gaps": 0,
    }
    try:
        reports = {"installed_but_never_captured": lab.report("demo", **options)}
        source.write_text(json.dumps([{"id": "1", "body": "synthetic history"}]))
        lab.capture("demo", source, "2026-01-01T00:00:00Z")
        reports["successful_capture"] = lab.report("demo", **options)
        source.write_text("malformed synthetic JSON")
        lab.capture("demo", source, "2026-01-01T00:30:00Z")
        reports["failed_after_success"] = lab.report("demo", **options)
        reports["disabled_hook"] = lab.report("demo", **{**options, "hook_registered": False})
        reports["delayed_capture"] = lab.report(
            "demo", **{**options, "now": "2026-01-02T00:00:00Z"}
        )
        reports["unknown_coverage"] = lab.report("demo", **{**options, "repair_gaps": None})
        result = json.dumps(reports, indent=2)
        (args.output / "report.json").write_text(result + "\n")
        print(result)
    finally:
        lab.close()


if __name__ == "__main__":
    main()
