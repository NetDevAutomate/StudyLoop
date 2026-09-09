# Conversation memory, repair and sync

StudyLoop stores imported coding conversations in SQLite so an agent can find
earlier discussion and you can revisit how an answer was reached. The reliability
candidate improves capture, repair and configured sync. It is awaiting release
acceptance; these instructions describe the candidate checkout.

This is conversation history. A stored statement such as “the tests passed” is
still a statement from that conversation, not independent proof of validation.
Automatic arbitration and source-bound decision checks remain deferred.

## Install and check capture

Use the [setup guide](setup-guide.md) to install StudyLoop from source. The
existing installer registers skills and hooks for its supported mentor harnesses;
see [agent installation](agent-install.md#session-memory-and-automatic-export).
Then inspect the wiring and import the local transcripts:

```sh
studyloop doctor --category harness
session-export
session-query list --since last-7-days
```

The importer accepts `claude`, `codex`, `grok`, `kiro`, `opencode` and `pi` as
`--sources` values. For example, `session-export --sources codex --sources claude`.
The `pi` importer also handles supported oh-my-pi archives.

Re-importing a session never destroys conversation text. Harnesses rewrite a
session's modified time on any touch, compact their own histories, and write
transcript files asynchronously, so a re-export can legitimately read fewer
messages than were captured before — or none at all. Every importer therefore
collects the new payload first and lets the shared commit path reconcile: it
removes only empty stale rows, refuses to drop a message that an evidence row
still cites, and records edited text as a further revision (carrying
`source_record_id`) rather than overwriting the original. A re-export that reads
nothing is reported as `empty` and changes no stored message. One failing batch
is recorded in the `errors` count and does not stop the remaining batches or
sources.

Grok import reads local `chat_history.jsonl` files with sibling `summary.json`
under `~/.grok/sessions/`, or the configured `GROK_HOME` sessions directory.
`session-export --grok-only` imports those files; it does not install a Grok
mentor integration or automatic hook. Choosing a Grok model through a gateway
does not identify a conversation archive.

Doctor checks executable, skill and hook configuration. A passing wiring check
does not prove the most recent session was exported. Verify a known recent
conversation with `session-query`. Desktop coverage depends on discoverable local
transcripts and the application's hook behaviour; consumer Claude Desktop is
not covered by the Claude Code integration.

## Recover missing conversations

The default database is `~/.config/studyloop/sessions.db`; use the path configured
for your installation if different. Repair requires an existing database. On a
new installation, run the normal export first.

```sh
# Inspect first; this does not apply conversation changes.
session-repair --db ~/.config/studyloop/sessions.db

# After reviewing the report, back up and apply the repair.
session-repair --db ~/.config/studyloop/sessions.db --apply

# With unchanged transcripts, missing/changed counts should now be zero.
session-repair --db ~/.config/studyloop/sessions.db
```

Apply creates a private SQLite-consistent backup beside the database and merges
inside a transaction. Errors and identity conflicts block application. Keep the
backup until you have checked the recovered history. Each machine can recover
only transcripts available there; no parser can recover deleted original files
or certify that every cloud conversation is present.

This release uses schema 47 (`migrations.CURRENT_VERSION`); sync refuses any
database whose `user_version` differs, in either direction. Do not use it to
downgrade a database upgraded by a research branch — the unmerged Phase 2 work
adds tables at v48 and later. Rehearse upgrades and recovery on a disposable
copy of a supported database first.

## Find useful history

```sh
session-query search "database decision" --project "$PWD"
session-query show SESSION_ID
session-query context SESSION_ID
```

Replace `SESSION_ID` with an ID returned by search or list. Project aliases can
group known checkout paths. Inspect contrary advice and changed requirements;
the newest or most frequently repeated answer is not automatically the right one.
Agents should identify the relevant session and explain what remains unverified.

Project filters narrow results. They do **not** enforce a work/personal privacy
boundary. Do not give an agent access to a database containing material it may
not read.

## Sync permitted databases

Only sync when each destination may receive the entire selected database.
There is no per-peer work/personal filtering in this candidate. A project filter
on a search command does not limit what sync transfers.

Configure the machines in the [hosts section](setup-guide.md#host-configuration)
and establish SSH access with verified host keys first. Install compatible tools
and run repair locally on each machine before reconciliation.

```sh
session-sync endpoints
session-sync all
# Or reconcile one configured peer:
session-sync sync macmini --reconcile
```

`all` pushes to every configured peer before pulling from every peer. It revisits
shared sessions to recover missing messages even when timestamps are unchanged.
Other peers are attempted after a failure, and any failed operation produces a
nonzero exit status. With more than two machines, another run may be needed to
distribute history first discovered during the pull phase.

Different nonempty messages are not silently overwritten. Sync reports the
conflict; explicit repair from a database snapshot can retain variants for review.
This does not promise identical databases after conflicting edits.

## What remains outside this release

- Enforced work/personal boundaries and destination-specific permissions.
- Forgetting that propagates through peers, restore and derived indexes.
- Automatic decision arbitration and verified interpretation of evidence.
- A new standalone shared installer and comprehensive capture-health telemetry.

Deleting a row locally is not a distributed forget operation: another database,
backup or original transcript can bring it back. Exported Obsidian notes are also
separate copies. See the [CLI reference](cli-reference.md#agent-session-tools)
for commands and the [roadmap](roadmap.md) for the broader product boundary.

For the architecture behind this guide — one SQLite file holding three table
families, what each MCP tool reads, and which retrieval and ontology claims the
measurements do and do not support — see the decision record at
`docs/architecture/session-memory/README.md` in the repository (internal; not
published on this site).
