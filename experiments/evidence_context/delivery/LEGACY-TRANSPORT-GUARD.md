# Refuse unsafe legacy transfer during structured integration

This is an implementation checkpoint toward Stage33, not a completed new sync path.
Stage32's runnable content lesson remains pinned at `b05e6b4c`.

## Behavior

`session-sync push`, `pull` and `sync` now refuse legacy SQL when local explicit scope
configuration, peer policy, applied classification, modern context or retirement state
is present. The refusal occurs before remote resolution. The installed command prints
a concise explanation and exits unsuccessfully; it cannot call the unfinished
structured content phase and report complete sync.

Direct legacy dump, import and seed helpers also check protection. Remote DB checks
return only table names and an existence bit, before body selection or an 'up to date'
decision. Source-dump and destination-import SQL transactions repeat existence checks
before selecting or writing bodies, catching a DB classification added after preflight.

Whole-file seeding is refused for a modern schema even when its current context rows
are empty. A DB file includes free pages and indexes, so current-row absence cannot
authorize copying the whole artifact.

Old unclassified fixtures without populated modern context can still exercise the
legacy helpers. This preserves regression coverage; it does **not** certify old SQL
as a scoped protocol. The structured coordinator remains required for the product.
Fresh remote configuration, authenticated capability negotiation and complete lifecycle
reconciliation cannot be inferred from this interim refusal mechanism.

## What the tests establish

The 15 new cases cover real Typer command dispatch, direct helper bypasses, empty-schema
whole-file refusal, four explicit policy forms, tombstones without bodies, and an
import that becomes protected between preflight and the SQLite subprocess. The latter
rolls back the attempted import and its archive-table creation.

A source-dump test builds the real remote SQL command sequence, adds classification,
then executes the sequence with `sqlite3 -bail`. It fails before returning any source
body. Its transcript marker is absent from stdout and stderr. This exercises the
actual SQLite boundary locally; it is not an SSH integration test.

SQLite FTS shadow tables contain bookkeeping rows even for an empty index. Those
internal rows are excluded from the existence test; their canonical source and public
FTS rows remain covered. Whole-file transfer stays refused regardless.

Run the contract checks independently from the repository root:

```sh
uv run pytest packages/agent-session-tools/tests/test_legacy_replication_guard.py packages/agent-session-tools/tests/test_sync.py -q
```

Observed: 35 focused tests pass; the complete memory package has 1,425 passing tests
after the guards. Ruff/Pyright and the installed-entrypoint check are recorded at the
checkpoint. The later exception subtype changes only clean CLI error rendering.

## Required continuation

Implement [LIFECYCLE-DESIGN.md](LIFECYCLE-DESIGN.md), then wire the structured coordinator
into these commands. Do not work around a refusal by removing scope configuration,
discarding context tables, or copying the full database manually.

The disposable schema inventory also found `context_native_message_sources`, a native
message-to-source binding table absent from Stage32's fixed content table set. Include
and validate this edge in the full protocol. Optional embeddings should be rebuilt
under policy rather than independently trusted. `SET NULL` foreign keys in old notes
and parked records require explicit purge handling so forgetting cannot leave detached
derived bodies. These are concrete next implementation obligations, not claims that
the guard has solved them.
