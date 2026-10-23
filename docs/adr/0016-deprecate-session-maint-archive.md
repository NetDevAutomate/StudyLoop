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

*Amendment, 2026-10-23 (plan 5, lane Q, merged `d20c355c`; coordinator unit): the blocker above is
wider than "a large class of learners" — it is every learner with an exported session. Lane Q's
read-and-prove, reproduced by the coordinator against source: one ordinary `session-export` writes
a `context_evidence` row per message (`exporters/base.py:198-200` → `context/capture.py`,
`ContextStore.capture`), so `check_database` refuses every current database, and it refuses
correctly — with the guard bypassed, `sync_to_full` (`tiering.py:447-531`) copies only `sessions`,
`messages` and `file_references` (`_copy_table` at `:505,:511,:525`) and the full copy loses the
session's evidence tier; `prune_hot` then verifies nothing (`_archive_context_complete`, `:867`,
requires hot's whole context set ⊆ full, which the copier never produces) and evicts nothing. Both
halves of the replacement this record names are therefore inert on schema ≥ 41 for any real
database, independent of parking or deletion, and exempting `context_board_columns` /
`context_tombstones` from the guard would unblock nobody (a real post-delete database also carries
`context_retirements` and `context_erasure_pending`); the protected set was deliberately left
unchanged and the refusal now names the offending table(s) (`49c90373`). Consequence for this
record: the decision (deprecate; one mechanism on the canonical schema) stands, but its premise that
`sync-full` + `prune` is the supported path today was wrong, so the removal is no longer promised
for "the release after the one that deprecates it" — it waits on `sync-full` carrying the current
schema. The notice (`maintenance.py` `_ARCHIVE_DEPRECATION`), `docs/cli-reference.md`,
`docs/setup-guide.md` and the changelog now say so instead of sending learners to a command that
refuses them. Owner decision recorded for the next cycle, coordinator's recommendation first: (a)
make `sync-full` carry the whole context tier — `tiering.compact_database` (`:358-430`) is the only
all-tables copier in the package and `_archive_context_complete` already states the acceptance
condition, so this is the path that makes the ADR true; or (b) supersede this record and un-deprecate
`archive`. (a) is recommended because `archive`'s two-table file also drops the evidence tier, so
un-deprecating it would bless the same loss under a different name.*

*Decision, 2026-10-23 (owner, after plan 5): option (a) is adopted — `session-maint sync-full` is to
carry the whole context tier, so that `prune`'s acceptance condition (`_archive_context_complete`)
can be met by a real database and this record's removal of `archive` becomes achievable; option (b)
is rejected for the reason given above. What is decided is the goal, not the copier: the legacy
guard (`replication/legacy.py`, `4eb649fa`) was written on the principle that protected context
moves only through the structured replica protocol, never by executable SQL, and the full tier is
already lifecycle-reconciled by `context.managed_history.reconcile_full` (controls, no bodies). How
the content phase of a local hot → full transfer is built — SQL copy of the verified table set under a
narrowed guard, or the structured data plane (`replication/snapshot.py` → `content.py`) run locally —
is the design question for the implementation cycle; it is put to a council (pass 7) before the lane
is briefed, and this record will be amended with the outcome. Until the implementation lands, the
notice, docs and changelog keep the wording the previous amendment gave them.*

*Amendment, 2026-10-23 (council pass 7, remediation plan 6; **lands with lane T,
`review6/tiering-mirror`** — until that branch is merged this paragraph records a ruling, not
shipped behaviour): the design question above is decided. All five seats ruled ADOPT WITH CHANGES
on a SQL copy of a verified table set under a narrowed guard, not the structured data plane run
locally. The principle the legacy guard was written on is kept, and narrowed, in these words: "The
protected-memory principle remains mandatory for peer and scoped replication and for every legacy
SQL entry point. Tiering is a separate, same-owner mirror: explicit table roles, lifecycle
reconciliation before content, foreign keys on, immutable-row rules, no peer-convergence claim, and
no copy of instance-local peer, receipt, access-generation, retention-origin, quarantine or policy
state. It is not a fallback and authorises no SQL transfer between independent nodes."*

*The mirror contract `session-maint sync-full` implements under that principle: it runs only with
`database.full_db_path` set; the full database is a single-writer mirror, bound on its first sync
to the hot database's instance (`context_access_state.instance`), and a populated full that is
unbound, or bound to another instance, is refused; a hot database that has used structured
replication (any peer-ledger row) is refused; permanent controls (tombstones, retirements) are
reconciled canonical-first before any content moves, without compacting either file, and the
bodies those controls retire are purged from full; content then moves in one transaction with foreign keys on,
driven by one table-role registry that both the copier and `prune`'s acceptance check consume, so
a `context_*` table the registry does not classify makes both fail closed; immutable rows are
inserted if absent and never replaced, and a divergent row under an overlapping key is a refusal
naming table and key; mutable rows are upserted, never `INSERT OR REPLACE`; instance-local state
(access generations, replica receipts, policy, lifecycle mode, capture runs, retention origins, the
peer ledger, quarantine) is never copied; a repeated run with nothing changed inserts nothing.
`session-maint prune` then evicts from hot only the sessions that check verifies in full. A refusal
is its own exception with a reason code, not the `LegacySyncRefused` message, and the CLI prints the
reason and the fix.*

*What remains forbidden: every SQL transfer between independent instances. `session-sync` and every
other legacy SQL entry point, and any scoped configuration (`memory.sync`, `memory.projects`, a
non-default `memory.default_scope`, which `sync-full` still refuses through `check_config`), keep
the legacy guard (`replication/legacy.py`) and its existing refusal pins unchanged; `refocus`
(full → hot) still shares that guard and is its own design item. The guard is narrowed for one
path only — `sync-full` into the full database bound to this hot one — and that path is not a
fallback for any other. The removal promise stays withdrawn by this amendment. It returns — the
notice, docs and changelog may again say `archive` is removed in the release after the one in which
`sync-full` carries the context tier — only when the end-to-end acceptance test (pass 7, R1) is
green on `main`: a current-schema session created through the real exporter, synced with
`sync_to_full`, is evicted from hot by `prune_hot(dry_run=False)` with its whole closure queryable
in full; the foreign-key check and both full-text invariants hold; a repeat sync inserts zero rows;
a permanent forget never resurrects; and every existing peer refusal pin stays green. Until then the
docs describe the mirror contract but name no removal release.*

*Condition met, 2026-10-23 (coordinator, after lane T merged as `ee0750eb`): the end-to-end
acceptance test R1 (`test_sync_full_then_prune_evicts_a_real_exported_session`) is green on `main`
with the full gate (9038 passed, 0 failed), and a live run of the CLI on an exporter-built database
bound, copied, no-op'd, pruned and re-synced as the contract says. The removal promise therefore
returns in the concrete form of this record's original decision: `archive` is removed in the
release after the one that ships the mirror. The notice, `docs/cli-reference.md`,
`docs/setup-guide.md` and the changelog say so.*

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
