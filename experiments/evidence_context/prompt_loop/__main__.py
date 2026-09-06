import argparse
from pathlib import Path

from .runner import run

parser = argparse.ArgumentParser(
    description="Stage 7: scripted offline by default; --live calls providers"
)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--live", action="store_true", help="Use paid local gateway; maximum 18 calls")
args = parser.parse_args()
report = run(args.output, live=args.live)
print(f"{report['manifest']['mode']}: {report['calls']} calls; selected {report['winner']['id']}")
print("Development proxy only. No independent holdout or production promotion.")
