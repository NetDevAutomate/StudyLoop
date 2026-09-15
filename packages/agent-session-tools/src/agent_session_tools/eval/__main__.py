"""``python -m agent_session_tools.eval`` -- run a ruler and write its receipt.

    python -m agent_session_tools.eval gold \
        --db ~/.config/studyloop/sessions.db \
        --arms mcp,cli,frozen --rows 10 --out receipt.json

Every arm answers every gold question in the same run against the same
database, then each ordered pair is compared with the paired cluster
bootstrap. Nothing is written to the database: the arms read it read-only.

``stage5-latency`` is the third door -- Stage 5's Gate L measurement runner
(:mod:`.stage5_latency`), which launches independent process starts instead of
scoring one:

    python -m agent_session_tools.eval stage5-latency \
        --db ~/.local/share/studyloop/eval-clones/bakeoff-bge-20260915/sessions.db \
        --out receipt.json

``lexical-verdict`` (§5 stream, council D-12) judges a gold receipt that carries
the planner-variant arms (``--arms mcp,mcp:and_then_prose_or,...``) by the
pre-registered clauses in :mod:`.lexical` and writes the committed form:

    python -m agent_session_tools.eval lexical-verdict \
        --receipt raw.json --candidate mcp:and_then_prose_or --control mcp \
        --out docs/architecture/session-memory/receipts/lexical/or-fallback-dev-2026-09-15.json
"""

from __future__ import annotations

import argparse
import sys
from itertools import permutations
from pathlib import Path
from typing import Any

from . import K, SEED
from .arms import ARMS, DEFAULT_ROWS, PLANNERS, build_arm
from .census import census_receipt, collect_questions, run_census
from .gold import load_gold, score_arm
from .metrics import (
    cluster_bootstrap,
    non_inferiority,
    paired_cluster_bootstrap,
    precision_values,
)
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
        help=(
            f"comma-separated arm names ({', '.join(sorted(ARMS))}); "
            f"<arm>:<planner> selects a planner variant ({', '.join(PLANNERS)}) "
            "on an in-process arm"
        ),
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

    # Stage 5 Gate L is a measurement runner rather than a ruler, but it is
    # invoked the same way as one so there is a single door into the harness.
    # Its own module keeps a lean ``child`` entry point (one start = one fresh
    # interpreter), which this parser deliberately does not expose: a child is
    # launched by the parent, never by hand.
    from .stage5_latency import add_parent_arguments

    add_parent_arguments(
        sub.add_parser(
            "stage5-latency",
            help="Gate L: resident-state latency for the mcp/web default flip",
        )
    )

    # §5 stream: the adopt/reject verdict, computed from a gold receipt by the
    # frozen clauses in ``eval/lexical.py`` and written as the committed form.
    from .lexical import DEFAULT_CANDIDATE, DEFAULT_CONTROL

    verdict = sub.add_parser(
        "lexical-verdict",
        help="§5: judge the prose-OR widen candidate from a gold receipt (D-12 clauses)",
    )
    verdict.add_argument("--receipt", required=True, help="raw gold receipt to judge")
    verdict.add_argument(
        "--candidate", default=DEFAULT_CANDIDATE, help="candidate arm name"
    )
    verdict.add_argument("--control", default=DEFAULT_CONTROL, help="control arm name")
    verdict.add_argument("--k", type=int, default=K, help=f"rank cut-off (default {K})")
    verdict.add_argument(
        "--out", required=True, help="committed receipt to write (digests prefixed)"
    )
    return parser


def _format_comparison(pair: str, stats: dict) -> str:
    """One console line per comparison, speaking EVERY receipt shape.

    Delta comparisons carry a ``ci95`` pair and either ``established`` (the
    recall lift rule) or ``lower_above_zero`` (the §5 value bootstraps); the K
    non-inferiority entry carries ``ci95_upper``/``upper_at_least_zero``
    instead (Stage 4 addendum, astra 5 / kimi 1). The 2026-09-15 SEALED run
    proved the printer must never assume one shape: it crashed AFTER the
    receipt was written, on the first two-arm run that reached the K entry.
    """
    if "ci95" in stats:
        low, high = stats["ci95"]
        verdict = (
            f"established={stats['established']}"
            if "established" in stats
            else f"lower_above_zero={stats['lower_above_zero']}"
        )
        return (
            f"{pair:>48}  delta macro {stats['point']:+.4f}"
            f"  CI95 [{low:+.4f}, {high:+.4f}]  {verdict}"
        )
    return (
        f"{pair:>48}  delta {stats.get('stratum', '?')} {stats['point']:+.4f}"
        f"  CI95 upper {stats['ci95_upper']:+.4f}"
        f"  upper_at_least_zero={stats['upper_at_least_zero']}"
    )


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
        # §5 guardrails (pre-registration 2026-09-15): precision@K and MRR@K
        # paired the same way, so a widen step that buys recall with junk
        # rows is visible as a precision interval, not a footnote.
        comparisons[f"{a}_vs_{b}_precision"] = paired_cluster_bootstrap(
            precision_values(results[a].per_item, items, args.k),
            precision_values(results[b].per_item, items, args.k),
            items,
        )
        comparisons[f"{a}_vs_{b}_mrr"] = paired_cluster_bootstrap(
            {i: s.rr for i, s in results[a].per_item.items()},
            {i: s.rr for i, s in results[b].per_item.items()},
            items,
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
            f"{name:>24}  macro recall@{args.k} {recall['macro']:.4f}  {strata}"
            f"  P@{args.k} {result.precision['macro']:.4f}"
            f"  MRR {result.mrr['macro']:.4f}"
            f"  crashes {result.crashes}/{gold.n} ({kinds})"
            f"  p50 {result.latency_ms['p50']:.1f} ms  p95 {result.latency_ms['p95']:.1f} ms"
        )
    for pair, stats in comparisons.items():
        print(_format_comparison(pair, stats))
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


def _run_lexical_verdict(args: argparse.Namespace) -> int:
    import json

    from .lexical import derive_receipt, format_verdict, judge

    raw_path = Path(args.receipt).expanduser()
    raw_bytes = raw_path.read_bytes()
    raw = json.loads(raw_bytes)
    verdict = judge(raw, candidate=args.candidate, control=args.control, k=args.k)
    derived = derive_receipt(raw, raw_bytes, verdict, raw_path=str(raw_path))
    out = write_receipt(args.out, derived)
    print(format_verdict(verdict))
    print(f"receipt -> {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.ruler == "gold":
        return _run_gold(args)
    if args.ruler == "census":
        return _run_census(args)
    if args.ruler == "stage5-latency":
        from .stage5_latency import run_parent

        return run_parent(args)
    if args.ruler == "lexical-verdict":
        return _run_lexical_verdict(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
