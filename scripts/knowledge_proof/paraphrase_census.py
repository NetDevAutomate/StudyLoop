"""Paraphrase census over REAL learner questions (no model, read-only).

Design question this answers: when a learner asks about something discussed in a past session,
how often are the question's words absent from the transcript — i.e. how often would a lexical
retriever fail for vocabulary reasons rather than ranking?

Proxy (stated limits below): every learner turn in a *human-driven* session (session id not
``agent-*``) is treated as a real question about its own session. For each one we measure

1. **Vocabulary overlap** — the share of the question's stemmed content tokens that occur anywhere
   in the *rest* of the same session's prose (the question row itself and byte-identical re-asks
   excluded). 0.0 means the transcript never used any of the question's words.
2. **Self-retrieval without self** — the committed prose FTS + phrase-token OR planner is queried
   with the question; rows belonging to the question (and its identical re-asks) are dropped from
   the ranking; we record whether the question's own session is still in the top 5. A miss is
   classed ``vocabulary_gap`` if overlap == 0 (no token could have matched) else ``ranking``.

Limits, stated up front: this compares a question with its OWN session, where the assistant
usually echoes the learner's terms. A real cross-session lookup targets a *different* past
session, so vocabulary drift is larger there — treat every paraphrase rate here as a LOWER bound.

Usage::

    KNOWLEDGE_PROOF_STORE=~/.local/share/studyloop/knowledge-proof/learning-memory.db \
    uv run python scripts/knowledge_proof/paraphrase_census.py \
        --out docs/architecture/session-memory/receipts/paraphrase-census.json [--sample N --seed S]
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import random
import re
import statistics
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import proof_arms as pa

MIN_TOKENS = 3
MAX_WORDS = 200  # longer learner turns are pasted material (logs, docs, briefs), not questions
K = 5
STOP = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "if",
    "then",
    "than",
    "that",
    "this",
    "these",
    "those",
    "it",
    "its",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "doing",
    "will",
    "would",
    "shall",
    "should",
    "can",
    "could",
    "may",
    "might",
    "must",
    "of",
    "in",
    "on",
    "at",
    "to",
    "for",
    "from",
    "with",
    "by",
    "as",
    "into",
    "onto",
    "about",
    "over",
    "under",
    "after",
    "before",
    "between",
    "during",
    "without",
    "within",
    "i",
    "me",
    "my",
    "we",
    "our",
    "you",
    "your",
    "he",
    "she",
    "they",
    "them",
    "their",
    "what",
    "which",
    "who",
    "whom",
    "whose",
    "why",
    "how",
    "when",
    "where",
    "not",
    "no",
    "yes",
    "so",
    "up",
    "out",
    "off",
    "just",
    "also",
    "only",
    "very",
    "too",
    "more",
    "most",
    "some",
    "any",
    "each",
    "all",
    "both",
    "few",
    "many",
    "there",
    "here",
    "now",
    "please",
    "want",
    "need",
    "like",
    "get",
    "got",
    "make",
    "made",
    "use",
    "used",
    "using",
    "let",
    "lets",
    "ok",
    "okay",
    "thanks",
    "thank",
    "yeah",
    "right",
    "sure",
    "well",
    "still",
    "again",
    "back",
    "new",
    "one",
    "two",
    "way",
    "thing",
    "things",
    "something",
    "anything",
    "done",
    "go",
    "going",
    "come",
    "went",
}
TOKEN_RE = re.compile(r"[a-z0-9_][a-z0-9_./-]{1,}")


def _stem(tok: str) -> str:
    """A cheap Porter-ish stem: enough to make 'planner'/'planners', 'failing'/'failed' agree.

    The FTS index uses SQLite's porter tokenizer; this approximation is only used for the overlap
    statistic, never for retrieval (retrieval goes through the real index).
    """
    for suf in ("ings", "ing", "edly", "ed", "ies", "es", "s", "ly", "er", "ers", "tion", "tions"):
        if tok.endswith(suf) and len(tok) - len(suf) >= 3:
            return tok[: -len(suf)]
    return tok


def content_tokens(text: str) -> set[str]:
    toks = TOKEN_RE.findall(text.lower())
    return {_stem(t) for t in toks if t not in STOP and not t.isdigit()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sample", type=int, default=0, help="0 = all eligible questions")
    ap.add_argument("--seed", type=int, default=20260910)
    args = ap.parse_args()

    store_path = pa._store_path()
    store_sha = hashlib.sha256(store_path.read_bytes()).hexdigest()
    db = pa._open_store_ro(store_path)
    from learning_memory.store import plan_prose_query

    rows = db.execute(
        "SELECT e.id, e.session_id, e.text, s.harness FROM events e "
        "JOIN sessions s ON s.id = e.session_id "
        "WHERE e.kind = 'user' AND e.session_id NOT LIKE 'agent-%' ORDER BY e.id"
    ).fetchall()
    total_turns = len(rows)

    # Per-session prose (excluding nothing yet) and per-session learner texts for re-ask detection.
    prose_by_session: dict[str, list[tuple[int, str]]] = collections.defaultdict(list)
    for eid, sid, text in db.execute(
        "SELECT id, session_id, text FROM events WHERE kind IN ('user','assistant_prose') "
        "AND session_id NOT LIKE 'agent-%'"
    ):
        prose_by_session[sid].append((eid, text or ""))

    # Per-event token sets and per-session "number of events containing token" — computed once,
    # so each question's overlap with the REST of its session is O(question tokens).
    event_tokens: dict[int, set[str]] = {}
    session_token_events: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter
    )
    for sid, evs in prose_by_session.items():
        for oid, t in evs:
            toks_e = content_tokens(t)
            event_tokens[oid] = toks_e
            session_token_events[sid].update(toks_e)

    eligible = []
    short = 0
    pasted = 0
    for eid, sid, text, harness in rows:
        if len((text or "").split()) > MAX_WORDS:
            pasted += 1
            continue
        toks = content_tokens(text or "")
        if len(toks) < MIN_TOKENS:
            short += 1
            continue
        eligible.append((eid, sid, text, harness, toks))
    if args.sample and args.sample < len(eligible):
        rng = random.Random(args.seed)  # nosec B311 - deterministic sampling, not cryptography
        eligible = rng.sample(eligible, args.sample)

    overlaps: list[float] = []
    hits = 0
    miss_vocab = 0
    miss_rank = 0
    by_harness: dict[str, dict[str, int]] = collections.defaultdict(lambda: collections.Counter())
    zero_overlap_examples: list[dict] = []
    t0 = time.time()
    for n, (eid, sid, text, harness, toks) in enumerate(eligible, 1):
        # tokens present in some OTHER event of the session (own row and identical re-asks excluded)
        self_ids = [oid for oid, t in prose_by_session[sid] if oid == eid or t == text]
        self_counts: collections.Counter = collections.Counter()
        for oid in self_ids:
            self_counts.update(event_tokens.get(oid, set()))
        counts = session_token_events[sid]
        present = {t for t in toks if counts[t] - self_counts[t] > 0}
        overlap = len(present) / len(toks)
        overlaps.append(overlap)

        planned = plan_prose_query(text)
        ranked_sessions: list[str] = []
        if planned:
            excluded = {eid} | {oid for oid, t in prose_by_session[sid] if t == text}
            for rid, rsid in db.execute(
                "SELECT e.id, e.session_id FROM prose_fts "
                "JOIN events AS e ON e.id = prose_fts.rowid "
                "WHERE prose_fts MATCH ? ORDER BY bm25(prose_fts), e.id "
                f"LIMIT {pa.CANDIDATE_ROWS}",
                (planned,),
            ):
                if rid in excluded:
                    continue
                if rsid not in ranked_sessions:
                    ranked_sessions.append(rsid)
                if len(ranked_sessions) == K:
                    break
        hit = sid in ranked_sessions
        b = by_harness[harness]
        b["n"] += 1
        if hit:
            hits += 1
            b["hit"] += 1
        elif overlap == 0.0:
            miss_vocab += 1
            b["miss_vocab"] += 1
            if len(zero_overlap_examples) < 12:
                zero_overlap_examples.append(
                    {"session": sid[:20], "harness": harness, "question": text[:140]}
                )
        else:
            miss_rank += 1
            b["miss_rank"] += 1
        if n % 500 == 0:
            print(f"  … {n}/{len(eligible)}  {time.time() - t0:.0f}s", file=sys.stderr)

    n = len(eligible)
    quantiles = statistics.quantiles(overlaps, n=10) if n >= 10 else []
    summary = {
        "learner_turns_human_sessions": total_turns,
        "excluded_under_3_content_tokens": short,
        "excluded_pasted_over_200_words": pasted,
        "measured": n,
        "sampled": bool(args.sample),
        "overlap_with_own_session_other_prose": {
            "mean": round(statistics.fmean(overlaps), 3),
            "median": round(statistics.median(overlaps), 3),
            "deciles": [round(q, 3) for q in quantiles],
            "share_zero_overlap": round(sum(1 for o in overlaps if o == 0.0) / n, 4),
            "share_below_0.25": round(sum(1 for o in overlaps if o < 0.25) / n, 4),
            "share_below_0.5": round(sum(1 for o in overlaps if o < 0.5) / n, 4),
            "share_at_least_0.5": round(sum(1 for o in overlaps if o >= 0.5) / n, 4),
        },
        "self_retrieval_without_self_top5": {
            "hit": hits,
            "hit_rate": round(hits / n, 4),
            "miss_vocabulary_gap": miss_vocab,
            "miss_vocabulary_gap_rate": round(miss_vocab / n, 4),
            "miss_ranking": miss_rank,
            "miss_ranking_rate": round(miss_rank / n, 4),
        },
        "by_harness": {
            h: {**dict(c), "hit_rate": round(c["hit"] / c["n"], 3)}
            for h, c in sorted(by_harness.items(), key=lambda kv: -kv[1]["n"])
            if c["n"] >= 50
        },
    }
    out = {
        "artefact": "paraphrase-census",
        "store_sha256": store_sha,
        "method": __doc__.split("Limits")[0].strip(),
        "limits": (
            "own-session comparison; cross-session vocabulary drift is larger, "
            "so paraphrase rates are LOWER bounds"
        ),
        "planner": "learning_memory.store.plan_prose_query (phrase-token OR)",
        "k": K,
        "min_content_tokens": MIN_TOKENS,
        "max_words": MAX_WORDS,
        "summary": summary,
        "zero_overlap_examples": zero_overlap_examples,
    }
    pathlib.Path(args.out).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
