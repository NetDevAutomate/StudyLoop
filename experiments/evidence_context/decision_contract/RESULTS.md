# Stage 8 results — A more inspectable decision, not a guarantee

## What was frozen before the answer run

Eight authored synthetic scenarios, explicit expected decisions/applicability labels,
a fixed new contract prompt, and the unchanged Stage 6 v2 prompt. Both prompts
received identical user payloads with structured source facts. No prompt search,
post-result label changes, or independent real holdout was involved.

The pre-run council returned three valid provider responses. Fable and Grok explicitly
labelled all eight cases consistently with the expectations; Qwen gave general
approval but omitted the requested case-by-case labels. Before running the model we
clarified measurement precedence, minimum citation coverage and insufficiency reason
codes, and clarified the wording of one requirement-fit report.

## Observed choice behavior

| Synthetic scenario | Expected choice | Legacy prompt | New contract |
|---|---|---|---|
| Reports only | Abstain | Abstain | Abstain |
| Matching artifact | B, within fixture scope | B | B |
| Wrong revision | Abstain | B | Abstain |
| Unknown revision | Abstain | B | B |
| Conflicting checks | Abstain | Abstain | Abstain |
| Wrong metric | Abstain | Abstain | Abstain |
| Requirement-fit reports | Conditional B proposal | Abstain | Conditional B |
| Requirement fit plus applicable check | B, within fixture scope | B | B |

The legacy prompt matched 5/8 choice categories; the new contract matched 7/8.
New-contract mechanical checks passed completely for seven cases. All sixteen
responses parsed and had valid citation IDs. One sample per condition is insufficient
to establish reliability or a general improvement. The legacy abstention on
requirement_fit is cautious and substantively explained; its label mismatch should
not be confused with the unsafe endorsement of a wrong-revision artifact.

The prompts and output schemas change together, so there is no causal attribution
to schema alone. The cases are highly related and share authored metadata; they are
not eight independent real-world questions. The model alias is Qwen3-Coder, not a
permanently pinned backend model revision.

## The failure worth studying

In `unknown_revision`, S3 has environment, workload and metric, but no revision.
The new model answer said:

> Artifact matches target environment, metric, workload, and implicit revision r2.

No source established that revision. The model appears to have imported the target
revision into the source's missing metadata. This is an interpretation of its visible
answer, not a claim about hidden internal reasoning. It then marked S3 applicable
and recommended B. The reference policy correctly produces unknown applicability,
insufficient evidence and no selected option. The evaluator flags applicability,
decision and citation-coverage mismatches.

In `wrong_revision`, the legacy answer noticed r1 versus r2 but still chose B, adding
a caveat. The new answer rejected that artifact for the target and abstained.
However, its next_check also suggested obtaining requirement-match reports even
though this case is measured mode. Such reports would not resolve the required
measurement gap. Mechanical checks do not grade that advice's usefulness.

## Deterministic reference versus model answer

The offline HTML walkthrough always follows the declared structured-fact policy.
It is not the live model output. In particular its unknown-revision example abstains,
while the actual new-contract model answer above did not. Read
`observations/results.json` for actual answers and `observations/reference.json` for
the reference. `observations/live-inputs.json` preserves both prompt conditions and
pre-run expectations, with fingerprint values omitted from the readable copy.

This distinction matters: a correct policy implementation does not prove an LLM
will follow that policy. The reference policy could inform a later deterministic
gate, but trustworthy extraction, source authenticity and semantic support still
need their own checks.

## Cost and verification

Sixteen completed answer calls reported 17,442 total tokens and $0.01011932 through
the gateway. Every response included cost metadata. Council calls are additional;
these figures are not the complete task bill. No provider retry or optimisation was
performed for the answer probe.

All 145 evidence-context tests passed, including sixteen Stage 8 tests. Coverage
includes reviewed labels, mismatch-versus-unknown priority, scope casing, extra
metadata, conflicting/absent requirement fits, measurement precedence, empty inputs,
citation coverage, invalid output combinations, bounded failures and preserved
semantic blind spots. The generated HTML has eight expandable scenario tables.
No production database, installed integration or database engine was changed.

## Explanation review matters more than the aggregate

The first result-review round had two valid providers. Fable marked twelve answers
supported, three unsupported (new and legacy unknown-revision, legacy wrong-revision),
and one needs_review (legacy's cautious requirement-fit abstention). Those judgments
fit the recorded answers. Qwen produced a contradictory grade set, including penalizing
correct abstentions merely because evidence was insufficient; the coordinator rejected
those grades. Grok returned invalid JSON on its first attempt and its one bounded retry, leaving
two valid result reviewers. This is insufficient diversity for a strong three-provider
result council. The design review had all three providers. See COUNCIL-DECISION.md
and the preserved review files for the exact coverage and coordinator arbitration.

This distinguishes the main behavioral improvement from a label change: correcting
the wrong-revision endorsement matters more than changing a cautious abstention into
a conditional proposal. Neither result measures whether a learner better understands
the decision. The wrong-revision new answer's unhelpful report-seeking next_check is
also retained as an explanation-quality limitation beyond the mechanical score.
