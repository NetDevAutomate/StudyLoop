# Stage 7 results — A score can hide a better decision

## Pre-loop review

Three independently invoked model providers reviewed full source-only cases without
expected labels or prior outputs: Claude Fable 5.1, Grok 4.6 and Qwen3-Coder.
They supported a limited synthetic development proxy. They agreed that queue speed
could not be decided, artifact cases supported B only within fixture scope, and the
cache recommendation could be justified by requirement fit without claiming a benchmark.

A separate shuffled, anonymised review supplied each of the previous 24 answers
with its actual evidence. All three returned exactly 24 distinct item grades:

| Reviewer | Supported | Unsupported | Needs review |
|---|---:|---:|---:|
| Claude Fable 5.1 | 20 | 4 | 0 |
| Grok 4.6 | 20 | 4 | 0 |
| Qwen3-Coder | 20 | 0 | 4 |

The same four queue items were problematic: G06, G16, G18, G22. The coordinator
accepts the unsupported judgment because no performance evidence justified B.
Qwen identifies the same issue but labels it more cautiously. Qwen also generated
the original answers; its review is not independent validation of its own provider.
Twenty-four outputs represent four scenarios with repeated/overlapping contexts,
not 24 independent cases. No human ground-truth review has been completed.

Full readable review responses, mapping and packets are in observations/.

## Live loop

Qwen3-Coder proposed two amendments and answered the fixed cases through the local
gateway. Temperature zero; at most 1,500 output tokens per call; development cases
queue/retry twice each. Cache/storage were audited only after locking selection.

| Prompt | Integrity checks | Frozen development proxy | Queue recommendation |
|---|---:|---:|---|
| Baseline (Stage 6 v2) | 4/4 | 2/4 | B in both samples |
| Candidate 1 | 4/4 | 2/4 | insufficient in both samples |
| Candidate 2 | 4/4 | 2/4 | insufficient in both samples |

The frozen selector retained baseline because neither candidate strictly improved
its proxy. Only baseline reached the post-selection audit: 2/2 integrity and 2/2
proxy passes. **Candidate cache/storage behavior was not tested.** There is no
candidate regression or generalisation result on those scenarios.

16 calls completed (14 answer calls plus two proposals), with 21,918 reported total
tokens and $0.01003438 in gateway-reported cost. Every call returned cost metadata.
Council calls are additional and excluded; these figures are not the total task bill.
The observed provider alias does not pin a permanent underlying model revision.

## What failed in the evaluator

The queue rule demanded `recommendation=insufficient` AND
`evidence_basis=insufficient`. Both candidates correctly declined to choose but
labelled their sources `reported_only`. The explanations explicitly said neither
report was measured and a benchmark was needed. The score rejected those labels.

This is a **false negative in the proxy**: it conflates source type and decision
sufficiency. A separate test demonstrates a false positive: fabricated explanatory
claims can pass if the categories and citation IDs are acceptable.

A retrospective reading of the recommendation field alone gives 2/4 baseline and
4/4 for each candidate. That is a diagnostic after seeing results, not a replacement
score, a new winner, or a pre-registered improvement estimate. Both candidates'
queue explanations look better in these observed samples; broader usefulness is unproven.

Candidate 1 also contains a concerning exception: reports may be treated as
corrections when they explicitly supersede earlier advice. A correction to advice
is not performance validation. Candidate 2 leans toward artifact-only support,
which may over-restrict legitimate conditional requirement-fit advice. No automatic
promotion follows from either candidate's queue behavior.

## Preservation and verification

The exact executed runner was retained privately and its SHA-256 verified against
the run manifest before publication. The current runnable module adds saving the
initial candidate list and formatting changes; scoring, prompts and selection rules
are unchanged. Readable observations alias evidence IDs consistently to SourceNN
and omit the private runner hash. They contain synthetic material, not real sessions.

The default offline demo is scripted and deliberately selects candidate 1. Its
success demonstrates mechanics, not model improvement. The preserved live run above
retained baseline. Do not combine those results.

Tests cover bounds, proposal isolation from audit, tie behavior, audit regressions
without retuning, missing/invalid responses, no automatic retries, preservation of
attempts and the semantic blind spot. All 129 evidence-context tests passed after
adding five Stage 7 tests. Prior stage entry points remain separate.
