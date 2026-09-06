# Stage28: one response, one access boundary

This stage closes a composition gap in the existing scoped readers. It adds a
production read-response guard and an independently runnable lesson. It does not
complete the full [production contract](../delivery/GOAL.md).

## Why individually correct queries were insufficient

`get_study_history` combines session statistics, last-studied dates, struggles,
wins, scores and practice attempts. Each helper opens its own connection and reads
the current scope configuration. A personal request could read personal statistics,
then read work assessments after the scope changed between helpers. Every query
would be individually permitted at its own instant, but the combined answer would
mix two boundaries. The first regression reproduced this: the MCP function did not
raise when its resolved scope changed halfway through.

This resembles assembling a network report from several services while the access
policy changes. Correct filtering in each service is necessary, but the completed
report also needs one consistent permission context. We must check the assembly,
not only its ingredients.

## What the four-view lesson shows

The lesson uses fictional personal/work sessions, real installed StudyLoop HTTP
routes and the real MCP server over stdio. A small test wrapper injects a controlled
scope change around an actual helper; it does not replace the query or response
implementation. No model provider is called and owner data/configuration is untouched.

1. A normal personal notes request returns the personal note.
2. A scope change after the final query causes HTTP 409. The already assembled
   personal note is absent from the transmitted response.
3. Assigning a source to work and then back to personal still changes the durable
   generation. Matching the final owner is insufficient to erase an intervening
   revocation.
4. The MCP request containing a between-helper change fails without partial
   history. Its next request independently resolves work scope and returns the
   work statistics. Scope is not cached for the life of the server.

All eight checks passed from fresh local wheels with StudyLoop's existing web
extra. The four disclosures and viewport were checked in the browser with no
console errors. The HTTP test uses ASGI transport without the application's
lifespan startup. This is installed route/MCP evidence, not complete startup UAT.

## Run from the frozen stage

Use the checkpoint in [STAGES.md](../STAGES.md) for exact historical behavior.
Choose a fresh output directory on every run:

```sh
uv run python -m experiments.evidence_context.response_boundary.runner --output /tmp/stage28-demo
open /tmp/stage28-demo/walkthrough.html
uv run pytest packages/agent-session-tools/tests/test_context_response.py packages/studyloop/tests/test_context_consumer_scope.py packages/studyloop/tests/test_context_response_middleware.py experiments/evidence_context/tests/test_response_boundary_lesson.py --import-mode=importlib -q
```

For a fresh runtime containing only installed packages:

```sh
uv build --package agent-session-tools --wheel --out-dir /tmp/stage28-wheels
uv build --package studyloop --wheel --out-dir /tmp/stage28-wheels
uv venv /tmp/stage28-runtime --python 3.13
uv pip install --python /tmp/stage28-runtime/bin/python /tmp/stage28-wheels/agent_session_tools-0.1.0-py3-none-any.whl '/tmp/stage28-wheels/studyloop-0.2.1-py3-none-any.whl[web]'
uv run python -m experiments.evidence_context.response_boundary.runner --python /tmp/stage28-runtime/bin/python --require-installed --output /tmp/stage28-installed
```

A separate installed migration rehearsal accepts a schema37 database and copies
it read-only before upgrading:

```sh
/tmp/stage28-runtime/bin/python -I experiments/evidence_context/response_boundary/upgrade_probe.py --source /path/to/stage27-demo/sessions.db --output /tmp/stage28-upgrade --require-installed
```

The observed copy preserved 67 rows across 56 preexisting tables, with empty foreign-key
errors and `integrity_check=ok`. An injected schema38 failure also rolls back its
new table/triggers and retries successfully. This is not managed restore with
current deletion metadata.

## Why this design

| Alternative | Benefit | Cost or limitation | Decision |
|---|---|---|---|
| Pass one connection/policy through every helper | One data snapshot and explicit dependencies | Broad consumer rewrite; still needs a defined revocation/release boundary | Remains an option if one historical fact snapshot is required |
| Request-local frame plus access generation | Detects inconsistent permissions across existing helpers | Extra monitor connection/checks, careful transport integration | Implement |
| One process-wide lock | Simple serialization within that process | Does not coordinate another process or external config edits; serializes unrelated requests | Do not use as the access guarantee |
| Compare only config digest | Cheap | Misses per-session assignments, tombstones and scope-default changes | Insufficient |
| Use only `PRAGMA data_version` | Built-in connection change detection | Includes ordinary writes and cannot align an older helper snapshot with a newly opened monitor | Insufficient fallback |

A `ContextVar` associates the frame with one request task. FastAPI copies that
context into its synchronous worker thread; the frame object carries observations
back to the awaiting request. An `RLock` protects the frame and its monitor
connections if contributors overlap. This is not a global request lock. Tests cover
actual FastAPI sync endpoints, `asyncio.to_thread`, independent tasks and sixteen
simultaneous requests. A new custom thread pool must explicitly propagate context
or establish its own read boundary; arbitrary threading is not automatically proven.

Each helper continues to resolve the live policy. The frame rejects a different
policy or scope instead of silently switching or retaining a long-lived cached
policy. A detected conflict remains failed even if a helper catches the exception
and the scope is later restored. A completed/cancelled frame cannot be reused.

## What the database contributes

Schema38 adds `context_access_state(instance, revision)`. The instance identifies
this local database generation. The revision increases transactionally for the
specific access/dependency/retirement operations in `response_schema.EVENTS`:
project and session assignment changes, tombstones, dependency changes and removal
of owned/evidence/observation records. Rolled-back changes do not advance the
committed counter. Changes away and back do. New access-affecting features must
extend this contract and tests; a counter is only as complete as its writers.

Each helper records the generation from its own read snapshot. A separate read-only
monitor sees the committed generation without retaining that old transaction. At
completion, the frame checks live configuration/scope, instance/revision and file
identity again. A replacement file is not mistaken for the previously opened DB.
Compaction preserves real content while retaining the destination's fresh access
identity; it must not copy or merge this local singleton as shared conversation
content. The regression found and fixed a singleton collision in that path.

Older schemas cannot provide this comparison. Protected response APIs now explain
that `session-context policy apply` is needed to perform the migration. They do not
auto-migrate a native memory read or silently claim equivalent protection. Ordinary
StudyLoop connections continue through canonical migrations. The old-stage versions
remain runnable at their own checkpoints.

## Where the response is released

`consistent_read` guards the return of the selected StudyLoop and session-db MCP
read functions. Canonical native context reads use `read_boundary` inside
`open_context`. The finite HTTP middleware retains both headers and body until the
application has finished and validation succeeds. On conflict it sends 409 and a
retry explanation, without the earlier body. The outer security-header wrapper
continues to apply to that error response.

The HTTP buffer is limited to 8 MiB and 1,024 ASGI messages. Oversized output produces 413
with a narrower-query/smaller-limit instruction. The test proves an early buffered
header and private prefix are discarded. This is a per-response bound, not a claim
about total server memory under arbitrary concurrency.

Business mutations are not treated as read responses. Existing transactional write
guards remain responsible for commit/rollback; native `open_context(write=True)`
now rechecks the resolved scope as well as the full policy. A changed default or
environment scope cannot pass merely because project definitions are unchanged.
Normal POST note creation still commits and returns 201. The read guard never claims
that an already committed write was rolled back.

Cancellation tests interrupt assembly and transport release, verify no early body,
close monitors, restore context and refuse delayed frame reuse. Validation is
synchronous, so cancellation is observed at async suspension points; the tests do
not invent an async cancellation point inside a synchronous SQLite call.

## Measurements and limits

The installed two-session fixture used 20 iterations per variant with alternating
paired order. Direct history calls measured median 14.932 ms without the outer
response guard and 16.892 ms with it: about 1.96 ms additional time. Both variants retain
per-query scope filtering. Helpers/policy reads are included; process startup and
MCP transport are excluded. This is neither a production-scale benchmark nor an
engine comparison, and it gives no general throughput guarantee.

The combined memory/experiment suite passed 1,581 tests with one optional skip. The
StudyLoop suite passed 3,791 tests, four skipped and 704 deselected before final added
cancellation/HTTP tests. Final focused results are recorded in OBSERVED-RESULTS.json.
Both council rounds returned three provider buckets; the arbitration is separate
from test evidence in [COUNCIL-DECISION.md](COUNCIL-DECISION.md).

This is optimistic permission validation at a defined completion point. It does
not freeze all business facts at one historical instant, lock external configuration,
or recall data already delivered under a valid policy. Original transcripts,
unmanaged backups and clients that already received content have separate retention
boundaries. Managed restore and deletion propagation still require their own work.

The live session SSE stream, WebSockets, session IPC files, remaining learner graphs
and planning storage are not covered by this finite-response guard. Their ownership
and appropriate per-event release checks remain required, along with protected sync,
forget/reimport/restore/index behavior, shared setup/doctor and installed startup.
The full production goal remains active.
