"""Run with python -m experiments.evidence_context.lifecycle_demo --output NEW_DIR."""

from __future__ import annotations

import argparse
from pathlib import Path

from .lifecycle import Replica
from .store import canonical_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    a = Replica.create(args.output / "a.db")
    b = Replica.create(args.output / "b.db")
    scopes = {"personal"}
    try:
        original = a.add("demo-decision", "personal", "Use the old policy", "2026-01-01T00:00:00Z")
        b.receive(a.export(scopes), scopes)
        stale = b.export(scopes)
        a.add(
            "demo-decision",
            "personal",
            "Use the corrected policy",
            "2026-01-02T00:00:00Z",
            original,
            "The earlier policy omitted an observed constraint",
        )
        before = {
            "current": a.heads("demo-decision"),
            "earlier": a.heads("demo-decision", "2026-01-01T00:00:00Z"),
        }
        a.forget("demo-decision", "personal")
        a.receive(stale, scopes)
        b.receive(a.export(scopes), scopes)
        b.receive(stale, scopes)
        a.rebuild()
        b.rebuild()
        result = {
            "experiment": "synthetic lifecycle only",
            "before_forgetting": before,
            "after_forgetting": {
                "a_heads": a.heads("demo-decision"),
                "b_heads": b.heads("demo-decision"),
                "a_search": a.search("policy"),
                "b_search": b.search("policy"),
            },
            "converged": a.export(scopes) == b.export(scopes),
            "limits": (
                "Logical deletion only. This report retains synthetic pre-deletion text; "
                "it is not a managed cache."
            ),
        }
        (args.output / "summary.json").write_text(canonical_json(result) + "\n")
        print(canonical_json(result))
    finally:
        a.close()
        b.close()


if __name__ == "__main__":
    main()
