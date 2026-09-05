# Stage18: bind the explanation to stored evidence

Stage17 separated captured metadata from model interpretations. This stage puts
that boundary in the actual `agent-session-tools` package and canonical SQLite
schema, exercised on a disposable database. It is an implementation checkpoint,
not proof that the existing CLI, harness hooks or sync already use the boundary.

## Run the lesson

```sh
uv run python -m experiments.evidence_context.canonical_sources.runner --output /tmp/evidence-stage-18
open /tmp/evidence-stage-18/walkthrough.html
uv run --group dev pytest packages/agent-session-tools/tests/test_context_store.py experiments/evidence_context/tests/test_canonical_sources.py -q
```

Use a new output directory. The command creates a synthetic `sessions.db`, JSON
results and a walkthrough. No provider call, real conversation or live configuration
is used. The demo names two personal projects and one work project, but they are
fictional records, explicitly classified by the script.

Follow the source from Codex, a proposed correction from Kiro on another machine,
an edit to the original source, then a project scope change. A work fixture remains
outside the personal query. The earlier citation still quotes the earlier version.
After reclassification the affected assertion and relationship become unavailable
to the personal reader. The retained before/after walkthrough is educational fixture
output, not an implementation of purging previously delivered real context.

## Why this schema?

| Record | Owns | Why separate? |
|---|---|---|
| projects / session assignments | Explicit current scope and project identity | A harness can be used for both work and personal sessions. |
| evidence versions | Native locator, parser, origin, body hash and immutable text | A later import cannot silently rewrite an earlier citation. |
| assertions | Proposed meaning and generator identity | A genuine source does not guarantee the proposed interpretation. |
| citations | Exact evidence ID, Unicode offsets and quote | The reader can inspect precisely which words supported the proposal. |
| relations | Proposed supports, contradicts or corrects links | Competing corrections remain visible; arrival order does not establish truth. |
| tombstones | Content-free session deletion identity | Capture must not recreate an explicitly forgotten session. Full forgetting is still pending. |
| FTS index | Disposable search projection | Search can be rebuilt from canonical records. |

All these are in the same SQLite database. That permits atomic writes across a
proposal and its citations. A separate evidence database would introduce coordination
and failure handling without a demonstrated retrieval benefit. Typed relationship
rows also preserve the route to bounded graph traversal without requiring a graph
server now.

## A source identity is not a source version

The native harness, session ID and native event key determine the logical source key.
The immutable version ID binds its text and captured metadata. A changed body creates
a new version; old citations retain their old ID and offsets. Machine/locator/parser
changes can also create versions. Deduplicating equivalent captures for retrieval
is a later policy task; version count must not be reported as conversation count.

Source event time and first import time are separate. Missing event time remains
unknown; it is not filled with today's import time. Known source timestamps normalize
to UTC so sorting different time zones remains chronological. Neither recency nor a
lexical match establishes validation applicability or decision sufficiency.

## What failed while integrating it?

The initial broader package run had 1,140 passes and nine failures. Seven failures
came from old migration tests using a session-only mock despite running every later
migration; those fixtures now include the real base messages schema. The other two
exposed a production compaction defect: its index-name exception only recognized
`messages_fts`, so it copied the new index's internal tables into an initialized index.

Compaction now enumerates SQLite's table types and copies canonical tables, letting
source insertion rebuild FTS. A separate populated-source test then reproduced
another defect: `immutable=1` ignored committed records still in a live WAL journal.
A read-only `mode=ro` attachment held in a transaction includes those committed records
and supplies a consistent snapshot. The regression preserves evidence, citations,
search results and foreign-key integrity through compaction while the writer remains open.

Migration tests deliberately inject invalid SQL after partial schema creation. The
whole upgrade rolls back; retry preserves existing conversations. A migration inside
a caller-owned transaction uses a savepoint, so it can roll back its own failed work
without discarding the caller's earlier rows. Newer database versions are refused.
The framework remains forward-only; this is not a down-migration implementation.

## What is proven at this boundary?

Tests exercise exact Unicode citations, late-failure rollback, old source versions,
wrong-scope direct/search reads, multi-project reclassification, both concurrent
correction branches, immutable updates, corrupted-source rejection through every body
read path, time-zone ordering, FTS cleanup and low-level tombstone suppression.

The tests use the production storage and migration functions. They do not prove native
parser accuracy, installed hook invocation, complete forgetting, scoped sync, restore
suppression, or useful automatic arbitration. The `corrects` edge is a proposal with
recorded authorship, not a semantic certification or an instruction to erase its target.

## Next boundary

Connect trusted native capture, explicit configuration and all registered read paths
to the canonical store. Before exposing forgetting, trace every managed derived copy
and restore path. Before scoped sync, filter payloads before staging and refuse peers
that cannot enforce deletion/scope rules. These remain requirements in
[../delivery/GOAL.md](../delivery/GOAL.md), not optional follow-up improvements.
