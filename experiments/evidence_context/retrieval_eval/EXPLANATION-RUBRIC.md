# What a useful answer must explain

User clarification: the valuable outcome is an answer with validated context
showing how the conclusion was reached. For a learner, that explanation may be
more valuable than the answer alone. This changes the eventual success criterion:
retrieval recall is an intermediate measure, not the final goal.

## The answer's inspectable evidence trail

A good explanation connects:

1. The question and applicable constraints.
2. Specific observations, with source/version and exact evidence references.
3. What those observations support, distinguishing reported claims from directly
   observed validation artifacts.
4. Why the conclusion follows and why a plausible alternative is less suitable.
5. Assumptions, conflicts, scope/time limitations and what would change the answer.

This should be a concise, auditable rationale appropriate to the learner, not a
long narrative that merely sounds confident. More explanation text is not itself
better evidence. Avoid adding irrelevant alternatives just to fill the rubric.

## Human review rubric for a later answering experiment

Score each applicable dimension 0 (missing/misleading), 1 (partial) or 2 (clear and
supported). Record the evidence for the score; preserve dimension-level results
rather than hiding weaknesses behind a single total. Use N/A with a reason where
an alternative or validation claim is genuinely unnecessary.

| Dimension | What a score of 2 would require |
|---|---|
| Evidence fidelity | Material factual claims point to exact sources that actually support those claims. |
| Validation discipline | An agent's historical report is labelled as reported. A claimed validation names the observed artifact, check, result, revision/environment and applicable scope. |
| Connection to conclusion | The explanation shows which evidence and constraints justify the recommendation; unsupported inferences are explicitly marked. |
| Alternatives and trade-offs | Explains why a relevant alternative is less suitable under these constraints, without claiming an untested option is inferior. |
| Counterevidence and freshness | Addresses known corrections, contrary results and applicability dates instead of citing only favourable history. |
| Learning usefulness | The learner can explain the decision in their own words and identify what new evidence would change it. This requires learner feedback, not an automatic keyword score. |
| Uncertainty | Missing evidence is acknowledged; the answer does not convert an incomplete history into certainty. |

Invalid citations, forbidden-scope disclosure or falsely elevated validation are
separate failures. A fluent explanation must not compensate for them in an average.

## A concrete distinction (illustrative, not a real experiment result)

Weak: "Use A. We tested it before."

Better: "An earlier session reports that A passed a small test. We have the report,
but not its test output, so that is reported evidence. A currently fits constraint
X because of property Y. We have not compared B at this workload, so I would keep
A as the baseline and run comparison Z before claiming it is the better option."

Stronger validation would require the actual check output and its revision,
environment and limits. Even a passing check supports only the property it tested,
not a universal claim about the system.

## What stage 5 can and cannot score now

The current runner checks retrieval spans, citation integrity, scope/time and
payload. It does not produce answers, ingest validation artifacts, judge logical
support or assess learner understanding. Its results mark explanation_quality and
validation_claim_accuracy as not_measured. Citations resolve to conversation
records; they do not become independently validated facts.

For a later end-to-end evaluation, hold the answer model, instructions and actual
token budget constant. Randomize/blind the retrieval arm during review. Keep the
question/expected-evidence labels independent of generated answers. Use the above
rubric alongside retrieval metrics, then ask the learner which explanation helped
and why. Model judges can assist, but they cannot substitute for actual artifacts
or the learner's assessment.

The user's clarification is a product/evaluation requirement. It is not itself a
specific held-out question or an independently reviewed relevance label. The real
held-out dataset still needs that separate preparation.
