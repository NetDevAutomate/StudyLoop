"""An independently runnable walkthrough of attributed review and retirement."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from ..assertion_gate.viewer import block, escape


def render(result):
    sections = [
        (
            "1 · An exact quote can accompany an overclaim",
            "initial",
            "The citation is exact, but atomic writes do not establish comparative database speed.",
        ),
        (
            "2 · Record the review and its evidence",
            "unsupported",
            "An attributed review points out the missing benchmark. "
            "The source's native authority stays unchanged.",
        ),
        (
            "3 · Keep disagreeing assessments visible",
            "disputed",
            "Another fictional review supports the overclaim. "
            "Code reports disagreement without picking a winner.",
        ),
        (
            "4 · Revise your own assessment",
            "history",
            "The CLI producer revises its own earlier assessment. "
            "The original remains inspectable as retired.",
        ),
        (
            "5 · Forgetting does not revive old approval",
            "retired",
            "The successor's body is deleted, but the content-free retirement link "
            "still prevents reactivation.",
        ),
        (
            "6 · Scope follows every contributing source",
            "revoked",
            "Moving the extra evidence into work scope withholds its dependent review. "
            "The retired favourable review stays retired.",
        ),
    ]
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Stage25 · Reviews are evidence too</title><style>"
        "body{font:18px/1.6 system-ui;max-width:920px;margin:3rem auto;padding:0 1rem;"
        "background:#faf9f5;color:#24363b}section{margin:2rem 0;border-top:2px solid #cbded5}"
        "pre{font:14px/1.5 monospace;white-space:pre-wrap;overflow-wrap:anywhere}"
        "summary{cursor:pointer;color:#11665b}</style><h1>Who assessed this claim, and why?</h1>"
        "<p>Fictional source records and reviews, actual CLI and MCP over stdio.</p>"
        "<p>A review is an attributed interpretation. "
        "It does not certify truth or authorize release.</p>"
        + "".join(
            "<section><h2>" + escape(title) + "</h2><p>" + escape(prose) + "</p>"
            "<details><summary>Inspect evidence and review history</summary>"
            + block(result[key])
            + "</details></section>"
            for title, key, prose in sections
        )
        + "<details><summary>Runtime and acceptance checks</summary>"
        + block({"runtime": result["runtime"], "checks": result["checks"]})
        + "</details></html>"
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
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=45)
    data = json.loads((args.output / "results.json").read_text())
    (args.output / "walkthrough.html").write_text(render(data))
    print(result.stdout.strip())


if __name__ == "__main__":
    main()
