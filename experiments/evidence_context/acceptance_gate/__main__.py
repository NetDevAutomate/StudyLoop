import argparse
from pathlib import Path

from .runner import prepare, run_live

parser = argparse.ArgumentParser(description="Stage 9: offline gate replay; --live makes 12 calls")
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--live", action="store_true")
args = parser.parse_args()
frozen = prepare(args.output)
print(f"Replay and offline probes: {args.output / 'walkthrough.html'}")
if args.live:
    report = run_live(args.output, frozen)
    for arm in ("prompt_only", "contract_copy_control"):
        rows = [r for r in report["rows"] if r["arm"] == arm]
        count = sum(r["gate"]["status"] == "draft_agrees" for r in rows)
        print(f"{arm}: {count}/6 drafts conform to the structured policy")
print("Release is policy-rendered. Source authenticity and model prose are not validated.")
