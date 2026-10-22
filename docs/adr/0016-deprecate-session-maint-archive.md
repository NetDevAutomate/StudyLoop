# ADR-0016: `session-maint archive` is deprecated for `sync-full` + `prune`, not rebuilt

**Status:** Accepted, 2026-10-22 (proposed and implemented the same day; the owner accepted the
eight pass-3 records together at 16:36 BST) · **Date:** 2026-10-22 · **Deciders:** council pass 3
of the 2026-10-21 full-repository review (five no-tool seats: kimi-k3, gpt-6-astra, grok-4.6,
deepseek-r1, mistral-large-3), arbitrated by argument by the review coordinator under the owner's
standing delegation; accepted by Andy Taylor (owner). · **Change:** 2026-10-22 council pass 3, ruling D4 (5–0); implemented in `4485f5e5`,
merge `85e4a072` (lane G, `maintenance-contracts`).

The council record (`reviews/2026-10-21-full-repo-review/`, gitignored, owner's machine only)
holds the seat transcripts; everything this record relies on is restated here. Symbols were read
at `309074c7` in `packages/agent-session-tools/src/agent_session_tools/`.

## Context

`session-maint archive --days N` moved sessions older than N days out of the everyday database
into a separate archive file whose two-table schema (sessions, messages) was written by hand in
`maintenance.py`, not the canonical schema the rest of the package migrates. The 2026-10-21
review's lane 4 had already made it safe: it refuses to move any session that owns rows the
archive cannot hold (notes, tags, file references, evidence, learner records) and prints how many
it kept; the archive file is created 0600; the operation is re-runnable. It did not rebuild the
schema, because that was a design choice.

The same CLI already had the canonical-schema alternative: `sync-full` copies whole sessions into
`database.full_db_path` with verification, and `prune` (`tiering.prune_hot`) then removes them
from the everyday database.

The fact that settled it was read twice (the lane corrected the coordinator's first reading, and
the correction made the case simpler): **nothing reads the file `archive` writes.** `_archive`
writes `<db>_archive.db` beside the source database. The only archive-shaped reader in the
package, `context/managed_history.py`, opens `database.full_db_path` via
`tiering.get_full_db_path`, a different canonical-schema file. Nothing reads
`database.archive_path` at all, so that config key and `get_archive_path` are dead. The
hand-written archive is write-only; retiring it needs no migrate-off tool.

Unknown and not needed: how many learners beyond the owner ever ran `archive` (there is no
telemetry).

## Decision

Deprecate now, remove after one release.

- The command is registered `deprecated=True` and prints a notice **before** doing anything,
  naming `session-maint sync-full` then `session-maint prune` and stating the difference: they
  move **whole** sessions on the **canonical** schema with verification, and need
  `database.full_db_path`; this is **not a drop-in replacement**. The notice does not claim parity
  it does not have.
- Behaviour after the notice is unchanged, lane 4's refusal logic included, so a learner who
  depends on it today loses nothing in this release.
- `CHANGELOG.md` carries the Keep a Changelog `Deprecated` entry with the removal release
  (written as 0.7.0, assuming the next release is 0.6.0).
- At removal, the dead `database.archive_path` key and `get_archive_path` go with the command.

*Amendment, 2026-10-22 (plan 4, lane N, merged `e1b87a63`): two consequences above have moved.
The `database.archive_path` key and `get_archive_path` were removed ahead of the command, because
reading the code showed they had no reader at all (the `archive` command derives `<db>_archive.db`
from `database.path`, `maintenance.py:508`); a `config.yaml` still carrying the key loads. The
removal release is no longer written as a version: the notice and the changelog say "the release
after the one that deprecates it". And a blocker on the removal itself was found and reproduced:
`sync-full` refuses with `LegacySyncRefused` (`replication/legacy.py:49-70`) on any row in any
`context_*` table, and `parking.py:41-56` seeds `context_board_columns` on first connect for anyone
who has parked a topic, while every current-schema `delete` writes a `context_tombstones` row. So
the replacement this deprecation names is unavailable to a large class of learners, and the CLI
shows the refusal as a traceback (`maintenance.py:1209` catches only `ValueError` and
`FileNotFoundError`; `LegacySyncRefused` is a `RuntimeError`). `archive` must not be removed until
those learners have a path; ledgered as a larger follow-up.*

Grounding adopted: single source of truth for the schema (one migration path, one reader set);
Keep a Changelog's deprecate-then-remove.

## Alternatives considered

- **(b) Rebuild `archive` on the canonical schema** (`VACUUM INTO` a full-fidelity copy, then
  delete the moved sessions through the tombstone path) so it can move every session. Rejected:
  that *is* `sync-full` + `prune`, rebuilt under a second name, with a second file nothing reads.
- **(c) Keep the safe partial archive as merged.** Rejected: a command that refuses whatever it
  cannot hold and writes a file nothing reads is a trap for the next learner who tries it; its
  honesty is already at the ceiling of what a two-table schema allows.

## Consequences

- One mechanism for moving old sessions out of the hot database, on the canonical schema.
- `docs/contributor-changelog.md` lists five sections and says not to add others; the `Deprecated`
  section the ruling required contradicts that guide. The guide needs updating (ledgered); this
  record follows Keep a Changelog, which the guide itself cites.
- Two docs pages still recommend `archive` (ledgered). The deprecation notice is the learner's
  pointer in the meantime.
- Owner-side: nothing to do until removal, which is a `Removed` entry and a small deletion in
  `maintenance.py`, `config_loader.py` and `tiering.py`.

## Verification

`packages/agent-session-tools/tests/test_maintenance_archive_deprecation.py`: the notice is
printed and names both replacement commands and the difference; existing archive tests stay green;
a deprecated run modifies an existing archive file no more than the old command did. Coordinator
probe on the lane tree against a current-schema database: notice first, then the lane-4 behaviour
unchanged.
