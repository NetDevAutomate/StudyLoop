# Stage 5: measuring retrieval usefulness

## Start with the decision, not a score

Suppose you ask: "Is this release ready, and what evidence supports that?"
History contains a proposal saying yes and a later validation report saying the
derived index is stale. A useful context pack includes both. Finding only the
proposal may produce a fluent but poorly supported recommendation.

This stage measures whether retrieval supplies that evidence. It does not generate
an answer or establish that a model will reason correctly from the evidence.

## Run independently

```sh
uv run python -m experiments.evidence_context.retrieval_eval --output /tmp/evidence-stage-5
uv run --group dev pytest experiments/evidence_context/tests/test_retrieval_eval.py -q
```

Use a new output directory. The default dataset is synthetic.json. The command
creates three isolated SQLite stores, frozen-input.json, manifest.json and
report.json and a readable report.md comparison table. Earlier stage outputs are not needed. No provider/network calls are
made. Do not overwrite old results: keep each run for comparison and learning.

To use a separate locally prepared dataset:

```sh
uv run python -m experiments.evidence_context.retrieval_eval --dataset /absolute/path/to/reviewed-cases.json --output /tmp/evidence-stage-5-candidate
```

Outputs contain the supplied corpus. Keep private datasets and their resulting
stores/output outside public Git. Output directories use owner-only permissions.

## What is scored?

| Measurement | Calculation | Why it matters and limits |
|---|---|---|
| Passage precision | Relevant returned passages / all returned passages | Measures distracting content. Null for no results or incomplete relevance labels; unlabelled is not automatically irrelevant. |
| Passage recall | Relevant returned passages / labelled relevant passages | Measures what retrieval missed. Labels may be incomplete; this is recall against the provided labels, not all possible evidence. |
| Required-span recall | Required exact text spans included / required spans | A document hit is insufficient when its excerpt omits the key sentence. |
| All required evidence present | Every required span returned | Tests whether the labelled minimum evidence is available. Not proof that the answer is correct or safe. |
| Citation validity | Resolve each returned citation against immutable source text | Evidence must be traceable. A valid citation does not prove the source's assertion true. |
| Scope/time violations | Returned passages outside the case's project, scope or cutoff | Hard integrity failures, not a quality trade-off. Earlier-stage tests additionally cover full-pack leakage. |
| Context cost | Complete serialized UTF-8 JSON bytes | Includes metadata and relationships, which consume real context space. This is not a model token count. |
| Retrieval latency | Wall time around retrieval only | Single local observation per case/arm; not a reliable performance benchmark. Excludes import and scoring. |
| Empty result | Whether any evidence was returned | Useful diagnostic. Not equivalent to appropriate model abstention. |

For example, if two passages are required and keyword search returns one, both
passage recall and required-span recall can be 0.5. Adding the second gives 1.0.
Adding a third irrelevant passage lowers precision to 2/3. Returning a truncated
excerpt can give a document hit while required-span recall remains zero.

Unanswerable cases have no required evidence, so required recall is null rather
than a misleading perfect score from a zero denominator. Even irrelevant results
could be useful to explain uncertainty; an answering-model evaluation is needed
to judge whether the model correctly abstains. This runner reports answer_quality
and abstention_quality as not_measured in every case.

## The three arms

1. Keyword: the existing FTS-based retriever.
2. Relationships: the same retriever with reviewed edges enabled.
3. Shuffled control: replace each target with a different eligible source in the
   same project/scope, available by the edge's time. Keep an explicit random seed.

The third arm is intentionally false connectivity, used ONLY in a disposable
negative-control database. It must never be presented as factual knowledge. Its
citations contain real fixture text, but they do not establish the invented link.
The report records the replacement edges so you can inspect them.

This first control uses one deterministic seed, preserves edge count/type but not
degrees, and may change payload length. It is a diagnostic, not a statistically
matched graph randomization. A real evaluation should use multiple seeds and check
whether topology or budget differences explain the observed effect. A source with
no eligible alternative causes a clear error rather than a fake control result.

All arms use the same corpus, query, scope, time cutoff and byte ceiling, with the
same retrieval limits (8 passages, one hop, no neighbouring turns, 1200-character
excerpts). Arm execution order is seeded and shuffled within each question. Data
loading/scoring is outside the timed retrieval. A single observation cannot control
cache and machine noise; do not infer a latency winner from this demo.

## Expected synthetic observations

The bundled data is deliberately engineered:

- needs-counterevidence: keyword returns the proposal; reviewed edges also recover
  the warning. Required-span recall rises from 0.5 to 1.0. The rewired control
  retrieves a distractor and remains at 0.5, with lower precision.
- exact-match: keyword already finds the required warning. Relationship expansion
  adds content/cost without improving required-span coverage.
- no-evidence: no arm finds the absent topic. Recall remains undefined and model
  abstention remains unmeasured.

These examples establish that the scorer distinguishes the behaviours. Their
labels and relationships were designed together, so they cannot establish that
real relationships help users. The report says Scoring demonstration only.

## What makes a question held-out?

A question is held-out relative to the development process. It and its evidence
labels must not have been used to choose queries, tune retrieval or curate edges.
Freeze a corpus snapshot and define eligible scope/time. An independent reviewer
labels useful/required evidence before seeing each arm's output. Keep all messages
from a shared decision/discussion lineage on one side of the development/evaluation
split; otherwise near-duplicates can leak the answer across the split.

The tool hashes and saves the supplied inputs/settings before queries. It hashes
the evaluator and stage-1 retriever source, and rejects declared development-lineage
overlap for holdout_candidate datasets. It cannot prove the reviewer is independent,
that undeclared lineage is absent or that nobody has already tuned on a question.
Even a declared holdout remains a candidate until that process is reviewed.

The optional reviewer and split_note fields record that provenance. They are
attestations, not magic certificates. Seeing evaluation results and changing the
retriever turns that set into development data for the next iteration; retain a
fresh unseen set for the next claim.

## Dataset shape and labelling

Use synthetic.json as the executable example. Each record has a human-readable key
and the stage-1 EvidenceRecord fields. Each case includes:

- id and lineage: question identity and the group excluded from development overlap.
- query: exact retrieval input, frozen across arms. Natural question-to-query
  rewriting is not evaluated; if added later it must be controlled separately.
- project, scope, as_of: eligibility boundary.
- relevant: all judged useful source keys. Set labels_complete false when the
  relevance review is incomplete; precision will be withheld.
- required: source key and unique exact text for each indispensable evidence span.
- answerable: whether required evidence exists in this frozen eligible corpus.

Kind is synthetic, development or holdout_candidate. Holdout candidates additionally
require label_reviewer, split_note and case lineages; development_lineages lists
excluded lineages. Work/personal scope must be assigned, not inferred from harness.

Required spans currently use an AND rule: all are required. Real questions may have
alternative sufficient evidence sets. Do not label two equivalent sources as both
mandatory: that would unfairly penalize good retrieval. Extend the label format
with alternatives before evaluating cases that require them. Duplicate/missing
spans and out-of-scope/future relevance labels are rejected.

## How would we judge real usefulness?

First report per-question paired differences, not only one average. Include wins,
ties, regressions, required correction/counterevidence coverage and cost. Retain
zero-tolerance integrity gates. Decide the minimum practically worthwhile benefit
before inspecting the results, based on the consequences of a missed decision and
the added cost. A small pilot has uncertainty; do not invent a universal six-out-of-
twenty threshold or assign statistical significance to three engineered cases.

Retrieval metrics are intermediate evidence. A later end-to-end study should hold
the answering model and actual tokenizer budget constant, hide arm names from
reviewers, and score whether recommendations are supported, recognize conflicting
or stale evidence, and appropriately abstain. Compare that benefit with latency,
context tokens and maintenance/extraction cost. More passages alone is not value.

For missing capture, record coverage separately. Missing source evidence cannot
be retrieved; it should not be confused with a retrieval algorithm failing on a
complete corpus. Current health flags remain a separate lab and are not used to
pretend that a corpus is complete.

## Current result and next boundary

We now have an executable evaluator, synthetic scoring regressions and a dataset
input path. We do not yet have independently reviewed held-out real questions.
The user's real examples are candidate questions, not automatically gold labels.
The next meaningful result needs that independent labelling/split review; until
then only scorer correctness is established. No real decision-quality improvement
or optimal engine is claimed, and no paid model calls are needed for this stage.

Optional learning exercise: calculate precision and required-span recall for a
pack containing the proposal plus the holiday distractor. Then compare your result
with the shuffled arm. Explain why perfectly resolving citations does not rescue
an irrelevant or misleading relationship.

## User priority: learning through validated context

[EXPLANATION-RUBRIC.md](EXPLANATION-RUBRIC.md) captures the user's clarified goal:
a justified answer with an inspectable evidence trail, often more valuable than
the answer alone. It separates citation fidelity, validation artifacts, reasoning
from evidence, alternatives, uncertainty and learner usefulness. These answer-level
dimensions remain explicitly unmeasured in the retrieval-only runner.

## Council review and pilot protocol

[COUNCIL-DECISION.md](COUNCIL-DECISION.md) distinguishes accepted scorer fixes
from unproven efficacy. [HOLDOUT-PROTOCOL.md](HOLDOUT-PROTOCOL.md) defines the next
small independently reviewed real pilot. Final local suite: 113 passing tests.
Post-review output includes control paired differences, relationship time/citation
checks and neutral unanswerable-retrieval outcomes. None is an answer-confidence
or independent factual-validation score.
