# Stage 13 results — no migration justified

Run date: 2026-09-05. The three layouts returned identical complete rows for all 120
sampled queries at each size. The 3,600 timed executions measure warm client query
latency; they are not 3,600 independent quality observations.

## Frozen original benchmark

Median / p95 milliseconds, two-hop traversal:

| Corpus | SQLite | LadybugDB | Mixed |
|---|---:|---:|---:|
| 1,019 real nodes | 0.0757 / 0.1676 | 0.3387 / 0.4444 | 0.2878 / 0.3925 |
| 10,190 replicated nodes | 0.5286 / 0.7582 | 0.5003 / 0.6169 | 0.3518 / 0.4935 |

The mixed layout is faster than the original SQLite query at the replicated size.
That is a real observation about these implementations, but inspection found an
avoidable SQLite scan. It cannot establish an inherent graph-engine advantage.
All results fit within 47 returned rows. Lookup and one-hop timings, exact byte counts,
reopen measurements and build times are preserved in observations.json.

| Corpus | SQLite MB | LadybugDB MB | Mixed MB |
|---|---:|---:|---:|
| actual | 1.073 | 2.884 | 3.342 |
| ten disjoint copies | 10.506 | 3.617 | 13.496 |

MB uses decimal bytes. Ladybug's small replicated file is consistent with compression
of repeated text; this was not separately instrumented. It does not establish the
storage ratio on ten times as much unique history. Mixed retains redundant SQLite edges.

Actual-size build times were SQLite 0.0061s, Ladybug 0.2835s, mixed 0.2599s; replicated
size 0.0485s, 2.1990s, 2.1454s. Different Python insertion strategies confound an engine
bulk-loading claim. Reopen-plus-count was about 0.26–0.29ms for SQLite and 27–30ms for
the graph files; it is not a cold-cache or production startup measurement.

## Separate post-hoc SQL diagnostic

Same roots, same rows, five paired randomized warm rounds per formulation. No schema
or index additions: change the recursive result join to an IN-based indexed lookup.

| Corpus | Original SQL two-hop median | Indexed lookup median | Indexed p95 |
|---|---:|---:|---:|
| actual | 0.0654ms | 0.0158ms | 0.0602ms |
| ten copies | 0.4939ms | 0.0193ms | 0.0544ms |

At ten copies that is approximately a 25.6-fold reduction within SQLite. Query plans
confirm the final message access changed from a scan to lookup by ID. See
query-diagnostic.json and query_diagnostic.py; the original baseline is preserved.
Do not splice this timing into the original engine table as though it was preregistered
or interleaved with the graph queries. A fair new race would include all formulations.

## Interpretation

SQLite is an adequate baseline for the observed small-neighbourhood workload. No
storage-induced answer-quality gain was measured: the engine comparison deliberately
returned identical context and did not invoke a generator. This is compatible with
representing explicit relationships in SQLite tables.

There is no measured product need for migration. Before testing another engine again,
name the workload SQLite cannot meet: e.g. validated high-degree traversal, concurrent
capture/read pressure, or a measured retrieval-index constraint. Use distinct text and
real topology growth if scale becomes relevant. No universal latency SLA was set here.

A second engine adds index freshness, correction/forgetting propagation, install and
recovery obligations. These were not measured, so it would be misleading to assign
an exact operational overhead number. Preserve the standalone/StudyLoop integration
boundary and canonical records while exploring replaceable retrieval adapters.
