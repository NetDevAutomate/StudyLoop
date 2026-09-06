"""Opt-in local CLI retrieval probe; retain aggregates, never source bodies.

Uses Stage22's read-only, bounded archive selection and temporary capture store.
The fixed queries exercise the public retrieval contract, not semantic usefulness.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from ..native_capture.audit_local import audit

QUERIES = ("SQLite", "validation", "session sync", "scope", "test", "context")


def inspect_context(conn):
    from agent_session_tools.context.scope import active_policy, apply_policy

    apply_policy(conn, active_policy(), actor="local-evaluation", dry_run=False)
    db = conn.execute("PRAGMA database_list").fetchone()[2]
    environment = {**os.environ, "SESSION_CONTEXT_SCOPE": "unclassified"}
    rows = []
    selected = set()
    for query in QUERIES:
        before = time.perf_counter()
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_session_tools.context.cli",
                "search",
                query,
                "--db",
                db,
                "--max-sources",
                "12",
                "--budget-bytes",
                "32768",
            ],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        elapsed = time.perf_counter() - before
        pack = json.loads(completed.stdout)
        assert len(completed.stdout.rstrip("\n").encode()) == pack["response_bytes"]
        assert pack["response_bytes"] <= 32768
        for source in pack["sources"]:
            body, digest = conn.execute(
                "SELECT body,body_sha256 FROM context_evidence WHERE id=?", (source["id"],)
            ).fetchone()
            citation = source["citation"]
            assert hashlib.sha256(body.encode()).hexdigest() == digest
            assert digest == source["body_sha256"] == citation["body_sha256"]
            assert body[citation["start"] : citation["end"]] == citation["quote"]
            assert source["why_selected"]["method"] == "lexical_match"
            selected.add(source["id"])
        rows.append(
            {
                "query": query,
                "sources": len(pack["sources"]),
                "verified_citations": len(pack["sources"]),
                "response_bytes": pack["response_bytes"],
                "cli_wall_seconds": round(elapsed, 4),
                "harness_counts": dict(Counter(s["harness"] for s in pack["sources"])),
                "origin_counts": dict(Counter(s["origin"] for s in pack["sources"])),
                "known_revision_count": sum(s["revision"] is not None for s in pack["sources"]),
                "limits_reached": pack["coverage"]["limits_reached"],
                "hook_liveness": pack["capture_health"]["hook_liveness"],
            }
        )
    return {
        "queries": rows,
        "unique_selected_sources": len(selected),
        "contract": "actual session-context subprocess; exact full source bindings and offsets",
        "scope": "temporary explicit unclassified policy; owner policy is unchanged",
        "semantic_relevance_or_answer_accuracy": "not_measured",
        "cross_harness_recall": "not_established_by_lexical_top_k",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=2, choices=range(1, 6))
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a fresh report path")
    report = audit(args.limit, inspect=inspect_context)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps({"output": str(args.output), "context_probe": report["context_probe"]}))


if __name__ == "__main__":
    main()
