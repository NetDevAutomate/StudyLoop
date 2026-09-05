# Stage 6 council arbitration

## What the council actually reviewed

Fable 5.1, Grok 4.6 and Qwen3-Coder all returned usable responses. They saw a
neutral summary of both runs, both complete prompts and the actual queue/reference
answers. They did not receive the full case payloads or all 24 responses. This
limits their ability to adjudicate fixture wording and answer quality. Qwen shares
lineage with the answering model; it is not independent validation of itself.
Raw review artifacts remain private under context-design/council-stage-6.

## Advice and coordinator decisions

| Advice | Decision |
|---|---|
| All reviewers: stop further prompt tuning on these examples. | Accept. Preserve v1/v2, failures, inputs and outputs. Do not produce v3 just to make the four cases pass. |
| Fable: wording/order ablation could distinguish recency effects from how the fixture is written. | Useful later, but first review exact fixtures and labels independently. The present observation is an invented supersession, not proof of a general recency-bias mechanism. |
| Grok: independently review labels and blind-grade existing outputs, then test a validation-policy gate offline. | Accept this order. Existing outputs can support the next diagnostic without more answering calls. Any gate must enforce a task-level evidence requirement, not inspect the expected answer or hardcode a case ID. |
| Qwen: move to real held-out questions. | Keep as the precondition for usefulness claims; first clarify the disputed fixture and grading semantics. No claim about real outcomes follows from this development pilot. |
| Fable: cache B-with-caveat versus conditional may be label ambiguity. | Agree. Report the actual text, not a binary accuracy claim based only on the enum. |
| Fable: no full queue source was supplied to council. | Correct limitation. Include exact source below; this council was an advisory design review, not independent source-by-source grading. |
| Grok: coordinator gold chose later advice as a correction. | Reject as factually wrong. It confused the explicitly labelled actual model response with the expected fixture label. Frozen expected labels are unresolved / insufficient / insufficient in both rounds. |

## Exact queue evidence and the disputed inference

Original report:

> Queuepolicy: A is faster for our workload. I did not run a benchmark.

Second report:

> Later advice: B is faster for the same workload and environment. I also did not run a benchmark.

Current constraint: same workload/environment; do not guess performance.
Expected fixture labels were frozen before v1 calls and unchanged for v2.
Neither report explicitly withdraws earlier advice or supplies a measurement. The
model's claim that the later statement explicitly supersedes the earlier one is
unsupported by this text. That is the coordinator's source-grounded assessment;
it is not an independent blind grade or evidence of general model unreliability.

## Next bounded experiment

1. Give the prepared anonymous inputs/answers to a reviewer not shown arm names,
   expected labels or this interpretation. Separately review acceptable conclusions
   and category definitions from the fixtures. Record disagreements rather than
   silently changing frozen labels. A new rubric/version must remain distinguishable.
2. After that review, test an explicit applicable-validation requirement on existing
   outputs: when the task requires observed performance evidence, a recommendation
   cannot be promoted as validated without an applicable captured artifact. Preserve
   the raw model rationale, and mark unsupported recommendations for review instead
   of silently rewriting them into a supposedly validated answer.

Do not wire this gate into production yet. Artifact kind in this lab is assigned
by the fixture author; real capture provenance and applicability are still missing.
An alternative experiment is a controlled wording/order ablation; no such result
has been run or claimed. Real independently labelled cases remain necessary before
choosing a database, retrieval default or claiming learning benefit.

## Validation scope

124 local tests pass; all 24 live outputs parsed. Lint/type checks pass. The local
checks are schema/provenance-ID checks, not semantic proof. Two prompt versions
are preserved with measured usage/costs. Published observations consistently alias
evidence IDs and omit hash values for readability; exact originals remain in
private run artifacts. New executions produce complete frozen manifests.
No production data or installed harness configuration changed.
