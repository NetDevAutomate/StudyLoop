"""Run Stage32 in an isolated process and render its five-part walkthrough."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from ..assertion_gate.viewer import block, escape


def render(result):
    steps = [
        (
            "1 · Agree the permitted boundary",
            "negotiation",
            "Both peers allow personal context and agree on stable project IDs. "
            "Their local paths can differ.",
        ),
        (
            "2 · Select the whole dependency group",
            "projection",
            "Excluded work text is absent from the staged snapshot. "
            "Sources, reports and their owners travel together.",
        ),
        (
            "3 · Preserve meaning across local IDs",
            "import",
            "The source row is numbered 1; the destination uses 2 because its own row 1 already "
            "exists. The immutable report binding stays the same.",
        ),
        (
            "4 · Refuse an invented winner",
            "conflict",
            "A concurrent edit causes an explicit conflict and rolls back the whole content phase.",
        ),
        (
            "5 · Reject a stale grant",
            "stale_negotiation",
            "Changing source ownership invalidates negotiation before another "
            "content snapshot can be returned.",
        ),
    ]
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Stage32 · Scoped content before complete synchronization</title><style>"
        "body{font:18px/1.6 system-ui;max-width:950px;margin:3rem auto;padding:0 1rem;"
        "background:#faf9f5;color:#24363b}section{margin:2rem 0;border-top:2px solid #cbded5}"
        "pre{font:14px/1.5 monospace;white-space:pre-wrap;overflow-wrap:anywhere}"
        "summary{cursor:pointer;color:#11665b}</style>"
        "<h1>Scoped content before complete synchronization</h1>"
        + "".join(
            "<section><h2>"
            + escape(title)
            + "</h2><p>"
            + escape(prose)
            + "</p><details><summary>Inspect the returned records</summary>"
            + block(result[key])
            + "</details></section>"
            for title, key, prose in steps
        )
        + "<h2>Measured overhead and checks</h2>"
        + block(result["timing"])
        + block(result["checks"])
        + "<p>"
        + escape(result["limits"])
        + "</p>"
        + block(result["runtime"])
        + "</html>"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--require-installed", action="store_true")
    args = parser.parse_args()
    command = [
        str(args.python),
        "-I",
        str(Path(__file__).with_name("probe.py")),
        "--output",
        str(args.output.resolve()),
    ]
    if args.require_installed:
        command.append("--require-installed")
    result = subprocess.run(command, text=True, capture_output=True, timeout=180)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    data = json.loads((args.output / "results.json").read_text())
    (args.output / "walkthrough.html").write_text(render(data))
    print(result.stdout.strip())


if __name__ == "__main__":
    main()
