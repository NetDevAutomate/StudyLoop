"""Cross-session duplicate learner texts among census-eligible questions (no model, read-only).

Why this exists: the v1 census's ``aider`` row (1 hit in 204) turned out to be 203 byte-identical
copies of one fixture prompt across 203 sessions. Self-retrieval-without-self cannot pick one
session out of N sessions holding the identical text — the identical sibling rows are perfect
matches and fill the top-K before the question's own session can rank. That is a **structural**
miss, not a ranking-quality miss, and the census counts it under ``ranking``. This script measures
how much of the six-source corpus is in that state, so the "ranking misses dominate" reading in the
v2 sidecar is bounded rather than taken at face value.

Eligibility is imported from ``paraphrase_census`` (>= MIN_TOKENS content tokens, <= MAX_WORDS
words, human-driven sessions) so the population is exactly the census's 3,299 (for the v2 store).

Usage::

    KNOWLEDGE_PROOF_STORE=~/.local/share/studyloop/knowledge-proof/learning-memory-v2.db \\
    uv run python scripts/knowledge_proof/paraphrase_census_duplicates.py \\
        --out docs/architecture/session-memory/receipts/paraphrase-census-duplicates-v2.json
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import paraphrase_census as pc
import proof_arms as pa


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--k", type=int, default=pc.K, help="top-K used by the census (default 5)")
    args = ap.parse_args()

    store = pa._store_path()
    store_sha = hashlib.sha256(store.read_bytes()).hexdigest()
    db = pa._open_store_ro(store)

    # Sessions holding each exact user text (human sessions only), computed once.
    sessions_by_text: dict[str, set[str]] = collections.defaultdict(set)
    for sid, text in db.execute(
        "SELECT session_id, text FROM events WHERE kind = 'user' AND session_id NOT LIKE 'agent-%'"
    ):
        sessions_by_text[text or ""].add(sid)

    rows = db.execute(
        "SELECT e.id, e.session_id, e.text, s.harness FROM events e "
        "JOIN sessions s ON s.id = e.session_id "
        "WHERE e.kind = 'user' AND e.session_id NOT LIKE 'agent-%' ORDER BY e.id"
    ).fetchall()

    eligible = 0
    per_harness: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    totals: collections.Counter[str] = collections.Counter()
    top_texts: collections.Counter[str] = collections.Counter()
    for _eid, _sid, text, harness in rows:
        text = text or ""
        if len(text.split()) > pc.MAX_WORDS or len(pc.content_tokens(text)) < pc.MIN_TOKENS:
            continue
        eligible += 1
        others = len(sessions_by_text[text]) - 1  # other sessions holding the identical text
        c = per_harness[harness]
        c["n"] += 1
        totals["n"] += 1
        if others >= 1:
            c["identical_text_in_other_sessions"] += 1
            totals["identical_text_in_other_sessions"] += 1
            top_texts[text] += 1
        if others >= args.k:
            c[f"identical_text_in_at_least_{args.k}_other_sessions"] += 1
            totals[f"identical_text_in_at_least_{args.k}_other_sessions"] += 1

    out = {
        "artefact": "paraphrase-census-duplicates",
        "store": str(store),
        "store_sha256": store_sha,
        "method": __doc__.split("Usage::")[0].strip(),
        "k": args.k,
        "summary": {
            "eligible_questions": eligible,
            **{k: v for k, v in totals.items() if k != "n"},
            "share_identical_text_in_other_sessions": round(
                totals["identical_text_in_other_sessions"] / eligible, 4
            ),
            f"share_identical_text_in_at_least_{args.k}_other_sessions": round(
                totals[f"identical_text_in_at_least_{args.k}_other_sessions"] / eligible, 4
            ),
        },
        "by_harness": {
            h: dict(sorted(c.items()))
            for h, c in sorted(per_harness.items(), key=lambda kv: -kv[1]["n"])
        },
        "most_repeated_eligible_texts": [
            {
                "eligible_questions": n,
                "sessions_holding_text": len(sessions_by_text[t]),
                "text": t[:120].replace("\n", " "),
            }
            for t, n in top_texts.most_common(12)
        ],
    }
    pathlib.Path(args.out).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(out["summary"], indent=1))
    print(json.dumps(out["by_harness"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
