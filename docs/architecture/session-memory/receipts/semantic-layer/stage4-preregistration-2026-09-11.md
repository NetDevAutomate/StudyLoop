# Stage 4 pre-registration — hybrid retrieval, measured before it is believed

Written and committed **before any hybrid result was computed** on any question set. The
bake-off clones were being embedded while this was written (`session-maint embed` only); no
search had been run through a hybrid arm. Changing anything below after a number has been seen
is a ruler change and is recorded as a new pre-registration, not an edit to this one.

Anchors this stage pairs against, all from committed receipts:

| ruler | arm | number | receipt |
|---|---|---|---|
| gold DEV (91 · 57 clusters · K 33 / P 29 / R 29) | `mcp` lexical, Stage 2 service | macro recall@5 **0.1585** (K 0.303 · P 0.034 · R 0.138) · MRR@5 0.1305 · 0 crashes | `stage2-gold-v2.json` |
| gold DEV latency | `mcp`, Stage 1 measurement | p50 18 ms · **p95 96 ms** (the latency gate's baseline: `96 + 50 = 146 ms`) | `stage1-baseline-gold.json` |
| census (5,434 eligible) | `mcp` lexical | hit@5 **0.6154** (3,344 hits) | `stage2-census-mcp-v2.json` |
| corpus | — | 51,742 eligible messages; MiniLM 174,371 chunks | `stage3-alignment-clone*.json` |

## H1 — the hypothesis

Fusing a semantic arm into the lexical service raises macro recall@5 on the gold set, with the
lift concentrated in the **P (paraphrase)** stratum, where the lexical arm scores 0.034 because
the question does not share vocabulary with the session. K (keyword) must not regress.

## The semantic arm

1. **Query vector**: the query text encoded by the model pinned in `message_embeddings.model`
   (one model per database; the encoder is loaded once per process, offline —
   `HF_HUB_OFFLINE=1` — and never downloaded during a search). For `BAAI/bge-small-en-v1.5` the
   model card's query instruction is prepended to the query only
   (`Represent this sentence for searching relevant passages: `); the other two models take
   the bare query. Passages were embedded without any prefix in every case.
2. **Candidates**: `embedding_store.candidates(conn, vector, n=100)` — the Stage 3 filtered
   call (canonical row present with the same `(content_sha256, model)` as the sidecar row;
   message and session pass `eligible_predicate`). Chunk rows collapse to messages by their
   **best (smallest) distance**; the message list is ranked by that distance.
3. **Filters**: the semantic candidates are then hydrated through the **same SQL and the same
   visibility, source, project, date and exclusion clauses the lexical arm uses**, restricted to
   the candidate ids. A candidate the lexical arm could not have returned is dropped here. This
   is what makes "hidden never returned" one predicate for both arms and keeps CLI ≡ MCP.
4. **Explicit syntax** (`fts:` prefix or bare FTS5 operators outside quotes) is the power-user
   door and stays **lexical only**; the semantic arm applies to natural-language queries.

## The one fusion

Reciprocal Rank Fusion, `k = 60`, over two message-level ranked lists — the lexical arm's top
50 (its own bm25 order, after the planner's AND→OR widening exactly as today) and the semantic
arm's top 50 — `score(m) = Σ_arms 1 / (k + rank_arm(m))`. Ties: present in both arms first,
then lexical rank, then newest `timestamp`. The fused list is cut to the caller's `limit`.
`k` is the literature default and is **not tuned** on DEV or anywhere else; there are no arm
weights; there is one fusion. `retrieval_status.mode` reports `"hybrid"` when both arms ran,
`"lexical"` with a `note` when the semantic arm could not run (extension or model unavailable,
no vectors, dimension mismatch, explicit syntax).

## Gates (all must hold to ship on by default)

| gate | definition | where measured |
|---|---|---|
| G1 established lift | paired cluster bootstrap (cluster = gold `cluster`, 10,000 resamples, seed 20260910, percentile CI95) of macro recall@5, hybrid − lexical; **CI95 lower bound ≥ +0.05** | **SEALED**, scored **once** by the owner with the model chosen on DEV. DEV is reported, never the gate |
| G2 K non-inferior | K-stratum paired delta CI95 upper bound ≥ 0 (freeze guardrail 5, the exact-match regression check) | DEV and SEALED |
| G3 census non-inferior | paired hit@5 delta hybrid − lexical, cluster = session, same bootstrap; **CI95 lower bound ≥ −0.01** (stricter than the freeze's point margin) | census on the chosen model's clone, both arms on the same file (guardrail 6) |
| G4 latency | gold DEV through the `mcp` arm, warm process, **p95 ≤ 146 ms** (Stage 1 p95 96 ms + 50 ms) | the chosen model's clone, live-size |
| G5 hidden never returned | zero hidden sessions across every arm on gold and census (guardrail 3) plus the unit test through `candidates()` | every run |
| G0 freeze guardrails 1, 2, 4, 6 | 0 crashes on `mcp`; `cli` ≡ `mcp` ranked ids on the 91; the explicit-syntax golden file unchanged; paired receipts share a DB fingerprint | every run |

## Model bake-off (DEV only; selection, not evidence)

Candidates are the three Stage 1 measured models, each backfilled into its own `VACUUM INTO`
clone of the live database with the Stage 3 job (no chunk cap, no truncation beyond the
model's own window): `sentence-transformers/all-MiniLM-L6-v2` (384-d, 256 tokens),
`BAAI/bge-small-en-v1.5` (384-d, 512 tokens), `sentence-transformers/all-mpnet-base-v2`
(768-d, 384 tokens). For each: gold DEV through `mcp` hybrid and `mcp` lexical **on the same
clone**, paired.

**Selection rule**, fixed now: the model with the highest DEV macro recall@5 point estimate
among those meeting G4; if none meets G4, the highest point estimate still goes to SEALED and
G4 fails honestly. Ties within 0.005 → the smaller model. The chosen model's clone then runs
the census (G3) and its name goes to the owner for the single SEALED run (G1, G2).

## Decision rule

- All gates hold → `semantic_search.hybrid` ships **on by default**; `retrieval_status.mode`
  is `"hybrid"`; the live migration and backfill remain owner-gated (D-9).
- Any gate fails → the hybrid mode ships **off by default** and the layer is called
  "lexical, semantic deferred", stated in ADR-0012 with the measured numbers. Which of the two
  R3 readings the programme then adopts is the owner's open decision (plan §Owner decisions 1);
  this stage does not make it.

## Reported, not gated

DEV point estimates and CIs per model; MRR@5; per-stratum recall; CLI cold-start cost (the
model load the CLI pays per invocation — measured, not gated: the gate is the long-lived MCP
process); the number of hybrid results that came from the semantic arm alone; census
`hit_rate_untied`; the mpnet/bge chunk counts and backfill times.

## Not done in this stage

No fusion tuning, no arm weights, no re-ranker, no chunk cap. If G4 fails on the chosen model,
**one** pre-registered secondary is allowed: a per-message chunk cap of 32 on that model,
re-measured through the same gates and labelled as the secondary. Nothing else is tried.
