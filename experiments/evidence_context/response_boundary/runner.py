"""Run Stage28 in an isolated process and render its four-part walkthrough."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from ..assertion_gate.viewer import block, escape


def render(result):
    steps = [
        (
            "1 · A normal scoped response",
            "normal_http",
            "The actual notes route returns personal context before the policy changes.",
        ),
        (
            "2 · Withhold the assembled response",
            "withheld_http",
            "A controlled change happens after the final query. No note body leaves the app.",
        ),
        (
            "3 · Detect an assignment changed back",
            "generation",
            "A monotonic database generation detects the intervening change "
            "even when the final owner matches.",
        ),
        (
            "4 · The same rule at the agent interface",
            "mcp",
            "MCP rejects the mixed request; its next request independently resolves the new scope.",
        ),
    ]
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Stage28 · One response, one access boundary</title><style>"
        "body{font:18px/1.6 system-ui;max-width:950px;margin:3rem auto;padding:0 1rem;"
        "background:#faf9f5;color:#24363b}section{margin:2rem 0;border-top:2px solid #cbded5}"
        "pre{font:14px/1.5 monospace;white-space:pre-wrap;overflow-wrap:anywhere}"
        "summary{cursor:pointer;color:#11665b}</style>"
        "<h1>One response, one access boundary</h1>"
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
        + block(result["benchmark"])
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
    result = subprocess.run(command, check=True, text=True, capture_output=True, timeout=60)
    data = json.loads((args.output / "results.json").read_text())
    (args.output / "walkthrough.html").write_text(render(data))
    print(result.stdout.strip())


if __name__ == "__main__":
    main()
