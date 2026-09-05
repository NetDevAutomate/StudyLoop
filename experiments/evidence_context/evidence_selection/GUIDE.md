# Stage 14 — Better evidence is necessary, but is it sufficient?

Start with RESULTS.md, then compare Q3 across the three conditions in the private
walkthrough. This stage preserves one complete iteration: hypothesis, source review,
frozen design, live run, mechanical checks, analyst judgments and council review.
The previous stages and the saved Stage 8 exercise are unchanged.

## Why this test comes before a new retrieval algorithm

Stage 12 failed to retrieve the result passages for the Parking question. Its answers
then confused plans and other workflows with completed checks. Two causes were possible:

1. The answer would improve if the right evidence arrived.
2. The model would misuse even the right evidence.

A new embedding model, graph algorithm or prompt would change several things at once.
Instead we held the answering prompt/model fixed and replaced the evidence. The
reference selection uses known episode labels: it is an **oracle control**, not a
retriever we can ship. A successful control establishes a useful target for retrieval.
It does not prove we can find that target automatically.

In network terms: deliver a known-good packet to the destination application before
replacing the routing system. If the application still mishandles it, routing is only
part of the problem.

## Three conditions

| Condition | Context | Question it helps investigate |
|---|---|---|
| original | Exact Stage 12 combined pack, freshly answered | Does the old failure repeat now? |
| reviewed_only | Reviewed source passages covering the required facts | Does complete relevant evidence help? |
| reviewed_plus_original | Same required passages, then original passages that fit | Does nearby material reintroduce confusion? |

All use the original system prompt, Qwen3-Coder alias, temperature 0, max 1500 output
tokens, six-passage cap and 1400 evidence-token ceiling. Two calls per condition, four
questions,24 calls total. The answering prompt contains no arm name, expected label or
reviewer guidance. Scoring facets are withheld from the answering model.

There is no padding to equal actual lengths. Q3 uses 1,001 tokens original, 540 reviewed,
852 reviewed-plus-nearby. The clean pack is shorter and more focused; the mixed pack
also changes positions and which original passages survive. A change in answers cannot
be attributed solely to distractor content rather than density/order. Record this
confound instead of asserting a clean causal effect.

Required IDs go first in their frozen order, then original IDs in original order.
Deduplication uses passage IDs. Oversized filler is skipped; required evidence that
cannot fit causes a failure. Scope/time checks apply to both kinds of passage. They
inherit the snapshot's timestamp limitations and do not certify production isolation.

Q2's original and mixed packs have the same six passages in a different order. Q4's
reviewed pack is empty and the other two packs are identical. These are known order/
input-equivalence controls, not additional retrieval discoveries or independent cases.

## The council improved the evaluator before the model ran

Fable noticed that the port-correction passage says the agent is making a change.
It does not establish completion. We amended the rubric before freezing to reject a
completed-fix claim based only on that passage. We also verified that the repository
checks for Q1 belong to the intended session. Exact test counts remain optional:
clarifying whether they apply to browser voice matters more than reciting them.

Mistral proposed rejecting genuine Parking result passages for alleged study-plan
conflation. Inspection showed those passages explicitly discuss the Parking cards;
that criticism was rejected. Independent models can make factual mistakes too.
See COUNCIL-DECISION.md for coverage, disagreements and final arbitration.

## Provenance, execution state and validation are separate axes

| Axis | What the source establishes | What it does not establish |
|---|---|---|
| Quote provenance | These words occur in this passage | The words support the cited conclusion |
| Reported execution state | An agent reports a plan, ongoing change or completed check | Independent proof that it happened |
| Validation applicability | A particular check concerns a particular target | That any passing test validates another target |

A completed **report** is not the same thing as an independently verified **event**.
Likewise, an in-progress correction must not become a completed correction just because
nearby cleanup was reported as successful. One confidence score cannot preserve these
distinctions reliably.

## How we assessed outputs

The frozen rubric names required facts and forbidden inferences for each question.
The coordinator recorded judgments before reading the result council. Each judgment
keeps its reason and uncertainties; no global accuracy percentage hides ambiguity.
The council receives blinded answer IDs and allowed source IDs for the twelve Q1/Q3
answers. Its assessment is additional evidence, not an authoritative vote.

Mechanical checks reuse Stage 12: schema, exact citation ID/substring, and whether a
validated status lacks artifacts. A quote mismatch caused by punctuation is not the
same thing as hallucinating an event. Conversely, a perfectly copied plan can still
be falsely cited as a successful result. None of the drafts is accepted for release.

This experiment does not implement automatic semantic verification. The analyst flags
are illustrative manual judgments on known cases. A general release gate will need
source-backed claims, entity/episode identity and target applicability; its own false
blocks and unsupported releases must be evaluated separately.

## Replay the actual run without model calls

From the experimental worktree root, use a fresh output filename:

```sh
uv run python -m experiments.evidence_context.evidence_selection.viewer \
  --directory experiments/evidence_context/.private/stage-14/run \
  --output /tmp/stage-14-walkthrough.html
open /tmp/stage-14-walkthrough.html
uv run --group dev pytest experiments/evidence_context/tests/test_evidence_selection.py -q
```

The tests use synthetic fixtures and mocked provider responses. The actual replay
requires the owner's ignored private archive; cloning Git alone deliberately does not
copy personal conversations. Preserve that directory separately when keeping the lab.
The public observations contain aggregate measurements only.

## Run another deliberate experiment

```sh
uv run python -m experiments.evidence_context.evidence_selection.runner prepare \
  --source experiments/evidence_context/.private/stage-12/run \
  --spec experiments/evidence_context/.private/stage-14/spec.json \
  --output /tmp/stage-14-new-run
# Paid action; authorized gateway credentials must already be in process environment:
uv run python -m experiments.evidence_context.evidence_selection.runner live \
  --output /tmp/stage-14-new-run
```

Preparation embeds the unchanged prompt and source text, freezes the rubric and
records hashes. Live execution checks bundle and runner hashes before calls. A started
run cannot silently be retried, even if interrupted; raw failures are retained. These
checks detect accidental edits, not malicious replacement of both a file and its hash.
The cached tokenizer is required for real preparation. Gateway alias routing can change;
a rerun is a new observation rather than guaranteed reproduction of model text.

## Next experimental boundary

The evidence-selection target is now clearer: retrieve the relevant reported result,
its target and any unfinished action. The next bounded iteration should represent
those distinctions explicitly and test whether a verifier can reject an unsupported
completed-fix claim while still allowing the reported cleanup result. Evaluate that
against new independently labelled examples before attempting a product retriever.

Keep SQLite canonical. No database migration or prompt optimization was performed.
Work/personal boundaries, why-context explanations, propagated forgetting and capture
health remain production requirements; this focused stage does not replace their tests.
