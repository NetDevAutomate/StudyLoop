# G1 — the one SEALED look (reading)

**Receipt:** `stage-g1-sealed-look.json`, chained to `stage-f-look3-claims.json`. Candidate final at
`ceda1513` (arms unchanged since `94a11c1b`). SEALED gold sha `90ef67ad…` (84 questions, 56 clusters),
byte-verified against `gold-v2-receipt-r2.json` before the run; file mode 0400 before and after; the
path was used only by `score.py` run by the orchestrator on a fresh read-only copy of the store, then
the copy was deleted. This was the ruler's single permitted SEALED scoring run for G1.

| arm | SEALED macro recall@5 | K | P | R | DEV (look 3) |
|---|---|---|---|---|---|
| B0 / B1 (shipped) | 0.115 | 0.208 | 0.032 | 0.103 | 0.107 |
| **B1_clean** | **0.283** | 0.375 | 0.129 | 0.345 | 0.291 |
| recall_claims | 0.091 | 0.042 | 0.129 | 0.103 | 0.130 |
| B1_clean_plus_claims | 0.129 | 0.083 | 0.097 | 0.207 | 0.151 |

- B1_clean_vs_B1: Δ +0.168 CI95 [+0.076, +0.268] established=True non-inferior={'macro': True, 'K': True, 'P': True, 'R': True}
- B1_clean_plus_claims_vs_B1_clean: Δ -0.154 CI95 [-0.252, -0.065] established=False non-inferior={'macro': False, 'K': False, 'P': False, 'R': False}
- recall_claims_vs_B1: Δ -0.023 CI95 [-0.123, +0.078] established=False non-inferior={'macro': False, 'K': False, 'P': True, 'R': False}
- G1 clause on SEALED: macro 0.283 ≥ 0.64 → False | lift ≥+0.05 established → True | P point 0.129 ≥ 0.20 → False | ⇒ G1 NOT ESTABLISHED (bar), lift over shipped path ESTABLISHED on SEALED

## Verdict under the frozen ruler

- **G1: NOT ESTABLISHED.** The clause requires a fused arm at macro ≥ 0.64 on SEALED; the best arm
  reaches 0.283. No arm built in this programme approaches the bar.
- **Established on SEALED, and the programme's one shippable finding:** the prose-only FTS with the
  phrase-token OR planner (`B1_clean`) beats the shipped retrieval path by **+0.168** (CI95 lower
  bound +0.076, above the +0.05 rule), non-inferior on every stratum, replicating DEV (+0.184) on
  held-out data. Attribution from look 2 stands: the shipped AND-first planner (finding F-B0-1) is
  the main defect in today's retrieval.
- **Claims fusion replicates its DEV harm on SEALED** (−0.154, CI95 [−0.252, −0.065]) — the
  mechanism recorded in `stage-f-look3-reading.md` is not a DEV artefact.
- Paraphrase remains the unsolved stratum for every arm (best 0.129); this is where the ruler's G4
  (embeddings) was aimed and it was never reached.

## Composite claim

"The knowledge layers improve agent decisions" may not be written: G1 not established, G2 not
established (instrument), G3–G6 not reached. Recorded as such.
