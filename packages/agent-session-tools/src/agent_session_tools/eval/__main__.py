"""``python -m agent_session_tools.eval`` -- run a ruler and write its receipt.

    python -m agent_session_tools.eval gold \
        --db ~/.config/studyloop/sessions.db \
        --arms mcp,cli,frozen --rows 10 --out receipt.json

Every arm answers every gold question in the same run against the same
database, then each ordered pair is compared with the paired cluster
bootstrap. Nothing is written to the database: the arms read it read-only.
"""

from __future__ import annotations

import argparse
import sys
from itertools import permutations
from pathlib import Path
from typing import Any

from . import K, SEED
from .arms import ARMS, DEFAULT_ROWS, build_arm
from .census import census_receipt, collect_questions, run_census
from .gold import load_gold, score_arm
from .metrics import cluster_bootstrap, non_inferiority
from .receipt import build_receipt, write_receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agent_session_tools.eval",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="ruler", required=True)
    gold = sub.add_parser("gold", help="score arms against the gold DEV set")
    gold.add_argument(
        "--db",
        default="~/.config/studyloop/sessions.db",
        help="session database to read (read-only)",
    )
    gold.add_argument(
        "--arms",
        default="mcp,frozen",
        help=f"comma-separated arm names ({', '.join(sorted(ARMS))})",
    )
    gold.add_argument(
        "--rows",
        type=int,
        default=DEFAULT_ROWS,
        help="message-row limit each arm requests before sessions are collapsed",
    )
    gold.add_argument("--out", required=True, help="receipt path to write")
    gold.add_argument(
        "--gold", dest="gold_path", help="gold json (default: the in-repo DEV set)"
    )
    gold.add_argument("--k", type=int, default=K, help=f"rank cut-off (default {K})")

    census = sub.add_parser(
        "census",
        help="paraphrase census: every learner turn is a question about its own session",
    )
    census.add_argument(
        "--db", default="~/.config/studyloop/sessions.db", help="session database"
    )
    census.add_argument(
        "--arm", default="mcp", help=f"one arm name ({', '.join(sorted(ARMS))})"
    )
    census.add_argument(
        "--rows",
        type=int,
        default=4 * K,
        help="message rows the arm requests; the census excludes the question's own row",
    )
    census.add_argument("--out", required=True, help="receipt path to write")
    census.add_argument("--k", type=int, default=K, help=f"rank cut-off (default {K})")
    census.add_argument(
        "--sample", type=int, help="score a deterministic sample of N questions"
    )
    census.add_argument("--seed", type=int, default=SEED, help="sample seed")
    return parser


def _run_gold(args: argparse.Namespace) -> int:
    db_path = Path(args.db).expanduser()
    if not db_path.exists():
        print(f"no database at {db_path}", file=sys.stderr)
        return 2
    gold = load_gold(Path(args.gold_path) if args.gold_path else None)
    items = list(gold.items)
    names = [name.strip() for name in args.arms.split(",") if name.strip()]

    results = {}
    for name in names:
        arm = build_arm(name, db_path, args.rows)
        results[name] = score_arm(arm, items, args.k)

    comparisons: dict[str, Any] = {}
    for a, b in permutations(names, 2):
        comparisons[f"{a}_vs_{b}"] = cluster_bootstrap(
            results[a].per_item, results[b].per_item, items
        )
        # Stage 4 gate G2 / freeze guardrail 5: the exact-match (K) stratum on
        # its own, so a semantic arm cannot buy paraphrase recall with keyword
        # regressions hidden inside the macro.
        comparisons[f"{a}_vs_{b}_K"] = non_inferiority(
            results[a].per_item, results[b].per_item, items, margin=0.0, stratum="K"
        )

    from .arms import _git_head

    receipt = build_receipt(
        db_path=db_path,
        gold=gold,
        results=results,
        comparisons=comparisons,
        git_commit=_git_head(),
    )
    out = write_receipt(args.out, receipt)

    for name, result in results.items():
        recall = result.recall
        strata = "  ".join(f"{s} {v:.3f}" for s, v in recall["by_stratum"].items())
        kinds = (
            ", ".join(f"{k}={n}" for k, n in result.errors_by_kind.items()) or "none"
        )
        print(
            f"{name:>8}  macro recall@{args.k} {recall['macro']:.4f}  {strata}"
            f"  MRR {result.mrr['macro']:.4f}"
            f"  crashes {result.crashes}/{gold.n} ({kinds})"
            f"  p50 {result.latency_ms['p50']:.1f} ms  p95 {result.latency_ms['p95']:.1f} ms"
        )
    for pair, stats in comparisons.items():
        low, high = stats["ci95"]
        print(
            f"{pair:>16}  delta macro {stats['point']:+.4f}"
            f"  CI95 [{low:+.4f}, {high:+.4f}]  established={stats['established']}"
        )
    print(f"metrics_sha256 {receipt['metrics_sha256']}")
    print(f"receipt -> {out}")
    return 0


def _run_census(args: argparse.Namespace) -> int:
    import sqlite3

    db_path = Path(args.db).expanduser()
    if not db_path.exists():
        print(f"no database at {db_path}", file=sys.stderr)
        return 2
    arm = build_arm(args.arm, db_path, args.rows)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        questions = collect_questions(
            conn, k=args.k, sample=args.sample, seed=args.seed
        )
        result = run_census(conn, arm, questions, k=args.k)
    finally:
        conn.close()
    receipt = census_receipt(result, db_path=db_path, arm_describe=arm.describe())
    out = write_receipt(args.out, receipt)
    crashes = ", ".join(f"{k}={n}" for k, n in result.crashes.items()) or "none"
    print(
        f"{result.arm:>8}  eligible {result.n_eligible}  tied {result.n_tied}"
        f"  untied-share {result.untied_share:.4f}  hit@{result.k} {result.hit_rate:.4f}"
        f"  hit-untied {result.hit_rate_untied:.4f}"
        f"  miss vocab {result.miss_vocab}  crash {result.miss_crash}  ranking {result.miss_ranking}"
        f" (untied {result.miss_ranking_untied})  crashes {crashes}"
        f"  {result.elapsed_seconds:.1f} s"
    )
    print(f"receipt -> {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.ruler == "gold":
        return _run_gold(args)
    if args.ruler == "census":
        return _run_census(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
