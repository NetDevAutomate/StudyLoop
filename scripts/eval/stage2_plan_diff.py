#!/usr/bin/env python3
"""Plan-level diff of the lexical planner across two trees, over the two question sets.

The Stage 2 escalation council asked for the check the record had only sketched:
"compare old/new plans for BOTH complete query sets, not selected textual patterns."
``dump`` writes, for every eligible census question (the full population the census
receipt scored) and every gold DEV item, exactly what :func:`retrieval.plan_query`
returns under the planner of the tree it runs in; ``compare`` lists every id whose
plan differs between two dumps. Run ``dump`` once per tree (a worktree at the older
commit, then HEAD) and ``compare`` the two files. Read-only against the DB.

    uv run python scripts/eval/stage2_plan_diff.py dump --db <sessions.db> --out A.json
    uv run python scripts/eval/stage2_plan_diff.py compare A.json B.json --out receipt.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
from dataclasses import asdict
from pathlib import Path


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


def dump(db: Path, out: Path) -> None:
    from agent_session_tools import retrieval
    from agent_session_tools.eval.census import collect_questions
    from agent_session_tools.eval.gold import load_gold

    conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        questions = collect_questions(conn)
    finally:
        conn.close()
    gold = load_gold()
    planner_path = Path(retrieval.__file__)
    planner_source = planner_path.read_bytes()
    tree = str(planner_path.parent)  # the tree the planner was imported from, not the caller's
    payload = {
        "schema": "studyloop.plan-dump/v1",
        "planner_path": str(planner_path),
        "git_commit": _git("-C", tree, "rev-parse", "HEAD"),
        "tree_dirty": bool(_git("-C", tree, "status", "--porcelain", "--", ".")),
        "planner_sha256": hashlib.sha256(planner_source).hexdigest(),
        "db": str(db),
        "census": {
            q.message_id: {"text": q.text, "plan": asdict(retrieval.plan_query(q.text))}
            for q in questions
        },
        "gold": {
            item["id"]: {
                "text": item["question"],
                "plan": asdict(retrieval.plan_query(item["question"])),
            }
            for item in gold.items
        },
    }
    out.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"census {len(payload['census'])} · gold {len(payload['gold'])} → {out}")


def compare(before: Path, after: Path, out: Path) -> None:
    a = json.loads(before.read_text(encoding="utf-8"))
    b = json.loads(after.read_text(encoding="utf-8"))
    receipt: dict = {
        "schema": "studyloop.plan-diff/v1",
        "before": {k: a[k] for k in ("git_commit", "tree_dirty", "planner_sha256")},
        "after": {k: b[k] for k in ("git_commit", "tree_dirty", "planner_sha256")},
        "sets": {},
    }
    for name in ("census", "gold"):
        ids_a, ids_b = set(a[name]), set(b[name])
        common = sorted(ids_a & ids_b)
        changed = [i for i in common if a[name][i]["plan"] != b[name][i]["plan"]]
        receipt["sets"][name] = {
            "n_before": len(ids_a),
            "n_after": len(ids_b),
            "n_common": len(common),
            "n_changed": len(changed),
            "changed": [
                {
                    "id": i,
                    "text": b[name][i]["text"],
                    "before": a[name][i]["plan"],
                    "after": b[name][i]["plan"],
                }
                for i in changed
            ],
        }
    out.write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for name, s in receipt["sets"].items():
        print(f"{name}: {s['n_changed']} of {s['n_common']} plans changed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("--db", type=Path, required=True)
    d.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("compare")
    c.add_argument("before", type=Path)
    c.add_argument("after", type=Path)
    c.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.cmd == "dump":
        dump(args.db, args.out)
    else:
        compare(args.before, args.after, args.out)


if __name__ == "__main__":
    main()
