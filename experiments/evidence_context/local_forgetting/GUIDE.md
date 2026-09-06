# Stage33: forgetting is a lifecycle operation

This independently runnable stage adds permanent local forgetting and a distinct
reversible storage eviction operation to the standalone memory package. It uses real
Codex parsing, the actual `session-context` CLI, SQLite triggers, foreign keys, FTS
indexes and installed-wheel execution against fictional archives.

The full production objective remains [GOAL.md](../delivery/GOAL.md). This checkpoint
does **not** complete peer synchronization, full-store forgetting, managed backup
restore or all StudyLoop consumers. Every CLI result preserves those limits explicitly.

## Why this follows source grounding

A cited answer depends on more than a sentence in `messages`. The same source may
support a native evidence row, an assertion, a review, a corrected annotation and a
learner record. Source grounding gives us explicit links. Forgetting tests whether
the application actually obeys those links throughout the source's lifetime.

Consider a route withdrawal: removing a route from one display is insufficient if a
cached routing announcement immediately reinstates it. Memory has the same practical
problem. A source can return from a native archive, a peer, an index or a backup.
This stage proves selected **local** paths and records which others still need work.

## Follow the five-view demo

1. Import two fictional native Codex archives: one explicitly personal, one work.
   The importer retains exact native sources and message-to-source rendering bindings.
   A parser-observed message and an annotation about that message keep different authority.
2. Preview the personal session's deletion. The command returns affected row counts,
   no conversation body, and `applied: false`. An unavailable or excluded session is
   refused before its contents or counts are disclosed.
3. Apply forgetting. A single transaction removes the source and known dependent
   bodies and preserves content-free retirement identities. A separate maintenance
   phase reconstructs indexes and compacts the canonical database and WAL.
4. Import the unchanged native archives again. The actual Codex exporter counts the
   personal session as forgotten and does not recreate it. The work source remains.
5. On a separate disposable copy, use reversible eviction. Bodies leave this local
   copy without permanent controls. Native recapture is therefore possible. This is a
   storage primitive, not a demonstration of peer withdrawal or permission to regrant.

The installed probe checks 16 outcomes. It verifies the memory module came from the
wheel's `site-packages` and that StudyLoop is absent from that child runtime. It also
hashes the external fixture archives before and after: this command does not edit them.

## Two meanings of delete

| Operation | Intended meaning | Retained state | Replay behavior |
|---|---|---|---|
| Permanent forget | Stop retaining this source and its dependent material | Monotonic session/artifact retirement identities | Native source import remains blocked |
| Storage eviction | Remove this local copy while retaining a verified archive | No new permanent retirement | Recapture can be allowed by a later, separate policy |
| Peer withdrawal, still to implement | A previously authorized recipient loses access | Delivery/grant history and revocation state | Denied until a fresh valid grant |

Schema41 stores the internal mode in a singleton row. The writer changes it only
inside its SQLite transaction and restores ordinary mode before commit. Retirement
triggers consult that mode; dependency purges still run during eviction. A second
connection sees the committed ordinary mode and cannot write through the first
connection's lock. A test exercises both observations.

This internal helper is not an authorization interface. Trusted administrative code
must own the transaction. A caller with arbitrary SQL/schema-edit permission is outside
the local application's enforcement boundary.

We rejected a reversible flag inside the existing permanent tombstone table: importers
already interpret any entry in that table as a permanent forget. Reusing it would change
the meaning of old data and risk blocking legitimate cache restoration.

## Why SQL cascades alone were insufficient

Some older learner records use `ON DELETE SET NULL`. That protects referential integrity,
but it can detach a note from the very source needed to find it for deletion. The purge
therefore selects dependent learner IDs **before** deleting any parent, holds that set
in temporary tables and deletes the selected rows within the same transaction.

This distinction matters: a clean foreign-key check means every remaining reference is
valid. It does not prove that no source-derived text remains. Tests create an older note
without a modern owner wrapper and confirm that source forgetting still removes it.
Unbound legacy global aggregates have no reliable source lineage; this stage does not
claim to infer or erase every semantic derivative hidden in that older state.

Permanent artifact IDs are retained for native evidence, assertions, relations,
observations and stable learner owners. Reinserting a retired identity fails. Existing
correction links can remain as content-free history without retaining the old report.
These identifiers can still be sensitive metadata; they are not anonymous, and must
not be broadcast to arbitrary peers when the transport is implemented.

## Logical removal and physical cleanup

Deleting rows is not the same acceptance condition as removing their bytes from the
canonical files. The CLI separates the committed purge from the cleanup result.
`context_erasure_pending` retains unfinished work. A pinned reader, maintenance error,
concurrent update or process death must not become a false success.

There are two different FTS designs in this database:

- `messages_fts` stores its own content. Asking that index to rebuild itself would
  preserve its orphaned content. Cleanup deletes its rows and repopulates it from live
  canonical messages.
- `context_evidence_fts` uses the evidence table as its external content source, so its
  rebuild command reads the current canonical evidence.

The tests insert an old orphan FTS row with an unrelated session ID. A session-ID delete
cannot find it; reconstruction from live messages removes it. Cleanup also removes
orphan embedding rows, checkpoints/truncates WAL, vacuums, and reports only
`coverage: canonical_database_and_wal_only` when its guarded completion succeeds.

This does not erase native archives, a separate full database, unmanaged backups,
filesystem snapshots, peer files or arbitrary external caches. Managed restore needs
to reapply the current retirement ledger before exposing an older backup. That complete
workflow remains open; local retirement replay is a necessary primitive, not proof of it.

## The race the review helped expose

The first implementation reconciled deletion controls, committed, rebuilt indexes and
then read a revision number. A new control arriving between those phases could be
included in that later number even though its source had never been purged.

The directed test inserts a retirement from a second connection immediately after the
cleanup transaction commits. Replaying the pre-review `compact` function in a separate
process makes the test fail: it returns `complete: true` while the newly retired source
still exists. No checked-in source was reverted for this comparison.

The repaired implementation groups retirement reconciliation, index reconstruction,
pending-work registration and revision capture into one write transaction. Before
clearing the pending flag, a later `BEGIN IMMEDIATE` checks that exact revision. If a
control arrived meanwhile, cleanup returns `state_changed_during_cleanup`; a retry
reconciles it. The same test then passes and the fixture marker disappears.

That is a concrete reason to change the transaction boundary. It does not follow from
three reviewers voting to reject the code. Their claims were treated as hypotheses;
several other claims were contradicted by existing code and tests. See
[COUNCIL-DECISION.md](COUNCIL-DECISION.md).

## Archiving is not forgetting

The older pruning implementation verified a session hash and message count before
removing its hot copy. That is insufficient when a new report, legacy note, metadata
edit or source binding has not yet reached the full database.

For schema41, pruning checks exact session/message retention and compares context,
learner and older dependent tables against the archive inside an attached write
transaction. Missing data retains the hot candidates. This conservative whole-context
comparison can retain more data than necessary and is not a measured scale optimization.
The actual purge runs in eviction mode so it cannot mint permanent forget controls.

Tests cover an exact archive, a later observation, a legacy note and changed session
metadata. The latter three prevent pruning. An older timezone test had changed dates
after archiving; it now archives those actual fixture dates before testing the UTC
cutoff, preserving both requirements.

Owned learner rows can consequently reside only in the full database after eviction.
Many current rich consumers read only the hot database. Full consumer coverage and
restoration are still required before enabling a complete production lifecycle.
The existing full-copy/refocus helpers are not certified by these pruning tests.

## Run this stage independently

Choose the Stage33 commit in [STAGES.md](../STAGES.md) and a new output directory:

```sh
uv run python -m experiments.evidence_context.local_forgetting.runner --output /tmp/stage33-demo
open /tmp/stage33-demo/walkthrough.html
uv run pytest packages/agent-session-tools/tests/test_local_lifecycle.py packages/agent-session-tools/tests/test_tiering.py experiments/evidence_context/tests/test_local_forgetting_lesson.py -q
```

For a fresh standalone wheel runtime:

```sh
uv build --package agent-session-tools --wheel --out-dir /tmp/stage33-wheels
uv venv /tmp/stage33-runtime --python 3.13
uv pip install --python /tmp/stage33-runtime/bin/python /tmp/stage33-wheels/agent_session_tools-0.1.0-py3-none-any.whl
uv run python -m experiments.evidence_context.local_forgetting.runner --python /tmp/stage33-runtime/bin/python --require-installed --output /tmp/stage33-installed
```

No provider call is needed to run the lesson. Previous stages and the saved Stage8/DSPy
exercises remain unchanged. See [OBSERVED-RESULTS.json](OBSERVED-RESULTS.json) for exact
validation scope. The next implementation work is durable peer lifecycle routing,
the actual configured transport and complete managed storage integration.
