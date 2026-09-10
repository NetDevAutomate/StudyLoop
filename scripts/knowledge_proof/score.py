"""Knowledge-layer proof harness: score retrieval arms against gold v2.

Arm contract (pre-registered; see docs/architecture/session-memory/validation-ruler.md):
  * An arm maps a question to an ORDERED list of DISTINCT session ids.
  * recall@5 for a question = 1 if any gold session id is among the first five, else 0.
  * MRR@5 = 1/rank of the first gold session within the first five, else 0 (reported, never gated).
  * Every arm answers every question in the same run on the same database snapshot.

Arms in this file:
  B0  shipped FTS5 path, code pinned at the build base (imported from a detached
      worktree so later planner changes cannot move the control).
  B1  the same shipped path from the code under test (this checkout).
Feature arms register themselves via ``ARMS`` from their own modules.

Statistics: cluster bootstrap (resample gold clusters with replacement, 10,000
draws, fixed seed) of the paired per-question hit difference; 95 % percentile
interval; "established lift" = lower bound >= +0.05. Macro-average over strata.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import importlib
import json
import pathlib
import random
import sqlite3
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Callable, Iterable

Arm = Callable[[sqlite3.Connection, str], list[str]]

RESAMPLES = 10_000
SEED = 20260910
MIN_LIFT = 0.05
K = 5


# --------------------------------------------------------------------------- shipped path
def _shipped_fts_arm(pkg_src: pathlib.Path | None) -> Arm:
    """Build the shipped session_search ranking as a session-id arm.

    Mirrors ``mcp_server.session_search`` exactly: AND query then OR fallback via
    ``query_planner.plan``, ``bm25(messages_fts)`` ranking, scope visibility,
    LIMIT applied to MESSAGE rows -- so we over-fetch and take distinct sessions.
    """
    if pkg_src is not None:
        sys.path.insert(0, str(pkg_src))
        for mod in list(sys.modules):
            if mod.startswith("agent_session_tools"):
                del sys.modules[mod]
    mcp_server = importlib.import_module("agent_session_tools.mcp_server")
    public = importlib.import_module("agent_session_tools.context.public")
    queries = mcp_server._session_search_queries
    visibility_sql = public.visibility_sql
    if pkg_src is not None:
        sys.path.pop(0)

    def arm(conn: sqlite3.Connection, question: str) -> list[str]:
        for fts_query in queries(question):
            visible, scope_params = visibility_sql(conn, "s.id")
            rows = conn.execute(
                "SELECT s.id FROM messages m JOIN sessions s ON m.session_id = s.id "
                "JOIN messages_fts ON messages_fts.rowid = m.rowid "
                f"WHERE messages_fts MATCH ? AND {visible} "
                "ORDER BY bm25(messages_fts), m.timestamp DESC LIMIT 200",
                [fts_query, *scope_params],
            ).fetchall()
            if rows:
                seen: list[str] = []
                for (sid,) in rows:
                    if sid not in seen:
                        seen.append(sid)
                    if len(seen) == K:
                        break
                return seen
        return []

    return arm


# --------------------------------------------------------------------------- scoring
def _hit(ranked: list[str], gold: set[str]) -> tuple[int, float]:
    for i, sid in enumerate(ranked[:K], start=1):
        if sid in gold:
            return 1, 1.0 / i
    return 0, 0.0


def score_arm(conn: sqlite3.Connection, arm: Arm, items: list[dict]) -> dict:
    per: dict[str, dict] = {}
    latencies: list[float] = []
    errors: dict[str, str] = {}
    for it in items:
        t0 = time.perf_counter()
        try:
            ranked = arm(conn, it["question"])
        except (
            sqlite3.Error
        ) as exc:  # an arm that throws has answered nothing: a miss, recorded as a defect
            ranked = []
            errors[it["id"]] = f"{type(exc).__name__}: {exc}"
        latencies.append((time.perf_counter() - t0) * 1000)
        hit, rr = _hit(ranked, set(it["gold_session_ids"]))
        per[it["id"]] = {"hit": hit, "rr": rr, "stratum": it["stratum"], "cluster": it["cluster"]}
        if it["id"] in errors:
            per[it["id"]]["error"] = errors[it["id"]]
    latencies.sort()
    return {
        "per_question": per,
        "errors": len(errors),
        "latency_ms": {
            "p50": latencies[len(latencies) // 2],
            "p95": latencies[int(len(latencies) * 0.95) - 1],
        },
    }


def _macro(per: dict[str, dict], key: str) -> dict:
    by = defaultdict(list)
    for r in per.values():
        by[r["stratum"]].append(r[key])
    strata = {s: sum(v) / len(v) for s, v in sorted(by.items())}
    return {"by_stratum": strata, "macro": sum(strata.values()) / len(strata)}


def cluster_bootstrap(
    a: dict[str, dict], b: dict[str, dict], items: list[dict], seed: int = SEED
) -> dict:
    """Paired cluster bootstrap of macro recall@5 (a - b)."""
    clusters = defaultdict(list)
    for it in items:
        clusters[it["cluster"]].append(it["id"])
    cl = sorted(clusters)
    rng = random.Random(seed)  # nosec B311 - statistical bootstrap resampling, not cryptography

    def macro_diff(sample: Iterable[str]) -> float:
        by = defaultdict(list)
        for c in sample:
            for qid in clusters[c]:
                by[a[qid]["stratum"]].append(a[qid]["hit"] - b[qid]["hit"])
        return sum(sum(v) / len(v) for v in by.values()) / len(by)

    point = macro_diff(cl)
    draws = sorted(macro_diff(rng.choices(cl, k=len(cl))) for _ in range(RESAMPLES))
    lo, hi = draws[int(0.025 * RESAMPLES)], draws[int(0.975 * RESAMPLES) - 1]
    return {
        "point": point,
        "ci95": [lo, hi],
        "resamples": RESAMPLES,
        "clusters": len(cl),
        "established_lift": lo >= MIN_LIFT,
    }


def non_inferiority(a: dict, b: dict, items: list[dict], stratum: str, seed: int = SEED) -> dict:
    """One-sided 95% upper bound on (b - a) within one stratum; pass if <= 0.05."""
    clusters = defaultdict(list)
    for it in items:
        if it["stratum"] == stratum:
            clusters[it["cluster"]].append(it["id"])
    cl = sorted(clusters)
    rng = random.Random(seed)  # nosec B311 - statistical bootstrap resampling, not cryptography

    def diff(sample):
        vals = [b[q]["hit"] - a[q]["hit"] for c in sample for q in clusters[c]]
        return sum(vals) / len(vals)

    draws = sorted(diff(rng.choices(cl, k=len(cl))) for _ in range(RESAMPLES))
    upper = draws[int(0.95 * RESAMPLES) - 1]
    return {
        "stratum": stratum,
        "regression_point": diff(cl),
        "upper95": upper,
        "non_inferior": upper <= 0.05,
    }


def non_inferiority_macro(a: dict, b: dict, items: list[dict], seed: int = SEED) -> dict:
    """One-sided 95% upper bound on the macro (K/P/R) regression (b - a); pass if <= 0.05.

    The ruler's factorial-control clause is on the aggregate: "B1 must be non-inferior to
    B0 on the aggregate". Same paired cluster bootstrap as ``cluster_bootstrap``.
    """
    lift = cluster_bootstrap(a, b, items, seed)  # (a - b); regression is its negation
    draws_hi = -lift["ci95"][0]
    return {
        "stratum": "macro",
        "regression_point": -lift["point"],
        "upper95": draws_hi,
        "non_inferior": draws_hi <= 0.05,
    }


# --------------------------------------------------------------------------- receipts
def _sha_file(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _git(root: pathlib.Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def corpus_digest(conn: sqlite3.Connection, items: list[dict]) -> str:
    """Content digest over every gold cluster's messages, tokenizer and schema version."""
    h = hashlib.sha256()
    sessions = sorted(
        {sid for it in items for sid in it["gold_session_ids"]} | {it["cluster"] for it in items}
    )
    for sid in sessions:
        for mid, content in conn.execute(
            "SELECT id, content FROM messages WHERE session_id=? ORDER BY id", (sid,)
        ):
            h.update(str(mid).encode())
            h.update((content or "").encode("utf-8", "replace"))
    h.update(f"user_version={conn.execute('PRAGMA user_version').fetchone()[0]}".encode())
    tok = conn.execute("SELECT sql FROM sqlite_master WHERE name='messages_fts'").fetchone()
    h.update((tok[0] if tok else "").encode())
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--gold",
        required=True,
        help="gold json (DEV in repo, or the SEALED path for the one sealed look)",
    )
    ap.add_argument("--db", default=str(pathlib.Path.home() / ".config/studyloop/sessions.db"))
    ap.add_argument(
        "--b0-src", required=True, help="pinned agent-session-tools/src for the B0 control"
    )
    ap.add_argument(
        "--feature",
        action="append",
        default=[],
        help="module:callable returning an Arm, e.g. proof_arms:concepts",
    )
    ap.add_argument(
        "--out",
        required=True,
        help="receipt path (docs/architecture/session-memory/receipts/*.json)",
    )
    ap.add_argument("--previous", help="previous receipt path for hash chaining")
    ap.add_argument("--label", default="baseline")
    ap.add_argument(
        "--fusion-spec",
        help="receipts/fusion-spec-v<N>.md in force for this look (recorded on every receipt)",
    )
    ap.add_argument(
        "--store",
        help="learning-memory store read by feature arms; its sha256 binds the receipt to it",
    )
    args = ap.parse_args()

    root = pathlib.Path(__file__).resolve().parents[2]
    gold = json.loads(pathlib.Path(args.gold).read_text())
    items = gold["items"]
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)

    arms: dict[str, Arm] = {}
    arms["B0"] = _shipped_fts_arm(pathlib.Path(args.b0_src))
    arms["B1"] = _shipped_fts_arm(None)
    for spec in args.feature:
        mod, fn = spec.split(":")
        arms[fn] = getattr(importlib.import_module(mod), fn)()

    results = {name: score_arm(conn, arm, items) for name, arm in arms.items()}
    summary = {
        name: {
            "recall@5": _macro(r["per_question"], "hit"),
            "mrr@5": _macro(r["per_question"], "rr"),
            "latency_ms": r["latency_ms"],
            "errors": r["errors"],
        }
        for name, r in results.items()
    }

    def compare(cand: str, comp: str) -> dict:
        a, b = results[cand]["per_question"], results[comp]["per_question"]
        return {
            "lift": cluster_bootstrap(a, b, items),
            "non_inferiority": [non_inferiority_macro(a, b, items)]
            + [non_inferiority(a, b, items, s) for s in "KPR"],
        }

    comparisons = {"B1_vs_B0": compare("B1", "B0")}
    for name in arms:
        if name in ("B0", "B1"):
            continue
        comparisons[f"{name}_vs_B1"] = compare(name, "B1")

    fusion_spec = pathlib.Path(args.fusion_spec).resolve() if args.fusion_spec else None
    store = pathlib.Path(args.store).expanduser() if args.store else None
    receipt = {
        "receipt": args.label,
        "created_utc": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        "ruler_commit": _git(
            root,
            "log",
            "-1",
            "--format=%H",
            "--",
            "docs/architecture/session-memory/validation-ruler.md",
        ),
        "candidate_commit": _git(root, "rev-parse", "HEAD"),
        "b0_pin": _git(pathlib.Path(args.b0_src).parents[2], "rev-parse", "HEAD"),
        "fusion_spec": {
            "path": str(fusion_spec.relative_to(root)) if fusion_spec else None,
            "sha256": _sha_file(fusion_spec) if fusion_spec else None,
            "declared_commit": _git(
                root, "log", "--diff-filter=A", "-1", "--format=%H", "--", str(fusion_spec)
            )
            if fusion_spec
            else None,
        },
        "store": {
            "path": str(store) if store else None,
            "sha256": _sha_file(store) if store else None,
            "bytes": store.stat().st_size if store else None,
        },
        "gold": {
            "set": gold["set"],
            "sha256": hashlib.sha256(pathlib.Path(args.gold).read_bytes()).hexdigest(),
            "items": len(items),
            "clusters": len({it["cluster"] for it in items}),
        },
        "corpus_digest": corpus_digest(conn, items),
        "gold_corpus_digest_at_authoring": gold.get("corpus_digest"),
        "arms": summary,
        "comparisons": comparisons,
        "per_question": {name: r["per_question"] for name, r in results.items()},
        "previous_receipt_sha256": _sha_file(pathlib.Path(args.previous))
        if args.previous
        else None,
    }
    out = pathlib.Path(args.out)
    out.write_text(json.dumps(receipt, indent=1) + "\n")
    for name, s in summary.items():
        r = s["recall@5"]
        print(
            f"{name:>10}  macro recall@5 {r['macro']:.3f}  "
            + "  ".join(f"{k} {v:.3f}" for k, v in r["by_stratum"].items())
            + f"   p95 {s['latency_ms']['p95']:.0f} ms   errors {s['errors']}"
        )
    for name, c in comparisons.items():
        lift = c["lift"]
        lo, hi = lift["ci95"]
        print(
            f"{name:>10}  Δmacro {lift['point']:+.3f}  CI95 [{lo:+.3f}, {hi:+.3f}]"
            f"  established={lift['established_lift']}"
        )
    print(f"receipt -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
