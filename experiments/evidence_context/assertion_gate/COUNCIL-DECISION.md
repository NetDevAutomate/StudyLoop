# Stage 15 council arbitration

Decision: preserve this strict contract as a completed learning stage. The next
experiment should test **production of source-backed annotations**, keeping source
integrity, evidence origin and semantic applicability as separate measurements.
No gate or prompt was changed after the live run; no answer was regenerated.
No production implementation, new database or signing infrastructure was introduced.

## Who reviewed what

| Round | Packet | Usable responses | Failures |
|---|---|---|---|
| Design | Cases, expected labels, proposed gate and controls | Fable 5.1, Qwen3-Coder, Mistral Large 3 | Grok 4.6: no text |
| Results | All 32 drafts/releases, cases, gate and controls | Qwen3-Coder, Mistral Large 3 | Fable: malformed/truncated JSON; Grok: timeout |
| Focused result retry | Five selected drafts/releases, relevant sources, code, two gaps and full-run aggregates | Fable 5.1, Qwen3-Coder, Mistral Large 3 | Grok: timeout |

Four provider lineages were requested with two workers and bounded timeouts.
The full result round had insufficient diversity. The focused retry had three
provider buckets, but it did not independently review every response. All providers
received the same packet within each round. The selected five examples were C02,
C08, C17, C26 and C30; they were selected diagnostically, not blinded or held out.
Qwen was both answering model and one advisory reviewer. No council output is an
independent human gold label, nor does reviewer agreement establish event truth.
Raw packets, invalid replies and comparisons are retained in the private archive;
council-coverage.json records public coverage and recommendations.

## Before the trial

Fable approved all eight expected assertion-ID sets, but requested an explicit
basis-forgery probe, a dangling-correction probe, raw-input scoring caveats and a
qualification that labels are asserted rather than verified. These were accepted.
Additional scope/project/type checks were completed before the bundle was frozen.
The initial review packet remains unchanged for comparison.

Qwen supported the conditional contract experiment and asked that forged metadata
be demonstrated. Mistral rejected synthetic observed fixtures without cryptographic
attestation. I retained them as explicitly simulated fixtures: a unit experiment
can stipulate labels, provided we do not claim to have authenticated an event.
The fixture cannot support a claim of provenance detection without that information.

## Findings checked against saved evidence

**Accepted: metadata disclosure tests conformance, not extraction.** Every annotated
response followed the supplied labels. Copying is sufficient. No automatic annotation
pipeline or independent held-out annotation was evaluated.

**Accepted: C26 differs from C02/C05.** C26 promotes a conversation report to observed.
C02/C05 select a weaker reported basis when the observation origin is absent from
the raw input. The exact same input receives a different hidden label in C08/C20.
All three are basis mismatches, but they are not three unsafe model claims.

The full Mistral review incorrectly described all three as reported-when-observed,
including C26, and called 3/16 a false-withholding rate. That is rejected: C26 is
observed-when-reported. Qwen's blanket “incorrect evidence labeling” description
also loses the information-omission distinction. The focused review improved the
diagnosis but does not retroactively correct those original responses.

**Accepted: prose and typed claims require separate treatment.** Fable distinguished
C17/C30's matching typed labels from their stronger, insufficiently attributed prose.
The renderer uses the former and excludes the latter. This supports retaining an
explicit release boundary, not treating a valid JSON draft as a validated answer.

**Accepted: the ledger is an upstream trust dependency.** The two controlled forged
labels produced false semantic releases while source text and hash stayed unchanged.
The gate checks agreement with labels, not their justification. The frozen trial
bundle does detect later edits to that bundle before live execution; this does not
make an initially incorrect annotation correct. Do not conflate the standalone
check() trust boundary with the separate runner's frozen-bundle guard.

**Rejected: replacing the raw score with Fable's suggested “closer to 15/16.”** That
would change the evaluation after seeing outcomes. Keep the original counts and
explain the two omission controls. Abstention is also defensible when provenance
is unavailable; reported is not the only possible responsible model response.

## Why source-backed annotation is next

All three usable focused reviewers recommended grounding annotations in source
references or tool artifacts. Fable and Mistral also proposed signatures. I accept
the source-binding direction but do not adopt a signing service or new store yet.

A signature proves who signed particular bytes, subject to its trust model. It does
not prove that the signer correctly interpreted a report as an observation, selected
the right target, or inferred a justified completion state. A correctly signed wrong
annotation would retain the failure this user most cares about: a confident but
poorly justified answer. Merely repeating the two known forgery probes under an
unchanged gate, as the initial Qwen recommendation suggested, adds little new data.

The next small study should:

1. Preserve actual origin metadata from controlled, disposable harness/tool events,
   alongside matching narrative reports. Include a report quoting a successful tool
   output, a genuine scoped output, wrong-target output and missing-origin cases.
   Do not infer origin from words such as PASS, verified or exit status zero.
2. Compare transcript-only annotation against transcript plus capture metadata.
   Keep the answer contract fixed and do not reveal expected state/basis labels to
   the annotator. Label new cases independently before examining its answers; any
   model-only adjudication remains an explicitly provisional development label.
3. Measure source-origin classification, target applicability, unsupported state/basis
   promotion, unknown preservation and justified claim retention separately. Keep
   report-to-observation errors distinct from observation-to-report conservatism.
4. Inject both changes made after capture and incorrect labels produced before
   freezing/signing. Report integrity failures separately from semantic failures.
   A receipt/manifest may detect altered bytes; correctly preserved wrong labels
   must remain a negative control, not disappear behind an integrity score.

Falsifiable expectation: exposing usable origin metadata should reduce unsupported
basis promotion without losing justified attributed claims, while missing or mismatched
origin must remain unresolved. If gains require disclosure of the answer labels,
or legitimate claims disappear, the proposed pipeline has not passed that test.
Zero observed errors in a small batch would still not prove general reliability.

A permissive weaker-claim gate and richer outcome/abstention fields remain useful
follow-ups. They should be separate variants, so we can measure what each changes.
Adding an outcome field is particularly relevant: completed does not mean passed.
We have not demonstrated richer explanatory usefulness merely by emitting fewer
claims. Reuse the frozen draft corpus for policy comparisons; collect new independent
cases for generalisation claims.

## Consequence for database design

SQLite remains canonical; indexes remain replaceable. Source receipts, annotations
and correction relationships can be represented in tables or graph structures.
The current evidence does not favor a new engine. First demonstrate that independently
produced, source-backed relationships improve what the agent can responsibly say.
Then benchmark the workload that serves those relationships.

Work/personal configuration, forgetting through sync/indexes, capture health and
clean installation ownership remain integration requirements from earlier stages.
This stage does not claim to install or validate those production integrations.
The learner's saved Stage 8 exercise is unchanged.
