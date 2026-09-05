# Stage 8 — From evidence to a useful, bounded answer

Stage 7 exposed a category error. A report can exist without supplying enough evidence
to choose. Asking one field to express both source type and decision sufficiency hid
an improvement in the actual answers. Stage 8 separates those judgments and makes
the reason for abstaining visible.

## Run the walkthrough

From the experimental worktree root:

```sh
uv run python -m experiments.evidence_context.decision_contract --output /tmp/evidence-stage-8
open /tmp/evidence-stage-8/walkthrough.html
uv run --group dev pytest experiments/evidence_context/tests/test_decision_contract.py -q
```

Choose a new output directory for each run. The HTML opens each scenario into a
source table, decision explanation, limitation and next check. This default demo is
a deterministic reference policy over synthetic facts. It does not contact a model
or claim actual verification. `frozen.json` beside the HTML holds the full inputs,
pre-run expectations, prompts and code fingerprints; `reference.json` holds the
reference answers. Previous stages are unchanged.

The explicit live version makes sixteen calls, comparing the frozen Stage 6 v2
prompt and this stage's fixed contract prompt on the same eight user payloads:

```sh
# Supply LITELLM_API_KEY securely in the environment first.
uv run python -m experiments.evidence_context.decision_contract --live --output /tmp/evidence-stage-8-live
```

The existing loopback gateway client uses Qwen3-Coder, temperature zero, 1,500 maximum
output tokens, two concurrent requests and a 90-second socket timeout. There are no
application retries or prompt search. Each attempted call is saved independently
before execution. Failures stay in the denominator. Existing outputs/call directories
cannot be reused silently. Missing cost metadata is explicitly counted.

## The three questions

| Judgment | Question | Example | What it does not prove |
|---|---|---|---|
| Provenance | What kind of supplied source is this? | An agent report or an artifact | Authenticity, correct extraction, or that an artifact is trustworthy |
| Applicability | Does this check concern the decision's target? | Revision r2, eight writers, this environment, reopen correctness | That the check was sound, representative or independently reproduced |
| Sufficiency | What conclusion can these applicable sources support? | B within this fixture; a conditional proposal; or no choice | Universal superiority or production readiness |

In a network analogy: a genuine test report from another firmware revision is still
a genuine report. Its relevance to today's fault remains a separate question.
Likewise, a successful throughput test does not establish recovery correctness.

The narrow probe uses exact scope equality to make the policy inspectable. Production
would need versioned compatibility rules, normalized identifiers and explicit scope
transfer judgments. `r2` versus `R2` is deliberately a mismatch here. Extra metadata
keys do not establish additional coverage. Unknown fields stay unknown.

## Follow one source through the contract

Open `wrong_revision` in the walkthrough:

1. S3 is tagged as a synthetic artifact. Its kind does not change because it is old.
2. It tested r1, but the target is r2: applicability is **inapplicable**.
3. The remaining sources are unmeasured reports. The decision is **insufficient**,
   with no chosen option. The answer requests a check on the target revision.

Now open `unknown_revision`. The test omitted its revision. It is **unknown**, not
known to be wrong and not assumed to match. The resulting decision also abstains,
but the per-source reason explains a different next investigation.

Finally open `conflicting_checks`. Both sources are applicable, yet they support
opposite options. The decision remains insufficient, with reason
`conflicting_observations`. A user can see that more context did not resolve the
problem; the two observations need reconciliation.

## The output contract

`source_assessments` lists each source exactly once with its provenance, applicability
and reason. `decision` carries a sufficiency, recommendation, reason code, source IDs,
explanation, limitation and concrete next check.

| Sufficiency | Recommendation | Reason code | Appropriate claim |
|---|---|---|---|
| supported | A or B | applicable_observation | Within these authored fixture assumptions, the applicable observation supports this option |
| conditional | A or B | requirement_fit_only | The reports describe a plausible fit; test it before claiming measured success |
| insufficient | none | no_applicable_observation | Available evidence does not establish this choice |
| insufficient | none | conflicting_observations | Applicable checks disagree; choosing would hide the unresolved conflict |

This avoids losing the proposed option: the previous schema used `conditional` in
the recommendation field, leaving A/B buried in prose. It also distinguishes the
absence of applicable evidence from contradictory applicable evidence without
inventing a confidence percentage.

Measurements take precedence over requirement-fit reports, even in requirement-fit
mode. A conflicting measurement set cannot fall back to a preferred proposal. With
no applicable artifact, only an explicit requirement-fit mode plus reports identifying
exactly one fitting option permits a conditional recommendation. No mode implies
production authorization.

For decision citations, the contract defines **required minimum coverage**, not an
exact string/list match. All applicable artifacts must be included for measured
choices and conflicts. Conditional choices include the fitting reports. With no
applicable observation and no conditional choice, include all supplied sources to
show the gap. Additional valid source IDs can be cited as context without pretending
they are empirical proof. This avoids rejecting useful extra context as Stage 7
rejected a defensible evidence label.

## What is being measured?

We freeze `expected.json` before answer-model calls. Two council reviewers explicitly
labelled all eight cases; the third gave general approval without the requested
per-case labels. Their agreement is advisory evidence, not human ground truth.
Clarifications suggested by the council were applied before the live run.

Mechanical checks remain separate:

- **Integrity:** exact schema, coverage of all source IDs, valid decision/category
  combinations and citations that exist.
- **Provenance agreement:** source kinds match the authored fixture facts.
- **Applicability agreement:** per-source statuses match reviewed expectations.
- **Decision agreement:** sufficiency, option and reason code match expectations.
- **Basis coverage:** all required decision sources are cited; additional context is allowed.

A passing aggregate means only that all these checks passed on a fixture. The scorer
checks explanation presence, not whether every sentence follows from its sources.
The tests intentionally demonstrate this blind spot using a fabricated universal
validation claim. Another test contradicts an artifact's structured conclusion in
its text: the deterministic policy follows metadata. That is a missing extraction/
entailment gate, not a successfully detected attack or a source-validation feature.

For the old/new comparison, only **choice behavior** is directly comparable: A, B,
conditional proposal, or abstention. The old schema cannot express all the new axes.
We do not mark it wrong simply for lacking fields. New prompt and output schema
change together, so this probe cannot isolate which caused a behavioral difference.
Both arms receive identical structured user inputs; the legacy arm also benefits
from that extra structure compared with earlier stages.

## Why this is not yet a real evidence system

Every source is an authored synthetic fact. Provenance here is merely a source-kind
field. A product would also need source locator, originating harness/session, capture
time, content version, correction history, access scope and a way to inspect the
original artifact. Importing or extracting that metadata is not validated here.

The reference policy assumes one applicable fixture observation can support a local
conclusion. Real sufficiency may depend on replication, sample size, test quality,
risk and contrary evidence. It must be a versioned domain policy, not a universal
'one artifact means proven' rule. Successful JSON parsing or matching scope does not
satisfy those requirements.

This stage measures contract behavior, not learner understanding. A useful answer
should help you identify what was observed, why it applies, what remains unresolved,
and what test would change the decision. An evidence-backed explanation is an
inspectable account of the sources and decision rules, not private internal reasoning.

## Implication for the database

The three judgments belong to different relationships:

- A source/version has provenance and lifecycle/access metadata.
- An applicability assessment relates that source/claim to a particular target and
  policy version. It is not a permanent `validated=true` property of the source.
- A decision records the considered evidence, sufficiency, exclusions, unresolved
  conflicts and policy version. Corrections/deletions can invalidate that derivation.

SQLite tables and foreign keys could represent this. A graph could represent these
relations as edges. This stage informs the data contract, not the engine choice;
query cost, retrieval value and synchronized lifecycle behavior still need measurement.

See [RESULTS.md](RESULTS.md) for observed behavior and
[COUNCIL-DECISION.md](COUNCIL-DECISION.md) for accepted and rejected advice.

## Saved for the next dedicated learning session

The learner chose to leave this exercise for tomorrow rather than rush it at the
end of the evening. Start with the `unknown_revision` walkthrough, then the short
function below. The placeholder is intentionally unfinished, not a product blocker.

In `exercise.py`, implement `classify_revision(recorded, target)`. Decide whether
revision identifiers are case-sensitive in your own domain, and keep missing
metadata unknown. This is a useful policy choice: normalization can prevent false
mismatches, but unjustified equivalence can admit the wrong evidence. The exercise
is separate from the frozen experiment. Do not add compatibility assumptions merely
to make a test appear applicable.
