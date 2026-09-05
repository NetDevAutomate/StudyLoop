"""Offline stage-5 evaluator. The bundled dataset is deliberately synthetic."""

import argparse
import json
from pathlib import Path

from .evaluate import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--dataset", type=Path, default=Path(__file__).with_name("synthetic.json"))
    parser.add_argument("--budget", type=int, default=8000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    report = run(
        json.loads(args.dataset.read_text(encoding="utf-8")), args.output, args.budget, args.seed
    )
    print(
        json.dumps(
            {
                "conclusion": report["conclusion"],
                "manifest": report["manifest"],
                "paired_differences": report["paired_differences"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
