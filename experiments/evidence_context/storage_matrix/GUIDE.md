# Stage 13 — Which engine serves the same context best?

Stage 12 changed **information selection**. This stage fixes the information and
compares storage implementations. See RESULTS.md for actual measurements; the original
benchmark and subsequent query diagnostic remain separate runnable modules.

## Model versus engine

A knowledge graph is a way to model entities and relationships. A graph database is
one way to store and query that model. SQLite can represent the same nodes and edges
with tables and a recursive query. Choosing relationships does not require choosing
a graph engine.

We compared:

| Layout | Message bodies | Relationships | Query path |
|---|---|---|---|
| SQLite | message table | edge table | SQL lookup/recursive CTE |
| LadybugDB | node properties | Link relationships | Cypher lookup/traversal |
| mixed | SQLite message table | Ladybug projection | graph IDs, then SQL content lookup |

LadybugDB 0.20.2 was installed only in an ephemeral uv environment. Its documented
[Python API](https://docs.ladybugdb.com/client-apis/python/) supports the embedded
connection used here; see [installation](https://docs.ladybugdb.com/installation/).
We did not install a production service or add a workspace dependency.

## What equality establishes

The same nodes, edges, text, IDs and query roots go into every implementation. We
compare sorted full result rows before timing any query. A graph engine returning
extra context would fail this comparison rather than earn a quality bonus.

At depth zero, return one message. At depths one and two, return distinct messages
reachable within that many edges. Cycles can return the starting node at depth two.
Multiple relationship types between the same pair must not duplicate result rows.
The fixture tests also cover disconnected nodes and missing IDs.

This is like testing routing implementations with the same topology and requested
paths. Their execution cost can differ while their routing answer stays identical.
No answer generator is run here: equal generator inputs are the contract, not an
empirical assertion that stochastic model outputs are byte-identical.

## Workload and fairness limits

Actual snapshot: 1,019 nodes and 3,138 edges. Scale case: ten disjoint copies, yielding
10,190 nodes and 31,380 edges. Duplication preserves node degree, text and topology;
it does not simulate realistic vocabulary growth, hubs or new questions. Compression
can benefit especially from repeated text.

Forty seeded roots per scale, three depths, five randomized warm rounds yield 600
measurements per engine per scale, 3,600 total. Equality checks are untimed and warm
those queries. Graph settings: one thread, 128 MiB buffer. Single Python process and
client overhead included. SQLite uses default settings. Timing does not measure cold
cache, concurrency, streaming, vector search or cross-machine sync.

Build time is implementation cost: SQLite uses executemany while the graph uses
per-row CREATE within a transaction. It is not a bulk-loader competition. Reopen plus
COUNT includes opening, querying and closing without eviction of the OS page cache.
Mixed storage includes the SQLite content database and the graph projection. That
SQLite prototype also contains edges, so the mixed size has redundant structure;
an optimized mixed design might remove it. No memory/RSS measurements were taken.

## The query-plan lesson

The original SQL uses a recursive CTE, then joins and deduplicates full message rows.
At the larger scale SQLite selected a scan of the message primary-key index before
joining the small reachable set. That plan can get slower with the total table size,
even when the answer size stays small.

The separate diagnostic changes only final lookup formulation:

```sql
SELECT m.id, m.project, m.at, m.text
FROM message m
WHERE m.id IN (SELECT id FROM reach WHERE depth > 0)
ORDER BY m.id;
```

The recursive traversal and result semantics stay the same. EXPLAIN QUERY PLAN now
reports indexed message lookup by ID. We verify identical rows for the original
roots and rerun a paired, randomized original-vs-indexed SQL comparison. This is a
**post-hoc diagnostic**, not a silent replacement of the original result. A future
engine race must preregister this formulation and treat all engines comparably.

## Run independently

No gateway is needed. For a tiny synthetic exercise:

```sh
uv run --with ladybug==0.20.2 python -m experiments.evidence_context.storage_matrix.benchmark \
  --corpus experiments/evidence_context/storage_matrix/demo-corpus.json \
  --output /tmp/stage-13-demo
uv run python -m experiments.evidence_context.storage_matrix.query_diagnostic \
  --directory /tmp/stage-13-demo
uv run --with ladybug==0.20.2 --group dev pytest \
  experiments/evidence_context/tests/test_storage_matrix.py -q
```

The tiny demo checks mechanics; its timing is not the real result. To rerun the
owner's exact private snapshot, substitute
`experiments/evidence_context/.private/stage-12/run/corpus.json` as --corpus and
choose a fresh output directory. Private databases and timings from this run are
preserved under `.private/stage-13/run`; they are not part of a public Git clone.

Do not benchmark against the production sessions.db. The benchmark builds disposable
stores from the snapshot and refuses to reuse an existing output directory.

## What this leaves open

The graph engine offers native traversal syntax, while a mixed design can separate
retrieval indexes from canonical content. Both introduce a second engine dependency;
the mixed design also introduces index consistency, recovery and forgetting work.
Those costs were not measured by a sub-millisecond query benchmark.

No tests here certify correction/tombstone propagation into graph/vector indexes,
policy edits, authorization across an entire path, capture health or installation.
The earlier synthetic lifecycle stages preserve those requirements; an integration
must still prove them against its actual adapters. Better query speed cannot justify
lost work/personal boundaries or resurrection of forgotten material.

The committed runner adds a comment documenting non-cryptographic fixed-seed randomness
for the security linter after execution. Exact pre-comment sources are preserved in
the private executed-source directory; behavior and frozen inputs were not changed.
