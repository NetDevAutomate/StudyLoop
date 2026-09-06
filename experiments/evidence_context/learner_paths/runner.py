"""Run Stage27 independently and write an expandable learning walkthrough."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from ..assertion_gate.viewer import block, escape


def render(result):
    sections = [
        (
            "1 · Permitted notes and board",
            "before",
            "Identical questions from different owners stay separate. "
            "Counts and board names use the same boundary.",
        ),
        (
            "2 · An attributable practice report",
            "progress",
            "A progress report retains its application-record dependency. "
            "It does not become native evidence or proof of mastery.",
        ),
        (
            "3 · The agent's actual interface",
            "mcp_history",
            "The MCP server returns permitted practice history and its validation limits.",
        ),
        (
            "4 · Reclassify the source",
            "after",
            "The source's dependent notes and parked cards disappear from personal responses.",
        ),
        (
            "5 · Check deletion and runtime",
            "checks",
            "The database removes linked bodies and retires derived progress. "
            "Inspect every check and the runtime used.",
        ),
    ]
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Stage27 · Protect the derived records too</title><style>"
        "body{font:18px/1.6 system-ui;max-width:950px;margin:3rem auto;padding:0 1rem;"
        "background:#faf9f5;color:#24363b}section{margin:2rem 0;border-top:2px solid #cbded5}"
        "pre{font:14px/1.5 monospace;white-space:pre-wrap;overflow-wrap:anywhere}"
        "summary{cursor:pointer;color:#11665b}</style><h1>Protect the derived records too</h1>"
        + "".join(
            "<section><h2>"
            + escape(title)
            + "</h2><p>"
            + escape(prose)
            + "</p><details><summary>Inspect the returned records</summary>"
            + block(result[key])
            + "</details></section>"
            for title, key, prose in sections
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
    run = subprocess.run(command, check=True, text=True, capture_output=True, timeout=60)
    result = json.loads((args.output / "results.json").read_text())
    (args.output / "walkthrough.html").write_text(render(result))
    print(run.stdout.strip())


if __name__ == "__main__":
    main()
