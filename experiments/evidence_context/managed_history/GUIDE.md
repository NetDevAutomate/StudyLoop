# Stage40: current intent must govern older copies

A source can disappear from the active database while an older archive still contains
it. The first test in this stage demonstrated that ordinary search could return a
forgotten conversation from that archive. This checkpoint fixes that path and adds
retryable permanent cleanup across the configured canonical and full databases.

The [production goal](../delivery/GOAL.md) remains active. Modern full-history copying,
fresh archive regrant coverage, managed restore, complete consumer integration and
shared installation still need work. Preventing unsafe old operations is an interim
protection; it does not complete their replacements.

## Follow the five runnable views

1. **Preserve useful history.** Actual native export and verified hot pruning leave a
   permitted source in the full archive. Search retrieves it while excluding work data.
2. **Record current intent.** Preview an archive-only session using scoped metadata,
   then forget it. Canonical retirement commits before archive cleanup is acknowledged.
3. **Recover from an offline archive.** Forget another session while its full store is
   unavailable. The command reports pending cleanup. Bringing the old archive back does
   not make the source visible; retry completes its managed cleanup.
4. **Try native replay.** The fictional original files still exist. Exporting them
   again cannot recreate the permanently retired sessions or dependent report.
5. **Inspect the runtime.** The installed run uses the standalone wheel, real console
   commands and site-packages, with StudyLoop absent. Results expose their limits.

Every source, database, configuration and failure injection is disposable. The owner's
archives, databases, hooks, SSH peers and installed configuration are unchanged.

## Two stores answer two different questions

The canonical database holds current policy and lifecycle intent. A full archive holds
older bodies that may no longer be present in the hot working set. Its age does not
make those bodies false, but its old permission state cannot authorize a current read.

A network analogy is a disconnected cache behind an access controller: finding bytes
in the cache is not the same as receiving permission to return them. Both the cache's
classification and the current controller's rules must allow the operation.

| Design option | What it simplifies | What remains difficult |
|---|---|---|
| Treat full as another independent replica | Reuses a peer-shaped vocabulary | Requires a real identity, permission/receipt history and exact fresh-copy coverage; a copied file does not automatically have those facts |
| Read historical full data under canonical authority | Preserves current archive/pruning behavior and allows incremental repair | Every participating read and lifecycle path must use current authority; copying and restore need managed protocols |
| Consolidate into one canonical history store | Removes the hot/full authority split | Needs a reversible migration, bounded query performance evidence and preservation of existing archive-only history |
| Keep the old copy/refocus implementation | Avoids immediate user-visible change | Copies only part of modern data and can lose provenance/lifecycle relationships; not acceptable for protected memory |

The chosen checkpoint is canonical authority over the existing archive, with permanent
cleanup and strict boundaries. Consolidation remains a real candidate for the next
step. These tests do not measure whether consolidation or another engine gives better
answers. The [council record](COUNCIL-DECISION.md) distinguishes its disagreement from
the coordinator's decisions.

## Why commit intent before archive cleanup?

Suppose the archive contains a source already forgotten in canonical storage. The
operation locks canonical first, then full, unions permanent control identities, and
reapplies deletion in both transactions. Deleting a source can discover additional
assertion, report or learner identities; another bounded round includes those controls.
Both sides must reach the same logical retirement set before phase commits begin.

Canonical intent commits first. If the process then stops before the archive commit,
that archive may still contain old bytes, but ordinary search consults canonical
retirement and refuses to return them. Retry reuses the durable intent. If neither
commit happened, both transactions roll back. Actual child-process exits exercise
these phases; exceptions alone would not prove process-death behavior.

This is not an atomic transaction across two files. SQLite documents that attached
transactions do not have a cross-database atomicity guarantee in WAL mode, although
individual database commits are atomic. See [ATTACH transaction semantics](https://www.sqlite.org/lang_attach.html).
The implementation explicitly reports logical intent separately from physical cleanup.
It does not use a claim of cross-file atomicity to explain recovery.

After both logical commits, each managed database is compacted and its indexes rebuilt
from current rows. A pinned reader or newly pending control prevents a completed
cleanup acknowledgement. File identities and configuration are checked again, and
control identity sets must still match the converged set. These are optimistic checks
at defined boundaries, not locks on future external configuration edits or file moves.

The current budgets are one million control rows, 32 MiB of encoded control tuples and
16 closure rounds. Overflow refuses rather than silently truncating the control set.
Control tuples are held in memory. The limits do not promise acceptable latency or
constant memory for every allowed input.

## Forgetting needs a precise unit

This stage initially added an incorrect blanket purge of all observations with a
retired subject hash. The wider regression suite caught it: one correction's deletion
caused the peer to retire an earlier version that the sender still offered. A proposed
follow-up hiding every version failed an unchanged historical-inspection test.

The error was semantic. `context_observation_retired_subjects` prevents fallback to
unversioned legacy reports; it does not grant permission to erase every historical
version about that subject. The blanket purge was removed. The final code preserves
the existing distinction:

- Retire one report: remove its exact ID from both stores. Another version may remain
  inspectable. Explicit supersession prevents an old predecessor becoming current advice.
- Forget a source session: remove that session and every dependent version, including
  versions present only in full history. Preserve permanent suppression for native replay.

A parameterized test proves both outcomes. The earlier test was not rewritten to
accept the new behavior. This is why a green new test is insufficient: an experiment
can faithfully test the wrong interpretation of an existing contract.

## Filtering before bodies, checking before output

Full search applies its stored classification plus canonical tombstones, permanent
session retirement and withdrawal controls. If canonical still contains the session,
the existing search merge excludes its archive duplicate. Removing the archive from
configuration takes effect on the next operation; a stale configuration cache no
longer retains it. A direct full-database override through public CLI/native/MCP
connection entry points is refused because it would bypass canonical authority.

Full is attached read-only. On this SQLite build, URI processing must be enabled on
the connection for an attached `mode=ro` URI to work. The public connection factories
therefore use an escaped absolute file URI. A literal path containing URI-like text
still names a literal file; its characters cannot turn the database into an in-memory
connection. Attachment failure is explicit rather than an empty-history success.

Search constructs output locally, validates the configured paths/policy and every
participating database's access generation, then prints it. Injected canonical
retirement, archive retirement and configuration changes during rendering all release
no body. Old in-memory formatting fixtures were moved to temporary on-disk databases
so they exercise the actual committed-state boundary; the guard was not weakened.

Any canonical denial history, including a released denial after regrant, hides an old
archive-only copy. Fresh canonical receipt coverage does not prove that old archived
bytes were covered. This is conservative and incomplete: restoring useful archive
access requires a new managed copy/regrant path, which remains next-step work.

## Why the old backup and copy paths change

A plain copy of the main SQLite file can omit committed WAL content. StudyLoop backup
now uses SQLite's online backup API for real SQLite files and retains ordinary copying
for configuration and non-SQLite assets. A test keeps a WAL writer open and checks
that the backup contains the committed row. The API's snapshot behavior is described
in the [SQLite backup documentation](https://www.sqlite.org/backup.html).

The existing modern-data full copy/refocus path is refused because it transfers only
legacy tables, omitting evidence and control relationships. The old StudyLoop whole-file
restore is also refused when either current or backup memory has protected metadata.
It cannot overwrite current retirement with an older file. The restore test asserts
that neither current configuration nor tombstone changes and no safety backup is made.

These guards protect a transition. Managed restore must still merge current intent,
validate ownership and dependencies, preserve current peer/instance history, rebuild
managed indexes and offer a reviewable recovery plan. Arbitrary manual filesystem
replacement and independent external backups are not controlled by this API.

## Measured cost

The diagnostic runs one fresh child per size, using fictional legacy sessions/messages
in both stores, all permanently retired. Timing includes reconciliation and both
compactions. Peak process RSS includes fixture construction. The final installed run
is recorded in [OBSERVED-RESULTS.json](OBSERVED-RESULTS.json).

| Sessions per store | Cleanup time | Peak process RSS | Result |
|---|---|---|---|
| 100 | 0.572 s | 53.4 MiB | Both stores and FTS empty |
| 1,000 | 5.653 s | 52.1 MiB | Both stores and FTS empty |
| 5,000 | 35.389 s | 61.9 MiB | Both stores and FTS empty |

These are single samples, not confidence intervals. They exclude native evidence
fanout, network transfer and concurrent load. The useful signal is that cleanup grows
materially with history size: the next design must consider incremental work or
consolidation. This does not measure answer quality or establish an engine ranking.

## Run this stage independently

Use its immutable checkpoint in [STAGES.md](../STAGES.md), then run from that checkout.
Choose a new output directory each time; the fixtures are preserved for inspection.

```sh
uv run python -m experiments.evidence_context.managed_history.runner --output /tmp/stage40-demo
open /tmp/stage40-demo/walkthrough.html
uv run python -m experiments.evidence_context.managed_history.benchmark --output /tmp/stage40-measurements
uv run pytest packages/agent-session-tools/tests/test_managed_history.py packages/agent-session-tools/tests/test_context_observations.py packages/agent-session-tools/tests/test_replica_ledger.py -q
```

For actual installed acceptance, build and install only the standalone wheel in a new
Python3.13 environment, then select that interpreter:

```sh
uv build --package agent-session-tools --wheel --out-dir /tmp/stage40-wheels
uv venv --python 3.13 /tmp/stage40-runtime
uv pip install --python /tmp/stage40-runtime/bin/python /tmp/stage40-wheels/agent_session_tools-0.1.0-py3-none-any.whl
uv run python -m experiments.evidence_context.managed_history.runner --python /tmp/stage40-runtime/bin/python --require-installed --output /tmp/stage40-installed
```

The source runner can fall back to a module when a development console script is
absent. `--require-installed` never does: it verifies real installed entrypoints and
that StudyLoop is absent. The saved Stage8 and DSPy learning exercises are unchanged.
