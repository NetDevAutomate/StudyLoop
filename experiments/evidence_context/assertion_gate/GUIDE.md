# Stage 15 — Keep event state, evidence basis and target separate

The previous stage found useful evidence but still overstated what it established.
This stage asks whether an explicit contract can preserve useful reports while
preventing claims from becoming stronger than their reviewed evidence labels.

Start with the runnable walkthrough. It shows source, draft, checked claim and
released statement separately. The tests and default demo need no credentials,
private history or database. All source data is disposable.

```sh
uv run python -m experiments.evidence_context.assertion_gate.runner --output /tmp/evidence-stage-15
uv run python -m experiments.evidence_context.assertion_gate.viewer \
  --directory /tmp/evidence-stage-15 --output /tmp/evidence-stage-15/walkthrough.html
open /tmp/evidence-stage-15/walkthrough.html
uv run --group dev pytest experiments/evidence_context/tests/test_assertion_gate.py -q
```

Use a new output directory each time. These are commands from the experimental
worktree root; STAGES.md provides the exact Git checkpoint for an independent copy.
The default demo is an offline reference. It does not reproduce model performance.

## Follow one concrete claim

In separate_events, there are two different assertions:

| Target | Event state | Evidence basis |
|---|---|---|
| parking.cleanup | completed | reported |
| launcher.port_change | in_progress | reported |

The cleanup can have been reported complete while the port correction remains in
progress. Neither label says the report has independently been verified. Joining
these into a single “completed and validated” status would discard distinctions
that the earlier trial showed matter.

For a networking analogy, a message saying a configuration was applied, a command
exit status, and a fresh read of the actual interface state are different evidence.
They also need to refer to the same device and configuration revision. An exit
status from another device cannot validate this change.

Here the model proposes typed claims, for example:

```json
{"assertion_id":"E2","target":"launcher.port_change","state":"completed","basis":"reported"}
```

The gate looks up E2 in the reviewed ledger and finds in_progress. It withholds
that claim with state_mismatch. If E1 is correctly attributed in the same draft,
it still releases E1. A single faulty claim does not erase unrelated useful claims.
Open the mixed_valid_and_overstated control to see this happen deterministically.

Code renders approved fields into attributed statements. The model's free prose
is saved for inspection, but does not enter the released statement. This distinction
matters: live C17 had matching typed claims and still said “verified” in its prose.
The renderer cannot copy that extra assertion because it does not use that prose.

## Why these design choices?

**Separate fields instead of a single confidence score.** A numerical confidence
would not tell us whether an answer confused execution state, source type or target
identity. Separate fields expose a specific disagreement that can be investigated.
They do not make the labels themselves correct.

**A reviewed ledger before automatic extraction.** Supplying labels is an oracle
control: can the downstream system use the required distinctions at all? The
annotated model can simply copy metadata, so success here is conditional contract
conformance. Automatic interpretation of unseen transcripts remains untested.

**Strict equality before a more permissive rule.** A small exact gate is easy to
inspect. It also exposes false withholding: two raw answers said reported when the
hidden fixture label was observed. That weaker attribution may be useful, yet it
was rejected. Do not hide this cost behind an aggregate success percentage.

**Explicit correction links instead of newest-message-wins.** A newer claim does
not automatically invalidate an older claim about a different target. This gate
requires the correction target, project and scope to match before recognising the
link. Broken links produce metadata errors; they do not resurrect the old claim.
This is only a one-hop contract. Cycles, authority, time and semantic justification
are not resolved here. Stage 3 retains the separate sync/deletion experiments.

**Code-owned prose instead of another model judging the whole answer.** The earlier
reviewer audit showed that models can misread qualified answers. A fixed renderer
makes attribution inspectable. Its cost is expressiveness: it currently emits state
but not pass/fail, detailed cleanup facts, or a specific explanation for an empty
selection. A shorter answer is not automatically a more useful answer.

**No database change.** The failing boundary is an information/interpretation
boundary. These assertions could be represented as SQLite rows with foreign keys
or graph nodes and edges. An edge labelled validated does not authenticate its
meaning any more than a SQL column does. Storage changes cannot resolve the two
forged-annotation controls in this stage.

## The revealing identical-text control

observed_pass and identical_report have identical raw payloads, including question
and source IDs. One ledger declares a simulated tool observation; the other declares
a report containing exactly the same words. An agent cannot recover the hidden
origin reliably from the text alone. Both raw repeats chose reported in each case.
The gate therefore accepted the report-labelled case and rejected the observation-
labelled case. This is not evidence that the model reasoned worse on one case.

The annotated arm discloses that missing field, and all four corresponding drafts
follow it. The lesson is to preserve provenance through capture, not to demand
that an agent infer provenance from convincing-looking prose.

## What a hash does and does not prove

The gate recomputes the SHA-256 of the supplied source excerpt and checks the exact
quote span. Changing text without updating the binding is detected. These are
consistency checks inside a trusted snapshot, not signatures or authentication.

Now open forged_reviewed_annotation and forged_basis_annotation. Each changes a
label while leaving source text and hash intact. The model claim agrees with that
bad label, so the gate releases it. The semantic expectation was rejection: these
are **two demonstrated gaps**, deliberately retained in the results.

A trusted process must justify annotation state, basis, identity and correction
links. A source hash alone cannot provide that justification. This also constrains
work/personal scope: explicit configuration and capture ownership remain necessary;
a harness name is not a boundary. This experiment compares declared scope/project
values; it does not certify the configuration that supplied them.

## Replay the actual trial privately

```sh
uv run python -m experiments.evidence_context.assertion_gate.viewer \
  --directory experiments/evidence_context/.private/stage-15/run \
  --output /tmp/evidence-stage-15-actual.html
open /tmp/evidence-stage-15-actual.html
```

This requires the owner's ignored private archive. A public Git clone contains
synthetic fixtures, aggregate observations, code and guides; it does not contain
historical excerpts, raw drafts or council packets. Keep the private archive with
the learning checkout if you want this replay later; Git does not back it up.

The private run contains the frozen bundle/hash manifest, executed source copy,
32 provider responses, per-claim decisions, costs and timing. Source history came
from the prior saved snapshot. sessions.db and installed harnesses were not changed.

For an explicitly paid new run, the runner accepts --live and optionally --cases
with a matching eight-case file. It uses LITELLM_BASE_URL and LITELLM_API_KEY from
the environment. Do not paste credentials into code, commands or saved files.
The normal walkthrough never makes gateway calls. The runner refuses to overwrite
an existing run or repeat a paid call sequence in the same output directory.

Read RESULTS.md for measurements and COUNCIL-DECISION.md for disagreements and the
next test. The saved Stage 8 exercise remains available for a dedicated lesson.
