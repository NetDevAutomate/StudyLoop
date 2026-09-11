#!/usr/bin/env python3
"""Attribute a census delta to the planner change: score only the changed-plan questions.

Given a plan-diff receipt (``stage2_plan_diff.py compare``), run exactly the census
questions whose plan changed through the real MCP arm with the census's own exclusion
policy, under the planner of the tree this script is imported from, and write one row
per question (own-session hit, rank). Run once with ``PYTHONPATH`` pointing at a worktree
of the receipts' commit and once at HEAD, then ``compare``. Read-only against the DB.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def score(db: Path, plan_diff: Path, out: Path, rows: int) -> None:
    from agent_session_tools import retrieval
    from agent_session_tools.eval.arms import McpArm
    from agent_session_tools.eval.census import collect_questions, run_census

    changed = {c["id"] for c in json.loads(plan_diff.read_text())["sets"]["census"]["changed"]}
    conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        questions = [q for q in collect_questions(conn) if q.message_id in changed]
        result = run_census(conn, McpArm(db, rows=rows), questions)
    finally:
        conn.close()
    payload = {
        "schema": "studyloop.census-attribution/v1",
        "planner_path": retrieval.__file__,
        "n": len(questions),
        "rows": {
            r.message_id: {
                "hit": r.hit,
                "rank": r.rank,
                "miss_class": r.miss_class,
                "source": r.source,
                "tied": r.tied,
            }
            for r in result.rows
        },
    }
    out.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(questions)} questions scored -> {out}")


def compare(before: Path, after: Path, out: Path) -> None:
    a = json.loads(before.read_text())["rows"]
    b = json.loads(after.read_text())["rows"]
    changed = [
        {"id": i, "before": a[i], "after": b[i]}
        for i in sorted(set(a) & set(b))
        if a[i]["hit"] != b[i]["hit"] or a[i]["rank"] != b[i]["rank"]
    ]
    receipt = {
        "schema": "studyloop.census-attribution/v1",
        "n_questions": len(set(a) & set(b)),
        "hits_before": sum(1 for i in a if a[i]["hit"]),
        "hits_after": sum(1 for i in b if b[i]["hit"]),
        "n_outcome_changed": len(changed),
        "changed": changed,
    }
    out.write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"{receipt['n_questions']} questions: hits {receipt['hits_before']} -> "
        f"{receipt['hits_after']}, outcome changed on {len(changed)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score")
    s.add_argument("--db", type=Path, required=True)
    s.add_argument("--plan-diff", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--rows", type=int, default=20)
    c = sub.add_parser("compare")
    c.add_argument("before", type=Path)
    c.add_argument("after", type=Path)
    c.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.cmd == "score":
        score(args.db, args.plan_diff, args.out, args.rows)
    else:
        compare(args.before, args.after, args.out)


if __name__ == "__main__":
    main()
