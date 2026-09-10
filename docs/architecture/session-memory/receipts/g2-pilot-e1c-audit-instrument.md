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
