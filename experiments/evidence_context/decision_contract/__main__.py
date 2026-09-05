import argparse
from pathlib import Path

from .runner import prepare, run_live

parser = argparse.ArgumentParser(
    description="Stage 8: offline reference walkthrough; --live makes 16 calls"
)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--live", action="store_true")
args = parser.parse_args()
frozen = prepare(args.output)
print(f"Prepared eight synthetic examples: {args.output / 'walkthrough.html'}")
if args.live:
    report = run_live(args.output, frozen)
    for arm in ("legacy", "contract"):
        rows = [r for r in report["rows"] if r["arm"] == arm]
        print(f"{arm}: {sum(r.get('choice_matches', False) for r in rows)}/8 choice matches")
print("Synthetic contract probe only; not semantic correctness or learner usefulness.")
