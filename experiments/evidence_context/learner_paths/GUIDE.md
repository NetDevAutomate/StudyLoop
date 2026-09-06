# Stage27: protect the derived records too

This stage extends the production implementation to parked questions, study notes,
board names and practice attempts. It preserves a separate runnable lesson and a
Git checkpoint in [STAGES.md](../STAGES.md). The complete delivery contract remains
[GOAL.md](../delivery/GOAL.md); this increment does not complete that contract.

## Why this follows the earlier experiments

An agent can respect a conversation's scope yet leak its contents through a note
copied from that conversation. The same applies to derived confidence, counters and
board names. Rich context needs both provenance and continued permission to use
all of its dependencies. Protecting only the original transcript is insufficient.

In networking terms, a flow record and a packet capture can both reveal a restricted
connection. Filtering the packet payload does not make its copied metadata public.
Here we filter before reading bodies, applying a limit or counting occurrences.

## The five views

The runner creates fictional personal/work sessions in a disposable database. It
calls the actual StudyLoop application HTTP routes using ASGI transport and starts
the actual MCP server over stdio. It also runs one controlled local Python command
through practice verification. There are no model calls or changes to owner data.

1. **Permitted notes and board.** Personal and work owners park the same question.
   Personal requests see one personal card with frequency two, not the work card
   with frequency four. Work column names remain excluded. A limit of one returns
   a permitted note; excluded notes cannot occupy the slot.
2. **An attributable practice report.** The result records its application attempt
   and a progress observation. The observation exposes its record dependency.
   The confidence is an application report, not proof of learning mastery.
3. **The agent's interface.** MCP `get_study_history` returns permitted practice
   attempts with `authority: application_report` and
   `validation_of_learning: not_established`.
4. **Reclassify the source.** Moving the source project to work removes its notes
   and cards from personal responses without guessing a new owner.
5. **Delete and inspect runtime.** A logical source tombstone purges linked notes
   and cards. Deleting the practice attempt retires its progress observation.
   The final view reports the checks and actual Python/module paths used.

All ten checks passed in both the source test and a fresh wheel installation with
the documented web extra. The browser showed all five views, working disclosures,
no horizontal overflow at the inspected viewport and no console errors. The HTTP
probe deliberately omits the web application's lifespan startup. This is route
and MCP integration evidence, not full installed startup or visual product UAT.

## Run it independently

From the worktree root, use a fresh output directory each time:

```sh
uv run python -m experiments.evidence_context.learner_paths.runner --output /tmp/stage27-demo
open /tmp/stage27-demo/walkthrough.html
uv run pytest packages/agent-session-tools/tests/test_context_learner_schema.py packages/studyloop/tests/test_context_consumer_scope.py experiments/evidence_context/tests/test_learner_paths_lesson.py --import-mode=importlib -q
```

For a wheel-only runtime, explicitly install the optional web dependencies:

```sh
uv build --package agent-session-tools --wheel --out-dir /tmp/stage27-wheels
uv build --package studyloop --wheel --out-dir /tmp/stage27-wheels
uv venv /tmp/stage27-runtime --python 3.13
uv pip install --python /tmp/stage27-runtime/bin/python /tmp/stage27-wheels/agent_session_tools-0.1.0-py3-none-any.whl '/tmp/stage27-wheels/studyloop-0.2.1-py3-none-any.whl[web]'
uv run python -m experiments.evidence_context.learner_paths.runner --python /tmp/stage27-runtime/bin/python --require-installed --output /tmp/stage27-installed
```

The first minimal two-wheel run lacked FastAPI. Installing StudyLoop's existing
`web` extra fixed the runtime; source tests had hidden that optional-dependency
requirement. It is recorded here so a learner can reproduce the complete setup.

To rehearse upgrading a Stage26 demo database, preserve that original and use:

```sh
/tmp/stage27-runtime/bin/python -I experiments/evidence_context/learner_paths/upgrade_probe.py --source /path/to/stage26-demo/sessions.db --output /tmp/stage27-upgrade --require-installed
```

The source must be schema36. It is opened read-only and copied with SQLite's backup
API. The probe compares every old column value after migration; it accounts for
new columns and the explicit relocation of old board names. This is an upgrade
rehearsal, not deletion-aware managed restore. Follow STAGES.md to create a detached
worktree at this stage's checkpoint when later migrations have changed the code.

## Why these ownership rules

| Choice | Consequence | Decision |
|---|---|---|
| Merge identical questions globally | Combines work/personal bodies and frequencies | Reject |
| Merge by active scope only | Different native/study parents lose separate provenance | Reject for stored identity |
| Merge by exact owner and study parent | Repeated occurrences retain one card; differing dependencies stay separate | Implement; aggregate permitted frequencies at read time |
| Infer ownership from harness name | Kiro/Codex/Claude can span work and personal activity | Reject; use configured source/project or explicit scope |
| Invent a native session row when missing | An application placeholder appears to be captured history | Reject |
| Create an owned application study-session placeholder | Supports notes before native capture without claiming a native event | Allow, inside the same transaction |

Exactly one primary owner is attached to each application row: native session,
configured project or explicit scope. A note/card may additionally depend on one
study session. If the caller supplies a native session and a study parent, both
must be permitted. Without an explicit native session, the child's primary owner
is inherited from its study parent. Without either parent, configured project or
explicit request scope supplies the owner. A known opposite-scope working directory
is refused for practice; its actual working directory owns the resulting report.

The database keeps mutable application bodies separate from immutable ownership
and dependencies. This permits editing a note without rewriting its origin.
A relationship here is an ordinary typed relational table with foreign keys and
indexes. SQLite can represent and traverse it; the presence of a relationship
does not itself justify a graph database.

## What schema37 changes and what it costs

Schema37 extends the Stage26 ownership registry's table allowlist, adds typed
study-parent and record-to-observation dependency tables, brings the preexisting
notes schema under canonical migrations, and scopes board names. Old board names
move to **unclassified**, preserving their text. Legacy records are not silently
assigned to personal/work. They remain subject to the earlier explicit legacy
inspection rule; an operator classification workflow is still required.

The registry rebuild preserves its UUIDs and original rows. One transaction covers
all pending migration changes. A second connection tested during the rebuild saw
the old committed schema and trigger, and its attempted write was locked. An
injected failure restored schema36; retry succeeded. The installed copy preserved
80 rows across 52 old tables with clean foreign-key and integrity checks. The copy
had no old board table; a separate historical fixture tests that relocation.

Costs are extra ownership lookups, dependency joins and trigger-maintained deletion
paths. Board reads currently pass through initialization that can briefly acquire
a write lock to seed defaults. We have not measured Stage27's mixed-dependency
load or compared this representation with typed owner columns. Stage26's simpler
project-only benchmark must not be reused as a performance claim for this stage.

A failed canonical migration now remains an error. The old parking fallback could
swallow migration failure and construct a partial schema. Several old tests did
exactly that: they created a few tables and labelled them as the latest version.
Those fixtures were replaced with real historical/fresh migrated databases. This
does not claim arbitrary corrupted databases are repaired; doctor diagnostics and
an explicit supported repair path remain part of the production work.

## What the labels establish

`kind=assessment`, `confidence=confident` and a successful practice check are reports
from a known application path. The command path records its actual exit status,
but the existing heuristic does not independently prove that the intended learning
outcome was demonstrated. Checklist success still uses nonempty notes and artifact
existence. Artifact checks currently happen before command execution. Improving
those semantics requires its own tests and rationale; changing storage cannot make
those labels stronger evidence.

Deleting an attempt removes its linked progress body and retires the observation.
That prevents the derived report from outliving this dependency through the tested
local path. Full forgotten-source cleanup, replica ordering, stale archive reimport,
managed restore, vector indexes and copied planning files remain separate required
work. Likewise, separate DB connections within one combined response still need a
consistent policy boundary under concurrent changes.

## Evidence and next decision

The combined memory/experiment suite passed **1,566** tests with one optional skip.
The selected StudyLoop suite passed **3,788**, with four skips and 704 deselected.
Thirty final focused checks additionally covered the new policy-change and
second-connection migration tests. Workspace type checks passed. Exact observations
and limits are in [OBSERVED-RESULTS.json](OBSERVED-RESULTS.json).

Both council rounds returned three provider buckets. The decision uses code and
these tests, not their votes; see [COUNCIL-DECISION.md](COUNCIL-DECISION.md).
Next, complete the remaining learner-state inventory (concepts, dependencies, plans
and state files), address response-wide policy consistency, and exercise actual
scoped sync/forget/restore. Shared install/doctor and installed agent startup remain
required. The evidence still supports improving information and lifecycle contracts
within SQLite before introducing another storage engine.
