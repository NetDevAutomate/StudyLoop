"""Render the actual CLI/SSH result as five inspectable learning steps."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from ..assertion_gate.viewer import block, escape


def render(data):
    sections = [
        (
            "1 · Establish the peer",
            "connection",
            "A dedicated SSH key reaches a receiver-owned forced command. "
            "Host verification and local peer scope are separate checks.",
        ),
        (
            "2 · Transfer permitted context",
            "first_transfer",
            "The real session-sync CLI reconciles both control directions before sending "
            "the permitted personal scope. Work history stays local.",
        ),
        (
            "3 · Retry with metadata alone",
            "unchanged_retry",
            "The last committed receipt binds both database states. When they still match, "
            "no conversation body is sent again.",
        ),
        (
            "4 · Withdraw and regrant",
            "permissions",
            "A local permission command queues intent. Sync delivers generations in order; "
            "a fresh permitted transfer is needed to restore withdrawn content.",
        ),
        (
            "5 · Respect forgetting in either direction",
            "reverse_retirement",
            "The receiver forgets a source. Even a push-only command brings that retirement "
            "back before considering new content.",
        ),
    ]
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Stage38 · Configured SSH synchronization</title><style>"
        "body{font:18px/1.6 system-ui;max-width:950px;margin:3rem auto;padding:0 1rem;"
        "background:#faf9f5;color:#24363b}section{margin:2rem 0;border-top:2px solid #cbded5}"
        "pre{font:14px/1.5 monospace;white-space:pre-wrap;overflow-wrap:anywhere}"
        "summary{cursor:pointer;color:#11665b}</style><h1>From local rules to real transfers</h1>"
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
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    data = json.loads((args.output / "results.json").read_text())
    (args.output / "walkthrough.html").write_text(render(data))
    print(result.stdout.strip())


if __name__ == "__main__":
    main()
