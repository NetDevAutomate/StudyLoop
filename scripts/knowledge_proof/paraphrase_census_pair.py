"""Paired paraphrase census: the same questions, two stores, one outcome per question per store.

Answers the Stage 2 council's F1/F2 (receipt ``council-stage2-2026-09-10.md``). The aggregate
receipts ``paraphrase-census.json`` (v1, 14-source store) and ``paraphrase-census-v2.json`` (six
sources + ``study_mentor``) show identical per-harness ``n`` and identical vocabulary-gap counts,
from which the v2 sidecar inferred "same question set, 23 recoveries, zero regressions". An
aggregate cannot distinguish 23 net from 24 recoveries and 1 regression, nor show *why* a question
moved. This script measures it:

1. **Membership** — every eligible question is keyed ``session_id | sha256(text)[:16] | k`` (k = the
   k-th identical re-ask in that session, in event order). Are the two key sets identical on the
   in-scope harnesses?
2. **Transitions** — per question, class in v1 vs class in v2 (``hit`` / ``vocabulary_gap`` /
   ``ranking``), counted per harness, including the harnesses under the census's n >= 50 reporting
   threshold.
3. **Mechanism** — for every miss->hit, did a retired-label session occupy v1's top-5
   (displacement), or did the question rise with no retired session above it (bm25/IDF shift from
   a smaller index)?
4. **Content stability** — a sha256 over each session's ordered prose events (kind, text) in both
   stores; any mismatch means the corpus changed between runs.

Eligibility, tokenisation, self-exclusion, planner and K are imported from ``paraphrase_census`` so
the per-question decision is byte-for-byte the census's own. Read-only on both stores.

Usage::

    uv run python scripts/knowledge_proof/paraphrase_census_pair.py \\
        --v1 ~/.local/share/studyloop/knowledge-proof/learning-memory.db \\
        --v2 ~/.local/share/studyloop/knowledge-proof/learning-memory-v2.db \\
        --out docs/architecture/session-memory/receipts/paraphrase-census-pair.json
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import paraphrase_census as pc
import proof_arms as pa
from learning_memory.adapters.archive import SUPPORTED_SOURCES
from learning_memory.store import plan_prose_query

Outcome = dict[str, object]


def census(store: pathlib.Path) -> tuple[dict[str, Outcome], dict[str, str], dict[str, str]]:
    """Return (per-question outcomes, per-session prose digest, session -> harness)."""
    db = pa._open_store_ro(store)
    harness_of: dict[str, str] = dict(db.execute("SELECT id, harness FROM sessions").fetchall())
    rows = db.execute(
        "SELECT e.id, e.session_id, e.text, s.harness FROM events e "
        "JOIN sessions s ON s.id = e.session_id "
        "WHERE e.kind = 'user' AND e.session_id NOT LIKE 'agent-%' ORDER BY e.id"
    ).fetchall()

    prose_by_session: dict[str, list[tuple[int, str]]] = collections.defaultdict(list)
    digest_input: dict[str, hashlib._Hash] = {}
    for eid, sid, kind, text in db.execute(
        "SELECT id, session_id, kind, text FROM events "
        "WHERE kind IN ('user','assistant_prose') AND session_id NOT LIKE 'agent-%' ORDER BY id"
    ):
        prose_by_session[sid].append((eid, text or ""))
        h = digest_input.setdefault(sid, hashlib.sha256())
        h.update(kind.encode())
        h.update(b"\x00")
        h.update((text or "").encode())
        h.update(b"\x01")
    digests = {sid: h.hexdigest() for sid, h in digest_input.items()}

    event_tokens: dict[int, set[str]] = {}
    session_token_events: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    for sid, evs in prose_by_session.items():
        for oid, t in evs:
            toks_e = pc.content_tokens(t)
            event_tokens[oid] = toks_e
            session_token_events[sid].update(toks_e)

    eligible: list[tuple[int, str, str, str, set[str]]] = []
    for eid, sid, text, harness in rows:
        if len((text or "").split()) > pc.MAX_WORDS:
            continue
        toks = pc.content_tokens(text or "")
        if len(toks) < pc.MIN_TOKENS:
            continue
        eligible.append((eid, sid, text, harness, toks))

    occurrence: collections.Counter[tuple[str, str]] = collections.Counter()
    out: dict[str, Outcome] = {}
    t0 = time.time()
    for n, (eid, sid, text, harness, toks) in enumerate(eligible, 1):
        self_ids = [oid for oid, t in prose_by_session[sid] if oid == eid or t == text]
        self_counts: collections.Counter[str] = collections.Counter()
        for oid in self_ids:
            self_counts.update(event_tokens.get(oid, set()))
        counts = session_token_events[sid]
        present = {t for t in toks if counts[t] - self_counts[t] > 0}
        overlap = len(present) / len(toks)

        planned = plan_prose_query(text)
        ranked: list[str] = []
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
                if rsid not in ranked:
                    ranked.append(rsid)
                if len(ranked) == pc.K:
                    break
        if sid in ranked:
            cls = "hit"
        elif overlap == 0.0:
            cls = "vocabulary_gap"
        else:
            cls = "ranking"
        th = hashlib.sha256(text.encode()).hexdigest()[:16]
        key = f"{sid}|{th}|{occurrence[(sid, th)]}"
        occurrence[(sid, th)] += 1
        out[key] = {
            "harness": harness,
            "class": cls,
            "overlap": round(overlap, 4),
            "top5": [[r, harness_of.get(r, "?")] for r in ranked],
        }
        if n % 500 == 0:
            print(
                f"  … {store.name}: {n}/{len(eligible)}  {time.time() - t0:.0f}s", file=sys.stderr
            )
    return out, digests, harness_of


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--v1", required=True)
    ap.add_argument("--v2", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    p1 = pathlib.Path(args.v1).expanduser()
    p2 = pathlib.Path(args.v2).expanduser()
    sha1 = hashlib.sha256(p1.read_bytes()).hexdigest()
    sha2 = hashlib.sha256(p2.read_bytes()).hexdigest()

    q1, d1, h1 = census(p1)
    q2, d2, h2 = census(p2)
    in_scope = set(SUPPORTED_SOURCES)
    retired = sorted({h for h in h1.values() if h not in in_scope})

    keys1_scoped = {k for k, v in q1.items() if v["harness"] in in_scope}
    keys2 = set(q2)
    only_v1 = sorted(keys1_scoped - keys2)
    only_v2 = sorted(keys2 - keys1_scoped)
    common = keys1_scoped & keys2

    transitions: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    moved: list[dict[str, object]] = []
    displaced = 0
    idf_shift = 0
    for k in sorted(common):
        a, b = q1[k], q2[k]
        harness = str(b["harness"])
        transitions[harness][f"{a['class']}->{b['class']}"] += 1
        if a["class"] != b["class"]:
            top5_v1 = a["top5"]
            assert isinstance(top5_v1, list)
            retired_above = [h for _, h in top5_v1 if h not in in_scope]
            record = {
                "key": k,
                "harness": harness,
                "v1": a["class"],
                "v2": b["class"],
                "overlap": b["overlap"],
                "retired_sessions_in_v1_top5": len(retired_above),
                "v1_top5_harnesses": [h for _, h in top5_v1],
            }
            moved.append(record)
            if a["class"] != "hit" and b["class"] == "hit":
                if retired_above:
                    displaced += 1
                else:
                    idf_shift += 1

    def rate(qs: dict[str, Outcome], keys: set[str]) -> float:
        return round(sum(1 for k in keys if qs[k]["class"] == "hit") / len(keys), 4)

    per_harness_v2 = collections.Counter(str(v["harness"]) for v in q2.values())
    v1_overall = rate(q1, set(q1))
    v1_cohort = rate(q1, common) if common else 0.0
    v2_overall = rate(q2, keys2)

    sessions2 = set(h2)
    digest_mismatch = sorted(s for s in sessions2 if d1.get(s) != d2.get(s))
    sessions_only_v2 = sorted(sessions2 - set(h1))

    receipts = pathlib.Path(args.out).parent
    rej1 = rej2 = None
    try:
        r1 = json.loads((receipts / "ingest-archive-v1.json").read_text())
        r2 = json.loads((receipts / "ingest-archive-v2.json").read_text())
        rej1 = {d["session_id"] for d in r1["sessions"]["rejected_detail"]}
        rej2 = {d["session_id"] for d in r2["sessions"]["rejected_detail"]}
    except (OSError, KeyError, json.JSONDecodeError):
        pass

    summary = {
        "membership": {
            "v1_in_scope_questions": len(keys1_scoped),
            "v2_questions": len(keys2),
            "common": len(common),
            "only_in_v1": len(only_v1),
            "only_in_v2": len(only_v2),
            "identical": not only_v1 and not only_v2,
        },
        "hit_rate": {
            "v1_all_sources": v1_overall,
            "v1_restricted_to_v2_cohort": v1_cohort,
            "v2": v2_overall,
            "composition_effect_pt": round((v1_cohort - v1_overall) * 100, 2),
            "retrieval_effect_pt": round((v2_overall - v1_cohort) * 100, 2),
        },
        "transitions_by_harness": {
            h: dict(sorted(c.items())) for h, c in sorted(transitions.items())
        },
        "changed_questions": len(moved),
        "miss_to_hit": displaced + idf_shift,
        "miss_to_hit_with_retired_session_in_v1_top5": displaced,
        "miss_to_hit_without_retired_session_in_v1_top5": idf_shift,
        "hit_to_miss": sum(1 for m in moved if m["v1"] == "hit" and m["v2"] != "hit"),
        "class_change_among_misses": sum(1 for m in moved if m["v1"] != "hit" and m["v2"] != "hit"),
        "questions_per_harness_v2": dict(per_harness_v2.most_common()),
        "content_stability": {
            "v2_sessions": len(sessions2),
            "sessions_only_in_v2_store": len(sessions_only_v2),
            "prose_digest_mismatches": len(digest_mismatch),
            "identical": not digest_mismatch and not sessions_only_v2,
        },
        "rejected_sessions": (
            None
            if rej1 is None or rej2 is None
            else {
                "v1": len(rej1),
                "v2": len(rej2),
                "v2_subset_of_v1": rej2 <= rej1,
            }
        ),
    }
    out = {
        "artefact": "paraphrase-census-pair",
        "method": __doc__.split("Usage::")[0].strip(),
        "v1_store_sha256": sha1,
        "v2_store_sha256": sha2,
        "in_scope_sources": sorted(in_scope),
        "retired_sources_in_v1_store": retired,
        "summary": summary,
        "changed_questions": moved,
        "membership_diff": {"only_in_v1": only_v1[:50], "only_in_v2": only_v2[:50]},
        "digest_mismatches": digest_mismatch[:50],
    }
    pathlib.Path(args.out).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
