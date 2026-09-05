import argparse
from pathlib import Path

from .runner import prepare, run_live

parser = argparse.ArgumentParser(
    description="Stage 10: offline source-check demo; --live uses 64 calls"
)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--live", action="store_true")
args = parser.parse_args()
frozen = prepare(args.output)
print(f"Source-check walkthrough: {args.output / 'walkthrough.html'}")
if args.live:
    report = run_live(args.output, frozen)
    for arm in ("raw", "extracted", "candidate", "checked"):
        rows = [r for r in report["rows"] if r["arm"] == arm]
        print(
            f"{arm}: {sum(r['checks']['choice_matches'] for r in rows)}/{len(rows)} choice matches"
        )
print("Log correspondence only; source authenticity and answer usefulness are not established.")
