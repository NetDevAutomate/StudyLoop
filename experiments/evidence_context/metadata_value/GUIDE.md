# Stage 10 — Does metadata improve the result?

Metadata can make evidence easier to find and use, but it can also make an incorrect
interpretation look authoritative. This stage separates clean-metadata benefit from
recovery after deliberately corrupted metadata. It keeps original source text visible.

## Run the source-check walkthrough

From the experimental worktree root:

```sh
uv run python -m experiments.evidence_context.metadata_value --output /tmp/evidence-stage-10
open /tmp/evidence-stage-10/walkthrough.html
uv run --group dev pytest experiments/evidence_context/tests/test_metadata_value.py -q
```

Choose a fresh output directory. Offline mode makes no provider calls: it uses a
reference parser to demonstrate the fields, four seeded faults and the verifier's
responses. That reference extraction is not substituted into the live experiment.
The HTML shows source text, proposed values and checked values side by side.

For an explicit live run, supply LITELLM_API_KEY securely in the environment, then:

```sh
uv run python -m experiments.evidence_context.metadata_value --live --output /tmp/evidence-stage-10-live
```

Live mode is capped at 64 calls: eight source-only extractions plus 56 answer calls.
The original source, source kind, target, question and answer prompt are identical
across answer conditions for each case. Only the metadata block changes. The extractor
never sees the target or expected choice. Case names and injected-fault labels never
enter model inputs.

Qwen3-Coder is called through the existing loopback gateway at temperature zero,
maximum 1,500 output tokens per request, a 90-second socket timeout, with no application
retries. Calls are sequential; condition order rotates by case and repeat. There is
no random assignment or seed. Two repeats can reveal variability but are not independent
scenarios; gateway caching was not independently characterized. Costs and latency are
reported descriptively, not as token-matched efficiency evidence.

Each attempted call is saved before execution. A failed call remains in the results.
Existing run/call directories are not overwritten. An extraction failure is recorded;
the original source remains available to answer conditions, with invalid candidate
metadata rejected by the verifier. Do not interpret that as successful extraction.

## Why the design changed before running

The first council review challenged the original proposal: six short logs, mostly
corrupted metadata, would measure fault handling rather than clean-metadata value.
We accepted that criticism before any live model calls.

The revised, pre-run [PROTOCOL.md](PROTOCOL.md) uses eight cases, including two longer
noisy logs, four justified choices and four required abstentions. It preserves an
unmodified-extraction condition and uses two answer samples per condition. The revised
protocol is the coordinator's response to council advice, not a separately re-approved
council design. There is still no independent real-world holdout or learner study.

| Condition | Metadata shown | Answer calls | Purpose |
|---|---|---:|---|
| raw | None | 16 | Source-only baseline |
| extracted | Original model extraction, unmodified | 16 | Clean-metadata context comparison |
| candidate | Extraction with a predeclared fault | 8 | Susceptibility to incorrect metadata |
| checked | Candidate after narrow source checks | 16 | Fault recovery, plus checked-label controls |

Candidate runs only on the four fault cases. Compare it with the matching subset of
other arms, not their full denominators. The checked arm uses altered candidates for
those four cases and untouched candidates for the remaining four.

Correct metadata here adds organization, not new evidence. Longer sources give it a
plausible role in reducing search effort, but these fixtures may still be too easy to
show a benefit. No difference is a valid result. We do not keep changing examples until
metadata wins. Extra metadata/rejection reasons also add tokens; the contexts are not
length-matched.

## What source-backed means in this stage

The supported source format has one explicit block:

```text
[observed]
revision: r2
workload: eight writers
environment: fixture-local
metric: reopen correctness
winner: B
[/observed]
```

For each field, the extractor proposes a value and an exact complete source line.
The verifier checks four things: the line lies inside the sole observed block; it
names the correct field; that field appears exactly once; and the parsed value equals
the proposed value. It uses exact case and spacing for this narrow grammar, not a
semantic language model. Lines outside the block cannot establish a field.

A missing or duplicate field stays unknown. A rejected proposal is not silently
replaced with a corrected value. If the extractor omits a field actually present in
the source, the checker reports that omission and keeps its proposed value unknown.
The answer model can still inspect the original source and make a source-grounded
choice. Rejecting metadata does not mean the underlying source necessarily lacks data.

This is stronger than merely checking whether a quote exists somewhere:

- `value=r2` plus quote `revision: r1` is inconsistent.
- `value=r2` plus a fabricated quote `revision: r2` is unsupported if the source says r1.
- `winner: B` outside the observed block cannot override `winner: A` inside it.
- Selecting one of two revision declarations hides ambiguity, even when the selected
  quote really occurs in the source.

It is deliberately weaker than authenticating a test or validating arbitrary prose.
A fabricated log can satisfy every syntax check. A report can quote a valid-looking
log while remaining a report. The application-supplied source kind is shown equally
to every condition and is not promoted by successful field checking.

## What we measure

The pre-run labels specify A, B or no choice for each case. The verifier's grammar
also provides an exact extraction comparator. These labels and code were authored by
the coordinator and can share assumptions; they are not independently authored truth.

Report separately:

- Exact field/value/quote extraction agreement before any injected fault.
- Correct choice categories on the frozen cases.
- Unsupported endorsements: selecting the wrong A/B, including when abstention is required.
- Missed justified choices: abstaining when the fixture supports A/B.
- Invalid responses and citations not locatable in original source text.
- Model explanation review, separate from those mechanical checks.

Always answering none matches 4/8 cases (50%). A naive follow-metadata-winner baseline
ignores scope and helps show why copied metadata is not a decision policy. Neither is
a recommended approach.

A locatable quote can still fail to support its accompanying claim. A test deliberately
pairs `winner: B` with a fabricated universal-superiority explanation: the choice and
quote-location checks pass. This is a retained semantic blind spot, not a validated
answer. Learner understanding remains unmeasured.

## Boundaries and interpretation

Stage 9's code-owned release is not used here: these are unverified model drafts,
allowing differences between context conditions to remain visible. None is promoted
to a real decision system. The conditions test a narrow formatting/context effect,
not database performance, verified provenance or generalized retrieval usefulness.

If metadata helps on these examples, the next question is whether that transfers to
independently reviewed real sources. If it does not, we have evidence against adding
this complexity just for answer quality on similar easy logs. Source locators,
correction/deletion history, access scope and capture health may still justify metadata
for other purposes; those benefits are not measured by this probe.

The shared-memory design should retain original source versions alongside derived
metadata and its supporting spans. A graph edge or a database column cannot turn an
unsupported extraction into a fact. Verification status needs a clear meaning—here,
only correspondence with a narrow log grammar.

See [RESULTS.md](RESULTS.md) for observed outcomes and
[COUNCIL-DECISION.md](COUNCIL-DECISION.md) for accepted and rejected reviewer advice.
Your saved Stage 8 exercise remains untouched for its dedicated learning session.

## Read actual answers alongside the source-check demo

The completed run exposed a strict JSON formatting defect. RESULTS.md keeps that
measurement separate from a conservative post-run replay. Run the replay command
there to expand all 56 actual drafts, including unsupported recommendations. No live
calls are needed. The default source walkthrough remains an offline demonstration;
it must not be confused with the actual model-answer replay.
