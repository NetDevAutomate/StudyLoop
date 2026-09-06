# Stage31: bounded history without hidden disagreement

The storage engine remains SQLite. This stage changes **which work a read performs**,
then measures that change. It preserves the Stage30 checkpoint and its full-history
baseline. It is an increment in the open [delivery contract](../delivery/GOAL.md).

## The problem revealed by Stage30

A 32 KiB response cap limited what the agent received, but the implementation first
verified every visible historical report. At 1,000 short versions the installed helper
took 656.72 ms median over five warm reads. A separate SQL trace counted 74,220 SELECTs.
Tracing adds overhead; the traced duration is not the same measurement as that median.

Many statements rebuilt the same scope predicate and read the same schema metadata.
The response was small, but the work required to produce it grew with the whole history.
This resembles collecting every historical routing update before displaying one current
route. Limiting the display does not reduce the collection work.

## Alternatives and the decision

| Choice | Benefit | Cost or risk | Decision |
|---|---|---|---|
| A: cache the scope predicate, still check every body | Removes repeated policy/schema queries; retains full verification | Work still grows with every version, including omitted bodies | Keep as measured control |
| B: scoped headers, atomic current group, keyset history pages | Checks selected bodies; exposes continuation and omitted evidence | Page contract and bounded-work errors must be explicit | Implement |
| C: materialized current heads or cached pages | Could avoid repeated history counting | More state to invalidate on correction, scope change, forgetting and restore | Defer until measurements justify it |

The same transaction supplies the parent visibility check, selected rows and cached
predicate. Native-session ownership is exclusive, so the main query can use that
known parent instead of repeatedly evaluating unrelated project/source owner alternatives.
Additional learner-record dependencies still participate in visibility. A test makes one
such dependency private while leaving the native parent visible: its report is withheld.
The final public response guard also rechecks policy, request scope, database access
generation and file identity. Caching a predicate never caches permission across requests.

Schema 40 adds only an ordered index on `(kind, subject, recorded_at, id)`. A simplified
header query diagnostic reduced 13,900 VM steps to 300 with that index. Those figures
describe a query-plan probe, not the full endpoint. The index allows descending keyset
selection without sorting all matching headers. It does not eliminate the count scan.
An installed schema 39 copy upgraded transactionally to 40, preserving34 rows across 57
pre-existing tables. Failure/retry is tested separately.

## How to read the new contract

`session-annotations/v2` separates the **current group** from **historical pages**:

1. The overview counts visible current reports. It includes every current body or none
   of them. Two conflicting reports remain two reports; size and recency do not choose
   a winner. More than 64 current candidates, an oversized group or excessive dependencies
   produces `current_group_complete: false` and a specific `current_omission_reason`.
2. History is selected in descending `(recorded_at, id)` order, normally 32 candidates.
   If more history exists, `next_cursor` identifies a continuation. History does not
   evict one side of the current group to fit the response.
3. Continuation pages are explicitly `history_continuation: true`. They contain only
   historical bodies, retain the current count and do not claim current-group completeness.
   A consumer must keep the overview separately. Even the last continuation has partial
   coverage because that page alone does not contain the whole answer context.
4. If a body merely needs a fresh page, it is retried there without advancing past it.
   If it cannot fit an empty page, its ID and omission reason are recorded once and the
   cursor advances. `next_cursor: null` therefore does not mean every body was delivered.
5. A returned report still has its exact immutable binding, authority, producer,
   correction predecessors and `history_incomplete` flag. Checking selected bodies is
   not a full database integrity scan and does not semantically validate their claims.

The cursor binds the session, annotation kind, policy digest, resolved scope, database
instance/generation and file identity. Corrections, forgetting and reclassification make
it stale; a changed policy is rejected even when the parent remains visible. The message
asks the caller to restart. The anchor must still be a visible historical row.

The cursor is a continuation hint, not an access capability or an integrity certificate
for a client's assembled history. It is not signed. A local caller can construct a different
valid visible anchor and intentionally skip history; every resulting read still filters
scope, checks selected bindings and identifies the page as partial. Do not treat an
arbitrary client cursor as proof that preceding pages were consumed.

## What is bounded, and what is not

The default serialized result limit is 32 KiB, configurable from 4 to 128 KiB. There are at
most 64 current candidates and 1–64 history candidates per request. Before loading each
report, SQL checks the complete stored row's byte size and a combined 256 link limit
across predecessors, captured sources and learner-record dependencies. The count cap
does not silently drop links: that report becomes explicitly unavailable.

Legacy note/tag/learning bodies are also counted and sized before being materialized.
Oversized legacy data keeps an unattributed-report indicator and current count without
returning its body. More than 256 legacy items is a separate omission reason.
These caps are conservative local defaults, not conclusions about real workload distributions.

A SQLite progress handler interrupts after a 1,000,000 VM-step budget, checked in blocks
of 1,000. Exhaustion raises an error and returns no context. It is not a wall-clock, IO,
memory or Python-hashing deadline. One SQLite operation can still process many bytes.
Counts are still linear in history size; sufficiently large histories can hit the cap.
Final response-monitor queries and transport/startup costs are outside this query budget.

If a report is omitted for bytes, retry the overview or preceding cursor with a larger
allowed budget. Some reports and current groups still cannot fit 128 KiB; their automatic
context remains unavailable. This stage introduces no claim of complete automatic context
for those cases. Existing plain-note human reads and administrative full-history helpers
remain separate operations and do not inherit this endpoint's work limits.

## Run the independently preserved lesson

Use the Stage31 checkpoint from [STAGES.md](../STAGES.md), with fresh output directories:

```sh
uv run python -m experiments.evidence_context.bounded_history.runner --output /tmp/stage31-demo
open /tmp/stage31-demo/walkthrough.html
uv run python -m experiments.evidence_context.bounded_history.benchmark --output /tmp/stage31-benchmark --sizes 10 100 1000 10000
uv run pytest packages/agent-session-tools/tests/test_annotation_pages.py experiments/evidence_context/tests/test_bounded_history_lesson.py -q
```

The four walkthrough views invoke actual CLI/MCP interfaces against fictional data:
the complete current conflict, history continuation, rejection after a correction and
an oversized current group withheld atomically. Nothing changes the owner's live DB.

For installed-package validation:

```sh
uv build --package agent-session-tools --wheel --out-dir /tmp/stage31-wheels
uv build --package studyloop --wheel --out-dir /tmp/stage31-wheels
uv venv /tmp/stage31-runtime --python 3.13
uv pip install --python /tmp/stage31-runtime/bin/python /tmp/stage31-wheels/agent_session_tools-0.1.0-py3-none-any.whl '/tmp/stage31-wheels/studyloop-0.2.1-py3-none-any.whl[web]'
uv run python -m experiments.evidence_context.bounded_history.runner --python /tmp/stage31-runtime/bin/python --require-installed --output /tmp/stage31-installed
/tmp/stage31-runtime/bin/python -I experiments/evidence_context/bounded_history/benchmark.py --output /tmp/stage31-installed-benchmark --sizes 10 100 1000 10000
```

`upgrade_probe.py --source <schema 39-fixture> --output <fresh-directory>` opens its
source read-only and upgrades a consistent disposable copy. It does not implement
managed backup restoration or reconcile deletion instructions with an old backup.

## Interpret the measurements

| Historical versions | Full cached control median | First page median | First-page SELECTs | Returned versions |
|---|---:|---:|---:|---:|
| 10 | 1.609 ms | 2.514 ms | 257 | 10 |
| 100 | 5.114 ms | 4.680 ms | 534 | 33 |
| 1,000 | 37.778 ms | 5.373 ms | 534 | 33 |
| 10,000 | 400.020 ms | 12.738 ms | 534 | 33 |

See [OBSERVED-RESULTS.json](OBSERVED-RESULTS.json) for final installed measurements,
test scope and limits. Each benchmark has five warm reads without SQL tracing;
SELECT counts come from a separate read. The control uses the cached predicate but
checks every body and does no output packing. The candidate returns selected bodies.

These are deliberately different workloads. Faster first-page retrieval is useful,
but it is neither same-information answer-quality superiority nor evidence for choosing
SQLite over a graph engine. The small 10-version case can be slower because paging and
budget safeguards add overhead. At larger sizes, work saved by selecting bodies dominates.

The decision is to retain this bounded interface, preserve the baseline, and move to
scoped transport/lifecycle. The legacy SQL sync still lacks observation ownership and
retirement metadata. File/live-session ownership, shared setup, startup and full release
acceptance also remain open. [Council arbitration](COUNCIL-DECISION.md) records why
reviewer agreement did not turn these local results into a production approval.
