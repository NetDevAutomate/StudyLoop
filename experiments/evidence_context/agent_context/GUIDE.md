# Stage23: an agent can inspect the evidence contract

Stages17–22 established source authority, scope, immutable observations and native
capture. This stage connects those capabilities to the actual packaged CLI and
MCP server. An agent can retrieve bounded context, follow proposed relationships,
inspect exact source versions and assess an explicit execution requirement.

The complete production goal remains active. This increment does not complete
general advice arbitration, forgetting across replicas, full capture health,
shared installation or StudyLoop startup. The full contract remains in
[delivery/GOAL.md](../delivery/GOAL.md).

## Run it independently

From this worktree's root, choose a fresh output directory:

```sh
uv run python -m experiments.evidence_context.agent_context.runner --output /tmp/evidence-stage-23
open /tmp/evidence-stage-23/walkthrough.html
uv run pytest packages/agent-session-tools/tests/test_context_agent_api.py experiments/evidence_context/tests/test_agent_context_lesson.py -q
```

The lesson creates fictional receipts, a fresh database and configuration, then
launches a real MCP server over stdio in an isolated child process. It uses the
CLI console script when present, otherwise the same CLI Python module in an older
editable checkout. It does not read the owner's database, invoke models, change
hooks or start a StudyLoop learning session.

For a wheel-only check without StudyLoop installed, use separate build and runtime
directories. The runtime environment is created using only the memory wheel:

```sh
uv build --package agent-session-tools --wheel --out-dir /tmp/stage23-dist
uv venv /tmp/stage23-runtime --python 3.13
uv pip install --python /tmp/stage23-runtime/bin/python /tmp/stage23-dist/agent_session_tools-0.1.0-py3-none-any.whl
uv run python -m experiments.evidence_context.agent_context.runner --python /tmp/stage23-runtime/bin/python --require-installed --output /tmp/stage23-installed
```

`--require-installed` checks the source module is inside `site-packages`, StudyLoop
cannot be imported, and the real CLI console script exists. The probe runs with
Python's isolated import mode, so unrelated files in a working directory cannot
shadow installed dependencies. The HTML records the actual runtime and results.

The optional local probe deliberately reads recent stable StudyLoop/MailGraph
archives using Stage22's bounded selection. Its temporary database and source
copies disappear after the run. The output includes aggregates, not source bodies:

```sh
uv run python -m experiments.evidence_context.agent_context.audit_local --limit 2 --output /tmp/stage23-local-audit.json
```

The six fixed queries are SQLite, validation, session sync, scope, test and context.
This checks retrieval mechanics against actual captured data. It does not provide
human relevance judgements, semantic labels or an answer-quality comparison.

## Why an interface contract matters

A correct storage method is not enough if the agent-facing tool drops provenance,
ignores scope, truncates silently or calls a successful process a validated change.
The new `context/public.py` owns one common response contract for CLI and MCP.

Think of a network collector exposing an interface-status record. An API that
returns only “up” discards the device, interface, observation time and collection
failure state. Here the comparable fields are source/version, project, harness,
origin, invocation, revision, time and coverage. Their absence can change what
the agent is justified in concluding.

| Layer | What is established | What remains open |
|---|---|---|
| Captured source | Immutable bytes and native metadata in this local archive | Original-file authenticity and semantic truth |
| Exact citation | The quoted characters occur at those offsets in that version | Whether the quote supports the interpretation |
| Proposed relation | An agent linked two visible, supported interpretations | Whether the relation is correct or a correction is accepted |
| Recorded-check assessment | Native metadata meets specified execution requirements | Test adequacy, semantic correctness and release readiness |

The API never accepts native origin, project scope or captured revision as model
proposal fields. The producer label comes from the adapter. Both relation endpoints
and all cited source versions must be visible before their content is returned.

## Six parts of the walkthrough

1. A StudyLoop lexical match follows a proposed contrary claim into MailGraph.
   Source identity spans two configured projects, harnesses and fictional machines.
2. A recorded process matches an explicit command, project, full revision and exit
   requirement. The result says `recorded_checks_satisfied`, with software validation
   still `not_established`.
3. A contrary exit record produces `conflicting_records`. Neither newest arrival
   nor repeated votes supplies a truth rule.
4. Changing the requested revision makes those records inapplicable. Historical
   evidence can remain accurate while no longer answering today's validation question.
5. A smaller source/output allowance reports omitted coverage. An empty returned
   conflict list cannot prove no conflict exists.
6. Reclassifying MailGraph while MCP remains connected revokes its source and the
   dependent relationship on the next request.

The synthetic statements use illustrative interpretations, not adjudicated database
advice. The relationship is expressly proposed. It demonstrates retrieval of a
disagreement, not a conclusion that one database is better.

## Why use one SQLite transaction per request?

The request pins a database snapshot, checks the active classification digest and
filters scope before returning any body. A long-running MCP server reloads the
config for its next request. A proposal that overlaps a config change is rolled
back before commit. An explicit project argument can only narrow the allowed set.

This is local owner-controlled separation, not protection from someone who can
edit the database or process environment. Reclassification takes effect for new
requests; it cannot erase a response already delivered to an agent.

An `unclassified` request may inspect truly unassigned sessions. It may not use
that fallback to reopen a project removed from current configuration. That
distinction required an explicit `include_unassigned` access field and a regression
test; “unknown project” and “owner-approved unclassified source” are different states.

## Why byte budgets and actual match positions?

An evidence count alone does not bound a response: metadata and quotes vary in
length, and Unicode characters have different UTF-8 sizes. The byte limit covers
the complete compact JSON, including explanations and relationship support. MCP
transport wrapping is outside that limit. Extra source, assertion and edge caps
bound work; a full native body above one million characters is withheld by this
reader. These are practical bounds, not a comprehensive worst-case memory proof.

FTS tokenization can match `cafe` to `café`. A second Python regex searching for
`cafe` would miss the actual match and could return an unrelated opening excerpt.
The implementation uses SQLite's own highlight position, then computes exact
Unicode code-point offsets into the verified original body. A regression case puts
the accented match far beyond the initial excerpt.

Known future native timestamps are excluded by `as_of`. Interpretations and
relations also must have existed by that cutoff; otherwise a later interpretation
could contaminate an earlier historical view. Unknown native times stay unknown.
This is not a full reconstruction of replica knowledge at a past instant, and
health statistics describe the current visible database.

## Measured results

The installed wheel completed all eight CLI/stdio checks with no StudyLoop runtime
installed. The new public-interface suite has 27 passing cases. The complete
session-tools suite passed **1,264 tests**. The combined experiment and focused
StudyLoop compatibility run passed 300 cases with one optional dependency skip;
after fixing the lesson's stale editable-script assumption, its additional test
passed. No source implementation changed after the full package run.

The local audit read eight archives (two per major harness), captured 1,898 native
records and verified all stored body hashes. The source files stayed unchanged.
The six actual CLI searches returned 60 source appearances, all distinct, and all
60 citation/version/offset checks passed:

| Query | Sources | JSON bytes | CLI wall time | Harnesses in this result |
|---|---:|---:|---:|---|
| SQLite | 12 | 30,828 | 0.077s | Codex, Grok |
| validation | 12 | 27,324 | 0.078s | Claude Code, Codex, Kiro |
| session sync | 7 | 31,710 | 0.095s | Codex |
| scope | 11 | 30,103 | 0.094s | Codex, Claude Code |
| test | 8 | 30,480 | 0.096s | All four |
| context | 10 | 31,758 | 0.099s | Codex |

Times include Python startup on this machine and are not a scaling benchmark.
All responses stayed below 32KiB. Every query reported a source, byte or candidate
bound. None of the 60 records supplied a native revision. These are useful
constraints on a product design: bounded context can omit evidence, and capture
can preserve source identity without supplying revision applicability.

No human relevance review was available. This result does not mean 60 useful
answers, full cross-harness recall, or a measured quality increase. Explicit
relationships were exercised in the fixture, not automatically invented for the
real transcripts. No real transcript was sent in this stage's council briefs.

Browser inspection found six sections, working expansion, fitting viewport and no
console errors. The owner database, scope configuration and hooks were unchanged.

## What this says about storage and next work

SQLite supplied source joins, lexical lookup, scoped relationship expansion and
atomic writes without a second storage engine. This stage does not compare engines
or establish that a graph database would perform worse. The current limiting
factors are coverage selection, trustworthy applicability metadata and interpretation.

Lexical results can consume the source allowance before a contrary relation's
source fits. This is reported, and an execution decision cannot claim complete
sufficiency when evidence was omitted. A measured reserve for contrary evidence
is a concrete next retrieval experiment, with relevance and budget trade-offs to
test. It does not replace the remaining production requirements for complete
learner ownership, scoped sync/forget/restore, shared installation and actual
StudyLoop startup.

See [the interface reference](../../../docs/context-memory.md) for callable fields
and [the council decision](COUNCIL-DECISION.md) for accepted and rejected review claims.
