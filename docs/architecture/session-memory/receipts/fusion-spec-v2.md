# Fusion spec v2 — the claims arms, declared before DEV look 3

**Declared:** 2026-09-10, after E.2 (receipt `g2-population-e2.json`) and before any look-3 run.
Supersedes nothing: `B1_clean` (v1) and `B1_planner` (v1.1) remain as declared. Ruler unchanged.

## Why these arms

ADR-0011's claim is that a claim-centric memory improves *retrieval*, not only fidelity. The
two arms below are the smallest pair that can test that under G1: one that retrieves through
claims **only** (to see whether claims carry retrieval signal at all), and one that **fuses**
claims with the best prose arm already measured (`B1_clean`, +0.184 established over B1),
which is the arm the ruler's G1 clause actually names ("fused (B1 + bound concepts only)").

## Coverage bound (stated before the look, so the result is read against it)

Claims exist for **222 of 345** population sessions (writer-v2, 1,227 claims, 1,877 citations,
0 unbound writes). On the DEV gold set, **19 of 60** gold sessions carry ≥ 1 claim, so a
claims-only arm can hit at most **30 of 91** questions (K 11 · P 6 · R 13). The fused arm is
not bounded this way because `B1_clean` supplies candidates for every question. Every
in-population session was attempted once; one session (population index 318, not a gold
session) received the single permitted retry.

## Arm `recall_claims` (claims-only)

- **Index.** At construction, build an in-memory FTS5 table (`unicode61`, porter) over every
  row of `claims` in the read-only store whose `writer` starts with `sonnet5/writer-v2/`,
  columns `title`, `statement`, `tags` (space-joined) — one row per claim, `rowid` = claim
  rowid. Refused/never-inserted claims are, by construction, absent. v1 claims are excluded
  (different writer; recorded so the arm is attributable to one writer).
- **Planner.** `learning_memory.store.plan_prose_query(question)` — identical to `B1_clean`.
- **Ranking.** `bm25(claims_fts)` over the top `CANDIDATE_ROWS = 200` claim rows; map each
  claim to its `session_id`; dedup by session, first occurrence wins; tie-break bm25 then claim
  rowid; return the first `K = 5` distinct session ids.

## Arm `B1_clean_plus_claims` (fused)

- **Inputs.** The full ranked candidate list from `B1_clean` (its `CANDIDATE_ROWS` prose rows
  deduped to sessions, **before** the K cut) and the full ranked session list from
  `recall_claims` (deduped, before the K cut).
- **Fusion.** Reciprocal rank fusion, `score(s) = Σ_lists 1 / (60 + rank_list(s))`, ranks
  1-based, both lists weight 1. `k = 60` is the standard constant; it is fixed here and not tuned.
- **Tie-break.** Higher RRF score first; then the session's best (lowest) rank in `B1_clean`;
  then the session id string. Return the first `K = 5`.
- **Nothing else.** No query rewriting, no evidence drill-down at ranking time, no per-stratum
  switching, no thresholds.

## What look 3 reads (pre-registered)

| comparison | question it answers | rule |
|---|---|---|
| `B1_clean_plus_claims_vs_B1` | the ruler's G1 clause on DEV | established iff lower CI bound ≥ +0.05 (`score.py` unchanged) |
| `B1_clean_plus_claims_vs_B1_clean` | do claims add anything over the best prose arm? | established iff lower CI bound ≥ +0.05; **non-inferiority on K, P, R each** must hold, else the claims arm *hurts* a stratum and that is recorded |
| `recall_claims_vs_B1` | do claims carry retrieval signal alone (within the 30/91 bound)? | descriptive; per-stratum hit counts reported against the bound |

**Stop rule.** This is DEV look 3 of ≤ 4; the two-flat-looks rule is armed from look 2. If
`B1_clean_plus_claims_vs_B1_clean` is not established, the G1 looks end here and the result is
recorded; no look 4 is spent on a variant. `B1_clean_plus_claims_vs_B1` established alone is
**not** a claims result (it would be `B1_clean` carrying it) and is reported as such.

## Harness change declared with this spec

`score.py` gains pairwise comparisons between feature arms (`<A>_vs_<B>` for every ordered pair
of non-baseline arms passed), so `B1_clean_plus_claims_vs_B1_clean` is produced by the committed
script, not derived afterwards. Statistics functions are untouched.
