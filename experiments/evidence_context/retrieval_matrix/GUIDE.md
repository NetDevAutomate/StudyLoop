# Stage 12 — Which information helps a historical answer?

This is a real-data **development pilot**, separate from Stage 13's engine benchmark.
Its purpose is to find the next useful experiment, not certify a product design.
Read RESULTS.md first, then open the private replay and start with Q3.

## The question we separated

A database can store the right information while retrieval fails to return it. An
agent can receive a relevant quote and still infer more than the quote supports.
Those are different failure boundaries:

```
source history -> eligible passages -> ranking -> context budget -> answer -> acceptance
                   scope/time          recall     omissions        claims    evidence
```

Think of this like network troubleshooting: having the route in the table does not
prove the packet reached the application, and delivery does not prove the application
processed it correctly. We measure each boundary instead of crediting the whole chain
because one component worked.

## What stayed fixed

Nine Codex root sessions from explicitly allowed personal StudyLoop/MailGraph project
paths produced 1,019 passages. The source sessions.db was opened read-only in one
transaction. The personal boundary came from project-path configuration, not the
harness name. Sessions before 2026-08-21 with at least ten user/assistant messages
were eligible. Known earlier demo sessions, short/instruction envelopes and three
potentially sensitive chunks were excluded. This does not validate other harnesses,
work scopes, capture completeness or cross-machine behavior.

Four questions: browser voice rationale; a partially completed graph rebuild; browser
Parking checks; and a constructed unsupported database-benchmark claim. These were
selected from known episodes. One episode continues an earlier development lineage.
Neither the questions nor the reviewers are independent human ground truth. Do not call
this a held-out trial. The full corpus is not exhaustively labelled.

Passages use the local all-mpnet-base-v2 tokenizer: up to 280 tokens, step 240, exact
message offsets and digest preserved. Embedding uses the cached model on CPU, 768
normalized dimensions. Original-message tokenization can warn about long messages;
only bounded chunks go to the embedding model. No text truncation repairs were made.

A Qwen3-Coder tokenizer measures the final serialized evidence pack. Every arm gets
the same **ceiling** of 1,400 context tokens and six passages, not padding to an equal
length. System prompt, question and output tokens are outside that evidence ceiling.
Complete passages that do not fit are skipped. This packing policy itself can omit
useful evidence and is not optimal knapsack selection.

## Four ways to choose context

| Arm | How it ranks | What extra capability it tests |
|---|---|---|
| keyword | FTS5 BM25 over fixed natural-language query terms | lexical overlap |
| semantic | local normalized embedding cosine | wording similarity |
| relationships | keyword + one-hop structural neighbours using reciprocal-rank fusion | adjacent/shared-file context |
| combined | keyword + semantic + structural reciprocal-rank fusion | multiple retrieval signals |

Reciprocal-rank fusion adds `1 / (60 + rank)` per list, then breaks ties by passage ID.
The graph starts from three keyword seeds. Its 3,138 directed links are sequence links
between retained chunks and bounded neighbours sharing file references. These links
were built without relevance labels. They do **not** mean supports, refutes or validates;
a shared filename does not establish entity identity or factual agreement. This stage
tests one structural graph recipe, not all knowledge-graph designs.

All four arms use the same corpus and project/time eligibility. FTS statistics and
embedding computation span the allowed pilot corpus before candidate filtering; this
is not a production authorization or information-isolation proof. Historical timestamps
may fall back to session creation when a message lacks its own timestamp.

## Why scoring needed arbitration

Three model providers labelled fixed episode pools before seeing retrieval results.
The coordinator checked their proposed alternatives against actual source passages.
Some were partial facts, not equivalent alternatives. The original brief capped each
question at three required groups; Q3 needs four, so that cap was removed before
retrieval. The amendment, labels, reviewer outputs and hashes are preserved privately.

A group represents one required fact; passage IDs inside it are alternative witnesses
of that fact. Q2's final summary can cover several facts, but it remains one source.
Q3 needs the unsafe-default finding, CRUD actions, reload result and cleanup separately.
Coverage is **reviewed-fact coverage**, not corpus-wide recall, precision or factual truth.
An empty negative-control label set has no recall denominator, rather than perfect recall.

The frozen answer prompt asks for answer, evidence status, exact quote citations,
limitations and next check. Qwen3-Coder answered twice per condition: 32 calls, fixed
randomized order, temperature zero, 1,500 output-token limit, two client workers, no
application retries. A strict JSON parse is attempted first; only a complete Markdown
JSON fence may be removed. Invalid outputs would be retained, not regenerated.

Exact quote checking establishes location, not entailment. A source saying “cleanup
verification” in a plan can be quoted exactly while falsely supporting “cleanup passed.”
The answer council receives allowed source IDs and answers without retrieval-arm labels.
Qwen also served as a judge, so its judgment is not independent of the answer-model
lineage. Human assessment of explanation usefulness remains outstanding.

## Run without paying for models

From this worktree root:

```sh
uv run --group dev pytest experiments/evidence_context/tests/test_retrieval_matrix.py -q
uv run python -m experiments.evidence_context.retrieval_matrix.report \
  --directory experiments/evidence_context/.private/stage-12/run \
  --output /tmp/stage-12-replay.html
open /tmp/stage-12-replay.html
```

The tests use synthetic records and a fake tokenizer; the replay uses preserved actual
answers without network calls. Pick a new output filename. Private snapshots are
ignored by Git and must be preserved separately; a Git clone has aggregate results
and tests but deliberately has no personal transcripts. The local .private directory
keeps these snapshots alongside the learning checkout for the owner's study.

## Reproduce a new pilot deliberately

Use a fresh directory. The owner's private config records explicit source paths,
questions, exclusions and cached model/tokenizer. It is not a portable public fixture.
Review its personal/work scope before adapting it to another machine.

```sh
uv run python -m experiments.evidence_context.retrieval_matrix.trial prepare \
  --config experiments/evidence_context/.private/stage-12/config.json --directory /tmp/new-pilot
uv run python -m experiments.evidence_context.retrieval_matrix.trial embed --directory /tmp/new-pilot
# Independently review the episode pools, then write labels.json BEFORE retrieval.
uv run python -m experiments.evidence_context.retrieval_matrix.trial freeze --directory /tmp/new-pilot
uv run python -m experiments.evidence_context.retrieval_matrix.trial retrieve --directory /tmp/new-pilot
# Explicit paid step, only with the authorized gateway credentials already in process env:
uv run python -m experiments.evidence_context.retrieval_matrix.trial answers --directory /tmp/new-pilot
```

Freeze records inputs/code hashes and embeds the prompt. Keep the pinned stage checkout
and do not modify inputs after freezing; this experimental runner is not a tamper-proof
execution system. Model availability/backend routing, tokenizer caches and source DB
contents can change. A fresh preparation is a new experiment, not an exact replay.
Nothing here installs hooks, changes the source DB, promotes a production prompt or
completes the saved Stage 8 exercise.

The committed runner adds a comment documenting non-cryptographic fixed-seed randomness
for the security linter after execution. Exact pre-comment sources are preserved in
the private executed-source directory; behavior and frozen inputs were not changed.
