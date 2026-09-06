"""Render the actual CLI quarantine recovery journey in five inspectable steps."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from ..assertion_gate.viewer import block, escape


def render(data):
    sections = [
        (
            "1 · A retained local addition",
            "quarantined",
            "The receiver keeps two messages hidden because one was never supplied by the sender.",
        ),
        (
            "2 · Inspect the exact consequence",
            "preview",
            "The CLI lists withheld IDs and produces a body-free preview. Its digest binds "
            "the affected versions, scope, database and permission state.",
        ),
        (
            "3 · Refuse implicit or stale approval",
            "refusal",
            "The command requires acknowledgement of local additions. A regrant changes "
            "the state and invalidates the earlier preview.",
        ),
        (
            "4 · Deliberately discard this copy",
            "discard",
            "The operator approves the fresh plan. The complete local copy is removed, "
            "including its extra message. Denials remain and no permanent forgetting is broadcast.",
        ),
        (
            "5 · Fresh transfer and historical retry",
            "recovery",
            "A permitted new transfer restores the sender's copy. Repeating the old discard "
            "command returns its receipt without deleting the new content.",
        ),
    ]
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Stage37 · Deliberate quarantine recovery</title><style>"
        "body{font:18px/1.6 system-ui;max-width:950px;margin:3rem auto;padding:0 1rem;"
        "background:#faf9f5;color:#24363b}section{margin:2rem 0;border-top:2px solid #cbded5}"
        "pre{font:14px/1.5 monospace;white-space:pre-wrap;overflow-wrap:anywhere}"
        "summary{cursor:pointer;color:#11665b}</style><h1>A decision about this local copy</h1>"
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
    result = subprocess.run(command, text=True, capture_output=True, timeout=120)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    data = json.loads((args.output / "results.json").read_text())
    (args.output / "walkthrough.html").write_text(render(data))
    print(result.stdout.strip())


if __name__ == "__main__":
    main()
