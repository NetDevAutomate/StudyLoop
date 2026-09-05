# Stage 5 council arbitration and result

## Scope and provenance

Fable 5.1, Grok 4.6 and Qwen3-Coder all returned usable responses through the
healthy local gateway (Anthropic, xAI, Qwen). The same brief contained measured
stages 1–4 results/limits, stage-5 scorer source, synthetic outcomes and the user's
validated-explanation goal/rubric. No real transcripts or credentials were sent.
Private artifacts are under context-design/council-stage-5, including the exact
brief, comparison JSON/Markdown and per-provider responses.

The reviewed snapshot had 109 passing tests. Later local changes described below
were not re-reviewed by the council. No review is claimed for unseen source files.

## Recommendations and coordinator decisions

| Input | Decision |
|---|---|
| All three: synthetic results do not justify a product/database choice. | Accept. This stage establishes scorer behaviour only. No integration or engine recommendation follows from the engineered gain. |
| Fable: include control-arm paired differences. | Implemented explicit shuffled-versus-keyword and relationship-versus-shuffled span deltas and control byte delta. |
| Fable: check edge time leakage, not only passage dates. | Added independent returned-edge checks and future-edge tests, including a forged edge with valid old passages. Earlier retriever tests already enforced this; now the evaluator independently detects it. |
| Fable: unanswerable cases need a retrieval outcome. | Added neutral empty_context, unjudged_context, related_but_insufficient_context or contains_labelled_irrelevant_evidence. Reject inferring model confidence or abstention from those labels. |
| Grok: a small independent real holdout before further features. | Accept a 3–5 case feasibility pilot, not a powered efficacy study. Use naturally occurring disjoint questions and independent evidence review. No obligation for the user to author twenty questions. |
| Qwen: answer-generation trials now. | Defer until independent labels/artifact availability are established. Keep the user's explanation rubric, then apply it in a separate blinded answering stage with a fixed model and actual token budget. |
| Qwen: the scorer conflates citations with validation. | Accept the risk but reject that description of the reported result: answer/explanation/validation accuracy are explicitly not_measured. Citation validity is source fidelity only. Keep this distinction prominent. |
| Fable/Grok: growing test count is not retrieval efficacy. | Agree. Test counts describe implementation checks, not user benefit or improved decision quality. |

## Final local validation and observations

113 tests pass across the experiments (15 new evaluator tests), with clean Ruff
and focused Pyright. The final demo freezes four synthetic records and three
cases before queries. All nine case/arm runs have valid citations and no detected
scope/time/edge violations within the scorer's checks.

- Required counterevidence: keyword span recall 0.5; reviewed relationships 1.0;
  rewired control 0.5. Relationships add 1817 bytes versus keyword. Engineered gain.
- Exact-match case: no required-span gain; relationships add 1805 bytes.
- Missing topic: no results, null recall and empty_context outcome. Answerer
  abstention and learner usefulness remain unmeasured.

The control is one seeded target-rewiring, not degree-preserving randomization.
No statistical or latency superiority is inferred. Synthetic fixture labels were
constructed with the experiment, so they cannot be promoted to held-out evidence.

## Next decision

Prepare the small real candidate set following HOLDOUT-PROTOCOL.md. Until evidence
labels and lineage separation have independent review, report development or
candidate results only. No automated scoring trick establishes that independence.

The user's requirement is an answer with an auditable, educational evidence trail.
Retrieval metrics establish prerequisites. A separate answer-stage evaluation must
assess support, validation artifacts, explanation and learner feedback. No result
here proves that an agent's historical statement is true.
