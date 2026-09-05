# Stage 11 council review and coordinator arbitration

## Pre-run labels

Fable 5.1 (Anthropic), Grok 4.6 (xAI) and Qwen3-Coder (Qwen) each returned labels for
all twelve neutral case IDs before experiment calls. They saw original sources, targets
and the policy, without coordinator labels, case descriptions, prior scores or proposal
interventions. All original replies are preserved under observations/design-review/.

Eleven labels agreed. C05 differed: Qwen counted outside-block declarations as duplicates.
The coordinator retained A because the written rule explicitly excludes those lines.
The ledger records every reviewer label and rationale; no majority-vote gold was created.
These remain developer-authored rule labels with independent model review, not an
independent human-labelled or real-world holdout.

Fable and Grok requested a formal grammar and additional malformed-source controls.
Accepted: freeze GRAMMAR.md before execution, test same-value duplicates, invalid winner,
unclosed/malformed markers, trailing value whitespace, key case, ignored extra keys,
CRLF and Unicode line endings. These are offline implementation challenges, not new
live cases with unreviewed labels.

Rejected: replacing C01/C10 solely because their sources matched. They deliberately
isolate extraction omission while source and target remain fixed. The initial brief
hid interventions from label reviewers, so this purpose was not evident. The protocol
now states twelve conditions but eleven distinct source/target pairs. We agree that
they must not inflate an independence claim.

Qwen recommended loosening the policy to accommodate realistic malformed inputs. That
would change the experiment's meaning. We retained the narrow adapter contract and
explicitly limited applicability; arbitrary conversation text needs separate work.

## Result-review coverage

The first full result packet included all draft answers and detailed results. Qwen
returned a valid response. Fable failed structured JSON and Grok timed out. We preserved
those failures, then made one bounded retry with the same compact packet for all three.

The compact packet focused on C01, C03, C05, C06 and C11, both advisory repeats and both
policy outputs, plus adapter code and the overall results. Fable and Qwen responded;
Grok failed structured output. **Result review therefore has two successful provider
buckets, insufficient for a three-provider council.** The compact review is a five-case
focused audit, not a successful review of every answer. There were no further retries.

Qwen also reviewed drafts produced by its own model family; do not treat that as an
independent performance audit. Raw/parsed reviews and both brief versions are preserved.
Readable council text normalizes final newlines and trailing whitespace only; private
original artifacts retain exact bytes.

## Accepted findings

Fable's main qualification is correct: source_adapter is deterministic and does not
use the model to release a decision. The model calls expose advisory behavior; they
add no independent evidence about deterministic policy conformance. Report twelve
condition checks across eleven source/target pairs, with two model calls per condition.

The conservative gate's withholding on C01/C05 is correct under its own narrower
contract. Our false-block metric compares that result with what the complete source
justifies. It measures a trade-off in task usefulness, not an implementation bug.
This distinction is now explicit in RESULTS.md.

All four unsupported advisory outputs came from old failure cases. The fresh valid
responses already made the right choices. We cannot claim fresh-case evidence of
improved reasoning, model safety or general retrieval value.

Locatable quotes are not sufficient evidence. Their presence in all valid drafts,
including the unsupported decisions, is a useful counterexample rather than an answer
quality score. Source authenticity, explanation entailment and learner understanding
remain unmeasured.

The two source-parsing functions share underlying logic. Our tests cover some grammar
edges, but can share policy assumptions and fail together. Snapshot/span checks provide
identity and correspondence, not proof that an observed check actually happened.

## Reviewer hypotheses checked against the code and artifacts

- The C06 repeat-two failure came from response parsing: its raw text has an extra
  closing bracket. It was not an adapter exception and was never repaired or retried.
- C01/C10 have the same released decision and source facts. Their full traces intentionally
  differ because they retain different proposals, candidate checks and outer snapshot
  identities. Such trace differences are not evidence of proposal leakage into choice.
- Stage 8 requirement_match is fixed false and decision_mode measured in this adapter;
  requirement-fit recommendations cannot bypass the artifact requirement.
- Fable's suggestion that no exception should escape release needs an input boundary:
  valid snapshot inputs should produce a trace; an incomplete/invalid target deliberately
  raises an input error rather than being misreported as an evidence-based abstention.
- Qwen assumed internal policies are free of defects and synthetic sources reflect real
  edge-case frequencies. Neither assumption is established, and neither supports a
  product approval decision.

## Coordinator decision and bounded next evidence gate

Keep this as an independently runnable conformance stage. Prefer explicit source
rederivation over treating extraction omission as absent evidence when a trustworthy,
supported structured source is available. Do not promote the prototype as authentic
validation or require a new database engine.

Before integrating this adapter, perform a bounded differential parser check on about
20 independently labelled malformed and boundary-format examples. Compare recognized
fields, membership, reasons and locator resolution between declaration and span paths;
include valid controls to reveal over-blocking. Existing nine grammar-edge tests are
useful but not independently authored labels. Preserve failures rather than changing
labels until the parser passes. This has not been run as another live stage.

Then a small read-only sample of real, disjoint StudyLoop/MailGraph decisions should
establish which original artifacts and metadata are actually available. Human review
of whether explanations teach the right limitation remains necessary. Record source
versions and capture provenance before attempting general conversation extraction.
That evidence would inform schema and adapter boundaries; this synthetic result cannot
choose SQLite versus a graph database.
