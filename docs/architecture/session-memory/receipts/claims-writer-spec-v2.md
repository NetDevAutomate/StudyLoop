# Claims writer spec v2 — the writer investigation (pre-registered before any v2 run)

**Declared:** 2026-09-10, after the G2 pilot receipt (`g2-pilot-e1.json`) and before any
`writer-v2` run. Ruler G2 on failure: "record; investigate the writer, never relax the trigger".
This document is that investigation, made falsifiable.

## What the pilot measured (v1)

| measure | result | gate |
|---|---|---|
| unbound writes | 0 / 180 citations | 0 ✅ |
| yield, primary denominator | 24 / 29 = 82.8 % | ≥ 90 % ✗ |
| entailment (blinded, deepseek) | 82 yes / 18 partial / 0 no | ≥ 95 % yes ✗ |

Decomposition of the 18 partials: **14 under-citation** (the extra details are present in the
session's evidence; the writer cited one sentence of several it drew on), **4 with material absent
from the session**. 86 / 100 claims carried a single citation. One session's 8 claims were all
refused because the writer cited row numbers instead of the 64-hex `evidence_id`.

## What v2 changes, and the failure each change targets

| change (prompt v2) | targets |
|---|---|
| "Every factual element in the statement must be visible in a quote" + an element-by-element self-check | 14 under-citation partials |
| "1 to 4 citations; prefer 2 or 3" | 86 % single-citation habit |
| `evidence_id` = full 64-hex copied from the row header; never row numbers | the 8-claim id-format refusal |
| `statement` ≤ 300 chars (was 500) | shorter statements are easier to cover completely |
| "Do not state as fact what the session merely implies" | the 4 absent-material partials, the 1 preference-inferred |

## What is held fixed (so the comparison isolates the prompt)

Model `claude-sonnet-5`; the **same 40 pilot sessions** in the same hash order; the same packets
(byte-identical, already on disk); the same harness (`claims_writer.py` at the receipt's commit,
with the cap-truncation deviation now part of the contract); the same insertion contract; the
same auditor family (deepseek-3.2), same blinding (statement + quotes only), fresh seed
(20260911) drawn over **v2 claims only**. Writer label `sonnet5/writer-v2/<sha8 of prompt v2>`.
v1 claims remain in the store (immutable, distinguishable by `writer`); the recall arm, if declared
later, names which writer it serves.

## Pre-registered reading of the comparison

- **v2 passes G2 on the pilot** iff entailment ≥ 95 % yes on the fresh blinded sample **and**
  yield ≥ 90 % on the primary denominator. Then `fusion-spec-v2` may declare the claims arm
  (over v2 claims) before DEV look 3, and E.2 (population) proceeds with v2.
- **v2 improves but does not pass:** record both receipts; a v3 is allowed only if the taxonomy
  names a new, specific defect. Two prompt rounds without passing → Stage E stops with the
  receipt (mirrors the ruler's two-flat-looks rule).
- **Yield stays < 90 % because of no-learner-voice sessions inside the denominator:** report
  yield on the primary denominator *and* on "primary ∩ has ≥ 1 learner turn"; the gate is judged
  on the primary; the denominator finding goes to the ruler owner. It is not changed here.
- Budgets: 40 more writer runs (→ 80 / 400); 1 auditor run (→ 15 / 60 council).
