"""Run the Stage35 retention-history journey and render five inspectable steps."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from ..assertion_gate.viewer import block, escape


def render(data):
    sections = [
        (
            "1 · Native capture",
            "local_capture",
            "A trusted exporter records capture of this exact evidence version "
            "on this database instance.",
        ),
        (
            "2 · An accepted offer",
            "accepted_offer",
            "The peer has registered an offer, but no content contribution exists yet.",
        ),
        (
            "3 · Committed delivery",
            "committed_delivery",
            "Content and contribution facts commit with the receipt. "
            "The sender's local-capture label does not transfer.",
        ),
        (
            "4 · Changed content",
            "changed_version",
            "The row identity stays the same, but changing its body changes the binding. "
            "The old receipt cannot explain the new version.",
        ),
        (
            "5 · Capture is not permission",
            "recapture_and_forget",
            "A later archive read adds a capture fact. It does not grant retention; "
            "permanent forgetting still suppresses that archive.",
        ),
    ]
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Stage35 · Grounding retention history</title><style>"
        "body{font:18px/1.6 system-ui;max-width:950px;margin:3rem auto;padding:0 1rem;"
        "background:#faf9f5;color:#24363b}section{margin:2rem 0;border-top:2px solid #cbded5}"
        "pre{font:14px/1.5 monospace;white-space:pre-wrap;overflow-wrap:anywhere}"
        "summary{cursor:pointer;color:#11665b}</style>"
        "<h1>Where retention labels come from</h1>"
        + "".join(
            "<section><h2>"
            + escape(title)
            + "</h2><p>"
            + escape(prose)
            + "</p><details><summary>Inspect the observed result</summary>"
            + block(data[key])
            + "</details></section>"
            for title, key, prose in sections
        )
        + "<h2>Checks and limits</h2>"
        + block(data["checks"])
        + block(data["timing"])
        + "<p>"
        + escape(data["limits"])
        + "</p>"
        + block(data["runtime"])
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
    result = subprocess.run(command, text=True, capture_output=True, timeout=120)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    data = json.loads((args.output / "results.json").read_text())
    (args.output / "walkthrough.html").write_text(render(data))
    print(result.stdout.strip())


if __name__ == "__main__":
    main()
