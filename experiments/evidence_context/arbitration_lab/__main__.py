"""Stage 6 prepares offline by default. --live makes 12 bounded provider calls."""

import argparse
import json
from pathlib import Path

from .runner import prepare, run_live


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", default="qwen3-coder")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--prompt-version", choices=["v1", "v2"], default="v1")
    args = parser.parse_args()
    frozen = prepare(args.output, args.model, prompt_version=args.prompt_version)
    if args.live:
        report = run_live(args.output, frozen)
        print(
            json.dumps(
                {
                    "model": report["model"],
                    "parsed": sum(r["status"] == "parsed" for r in report["results"]),
                    "requests": len(report["results"]),
                    "report": str(args.output / "answers.md"),
                }
            )
        )
    else:
        print(
            "Prepared 12 synthetic requests without model calls. "
            "Inspect prompt.md and blind-review-input.json."
        )


if __name__ == "__main__":
    main()
