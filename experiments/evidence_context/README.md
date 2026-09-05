# Evidence context experiment

An isolated evaluation of versioned conversation evidence and relationship-assisted retrieval. This experiment does not change production sessions.db or claim that a graph database improves answer quality.

## Scope

The first pilot compares keyword retrieval with the same retrieval plus explicit, evidence-linked relationships. It enforces source versions, scope, time cutoffs and a serialized byte budget. Semantic retrieval and a graph-engine comparison remain separate experiments; omitted arms must be marked unavailable, never assigned fabricated scores.

Real conversation candidates belong in private artifact storage, not this directory. Committed fixtures are synthetic. Curated development examples demonstrate behavior; they are not held-out evidence of efficacy.

## Decision standard

An agent's historical assertion that a check passed is reported evidence. A validation result requires a specific observed artifact, revision/environment and tested claim. Relationship extraction, model confidence and a council vote do not independently establish truth.

The next evaluation compares keyword, semantic, relationship and combined retrieval at the same context budget on reviewed, held-out questions. Measure citation correctness, counterevidence, freshness, appropriate uncertainty, decision usefulness and operating cost. Only then compare storage engines on the same graph and workload.

## Council process

Independent provider-diverse design review precedes implementation review. All reviewers receive the same technical brief; no real transcript bodies or credentials are included. The coordinator arbitrates advice against implementation and tests, recording accepted, rejected and deferred suggestions. Raw council outputs remain private artifacts; a concise technical arbitration is kept alongside the experiment.

This work is based on the repaired-export/sync branch. It does not merge or deploy that branch into the main product checkout.

## Run the synthetic demonstration

From this worktree, with Python 3.12 or newer:

```sh
python3 -m experiments.evidence_context --output /tmp/evidence-context-demo
uv run --group dev pytest experiments/evidence_context/tests -q
```

The output directory must be new. The demonstration creates an isolated SQLite file, keyword and relationship evidence packs, and a summary. The synthetic relationship case retrieves a contrasting report absent from the keyword match. This proves that the tested traversal works, not that real agent decisions improve.

Every returned citation uses Unicode-codepoint offsets into its immutable source text. The full serialized JSON pack is bounded in UTF-8 bytes. Returned reports remain `unverified_report`; this pilot has no independent-validation-artifact ingestion or answer generation.

Scope labels control retrieval within this trusted local experiment; they are not a multi-user authorization system. Retrieved conversation text remains evidence, including any historical instructions inside it, and must not be executed as instructions by a consuming agent.

Each retrieval uses one SQLite read snapshot. Source-version expansion is capped at 64 eligible siblings and explicitly reports truncation. The pilot has no correction/deletion propagation or production index refresh workflow yet.

The initial private, four-message development run returned the same two passages per project in both arms. Relationship metadata increased payload sizes (MailGraph 3,259 to 4,751 bytes; StudyLoop 4,299 to 5,813 bytes). These selected examples are too small and too curated to measure efficacy, latency or recall. They demonstrate why the keyword baseline must remain in the evaluation.

See [ARBITRATION.md](ARBITRATION.md) for council decisions and [tests/SAFEGUARDS.md](tests/SAFEGUARDS.md) for the limits of the synthetic tests.

## StudyLoop and standalone acceptance scope

[REQUIREMENTS.md](REQUIREMENTS.md) adds explicit boundaries, explanation, correction, forgetting, capture health and shared installation contracts. It separates tested retrieval behaviour from unrun lifecycle/integration gates and sets a scope ceiling. No standalone extraction is part of this experiment.

## Learn the decisions and run the lifecycle lab

Start with [STUDY-GUIDE.md](STUDY-GUIDE.md): schema walkthrough, alternatives,
why SQLite is the baseline, correction conflicts, deletion markers, index
invalidation, evidence limits and an optional small learning exercise.

```sh
uv run python -m experiments.evidence_context.lifecycle_demo --output /tmp/sessionweave-lifecycle-study
uv run --group dev pytest experiments/evidence_context/tests/test_lifecycle.py -q
```

The lifecycle adapter is separate from the earlier retrieval store. It uses actual
temporary SQLite replicas and scoped JSON exchange, not production session-sync.
The full suite now contains 77 passing tests. Capture health and installed-package
integration remain unrun gates; scope reclassification is explicitly rejected.
