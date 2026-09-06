# Stage 14 council decisions and reviewer calibration

## Before execution

Fable 5.1, Qwen3-Coder and Mistral Large 3 returned valid design responses. Grok 4.6 timed
out. These are three provider lineages, but they did not unanimously endorse the same
interpretation. Fable's concrete warnings were particularly useful.

Accepted before freezing:

- The port-correction source states work in progress, not completed code modification.
- Confirm the repository-check passage belongs to the voice question's session.
- State deterministic merge, deduplication and overflow behavior; log actual token counts.
- Keep test counts optional; applicability is more useful than recalling numbers.
- Label oracle selection, repeated cases, token length and order confounds explicitly.

Rejected:

- Mistral claimed the selected Parking result passages conflate study-plan CRUD. They
  explicitly name the Parking cards and persistence outcome; that criticism misread them.
- The suggestion to invent fresh Ladybug hard negatives would expand this real-snapshot
  control and change its provenance. The duplicated Q4 input remains a declared
  input-equivalence/stochastic control, not another independent retrieval question.
- No source was promoted from conversation report to independently validated artifact.

The coordinator recorded the corrections in spec.json before preparation and execution.
The original design brief/reviews remain preserved rather than being rewritten to match.

## First result review: why agreement was insufficient

All four providers received the same blinded twelve-answer Q1/Q3 packet. Fable failed
to return a JSON object; Grok timed out. Qwen and Mistral returned structured reviews,
both recommending blanket rejection. This is not a three-provider result consensus.

The coordinator rejected several stated reasons against the actual answer text:

- B03 explicitly says the safety issue was not confirmed as resolved. Both reviewers
  incorrectly accused it of claiming a completed correction. It has a different
  problem: it calls report-only CRUD/cleanup actually validated.
- B04 explicitly says there were no validation artifacts and qualifies the conclusion
  as conversational reports. Reviewing it as an implementation-validation claim invents
  a claim that the draft did not make.
- B05 really does say the port correction was completed. Its provenance caveat cannot
  turn the in-progress source statement into evidence of completion.

Consequently, reviewer agreement was not counted as ground truth or used to overwrite
the coordinator's previously recorded judgments. The first review packet emphasized
known risks; that may have encouraged blanket rejection. This is a methodological
concern, not proof of why either model failed.

A single bounded follow-up audits B03/B04/B05 with literal answer quotes, separate
completion/provenance questions and no prior reviewer verdicts. It is a diagnostic of
the reviewer, not a retry of any answering-model output or an optimization result.

## Focused audit outcome

All four providers returned a structured response to the three-answer audit. This is
four-provider coverage of those three cases, **not** consensus on the twelve-answer
packet or the whole trial. Qwen additionally used an unrequested REPORTED_ONLY label
where the audit requested OVERCLAIM/QUALIFIED/AMBIGUOUS; its opinion is retained but
must not silently be counted as a conforming classification.

Fable and Grok independently made the literal distinctions supported by the text:

| Draft | Completed-fix claim? | Validation wording | Coordinator decision |
|---|---|---|---|
| B03 | No | Overclaims actually validated CRUD/cleanup | Reject that claim; retain correct unresolved-fix statement |
| B04 | Not applicable | Explicitly qualified as conversation reports | No such validation overclaim; reported decision is supportable |
| B05 | Yes, unsupported | Qualified as report-only | Reject completed-fix claim; retain reported outcomes |

Mistral still labelled the literal denial of validation artifacts an overclaim.
That finding contradicts its quoted evidence and is rejected. Qwen blurred the two
axes in B03: citing its correct unresolved-fix language did not answer whether it
separately overstated validation. Neither opinion overrides the actual clauses.

The coordinator's earlier judgments were preserved unchanged. Fable/Grok support the
three-case distinction, but this selected audit does not calibrate general reviewer
accuracy or establish a permanent ranking of models. The change in judgment after a
smaller, more literal brief itself shows sensitivity to review framing and packet size.
No answering-model prompt was changed, and no answer was regenerated.

## Decision for the next iteration

Evidence selection has a demonstrated target on the failed development case: all four
reported-result facets can fit within 540 tokens and appear in the answer. However,
a richer pack is insufficient for safe conclusions. Test source-linked event state
and evidence basis as separate fields, with a verifier that does not promote either
plans to completion or reports to independent validation.

Review findings should cite the exact answer clause and exact source clause. A model
judge must be tested on both genuine overclaims and honest qualified answers; otherwise
blanket rejection can look like safety. Keep analyst uncertainty and human adjudication
visible. Work toward this bounded contract before automatic extraction or installation.
