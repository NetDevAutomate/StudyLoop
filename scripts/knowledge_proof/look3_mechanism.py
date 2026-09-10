"""Retain the DEV look-3 mechanism evidence as a committed artefact.

Council seat gpt (Stage F/G1 review) noted that the reading's mechanism claim rested on a
diagnostic re-execution that was not retained. This script re-executes the *committed* arms
against the store named in the look-3 receipt (sha checked) and writes, for every question
``B1_clean`` hit and ``B1_clean_plus_claims`` missed, the gold session's rank in the full
prose ranking, the full claims ranking, and the fused ranking, plus both list lengths.
Deterministic; safe to re-run; it reads, never writes, the store.

Usage::

    KNOWLEDGE_PROOF_STORE=~/.local/share/studyloop/knowledge-proof/learning-memory.db \
    uv run python scripts/knowledge_proof/look3_mechanism.py \
        --receipt docs/architecture/session-memory/receipts/stage-f-look3-claims.json \
        --gold docs/architecture/session-memory/receipts/gold-v2-dev.json \
        --out docs/architecture/session-memory/receipts/stage-f-look3-mechanism.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import proof_arms as pa


def _rank(ranked: list[str], gold: set[str]) -> int | None:
    return next((i for i, s in enumerate(ranked, 1) if s in gold), None)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--receipt", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    receipt = json.loads(pathlib.Path(args.receipt).read_text())
    store_path = pa._store_path()
    store_sha = hashlib.sha256(store_path.read_bytes()).hexdigest()
    recorded = (receipt.get("store") or {}).get("sha256")
    if recorded and recorded != store_sha:
        print(f"store sha {store_sha[:12]} != receipt's {recorded[:12]}; refusing", file=sys.stderr)
        return 2

    items = {it["id"]: it for it in json.loads(pathlib.Path(args.gold).read_text())["items"]}
    pq = receipt["per_question"]
    hit = lambda arm, q: bool(pq[arm][q]["hit"])  # noqa: E731 - local predicate
    qs = list(pq["B1_clean"])
    lost = [q for q in qs if hit("B1_clean", q) and not hit("B1_clean_plus_claims", q)]
    gained = [q for q in qs if not hit("B1_clean", q) and hit("B1_clean_plus_claims", q)]

    store = pa._open_store_ro(store_path)
    index = pa._build_claims_index(store)
    rows = []
    for q in lost:
        it = items[q]
        gold = set(it["gold_session_ids"])
        prose = pa._prose_ranked_sessions(store, it["question"])
        claims = pa._claims_ranked_sessions(index, it["question"])
        fused = pa.rrf_fuse([prose, claims])
        rows.append(
            {
                "question_id": q,
                "stratum": it["stratum"],
                "gold_rank_prose": _rank(prose, gold),
                "gold_rank_claims": _rank(claims, gold),
                "gold_rank_fused": _rank(fused, gold),
                "prose_list_len": len(prose),
                "claims_list_len": len(claims),
            }
        )
    summary = {
        "lost_by_fusion": len(lost),
        "gained_by_fusion": len(gained),
        "lost_with_gold_prose_rank_le_2": sum(1 for r in rows if (r["gold_rank_prose"] or 99) <= 2),
        "lost_with_gold_absent_from_claims_list": sum(
            1 for r in rows if r["gold_rank_claims"] is None
        ),
        "median_claims_list_len_on_lost": statistics.median(r["claims_list_len"] for r in rows)
        if rows
        else None,
        "rrf_k": pa.RRF_K,
        "candidate_rows": pa.CANDIDATE_ROWS,
    }
    out = {
        "artefact": "stage-f-look3-mechanism",
        "derived_from_receipt": {
            "path": args.receipt,
            "sha256": hashlib.sha256(pathlib.Path(args.receipt).read_bytes()).hexdigest(),
        },
        "store_sha256": store_sha,
        "method": (
            "deterministic re-execution of the committed arms (proof_arms.py) on the same "
            "store; ranks are 1-based positions of the first gold session in each full "
            "deduped ranking"
        ),
        "summary": summary,
        "lost_questions": rows,
        "gained_questions": gained,
    }
    pathlib.Path(args.out).write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
