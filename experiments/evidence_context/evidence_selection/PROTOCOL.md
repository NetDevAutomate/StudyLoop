# Stage 14: frozen evidence replacement and distraction control

This stage follows the Stage 12 failure, not a new holdout. It tests a candidate cause:
missing relevant evidence and confusion between neighbouring episodes. No production
retriever or prompt is changed. Source bodies stay in the ignored private archive.

Four original questions, three evidence conditions, two calls per condition =24 calls.
Use the same Qwen3-Coder answering alias, original Stage 12 system prompt, temperature 0,
max 1500 output tokens, six-passage cap and 1400 evidence-token ceiling. Use the same cached
Qwen tokenizer. Equal ceiling is not equal actual length; report counts and cost.

1. original: exact Stage 12 combined pack, freshly answered to avoid historical-run effects.
2. reviewed_only: preselected source passages covering the reviewed facts, no filler.
3. reviewed_plus_original: same required passages first, then original pack order as filler.

Reference passages are checked against pre-run episode labels; they are an oracle
selection, not an automatic retriever. Require all reference passages to fit, without
silent truncation. Deduplicate by ID. Reject any passage outside project/time eligibility.
Filler never displaces a required passage. At Q4 reference is deliberately empty; adding
the original pack reproduces the baseline. That empty arm tests abstention with no
support, not reference-retriever quality.

Scope and timestamps are inherited from the historical snapshot. A session-created
fallback timestamp is not proof of strict historical availability. This study does not
validate capture, work isolation, synced deletion, or real artifact authenticity.

Freeze the full requests, rubric/spec, code and input hashes before calls. A changed
bundle or runner is rejected by the execution step. A started paid run cannot be
implicitly repeated; preserve failures and raw responses. Two client workers, seeded
order, no application retries. Same strict JSON parse and full-fence-only allowance as
Stage 12. Categories and exact quote checks remain mechanical, not meaning validation.

Before answers, a provider-diverse council reviews the design and reference evidence.
Retain valid outputs, malformed responses, failures, disagreements and coordinator
arbitration. Do not call an oracle improvement an implemented retrieval improvement.

After answers, evaluate every output against the frozen case facets. Record faithful
coverage, any material unsupported inference, and whether reports are mistaken for
independent validation. Overall labels: supported (sufficient and faithful), partial
(honest incomplete), unsupported (material inference/episode error), invalid (schema/
parse failure). Judge prose, limitations and citation claims, not only evidence_status.
Separate exact-quote formatting mistakes from entailment. Council reviews blinded
answer IDs and allowed source IDs, with special attention to the failed Q1/Q3 questions.
Qwen reviews are dependent on the answering model lineage. No model vote establishes truth.

No tuning based on outputs. Improvement with reviewed context supports an information
selection bottleneck on these cases, but source density, order and distractor mix also
change. Adverse effects after filler motivate a future position/counterbalance control.
A fresh case set and human-adjudicated labels are needed before general efficacy claims.
