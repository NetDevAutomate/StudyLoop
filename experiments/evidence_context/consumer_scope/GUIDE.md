# Stage20: StudyLoop consumes scoped history

Stage19 connected the memory component's readers to scope policy. This stage
follows that context into StudyLoop itself: resume, topic history, activity,
struggle extraction and its evaluator. It uses the existing product paths and
preserves the earlier stages independently.

## Run the lesson

```sh
uv run python -m experiments.evidence_context.consumer_scope.runner --output /tmp/evidence-stage-20
open /tmp/evidence-stage-20/walkthrough.html
uv run pytest packages/studyloop/tests/test_context_consumer_scope.py experiments/evidence_context/tests/test_consumer_scope.py -q
```

Choose a fresh output directory. The runner creates synthetic conversations and
config, then runs actual StudyLoop code in a subprocess. It invokes the real
resume CLI separately. The extractor is a local spy returning no observations:
we measure which messages it receives without a model call. The registered MCP
history function is exercised in the demo; the tests additionally use real MCP
stdio with a child server and an SDK client.

## What changed and why

Both fixture conversations use Kiro. The work conversation is newer. The request
scope is explicitly personal. That arrangement catches an easy mistake: choosing
the latest session before deciding which sessions may be used.

| Path | Boundary now tested |
|---|---|
| Resume | Choose the latest visible session, then select its visible messages. |
| Topic history | Apply policy before selecting FTS snippets. |
| Struggle search | Inspect only visible user messages. |
| Streaks | Count only visible conversation dates and sessions. |
| Extractor selection | Latest, full and direct-ID selections use the shared memory owner. |
| Extractor invocation | An excluded direct ID fails as unavailable before provider invocation. |
| Extractor persistence | Classified writes into the old global progress aggregate are refused before provider invocation. |
| Quality evaluator | Open the DB read-only and record unavailable scoped cases explicitly. |
| CLI/MCP errors | Missing or unapplied scope is actionable; it is not described as missing history. |

The prototype therefore returns the personal preview, counts one conversation and
delivers one personal transcript to the spy. Work bodies never appear in the
returned data. Editing scope config without applying it makes the next request
fail clearly. No original source body is erased by these read checks.

## The new finding: a pointer does not establish ownership of a merged record

The existing `study_progress` table combines observations with the same topic and
concept. Its writer replaces notes when supplied and carries older notes forward
when notes are omitted; its latest-source pointer can advance independently.
The original Stage20 text incorrectly said it appended notes. Consider:

1. A personal session reports difficulty with SQL windows.
2. A work session discusses a confidential example of the same concept.
3. The work note replaces the note under the shared concept key.
4. Another personal session updates the latest-source pointer but omits notes,
   leaving the work note in place.

Labelling the whole row personal from that final pointer would expose earlier
work content. A valid pointer is not evidence that it describes every component
of a merged result. This is a concrete case where provenance completeness matters
more than adding a new database engine.

For this increment, classified resume/history responses withhold the unowned
progress, stats and wins fields with `withheld_missing_scope_lineage`. The resume
CLI explains the omission. These fields remain inspectable in an explicitly
unclassified request only when the database has no source assignments. A personal
or work request never silently falls back to that inspection mode.

The extraction pipeline also refuses classified writes to the old global
aggregate. Read filtering alone would not prevent future mixing. `--dry-run`
remains available and **still invokes the selected model** with scoped messages;
it prevents progress writes, not model usage. The lesson's spy makes no network
calls, unlike the product's explicitly configured live extractor.

## How this affects evaluation

An unavailable session now carries a specific error in the evaluation result.
It is not quietly presented as an empty transcript or a successful abstention.
The old scoring formulas remain unchanged, so their scores still require review
alongside these availability errors; this stage does not claim improved semantic
accuracy or a new held-out result.

Likewise, the returned timestamp means the topic appeared in a visible message.
It does not prove mastery, successful validation or the correctness of the answer.

## Why observations plus rebuildable summaries are the next direction

The three responding council providers favored keeping each new observation
linked to its contributing source, then deriving a summary for the current scope.
This is the direction for the next implementation; it is not implemented by this
stage's conservative withholding.

| Option | Benefit | Limitation |
|---|---|---|
| Add scope to the old mutable aggregate | Small schema change; familiar reads | Cannot reconstruct which source contributed each note or undo one contribution. Existing mixed rows cannot be labelled safely. |
| Store source-linked observations and derive scoped aggregates | Reclassification, corrections and forgetting can follow individual contributions | More records and explicit derivation logic; caches must include policy/lifecycle state. |
| Move the same merged rows to a graph engine | Flexible traversal | Missing ownership and source contributions remain missing. |

For a networking analogy, keep the route announcements and their origin, then
derive the current routing table. A final routing-table row alone cannot explain
all earlier announcements or let you withdraw one contributing announcement safely.
Similarly, a learning summary is a projection of observations, not the evidence
that originally established them.

The next schema must also handle an explicit learner observation with no coding
session, concurrent corrections, source deletion and old snapshots. Historical
rows stay preserved and unclassified until reliable lineage exists; they must not
be retroactively labelled from their latest source pointer. A model-derived
observation remains an interpretation even when it has a valid source link.

## Verification discoveries

The first broad regression revealed that this stage's test fixture replaced
unrelated StudyLoop configuration. It was narrowed to the memory policy loader;
legacy test fixtures now explicitly request unclassified scope. New classified
tests use their own actual config. Product defaults were not weakened.

Lock-error test doubles needed to expose SQLite's transaction state. The full
suite also caught two pre-existing hook-installer exists/read races; direct reads
with missing-file handling now preserve the same merge behavior. A secrets test
fell back to an ambient credential: tests now remove those environment fallbacks,
and subsequent broad runs strip provider credentials from their process. No
credential values are included in this learning repository.

See STAGES.md and delivery/STATUS.json for final checkpoint verification totals.

## What this stage does not complete

The full production goal remains active. Other learning-data consumers and writers
need durable ownership, and the new canonical evidence store still needs complete
native capture, rich retrieval, protected sync, forgetting/restore and installed
acceptance. The helper is a local policy boundary, not OS-level access control.

See [COUNCIL-DECISION.md](COUNCIL-DECISION.md) for accepted corrections, rejected
assumptions and the exact review coverage. The Stage8 exercise remains unchanged.
