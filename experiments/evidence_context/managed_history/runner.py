"""Five-view walkthrough of actual installed managed-history lifecycle results."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from ..assertion_gate.viewer import block, escape


def render(data):
    views = [
        (
            "1 · Preserve useful archive history",
            "archive_read",
            "Verified hot pruning keeps the full native source. Search can still retrieve "
            "that permitted archive-only conversation while excluding work history.",
        ),
        (
            "2 · Current intent governs both copies",
            "permanent_forgetting",
            "An archive-only source can be selected without returning its body. Permanent "
            "intent commits in canonical storage before the archive cleanup is acknowledged.",
        ),
        (
            "3 · Offline means pending",
            "offline_recovery",
            "Returning an old archive does not make forgotten material visible. Cleanup "
            "retries apply retained intent, purge dependent records and compact managed files.",
        ),
        (
            "4 · Native replay remains suppressed",
            "reimport",
            "The original fictional native files remain intact. Exporting them again does "
            "not recreate the retired sessions or their derived report.",
        ),
        (
            "5 · Inspect what actually ran",
            "runtime",
            "The installed probe uses the standalone package and actual console commands. "
            "This checkpoint does not claim completed managed restore or full product readiness.",
        ),
    ]
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Stage40 · Current intent, older copies</title><style>"
        "body{font:18px/1.6 system-ui;max-width:950px;margin:3rem auto;padding:0 1rem;"
        "background:#faf9f5;color:#24363b}section{margin:2rem 0;border-top:2px solid #cbded5}"
        "pre{font:14px/1.5 monospace;white-space:pre-wrap;overflow-wrap:anywhere}"
        "summary{cursor:pointer;color:#11665b}</style><h1>Current intent, older copies</h1>"
        + "".join(
            "<section><h2>"
            + escape(title)
            + "</h2><p>"
            + escape(prose)
            + "</p><details><summary>Inspect the observed result</summary>"
            + block(data[key])
            + "</details></section>"
            for title, key, prose in views
        )
        + "<h2>Checks and limits</h2>"
        + block(data["checks"])
        + "<p>"
        + escape(data["limits"])
        + "</p></html>"
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
