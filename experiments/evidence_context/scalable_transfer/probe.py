"""Reuse the isolated SSH lifecycle fixture with a large actual native archive."""

import argparse
import runpy
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-installed", action="store_true")
    parser.add_argument("--messages", type=int, default=2300)
    args = parser.parse_args()
    if not 1500 <= args.messages <= 5000:
        parser.error("Use 1500 to 5000 fictional native messages for this large-scope lesson")
    fixture = runpy.run_path(str(Path(__file__).parents[1] / "configured_sync" / "probe.py"))
    fixture["run"](args.output.resolve(), args.require_installed, large_messages=args.messages)


if __name__ == "__main__":
    main()
