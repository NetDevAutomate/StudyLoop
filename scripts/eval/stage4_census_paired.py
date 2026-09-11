"""Stage 4 gate G3: the self-retrieval census, paired, hybrid against lexical.

Both arms run on the SAME database file (freeze guardrail 6) over the same
eligible questions, each question's own message excluded at query time. The
paired delta of hit@k is bootstrapped with the session as the cluster (10,000
resamples, seed 20260910, percentile CI95); G3 holds when the CI95 lower
bound is at least the pre-registered margin (-0.01). Receipts record message
ids and outcomes, never learner text.

Usage:
    uv run --group dev python scripts/eval/stage4_census_paired.py \
        --db <clone>/sessions.db --out-dir <receipt dir> --tag minilm
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

from agent_session_tools.eval import SEED, K
from agent_session_tools.eval.arms import _git_head, build_arm
from agent_session_tools.eval.census import (
    CensusResult,
    census_receipt,
    collect_questions,
    run_census,
)
from agent_session_tools.eval.receipt import write_receipt

MARGIN = -0.01
RESAMPLES = 10_000


def paired_delta(a: CensusResult, b: CensusResult, *, untied_only: bool) -> dict[str, object]:
    """Cluster bootstrap (cluster = session) of mean(hit_a - hit_b) over questions."""
    b_rows = {row.message_id: row for row in b.rows}
    by_session: defaultdict[str, list[float]] = defaultdict(list)
    n = 0
    for row in a.rows:
        other = b_rows[row.message_id]
        if untied_only and row.tied:
            continue
        by_session[row.session_id].append(float(row.hit) - float(other.hit))
        n += 1
    sessions = sorted(by_session)

    def mean_of(sample: list[str]) -> float:
        total = sum(sum(by_session[s]) for s in sample)
        count = sum(len(by_session[s]) for s in sample)
        return total / count if count else 0.0

    point = mean_of(sessions)
    rng = random.Random(SEED)  # nosec B311 - statistical bootstrap
    draws = sorted(mean_of(rng.choices(sessions, k=len(sessions))) for _ in range(RESAMPLES))
    lower = draws[int(0.025 * RESAMPLES)]
    upper = draws[max(int(0.975 * RESAMPLES) - 1, 0)]
    return {
        "questions": n,
        "clusters": len(sessions),
        "point": point,
        "ci95": [lower, upper],
        "margin": MARGIN,
        "non_inferior": lower >= MARGIN,
        "resamples": RESAMPLES,
        "seed": SEED,
        "untied_only": untied_only,
    }


def transitions(a: CensusResult, b: CensusResult) -> dict[str, int]:
    b_rows = {row.message_id: row for row in b.rows}
    counts = {"both_hit": 0, "a_only": 0, "b_only": 0, "neither": 0}
    for row in a.rows:
        other = b_rows[row.message_id]
        key = (
            "both_hit"
            if row.hit and other.hit
            else "a_only"
            if row.hit
            else "b_only"
            if other.hit
            else "neither"
        )
        counts[key] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--tag", required=True, help="model tag for the receipt names")
    parser.add_argument("--arm-a", default="hybrid")
    parser.add_argument("--arm-b", default="mcp")
    parser.add_argument("--k", type=int, default=K)
    parser.add_argument("--rows", type=int, default=4 * K)
    parser.add_argument("--sample", type=int, default=None)
    args = parser.parse_args(argv)

    db_path = Path(args.db).expanduser()
    out_dir = Path(args.out_dir)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    questions = collect_questions(conn, k=args.k, sample=args.sample, seed=SEED)
    print(f"{len(questions)} eligible questions", file=sys.stderr)

    results: dict[str, CensusResult] = {}
    for name in (args.arm_b, args.arm_a):
        arm = build_arm(name, db_path, args.rows)
        started = time.monotonic()
        results[name] = run_census(conn, arm, questions, args.k)
        elapsed = time.monotonic() - started
        receipt = census_receipt(results[name], db_path=db_path, arm_describe=arm.describe())
        path = write_receipt(out_dir / f"stage4-census-{args.tag}-{name}.json", receipt)
        print(
            f"{name}: hit@{args.k} {results[name].hit_rate:.4f} in {elapsed:.0f}s -> {path}",
            file=sys.stderr,
        )

    a, b = results[args.arm_a], results[args.arm_b]
    paired = {
        "schema": "studyloop.stage4-census-paired/v1",
        "git_commit": _git_head(),
        "database": str(db_path),
        "tag": args.tag,
        "arms": {"a": args.arm_a, "b": args.arm_b},
        "k": args.k,
        "hit_rate": {args.arm_a: a.hit_rate, args.arm_b: b.hit_rate},
        "all_questions": paired_delta(a, b, untied_only=False),
        "untied_questions": paired_delta(a, b, untied_only=True),
        "transitions": transitions(a, b),
    }
    path = out_dir / f"stage4-census-{args.tag}-paired.json"
    path.write_text(json.dumps(paired, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: paired[k] for k in ("hit_rate", "all_questions", "transitions")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
