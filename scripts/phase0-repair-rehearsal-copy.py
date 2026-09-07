from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    live = (Path.home() / ".config/studyloop/sessions.db").resolve()
    if args.source.resolve() == live:
        raise SystemExit("Refusing the live sessions.db; use the approved pre-fix .bak")
    if args.destination.exists():
        raise SystemExit(f"exists: {args.destination}")
    source_uri = f"file:{args.source.resolve()}?mode=ro"
    with (
        sqlite3.connect(source_uri, uri=True) as src,
        sqlite3.connect(args.destination) as dst,
    ):
        src.backup(dst)


if __name__ == "__main__":
    main()
