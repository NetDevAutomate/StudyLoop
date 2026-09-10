# Receipt council — Stage D DEV looks 1 and 2 (G1 family)

Ruler: "A gate passes only when … a two-family council review of the receipt finds no blocking
objection to its validity. The orchestrator may override a council objection only by citing
artifact evidence that refutes it, recorded in the receipt. Council findings are otherwise leads:
nothing is acted on until verified against the artifact."

| seat | model | run | reviewed | verdict |
|---|---|---|---|---|
| A | gpt-5.6-terra | `4ed818c7` | look 1 (`ca55c653`) | **VOID** — 4 blocking |
| B | deepseek-3.2 | `74685923` | look 2 (`543edf45`) + amendment-002 + r2 | **VALID-WITH-NOTES** — 1 blocking |

Council runs after this record: 13 of 60.

## Seat A (look 1) — dispositions

Every statistic re-derived exactly by the seat (macro recalls, paired cluster bootstrap CI95
[+0.091562, +0.281404] with the receipt's seed, per-stratum non-inferiority); arm conformance to
fusion-spec v1 exact; 91/91 questions returned exactly five distinct ids; no gold-controlled
ingestion or ranking path. The blocking findings were all provenance-record findings.

| # | finding | verified | disposition |
|---|---|---|---|
| A1 | candidate commit equals the spec commit rather than postdating it | true | **not void** — the ruler requires declaration *before the look*; spec and arm were committed at `690a37d4` and the look ran from that HEAD 10 s later; receipt commit `ca55c653` postdates both. Receipts now record `fusion_spec.declared_commit` for a mechanical check. |
| A2 | no fusion-spec field on the receipt | true | **accepted** — `score.py` records `fusion_spec.{path, sha256, declared_commit}`. |
| A3 | gold receipt `dev.sha256` does not identify the DEV file | true, and `sealed.sha256` does not identify the SEALED file either | **accepted; void upheld** — Stage 2 record defect; see amendment-002. |
| A4 | gold receipt `corpus_digest` ≠ result receipts'; ruler voids on mismatch | true; `a0df30bb…` reproduces from no item set | **accepted; void upheld** — cannot be overridden: the refuting evidence does not exist. |
| A5 | B1-vs-B0 non-inferiority not recorded on the aggregate | true | **accepted** — `non_inferiority_macro` on every comparison. |
| A6 | intervention bundles planner + index; scope filter differs | scope: `visibility_sql` excludes 0/5,879 — not a confound; bundling: true | **accepted as a measurement question** → `B1_planner` control, declared in spec v1.1 before look 2. |
| A7 | the 42 errors are not the whole lift (49-question subset 0.494 vs 0.320 correct) | true | note; confirmed by look 2's control. |
| A8–A9 | arm conformance exact; statistics re-derive exactly | — | notes. |
| A10 | store not cryptographically bound; `KNOWLEDGE_PROOF_STORE` can redirect | true | **accepted** — `--store` records sha256 + size on the receipt. |
| A11 | DEV evidence only; not a G1 pass | true | affirmed in every receipt's wording. |

Outcome: **look 1 voided, still counted** (the number was seen). Remedy: ruler-amendment-002,
`gold-v2-receipt-r2.json` via committed `recertify_gold.py`, harness provenance fields.

## Seat B (look 2 + remedy) — dispositions

| # | finding | verified | disposition |
|---|---|---|---|
| B1 | look 2's `previous_receipt_sha256` hashes the look 1 file **after** an in-place `VOIDED` edit, not as committed at `ca55c653` | true (`c4d52cea…` vs committed `ec9d6576…`) | **accepted (blocking)** — the orchestrator's error. Look 1 restored to its committed bytes; the void notice moved to a sidecar (`stage-d-look1-b1clean.VOIDED.md`); look 2 re-run chained to the pristine file; all four arms reproduced identically; chain verified `previous_receipt_sha256 == sha256(git show ca55c653:…)`. **Rule adopted: a receipt is never mutated after commit; annotations live in sidecars.** |
| B2 | `B1_planner` omits `visibility_sql`, so "identical to B1 except the planner" was not literally true (0 sessions excluded, so no recall effect) | true | **accepted** — predicate added; per-question hits identical; spec claim now exact. |
| B3 | `B1_planner` recovers 5 questions B1 threw on; supports planner attribution | true | note. |
| B4 | r2 hashes reproduce from committed code + gold files + DB | reproduced by the seat | the remedy holds. |
| B5 | clean-index increment Δ+0.042 CI95 [+0.009, +0.085] not established | true | recorded as such in the look 2 receipt commit. |
| B6 | look 2 is not an "improvement" (lower bound unchanged at +0.092) | true | **stop rule 2 armed: one more flat DEV look ends Stage D's G1 looks.** |
| B7 | amendment does not weaken SEALED protection (`corpus_digest.sealed` recorded; SEALED receipt must match it) | — | note. |

## Standing of the measurements

- **Look 1** — voided for provenance; numbers re-derived exactly by seat A and reproduced by look 2.
- **Look 2** — valid after B1/B2 remedies: `B1_planner` 0.249 (+0.142 vs B1, CI95 [+0.060, +0.231],
  established); `B1_clean` 0.291 (+0.184, CI95 [+0.092, +0.281], established); clean-index
  increment +0.042 (CI95 [+0.009, +0.085], **not** established; never loses: 4/0/87).
- **Attribution:** the planner is most of the effect. The shipped AND-first query form is too
  strict independent of crashing (0.479 vs 0.320 on the 49 questions it answered). F-B0-1 is
  thereby a *measured* defect in the shipped path worth +0.142 macro recall@5 on DEV.
- **G1 is not claimed.** DEV looks used: 2 of 4. SEALED untouched.
