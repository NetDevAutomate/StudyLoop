# Repair and synchronise conversations

Install the repaired exporter on each machine. Run `session-repair` to inspect
native transcripts, then `session-repair --apply` to back up and repair that
machine's database, including pending schema migrations. Sync checks both schema
versions before transferring rows. If a machine is outdated, its error identifies
the machine and asks you to run `session-repair --apply` there; no columns or
populated source fields are silently discarded. A machine can only recover native conversations available
there; syncing distributes the recovered history afterwards.

Configure the machines in the shared `~/.config/studyloop/config.yaml`:

```yaml
hosts:
  laptop:
    hostname: My-Laptop
    user: person
    ip_address:
      primary: 192.0.2.10
    sessions_db: /Users/person/.config/studyloop/sessions.db
  macmini:
    hostname: My-Mac-mini
    user: person
    ip_address:
      primary: 192.0.2.12
      secondary: 192.0.2.13
    sessions_db: /Users/person/.config/studyloop/sessions.db
```

Use each machine's actual hostname (without the `.local` suffix), SSH user,
reachable addresses, and absolute database path. The current hostname is
excluded automatically. Existing legacy `endpoints` configuration remains
supported when `hosts` is absent. SSH authentication must already work.

```sh
session-sync all
```

This pushes to every configured peer **before** pulling from every peer.
It reconciles shared sessions even when conversation timestamps have not changed,
so newly repaired messages can transfer. Each failed peer operation is reported;
other peers are attempted, and any failure produces a nonzero exit code.
With more than two machines, a later run may be needed to distribute history
first discovered during the pull phase to all other peers.

For one peer, use `session-sync sync macmini --reconcile`. For timestamp-only
routine transfers, use `session-sync all --incremental`. `--db /absolute/path`
overrides the local database; `--tier full` uses configured `full_db` paths.

Sync skips source-only empty message artifacts, preserving any empty rows already
present at the destination. A reference requiring an omitted empty row aborts the
transaction for explicit repair instead of leaving a dangling reference.

Sync adds missing messages and fills missing fields without replacing existing
nonempty conversation content or deleting local annotations. Different nonempty
versions of the same message are retained at their destination and counted in a
warning; they require explicit review with `session-repair --from-db SNAPSHOT`.
Thus reconciliation does not promise that conflicting databases become identical.
Per-destination writes are transactional and backups precede writes. Initial
seeding transfers a consistent SQLite backup, never a live database file.

## Parked-topic history across database variants

Some older databases enforce one parked question per study session, while newer
databases enforce one pending question across sessions. Their current views
cannot both hold every duplicate event. Sync resolves those known natural-key
collisions using the global metadata timestamp rule, preserving the destination
row ID and sync key. This policy applies to learning metadata, never conversation
message content.

Before merging, sync stores complete original parked rows from both machines in
`sync_row_archive`, including columns outside the current-view sync allowlist
(such as notes, board fields, and park counts). It also snapshots the resulting
current rows. Archiving and merging share one transaction. The composite key of
table name and JSON serialized with sorted column names makes identical snapshots
idempotent. Archive rows travel in subsequent syncs, so original variants remain
recoverable on other machines. The command reports newly preserved snapshots.

For read-only inspection:

```sql
SELECT row_json FROM sync_row_archive WHERE table_name = 'parked_topics';
```

The parked-topic UI presents the merged current view; the archive retains its
original variants for explicit review or restoration. Optional fields excluded
from the current-view allowlist are preserved in the archive rather than forced
into incompatible legacy table constraints.
