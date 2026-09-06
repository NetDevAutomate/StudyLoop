"""Run the isolated Stage26 ownership walkthrough, optionally against installed wheels."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from ..assertion_gate.viewer import block, escape


def render(result):
    steps = [
        (
            "1 · Useful permitted history",
            "before",
            "Session statistics, scores, bridges and progress share the "
            "configured personal boundary.",
        ),
        (
            "2 · The actual StudyLoop agent interface",
            "mcp_before",
            "The running MCP server returns permitted scores and session counts, "
            "with no work notes.",
        ),
        (
            "3 · Change the source classification",
            "mcp_after",
            "After policy apply, the same server withholds records linked to "
            "the reclassified source.",
        ),
        (
            "4 · Check lifecycle and runtime",
            "checks",
            "Cross-scope updates fail; a logical source-forgetting event purges "
            "the linked application rows.",
        ),
    ]
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Stage26 · Learning records have owners</title><style>"
        "body{font:18px/1.6 system-ui;max-width:950px;margin:3rem auto;padding:0 1rem;"
        "background:#faf9f5;color:#24363b}section{margin:2rem 0;border-top:2px solid #cbded5}"
        "pre{font:14px/1.5 monospace;white-space:pre-wrap;overflow-wrap:anywhere}"
        "summary{cursor:pointer;color:#11665b}</style><h1>Learning records have owners</h1>"
        "<p>Fictional personal/work records through real StudyLoop APIs and MCP stdio.</p>"
        + "".join(
            "<section><h2>" + escape(title) + "</h2><p>" + escape(prose) + "</p>"
            "<details><summary>Inspect the returned records</summary>"
            + block(result[key])
            + "</details></section>"
            for title, key, prose in steps
        )
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
