"""Build the independently runnable Stage23 CLI/MCP walkthrough."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from ..assertion_gate.viewer import block, escape


def render(result):
    pages = [
        (
            "1 · Follow the relationship",
            "A lexical match in StudyLoop leads to a proposed contrary claim in MailGraph. "
            "Both sources retain their harness, machine, project and exact citations.",
            "history",
        ),
        (
            "2 · A precise check contract",
            "The captured fixture record matches a requested command, project, immutable "
            "revision and exit code. This confirms only that recorded execution contract.",
            "matching_checks",
        ),
        (
            "3 · Keep the disagreement",
            "A second receipt for the same revision reports another exit code. "
            "Arrival order and recency do not select a winner.",
            "conflicting_checks",
        ),
        (
            "4 · Change the requested revision",
            "The same records no longer establish the requested check. Their historical "
            "value remains, but their validation applicability changes.",
            "different_revision",
        ),
        (
            "5 · Make omissions visible",
            "A smaller output budget limits the source set. The response explicitly reports "
            "that bound rather than suggesting all relevant evidence was returned.",
            "bounded_context",
        ),
        (
            "6 · Reclassify while MCP stays connected",
            "MailGraph moves to work scope in the fixture. The next request withholds "
            "its source and the relationship that depended on it.",
            "reclassified_context",
        ),
    ]
    sections = []
    for title, prose, key in pages:
        sections.append(
            "<section><h2>"
            + escape(title)
            + "</h2><p>"
            + escape(prose)
            + "</p><details><summary>Inspect returned context</summary>"
            + block(result[key])
            + "</details></section>"
        )
    return (
        """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stage23 · Context for an agent</title><style>
body{font:18px/1.6 system-ui;max-width:920px;margin:3rem auto;padding:0 1rem;
background:#faf9f5;color:#24363b}h1,h2{line-height:1.2}
section{margin:2.5rem 0;border-top:2px solid #d6e2df;padding-top:1rem}
summary{cursor:pointer;color:#11665b}
pre{font:14px/1.5 ui-monospace;white-space:pre-wrap;overflow-wrap:anywhere;
background:#edf2ef;padding:1rem}
</style><h1>What can an agent responsibly conclude?</h1>
<p>Stage23 · Fictional source receipts, actual CLI and MCP over stdio.</p>
<p>This lesson tests retrieval and execution-contract decisions. It does not prove
semantic correctness or general answer-quality improvements.</p>"""
        + "".join(sections)
        + (
            "<details><summary>Runtime and acceptance checks</summary>"
            + block({"runtime": result["runtime"], "checks": result["checks"]})
            + "</details></html>"
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--require-installed", action="store_true")
    parser.add_argument("--pressure", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error("Choose a new output directory")
    command = [
        str(args.python),
        "-I",
        str(Path(__file__).with_name("probe.py")),
        "--output",
        str(output),
    ]
    if args.require_installed:
        command.append("--require-installed")
    if args.pressure:
        command.append("--pressure")
    completed = subprocess.run(command, check=True, text=True, capture_output=True, timeout=45)
    result = json.loads((output / "results.json").read_text())
    (output / "walkthrough.html").write_text(render(result))
    print(completed.stdout.strip())


if __name__ == "__main__":
    main()
