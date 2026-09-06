"""Render the Stage36 permission journey from actual disposable protocol operations."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from ..assertion_gate.viewer import block, escape


def render(data):
    sections = [
        (
            "1 · A committed copy",
            "received",
            "A received conversation starts at permission generation zero.",
        ),
        (
            "2 · Withdraw permission",
            "withdrawal",
            "The complete purge footprint has only this peer's matching delivery facts. "
            "The receiver evicts it and completes canonical database cleanup.",
        ),
        (
            "3 · Regrant with fresh evidence",
            "regrant",
            "A regrant control leaves the old object hidden. A fresh offer at the current "
            "generation must cover the content before it can return.",
        ),
        (
            "4 · A local addition changes the decision",
            "quarantine",
            "The receiver added a message after delivery. Its retention history is unresolved. "
            "Bytes remain but context access is denied; cleanup is explicitly incomplete.",
        ),
        (
            "5 · A partial regrant is insufficient",
            "coverage",
            "The sender's fresh packet lacks the local addition. Reopening the session would "
            "expose an unoffered body, so the whole content transaction rolls back.",
        ),
        (
            "6 · Permanent forgetting remains separate",
            "forget",
            "An explicit permanent forget still removes this source and suppresses "
            "future native archive replay.",
        ),
    ]
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Stage36 · Withdrawal and regrant</title><style>"
        "body{font:18px/1.6 system-ui;max-width:950px;margin:3rem auto;padding:0 1rem;"
        "background:#faf9f5;color:#24363b}section{margin:2rem 0;border-top:2px solid #cbded5}"
        "pre{font:14px/1.5 monospace;white-space:pre-wrap;overflow-wrap:anywhere}"
        "summary{cursor:pointer;color:#11665b}</style>"
        "<h1>Permission needs current evidence</h1>"
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
