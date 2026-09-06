"""Render actual installed CLI/SSH large-scope outcomes as five learning views."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from ..assertion_gate.viewer import block, escape


def render(data):
    sections = [
        (
            "1 · Let history grow",
            "runtime",
            "The fixture exports thousands of messages through the actual Codex native "
            "exporter. The standalone installed memory package owns the database and sync command.",
        ),
        (
            "2 · Move bytes without splitting meaning",
            "first_transfer",
            "The CLI chooses staged streaming when a complete scope exceeds the small-snapshot "
            "bound. Ordered row frames rebuild a complete private projection; the final hash, "
            "dependencies and scope are checked before one canonical transaction commits.",
        ),
        (
            "3 · Recover or skip",
            "unchanged_retry",
            "A committed receipt records receiver state. An unchanged retry sends no body. "
            "Partial staging is disposable and is not a receipt; interrupted incomplete "
            "streams currently restart.",
        ),
        (
            "4 · Withdraw, then restore fresh content",
            "permissions",
            "Every chunk checks current endpoint policy and control state. Regrant still "
            "requires complete fresh coverage, including retained dependencies. A frame "
            "acknowledgement means staged, not committed.",
        ),
        (
            "5 · Forget in either direction",
            "reverse_retirement",
            "A push also reconciles receiver retirement. Both copies of the fictional source "
            "are removed before any new body is considered. Full-store and managed restore "
            "remain separate required work.",
        ),
    ]
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Stage39 · Larger histories with complete evidence</title><style>"
        "body{font:18px/1.6 system-ui;max-width:950px;margin:3rem auto;padding:0 1rem;"
        "background:#faf9f5;color:#24363b}section{margin:2rem 0;border-top:2px solid #cbded5}"
        "pre{font:14px/1.5 monospace;white-space:pre-wrap;overflow-wrap:anywhere}"
        "summary{cursor:pointer;color:#11665b}</style><h1>Larger histories, complete evidence</h1>"
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
        + "<h2>Checks and remaining limits</h2>"
        + block(data["checks"])
        + "<p>"
        + escape(data["limits"])
        + "</p>"
        + "<p>Current staged scope bounds: 1 GiB encoded, one million rows, 8 MiB raw per "
        "source row and 32 MiB encoded per staged row. Connection bounds and deadlines also "
        "apply. Metadata validation retains some sets of IDs; row deltas and resumable "
        "incomplete streams remain open.</p></html>"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--require-installed", action="store_true")
    parser.add_argument("--messages", type=int, default=2300)
    args = parser.parse_args()
    command = [
        str(args.python),
        "-I",
        str(Path(__file__).with_name("probe.py")),
        "--output",
        str(args.output.resolve()),
        "--messages",
        str(args.messages),
    ]
    if args.require_installed:
        command.append("--require-installed")
    result = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    data = json.loads((args.output / "results.json").read_text())
    (args.output / "walkthrough.html").write_text(render(data))
    print(result.stdout.strip())


if __name__ == "__main__":
    main()
