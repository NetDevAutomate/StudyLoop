# Stage 1 — model measurements (cost only, no choice)

Repo `3826a9b4` · 2026-09-11 · seed `20260911` · arm64, 16 CPU, torch 2.13.0 (12 threads), Python
3.12.8 / SQLite 3.47.1 · live `sessions.db` read-only (`mode=ro`), never written · all numbers in
[stage1-model-measurements.json](./stage1-model-measurements.json). Cost only — no model chosen.

## Corpus

Embeddable = `role IN ('user','assistant') AND length(content) >= 50` in sessions admitted by
`visibility_sql(conn, 's.id')`: **51,729 messages** across 4,600 of 5,879 sessions. **Correction:**
`lane-A.md` and `plan-brief.md` cite 57,247, a count taken WITHOUT the visibility predicate (57,250
today); with visibility applied — required, since a hidden session must never be embedded — the set
is 51,729, **9.6% fewer**, and every projection below uses it. Char length, full set: p50 **204**,
p90 3,271, p95 6,571, p99 26,532, max 961,112; share over 2,000 chars (the plan's crude ruler)
**14.39%**. The 2,000 sample tracks it (13.75%, 0.64 pp apart).

## Per model, on the deterministic 2,000

| | MiniLM-L6-v2 | bge-small-en-v1.5 | all-mpnet-base-v2 |
|---|---|---|---|
| dim / token cap | 384 / **256** | 384 / **512** | **768** / 384 |
| over cap (real tokenizer) | **21.80%** (436) | **15.65%** (313) | 18.10% (362) |
| tokens p50 / p95 / p99 | 53 / 2,032 / 10,152 | 53 / 2,032 / 10,152 | 53 / 2,032 / 10,152 |
| encode 2,000 (s) | **3.91** | 11.16 | 30.88 |
| messages / s | **511.6** | 179.2 | 64.8 |
| projected backfill (min) | **1.69** | 4.81 | 13.31 |
| bytes / vector | **1,536** | **1,536** | 3,072 |
| projected corpus | **75.8 MB** | **75.8 MB** | 151.5 MB |
| warm query mean / p95 (ms) | **3.58 / 3.82** | 6.31 / 6.49 | 15.02 / 15.73 |
| cold load (s, warm HF cache) | 2.90 | 2.87 | 2.60 |

Token counts are **identical across all three** — verified with three separate tokenizer objects
(BertTokenizer vocab 30,522 ×2, MPNetTokenizer vocab 30,527; 257,305 tokens each over the first 300
texts), all lowercase WordPiece over the same base vocab, so **overflow differs only by cap**. The
2 KB byte ruler understates it at a 256 cap (14.4% vs 21.8%) and roughly matches a 512 cap. Every
candidate exceeds the 5% materiality line, so **chunking is required whichever model Stage 4 picks**.

## sqlite-vec at corpus scale (57,247 vectors, scratch `:memory:`)

The 384-d control reproduces the previously recorded 4.8 ms; 768-d costs **1.87×** the KNN time.

| dim | index build | db size | KNN top-20 mean / p95 |
|---|---|---|---|
| 768 | 1.49 s | 169.5 MB | **8.54 / 9.32 ms** |
| 384 (control) | 0.92 s | 85.4 MB | **4.58 / 4.73 ms** |

## What the numbers favour, per axis — all four are cost, so no choice is made here

- **Overflow:** bge-small-en-v1.5 — its 512 cap gives the lowest share, 15.65%.
- **Backfill minutes:** MiniLM-L6-v2 — 1.69 min, 2.8× faster than bge, 7.9× than mpnet.
- **Bytes / index:** MiniLM and bge tie at 384-d (75.8 MB vectors, ~85 MB index); mpnet doubles both.
- **Query ms:** MiniLM-L6-v2 — 3.58 ms mean, ~4.2× faster than mpnet.

## Unverified

- First-use Hugging Face download — all three were already cached, so cold load is disk+init only.
- Index size / KNN latency use random unit vectors in memory; real embeddings cluster and an on-disk
  file adds page and WAL overhead — treat as a floor. Backfill minutes are projected from 2,000
  messages, not a full run. Timings are reported, not byte-stable (kimi F5/F6): do not compare runs.
