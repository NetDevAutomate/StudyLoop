# Stage 11 — When does checked evidence permit a decision?

Stage 10 showed that checked metadata can still accompany an unsupported answer.
Stage 11 asks a narrower question: can code prevent those unsupported choices without
unnecessarily withholding justified ones? The model prompt remains unchanged.

## Start with the saved learning walkthrough

From the experimental worktree root, with a fresh output filename:

```sh
uv run python -m experiments.evidence_context.source_decision.viewer \
  --input experiments/evidence_context/source_decision/observations \
  --output /tmp/stage-11-learning.html
open /tmp/stage-11-learning.html
```

This viewer reads preserved observations. It does not call a model or recalculate the
scores. Expand cases to compare source and target, candidate fields, validation reasons,
code-owned outputs, actual advisory drafts, and the reviewers' original labels.

The independently runnable reference demo and current-code replay are different:

```sh
# Construct offline policy outputs; no model calls.
uv run python -m experiments.evidence_context.source_decision --output /tmp/stage-11-reference
open /tmp/stage-11-reference/walkthrough.html

# Recalculate deterministic outputs against the same preserved model drafts.
uv run python -m experiments.evidence_context.source_decision \
  --replay experiments/evidence_context/source_decision/observations \
  --output /tmp/stage-11-replay
open /tmp/stage-11-replay/answer-replay.html

uv run --group dev pytest experiments/evidence_context/tests/test_source_decision.py -q
```

Existing output directories/files are protected. The replay explicitly says it uses
current code; the Git checkpoint is the way to recover the original implementation.
The saved observations themselves remain unchanged.

An explicit `--live` run makes at most 24 sequential gateway calls. Configure
LITELLM_API_KEY securely in the environment; no secrets belong in source files. The
model is qwen3-coder at temperature zero, 1500 maximum output tokens and a 90-second
request timeout, without application retries. No new LLM extraction is performed.

## First example: a missing extraction is not a missing source fact

Compare C01 (`omitted_present`) with C10 (`valid_b`). Their source and target are
identical. Both contain a unique matching revision and support B. Only C01's scripted
proposal omits that revision.

The source verifier correctly reports an omitted present field. What should happen
next depends on the boundary's responsibility:

- **checked_only:** accept only matched candidate fields. The accepted revision is
  unknown, so the existing decision policy withholds a choice. This is predictable
  enforcement, but a false block against the complete source's reviewed label.
- **source_adapter:** explicitly parse the original structured log again into a new
  derivation. That new derivation has a recorded revision and can support B. The
  incomplete candidate and its rejection history are retained, not silently rewritten.

The source-adapter path is a deterministic parser plus policy. It does not improve or
certify the model's answer. On this narrow grammar the model is unnecessary for the
released choice, although it remains an advisory comparison in the experiment.

These two conditions deliberately share one source; counting them as two independent
sources would overstate the evidence. There are 12 case conditions and 11 distinct
source/target pairs: three earlier cases and nine fresh conditions on eight new pairs.

## Second example: a real quote can still be outside the evidence boundary

C05 (`outside_distraction`) has winner A inside the observed block and a summary saying
winner B outside it. The candidate selects B. The checker rejects it. The conservative
path has no accepted winner and withholds a choice; the source adapter recovers A from
the original observed block.

Qwen's independent label was none because it counted the outside declarations as
duplicates. Fable and Grok labelled A. The coordinator retained A because the written
rule excludes outside declarations, not because two votes beat one. All three responses
and the dissent are retained in labels.json and the council observations.

This is why a policy must name its evidence boundary. The existence of a quotation
somewhere in a session does not make it the result of the test being discussed.

## Third example: matching fields do not authenticate a report

C03 (`report_only`) contains complete matching fields but source kind report. The model
recommended B twice and postponed deciding whether the report was acceptable until its
next check. Both deterministic paths withheld a choice under the measured-decision rule.

The kind comes from the synthetic fixture envelope. The adapter has **not** proved that
an artifact was created by an actual test run. A caller can forge a plausible log and
label it artifact. This retained test demonstrates the missing authenticity boundary.
It must be addressed before claiming production evidence validation.

## How the implementation is separated

```text
Original source + source kind + target + candidate proposal
                         |
                 EvidenceSnapshot
                   /           \
       matched candidate       explicit source reparse
              fields           (new derivation)
                   \           /
               Stage 9 policy Snapshot
                         |
             Stage 8 measured-decision policy
                         |
       code-rendered decision + issues + next checks + locators

Model draft → choice agreement telemetry only; model prose never enters release
```

The outer snapshot copies and binds source text, metadata, target and proposal. The
inner Stage 9 Snapshot binds the normalized policy input and policy version. Stage 8's
measured policy then decides whether an applicable observation supports A/B or none.
No earlier stage or exercise has been edited.

Unknown winner cannot be converted into an invented A/B merely to satisfy the older
schema. Such a source is excluded from the normalized policy input while its issue and
source trace remain visible. This adapter currently handles one source per case; it
must not be assumed to solve multi-source completeness or conflict arbitration.

The whole model answer is never accepted. `choice_agrees` means only that its A/B/none
field matches the independent release. A test deliberately gives it matching A plus
reckless prose: the prose is still withheld. A stale draft binding also cannot alter
the separately computed policy output.

## Evidence references with an explicit origin

A source-text locator includes source id, source version, character offsets and the
exact quote. A source-kind reference is an envelope-field locator. A target reference
has its own origin, target version, field key and value. They cannot be interchanged.

For a mismatch, the explanation trace references both the tested value and the target
value. Missing fields cite the inspected source instead of inventing a quote for an
absent declaration. Duplicate fields retain both locations. These are auditable rule
applications, not a semantic entailment proof for arbitrary natural-language claims.

## What the measurements mean

[RESULTS.md](RESULTS.md) records strict parsing, valid advisory coverage, unsupported
choices, false blocks, positive retention, and old versus fresh cases separately.
All accepted/blocked counts refer to output choices, not full model-answer approval.

A perfect score for the deterministic adapter establishes agreement with these reviewed
fixture rules. It does not establish rule correctness in every setting, authentic
provenance, general retrieval usefulness or learner understanding. Reviewers labelled
cases independently of coordinator labels; they are models, not human gold annotators.
The parser and policies share code and assumptions, another source of correlated error.

An always-none policy avoids unsafe choices but blocks every positive. Including
positive controls prevents us from mistaking that behavior for a useful solution.

## What this suggests about the database

This stage tests semantics rather than storage performance. The useful records are
original source versions, target scope, separately versioned derivations, exact evidence
locators, validation issues and policy identity. Keeping original and derived values
separate enables correction, replay and explanation. A generic verified flag would
collapse several different claims and obscure the report-only failure.

Both relational tables and graph representations can represent these records. We have
not yet measured a workload that justifies changing engines. A new engine cannot supply
missing source authenticity or settle an ambiguous policy.

The grammar, pre-run protocol and council arbitration are preserved beside this guide.
Your earlier optional revision exercise remains saved for its dedicated session.
