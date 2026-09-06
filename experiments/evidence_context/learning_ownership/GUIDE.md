# Stage26: learning records need an owner too

This stage connects the source-bound memory work to three real StudyLoop record
types: study sessions, teach-back scores and knowledge bridges. It is a production
implementation increment, not production acceptance. The full contract remains in
[GOAL.md](../delivery/GOAL.md). Previous stages retain their separate checkpoints.

## The problem we are testing

Protecting conversation excerpts is insufficient if a later progress report,
session note or assessment can copy the same information into an unscoped table.
The agent could retrieve work history through an apparently personal learning
summary. Even a count or a ranking can carry information from excluded records.

The earlier conservative response was to withhold ambiguous global learning
aggregates. That protects a boundary but removes useful context. This stage asks
whether explicit ownership can recover permitted history without guessing where
old records belong.

In networking terms, classifying the original packet does not protect a copy made
by another service. Its derived state needs the same boundary. A visible counter
must count only the permitted traffic, rather than count everything and hide the
packet payload afterwards.

## What the four-view lesson does

The runner creates a disposable database and configuration. It records fictional
personal and work sessions through the actual StudyLoop Python APIs, then starts
the actual StudyLoop MCP server over stdio. No owner's configuration or database
is changed and no model provider is called.

1. Personal requests return one permitted session, a score of 10, its progress
   assessment and a personal knowledge bridge. Work records about the same concept
   remain outside the response.
2. `get_study_history` returns the permitted session statistics and teach-back
   scores. This also fixes a preexisting `course`/`topic` key mismatch that discarded
   matching statistics and struggles.
3. Editing a project classification makes requests fail until the new policy is
   applied. After application, the already running MCP server withholds the
   reclassified source's dependent session and score.
4. Cross-scope updates are refused. Inserting a logical source-forgetting event
   removes the linked application rows and their ownership records.

Eight checks cover these observations. The source runner and fresh installed
wheels both passed all eight. Open each disclosure to inspect the actual returned
records, including their assessment status and source IDs.

## Run it

From the experimental checkout, choose a new output directory:

```sh
uv run python -m experiments.evidence_context.learning_ownership.runner --output /tmp/evidence-stage-26
open /tmp/evidence-stage-26/walkthrough.html
uv run pytest packages/agent-session-tools/tests/test_context_record_owners.py packages/studyloop/tests/test_context_consumer_scope.py experiments/evidence_context/tests/test_learning_ownership_lesson.py --import-mode=importlib -q
```

For a wheel-only runtime, use a fresh environment and install both local packages:

```sh
uv build --package agent-session-tools --wheel --out-dir /tmp/stage26-wheels
uv build --package studyloop --wheel --out-dir /tmp/stage26-wheels
uv venv /tmp/stage26-runtime
uv pip install --python /tmp/stage26-runtime/bin/python /tmp/stage26-wheels/*.whl
uv run python -m experiments.evidence_context.learning_ownership.runner --python /tmp/stage26-runtime/bin/python --require-installed --output /tmp/evidence-stage-26-installed
```

The child process uses isolated Python mode and checks that both production
packages resolve from `site-packages`. The lesson runner stays in the learning
repository. The independent memory package still imports no StudyLoop runtime.
Dependency installation can need network access; running the lesson is local.

## Why an ownership registry

Schema36 adds `context_record_owners`. Each row identifies one allowlisted business
table and local record ID, then exactly one owner:

| Owner | Meaning | What changes its visibility |
|---|---|---|
| Native session ID | This application record depends on a captured session | Current session classification and source forgetting |
| Configured project ID | A record made in a known project belongs to that project | Applied project classification |
| Explicit scope | The process/default explicitly selected a boundary without a matching project | Requested scope |

The mapping is immutable; the assessment or session note is ordinary mutable
application state. Ownership does not attest the content. A score remains a
reported assessment, not proof of mastery or native validation.

The central registry lets the independent memory package own the common boundary
without importing StudyLoop. It preserves existing business IDs and avoids copying
the same ownership schema into each legacy table. Source/project references have
real foreign keys. The allowlisted business-table mapping is verified in `bind`
and maintained by delete triggers; it is **not** a native foreign key to the
business row. This is a cost of the generic registry, not a free abstraction.

Direct ownership columns on each table are a reasonable alternative. They place
data and ownership together and can simplify individual queries, but duplicate
the ownership contract and migrations across tables. A generic `owner_type` and
`owner_id` pair also loses ordinary foreign keys to the different owner tables.
Three nullable, constrained typed columns would preserve those references. None
of those alternatives has been benchmarked here; we have not proved the registry
faster or universally simpler. The registry is the current implementation choice,
subject to measured workload evidence and the remaining integration audit.

Local numeric business IDs must not become global sync identities: two machines
can independently allocate score ID 1. Registry UUIDs provide identities for the
mapping, but do not themselves implement a peer protocol or conflict resolution.

## Where enforcement happens

`owned_write` takes a SQLite immediate transaction. The business insert, ownership
binding and any progress observation succeed together or roll back together.
`policy_guard` validates the applied policy and checks the file policy again before
commit. Applied DB changes serialize against the writer. This is not a promise
that an external file edit can retroactively revoke every in-flight operation;
the full release audit still needs coordinated read/write race scenarios.

Reads use the shared `visible_sql` predicate before reading bodies, aggregating or
applying a limit. The tests create 25 newer work assessments and one personal
assessment, then request personal history. The single personal result must survive.
Post-filtering a global top 20 would lose it even if it leaked no text.

A supplied native session ID is checked for current visibility and retained as the
owner. The code does not copy that session's current scope into a permanent scope
label. Reclassification therefore changes the next read. A project-owned record
likewise follows the configured project's applied classification.

Old records are not automatically personal. Ownerless rows retain the earlier
explicit unclassified inspection rule, which also refuses legacy aggregates once
the database contains session assignments. Configuration is the authority for
scope; a harness name or a model inference is not.

## What the measurements establish

The benchmark creates 50,000 synthetic project-owned study sessions, half in each
scope, and executes the production predicate ten times per query:

| Query | Median | Maximum |
|---|---:|---:|
| Count permitted records | 15.46 ms | 15.96 ms |
| Fetch latest 20 permitted records | 20.35 ms | 20.65 ms |

The database occupied 18,083,840 bytes. Timings include policy resolution and
exclude process startup. The data contains project owners only, with no concurrent
writers. This supports feasibility on this workload, not an engine or schema
ranking. Repeat it with:

```sh
uv run python -m experiments.evidence_context.learning_ownership.benchmark --output /tmp/evidence-stage-26-benchmark
```

The installed migration rehearsal opened a preserved schema35 fixture read-only,
made a consistent SQLite backup copy, then migrated the copy. All 62 rows across
49 preexisting tables retained identical fingerprints. Integrity and foreign-key
checks passed. An injected failure after schema creation also rolled back, then
retried successfully in the automated test.

To repeat against a disposable Stage25 fixture, use the Stage25 checkpoint to
generate its database first, then run from Stage26 with the installed interpreter:

```sh
/tmp/stage26-runtime/bin/python -I experiments/evidence_context/learning_ownership/upgrade_probe.py --source /tmp/evidence-stage-25/sessions.db --output /tmp/evidence-stage-26-upgrade --require-installed
```

This validates an additive upgrade. It does not validate restoring forgotten
material, merging tombstones from another machine or retaining old application
versions as safe readers.

## Evidence and what remains

The combined memory-package and learning-experiment run passed 1,564 tests with one
optional skip. The full StudyLoop run passed 3,782 tests, with four skips and 704
deselections. Later small time-window/status changes received focused regression
and installed-interface checks. Results and their timing boundaries are recorded
in [OBSERVED-RESULTS.json](OBSERVED-RESULTS.json). Council design alternatives,
incorrect findings and accepted limitations are in
[COUNCIL-DECISION.md](COUNCIL-DECISION.md).

This increment does not complete work/personal isolation for the whole product.
Parking, notes, practice, concept graphs/dependencies, plans and other learner paths
need an explicit ownership inventory and integration. Converting classified bridges
into the still-unowned concept graph is temporarily refused; dependency seeding
also stops in classified scope. Removing that limitation safely is follow-on work.

An explicitly source-linked teach-back requires nonempty captured source input.
Before capture, it raises a scope error and rolls back score, owner and progress;
it does not silently claim a successful write. Installed session startup must
coordinate capture or offer an explicit, accurately attributed recording path.

Logical tombstone deletion is demonstrated only for these mapped application rows.
Other source foreign keys require managed cleanup; raw `DELETE FROM sessions` is
not the full forgetting protocol. Scoped peer transfer, stale replay, managed
restore, all derived indexes, shared setup/doctor and installed agent startup remain
part of the active production goal. No answer-quality gain is inferred from test
counts or a correctly classified score.
