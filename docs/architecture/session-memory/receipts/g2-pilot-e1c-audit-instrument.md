# G2 pilot E.1c — audit instrument fault (recorded before any re-measurement)

**What happened.** The first blinded audit of writer-v2 output (deepseek-3.2, run `d7984adc`,
sample seed 20260911, 100 items) returned **17 yes / 83 partial / 0 no**. Before reading that as
the writer's entailment, the orchestrator checked the instrument and found two faults:

1. **The auditor brief was not held fixed.** Spec v2 declared "same auditor family, same
   blinding"; the v2 brief was rewritten from memory (2,183 chars vs 1,944) and added stricter
   wording ("every factual element… each number, name, cause, outcome"; "bundles three facts
   with quotes for two is partial"). That is a different ruler. Orchestrator error.
2. **The auditor failed known-answer items.** Items whose statement adds at most one content
   token beyond its quotes have a mechanically known verdict (yes). The v1 audit ruled 3/3 of
   these correctly; the v2 audit ruled **3 of 4 wrong** (A033, A043, A083 — its own `why` text
   says "identical but adds emphasis").

**Disposition.** The 17 % reading is **VOID as a gate measurement** (instrument fault), and is
kept on disk (`audit-verdicts-v2-deepseek.json`) as the record of the fault. It is **not**
evidence that v2 passed; v2's entailment is *unmeasured* until re-audited.

**Remedy (pre-declared here, before running).** The v1 brief is extracted verbatim from run
`faa5b262` into a committed template (`scripts/knowledge_proof/audit_brief_v1.md`; placeholders
for sample/out/auditor only). Two seats, same model, same brief bytes:
- **v2 sample re-audited** with brief v1 → the gate reading for writer-v2.
- **v1 sample re-audited** with brief v1 → measures the auditor's own run-to-run noise on a
  sample already scored (82 yes). The known-answer check is applied to both.

Reading rule: if the v1 re-run departs from 82 yes by more than the known-answer error rate
can explain, the auditor family is too noisy for a 95 % gate and that is itself a finding for
the ruler owner (the trigger is not relaxed). Council runs after this step: 17 / 60.

## Re-measurement result (runs `dce5a8f6` noise control, `43e38290` gate reading)

| seat | sample | brief | yes / partial / no | known-answer errors |
|---|---|---|---|---|
| faa5b262 (original) | v1 | A | **82** / 18 / 0 | 0 / 3 |
| dce5a8f6 (re-run) | v1 | A (pinned bytes) | **16** / 84 / 0 | 1 / 3 |
| d7984adc (voided) | v2 | B (drifted) | 17 / 83 / 0 | 3 / 4 |
| 43e38290 | v2 | A (pinned bytes) | **91** / 9 / 0 | 0 / 4 |

**Finding (instrument).** Same model, same brief bytes, same 100 items: 82 → 16 "yes";
per-item agreement 34 / 100, all 66 disagreements "yes → partial". The auditor is **bimodal**
(a lenient and a strict mode) with a repeat error far larger than the 5-point margin the gate
needs. Every v2 reading so far (17, 91) lies inside that swing. **No single-seat reading — v1's
82 included — is a valid G2 measurement.** The v1 pilot receipt's audit block stands as the
record of what was observed, not as a calibrated score.

**Protocol (declared before running; ruler text unchanged — it fixes "blinded, second family,
≥ 95 %", not one seat).**
1. Third deepseek-3.2 seat on each sample (same pinned brief) → **within-family majority of
   three** per item.
2. One gpt-5.6-terra seat on each sample (same pinned brief) → **cross-family** reading.
3. Reported per sample: majority-of-three yes-rate; gpt yes-rate; per-item agreement gpt vs
   majority; known-answer errors per seat. Gate reading for v2 = the *lower* of majority-of-three
   and gpt. Gate reading for v1 recomputed the same way (a fair v1-vs-v2 comparison needs both).
4. If the two families disagree by more than 10 points, or either family fails a known-answer
   item, the audit is **not measurable** with this method and G2 is recorded "not established —
   instrument" for the ruler owner. The trigger is not relaxed; no number is chosen by preference.
Council runs after this step: 21 / 60.
