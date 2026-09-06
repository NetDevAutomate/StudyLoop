"""Run Stage31 in an isolated process and render its four-part walkthrough."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from ..assertion_gate.viewer import block, escape


def render(result):
    steps = [
        (
            "1 · Complete current disagreement",
            "overview",
            "The overview retains both current reports and discloses more history.",
        ),
        (
            "2 · Continue historical context",
            "history_page",
            "The actual MCP page says it is history-only. Its cursor does not grant access.",
        ),
        (
            "3 · A correction invalidates the cursor",
            "stale_cursor",
            "Restart after a change, so old and new snapshots cannot be combined silently.",
        ),
        (
            "4 · A group that cannot fit",
            "atomic_group",
            "The response withholds all current bodies and explains why. "
            "It does not pick the smaller report as a winner.",
        ),
    ]
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Stage31 · Bounded history without hidden disagreement</title><style>"
        "body{font:18px/1.6 system-ui;max-width:950px;margin:3rem auto;padding:0 1rem;"
        "background:#faf9f5;color:#24363b}section{margin:2rem 0;border-top:2px solid #cbded5}"
        "pre{font:14px/1.5 monospace;white-space:pre-wrap;overflow-wrap:anywhere}"
        "summary{cursor:pointer;color:#11665b}</style>"
        "<h1>Bounded history without hidden disagreement</h1>"
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
        + block({"pages_traversed": result["pages_traversed"]})
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
