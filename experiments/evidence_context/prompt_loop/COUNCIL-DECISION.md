# Coordinator decision — Preserve the failed metric before redesigning it

## Before optimisation

Source-only and blinded-output reviews each received three valid provider responses:
Claude Fable 5.1 (Anthropic), Grok 4.6 (xAI) and Qwen3-Coder (Qwen). Source-only means
expected labels and prior answers were withheld; it does not mean our fixtures were
independently authored or that the reviewers have no shared model biases.

Accepted: conditional requirement-fit can be reasonable without performance proof;
fixture artifacts support only their stated scope; later unmeasured claims do not
establish performance corrections. A limited mechanical development score is usable
for a loop demonstration, but not as a measure of learner usefulness or factual truth.

Implemented: two bounded candidate amendments, frozen scorer, separate development
and post-selection audit, saved failed/rejected attempts, offline runnable version,
no automatic promotion. Fine-grained conflict labels were deliberately not scored.

What we missed: the remaining evidence-basis label still mixed provenance with
sufficiency. General approval of a limited proxy did not validate every label rule.

## Result review and coordinator arbitration

The result review received the complete live ledger, results, executed runner and
tests, with limitations disclosed. It was advisory review, not blinded answer grading.
Only Grok and Qwen returned valid responses: this round has insufficient diversity
for a strong three-provider council. Fable initially returned invalid JSON; one
provider-call retry with the identical brief also failed. An intermediate single-
provider command was rejected by the launcher before any call, because its default
minimum is three providers. The explicit single-provider retry was a retry only,
not a substitute council. We stopped there and retain the limitation. The two
pre-loop review rounds did each obtain all three providers.

Grok correctly identified the queue scoring false negative and that only baseline
was audited. Its recommendation to separate decision fields and review citation
support is accepted. Its claim that exposing development labels is necessarily
holdout contamination is rejected: training labels are intentional feedback here.
They do make fitting these cases easier; disjoint evaluation is still essential.

Qwen correctly advised against promotion, but claimed improved integrity scores and
candidate audit degradation. Neither happened: integrity stayed 4/4 for all three
prompts and candidates never reached audit. Those claims are rejected against the
ledger. Overfitting is a risk, not an observed audit result. Model agreement is not
an authority that can override recorded execution.

## Decision

Keep this Stage 7 checkpoint as a learning artefact. Preserve baseline as the frozen
selector's recorded result, while clearly reporting that both amendments improved
the queue recommendation in the observed samples. Neither is a production winner.
Do not silently repair RULES and rerun until a desired result appears.

The next discriminating stage should version a clearer answer contract:

- **Source kind:** report, observed artifact, or other provenance.
- **Validation applicability:** whether the artifact matches the claim, revision,
  workload and scope; unknown is a valid state.
- **Decision sufficiency:** supported, conditional or insufficient, with a cited reason.

First challenge that contract with paired counterexamples: later advice without a
measurement; a real-looking artifact for the wrong revision; directly conflicting
applicable artifacts; and conditional requirement-fit without a benchmark. Review
labels before viewing model answers. Compare fixed baseline/candidate behavior on
new, independently reviewed cases and use a different provider for answer review.

A small real disjoint-session question set remains the gate for product claims.
Record scope and deletion boundaries when assembling it. This stage does not yet
implement the new contract, a validation gate, a real holdout, or a DSPy adapter.
Those should be independently runnable subsequent stages rather than changes hidden
inside this completed experiment. No database-engine choice follows from this run.
