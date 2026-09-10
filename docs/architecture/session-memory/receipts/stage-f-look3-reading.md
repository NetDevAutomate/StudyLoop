# DEV look 3 — reading (G1 family, look 3 of ≤ 4; two-flat-looks stop rule FIRED)

**Receipt:** `stage-f-look3-claims.json` (chained to `g2-population-e2.json`). Arms declared in
`fusion-spec-v2.md` (94a11c1b) before the run. DEV gold sha `5632cd2b…`, 91 questions, 57 clusters.

| arm | macro recall@5 | K | P | R |
|---|---|---|---|---|
| B0 / B1 (shipped) | 0.107 | 0.182 | 0.034 | 0.103 |
| B1_clean (v1) | **0.291** | 0.424 | 0.172 | 0.276 |
| recall_claims (v2, claims only) | 0.130 | 0.182 | 0.000 | 0.207 |
| B1_clean_plus_claims (v2, RRF k=60) | 0.151 | 0.212 | 0.034 | 0.207 |

| pre-registered comparison | Δ macro | CI95 | reading |
|---|---|---|---|
| `B1_clean_plus_claims_vs_B1_clean` | **−0.140** | [−0.245, −0.041] | **not established; the fused arm is significantly WORSE than prose alone** |
| `B1_clean_plus_claims_vs_B1` | +0.045 | [−0.054, +0.147] | not established |
| `recall_claims_vs_B1` | +0.023 | [−0.073, +0.125] | descriptive: claims alone match B1 on K, beat it on R (0.207 vs 0.103), score 0 on P; within the 30/91 coverage bound |
| `B1_clean_vs_B1` (reproduction) | +0.184 | [+0.092, +0.281] | identical to looks 1–2 |

## Stop rule

Look 2's declared comparison (clean-over-planner) was not established; look 3's is not
established. Two flat looks → **the G1 DEV looks end here**. No look 4 is spent on a variant.
G1 on DEV stands at `B1_clean` +0.184 established over B1; the claims arms add nothing that the
looks could establish.

## Mechanism (read from the look-3 receipt and the same arms; no new look)

Hit matrix (clean, claims, fused): both-miss 59 · clean-only 17 · all-three 7 · claims+fused 4 ·
clean+fused 3 · claims-only 1. The fused arm **lost 17 questions `B1_clean` had and gained 4.**
On the 17 lost: the gold session was ranked **1st or 2nd by prose in 12/17**, was **absent from
the claims list in 16/17**, and landed at fused rank 7–39. The claims list (OR-planner over
claim text) is ~127 sessions long for a typical question, so equal-weight RRF gives every
claims-only session 1/(60+k) that a prose rank-1 session (1/61) cannot beat once the claims list
ranks it anywhere in its top ~60. **The declared fusion rule promotes any session matching a few
question tokens in any claim above the best prose hit.** This is a property of RRF over an
unweighted, high-recall/low-precision second list — the same failure a naive union would show —
and it is why the pre-registered attribution comparison was the right one to read.

## What this does and does not say

- It does **not** say claims carry no retrieval signal: `recall_claims` alone beats the shipped
  path on relational questions (0.207 vs 0.103) with a third of the corpus covered, and is
  exactly zero on paraphrase — claims are written in the assistant's vocabulary, not the
  learner's.
- It **does** say that fusing claims as a peer candidate list into the best prose arm is the
  wrong design, and that ADR-0011's retrieval benefit is **not established** on DEV under G1.
- Under the ruler, "not established" is a recorded outcome, not a failure to be re-tried. The
  looks are spent; any different fusion (weighted, claims-as-re-ranker, evidence drill-down) is a
  new pre-registration for a future programme, not this one.
