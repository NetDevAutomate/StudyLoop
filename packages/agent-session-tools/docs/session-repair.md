# Inspect and repair conversation imports

These instructions describe the reliability candidate, awaiting release
acceptance. It retains schema 30 and is not a downgrade path for the separate
context-memory research database. See the
[conversation memory guide](../../../docs/session-memory.md) for the product boundary.

Use `session-repair` after upgrading the exporter to recover native conversation
history on the machine where it was recorded. The command defaults to inspection.
It does not call models, change hooks, export Obsidian notes, or modify native
harness files.

```sh
session-repair --db ~/.config/studyloop/sessions.db
session-repair --db ~/.config/studyloop/sessions.db --source codex --source kiro
```

If the executable is not installed, the equivalent development command is:

```sh
uv run --package agent-session-tools python -m agent_session_tools.repair --db ~/.config/studyloop/sessions.db
```

The JSON report lists `migrations_needed` and counts missing/changed sessions and messages, retained messages
whose native records were not found, explicitly removed stale messages, exporter errors, and identity conflicts.
`staged_roles` shows user/assistant counts by source in the entire repaired snapshot. It includes previously imported history and does not prove current native-source availability. Missing source
installations are reported as unavailable; they do not cause old imported history
to be deleted. Exporter errors or identity collisions block application.

Inspect the report, then explicitly apply:

```sh
session-repair --db ~/.config/studyloop/sessions.db --apply
```

Each apply creates a private, SQLite-consistent `.repair-<timestamp>.bak` beside
the database, including committed WAL contents. The merge runs in a transaction,
preserves foreign-key references and history unavailable on this machine, and verifies that the
staged rows match afterward. SQLite quick-check and foreign-key checks run before
commit. Pending schema migrations run inside the same write transaction as the
conversation merge, even when there are no conversation differences. The result
lists `migrations_applied`. Any failure rolls back both schema and data changes. Keep the backup until validation is
complete. Repair requires an existing database/schema; use normal installation
and export first on a new machine.

Re-run inspection afterward. With unchanged native transcripts, missing/changed
counts should be zero. Continued conversations can legitimately produce new rows.
The comparison validates the *current parser's output*, not independent source
completeness; use parser fixtures and direct source checks as well.

## Multiple machines

Run inspection and repair locally on each machine, including a work machine. Each
machine can recover only native history available to its exporters. To save a
consistent repaired snapshot without changing the local target:

```sh
session-repair --stage-output /private/path/repaired-snapshot.db
```

The snapshot filename must not already exist. Transfer the private snapshot using
your established machine-to-machine transfer method, then inspect and merge:

```sh
session-repair --from-db /private/path/repaired-snapshot.db
session-repair --from-db /private/path/repaired-snapshot.db --apply
```

Database merge is additive: it includes all conversation sources (even unknown
ones), preserves existing target session metadata and local annotations, and
preserves differing nonempty content under a deterministic revision ID rather
than overwriting either version. Identical session/role/content keeps target
metadata and timestamps; empty source events cannot replace nonempty target
messages. Reports count preserved metadata, preserved nonempty messages, and new
message revisions. A repeated merge adds no further revisions. Message IDs owned
by a different session and session IDs owned by different sources still block
application for manual reconciliation. Source-only empty/whitespace events are
skipped and counted so a merge cannot resurrect cleaned parser artifacts;
existing target records and their evidence references remain untouched. It copies
new sessions/messages and their metadata, not source-only learning records or
annotation tables. It does not implement ongoing synchronisation or connect to
another machine. Do not overwrite one database with another.

## Active or changed histories

Prefer a quiet period for backfill. A writer changing the target during backup
causes a safe abort. Staging starts from a consistent target backup, allowing exporters to reuse IDs
and respect evidence references. Native files are read during staging; messages written later
are recovered on the next run. Native exporters may explicitly reconcile stale rows in the staging copy; only
those staged deletions are applied, after checking for protected references.
Any concurrent target conversation changes since the initial snapshot block
application. Database-to-database merges never delete target-only messages.
Parser changes must retain stable IDs where possible.

The tool currently stages and compares all selected history, so allow disk space
for a temporary database and a full backup, and memory for the compared rows.
It cannot recover deleted source transcripts or certify cloud-only desktop chats
that no exporter can discover locally.

Kiro imports record native extracted-message positions alongside evidence IDs.
Position plus role/content matching keeps repeated identical messages stable
when older retained history contains the same wording. Upgrading the parser
performs one metadata normalization; subsequent unchanged imports are stable.
