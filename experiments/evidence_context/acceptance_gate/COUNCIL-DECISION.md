# Stage 9 coordinator decision

## Coverage and scope

Both design and result review obtained valid responses from Claude Fable 5.1,
Grok 4.6 and Qwen3-Coder: three provider lineages in each round. No retries were
needed. Qwen is also the draft-generation provider; its review is not independent
provider validation of itself. Council agreement is advisory, not ground truth.

The design brief described the intended boundary, fixtures, replay and live plan.
The result brief included all live source cases and draft answers, released decisions,
gate outcomes, offline/replay summaries, gate.py, probes.py and the eight new tests.
It did not include the complete Stage 8 policy module, runner.py, exact full prompts
or every prior test. Reviewers correctly identified these as limits on their code
review. Do not describe this as an exhaustive independent audit of the implementation.
All those implementation files are retained in the checkpoint for inspection.

## Accepted before the live run

- Freeze application-owned input and bind drafts to input plus policy version/digest.
- Preserve unknown source scope instead of filling it from the target.
- Distinguish draft agreement from verified answer quality: public statuses became
  draft_agrees/draft_diverges rather than accepted_structured/rejected.
- Keep all model free-text fields outside released_answer, including per-source reasons.
- Label the precomputed-answer condition contract_copy_control. It cannot measure
  improved reasoning because it gives the model the answer to preserve.
- Add case-name invariance, serialization/copy isolation, policy binding, prose isolation,
  invalid target/empty evidence and separately written pre-run expectation tests.

We retained extra *valid* contextual citations under Stage 8's minimum-coverage rule;
unknown or duplicate citation IDs are rejected. Grok's broad wording about extra
citations should not reverse that existing distinction.

## Result arbitration

Fable is right that release protection belongs to derive() plus application input
ownership and serialization, because released_answer does not depend on the model.
The draft check provides conformance telemetry. It does not selectively certify
model prose or make the model more reliable. Its prose-isolation tests are regression
guards for that design boundary, not evidence that the code detects semantic lies.

Grok is right that the observed model scope inventions did not reach the release and
that the copy-control model failed on the injected example despite receiving the
correct contract. Those are narrow execution observations. We do not infer broad
injection resistance or a clean causal estimate from one sample per condition.

Qwen recommended production use and claimed 10/12 live instances aligned. Both are
rejected: the actual agreement count is 8/12 (3/6 prompt-only, 5/6 copy control), and
there is no production acceptance evidence. Its '153 offline probe tests' description
also conflates 153 tests across all stages with eighteen Stage 9 offline probes.
The snapshot hash is not source authentication or a tamper-proof trust anchor.

Fable's assumed independent authorship of expected labels is also not established.
The coordinator wrote them before the live model calls, knowing the Stage 8 policy.
They are separate from model answers, not an independent author's oracle. Stage 8's
pre-existing expectations and model reviews provide additional checks but can share
assumptions. The gate can reproduce policy errors perfectly.

## Decision

Preserve Stage 9 as a code-owned decision renderer with snapshot-bound draft-agreement
measurement. Keep the model out of this narrow release path. Do not deploy it or use
agreement counts as a proxy for validated context, learning value or safety in general.
No database choice follows, and the rich explanation problem remains open.

The most discriminating next learning stage is to challenge the *inputs*: artifact
text versus extracted metadata/conclusion, with missing, contradictory and misleading
sources. A source-grounded extraction/verification step must preserve unknowns and
show exact source spans rather than invent metadata. Compare that against independently
reviewed expectations. The current upstream-forgery case is the seed for that probe.

Fable suggested a live metadata/text contradiction probe with repeated samples;
Grok suggested an independently written policy oracle and injection variants. Both
would add evidence. Prioritize an independent check of metadata/claim correspondence
before increasing prompt search or letting model prose influence release. Repeats
characterize variability; a handful of clean runs still does not establish reliability.

For real use, source identity, current-version lookup, correction/deletion invalidation,
access boundaries, policy adequacy and original-artifact inspection remain required.
This stage does not implement those systems. Tomorrow's saved Stage 8 exercise remains
untouched and can be studied independently of this checkpoint.
