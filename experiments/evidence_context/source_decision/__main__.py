import argparse
from pathlib import Path

from .runner import prepare, replay, run_live

parser = argparse.ArgumentParser(
    description="Stage 11: offline source adapter; --live uses 24 calls"
)
parser.add_argument("--output", type=Path, required=True)
mode = parser.add_mutually_exclusive_group()
mode.add_argument("--live", action="store_true")
mode.add_argument("--replay", type=Path)
args = parser.parse_args()
if args.replay:
    print(replay(args.replay, args.output))
else:
    frozen = prepare(args.output)
    print(f"Offline walkthrough: {args.output / 'walkthrough.html'}")
    if args.live:
        print(run_live(args.output, frozen)["summary"])
print("Synthetic policy conformance only; source authenticity and learner value are unmeasured.")
