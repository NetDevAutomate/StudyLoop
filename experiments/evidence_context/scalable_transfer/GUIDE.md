# Stage39: larger histories without breaking their evidence relationships

The actual `session-sync` CLI now streams a complete scope when it exceeds the small
snapshot limit. The installed lesson transferred 2,300 additional native Codex messages
over a disposable SSH connection, then withdrew, regranted and forgot that history.
All 15 lesson checks passed after correcting a withdrawal bottleneck discovered by
the larger run. The [production goal](../delivery/GOAL.md) remains active.

This stage changes how bytes are represented and transported. It does not change
which sources are true, what a model may claim, or which database is canonical.
SQLite still owns the conversations, evidence, policy and durable receipts.

## Follow the five views

1. **Let history grow.** A fictional native archive passes through the actual Codex
   exporter. Its messages and captured evidence are larger than a small packet.
2. **Move bytes without splitting meaning.** Frames rebuild one private complete
   projection. Nothing becomes canonical merely because a frame arrived.
3. **Recover or skip.** A lost committed receipt is recoverable. An unchanged pair
   sends no body. An interrupted incomplete stream currently restarts.
4. **Withdraw, then restore fresh content.** Existing ownership and complete regrant
   coverage still govern deletion and re-exposure.
5. **Forget in either direction.** Even a push receives the destination's retirement
   controls before considering new content.

The lesson reuses Stage38's isolated authenticated SSH fixture. Keys, authorization
file and loopback daemon are disposable. The owner's databases, SSH configuration,
hooks, archives and actual MacMini are not changed. Fictional databases and native
archives remain under the chosen output directory for inspection.

## Why not split one packet per session?

A review can cite assertions from several sessions. A learner record can depend on
an observation, and an observation can depend on several captured sources. A packet
containing only one session could omit the evidence that gives the review meaning.

Regrant adds another constraint. If a receiver retained a quarantined local addition,
a fresh sender packet must cover everything that would become visible. Releasing one
session fragment before checking the rest could expose an unreviewed retained copy.

In network terms, packet fragmentation does not turn one application message into
several independent decisions. The receiver reassembles the message before accepting
its meaning. Here, ordered frames carry one complete evidence projection; its hash,
ownership and dependencies are validated before one canonical transaction commits.

| Choice | Benefit | Cost or unresolved issue |
|---|---|---|
| Raise the old packet limit | Small code change | Still constructs several full-body copies in memory and one large transport frame |
| Independent session batches | Natural retry granularity | Cross-session closure, large connected groups and complete regrant coverage need a new protocol |
| Private complete-scope staging | Reuses complete closure, ownership and atomic receipt rules | Disk work, complete retransmission when changed, some metadata sets remain proportional to IDs |
| Row manifests and deltas | Avoids resending unchanged rows | Requires exact portable identities, current receiver union validation, conflict handling and safe incomplete retry |

The decision was complete-scope staging first, with row deltas still required for
incremental efficiency. The council disagreed on sequencing; its objections and the
coordinator's evidence-based decisions are in [COUNCIL-DECISION.md](COUNCIL-DECISION.md).

## What the temporary database does

`Stage` stores canonical row JSON in an unnamed private SQLite database. Its page
cache is limited, and completed staging becomes read-only. Indexed `RowMap` lookups
replace dictionaries containing every evidence or message body. The canonical reader
interfaces cannot query this private connection.

An empty database filename creates private temporary storage that SQLite removes on
connection close. This follows the documented [connection behavior](https://www.sqlite.org/c3ref/open.html).
The [temporary-file documentation](https://www.sqlite.org/tempfiles.html) also explains
why a small cache can spill to disk and why implementation details can vary.

This stage observed real process exit while more than 64 MiB had been allocated to
staging, with no reusable temporary path left in the isolated directory on this Mac.
That is evidence about this OS/SQLite build. It is not a claim about every VFS, forensic
erasure, OS failure, swap or external backups. Staging is discarded on refusal, stream
close and server exit; a policy change is checked at the next controlled boundary.

The canonical transaction remains the crash-recovery authority. Staging is never a
substitute for its rollback journal, write lock, retirement checks or durable receipt.
A real child process was terminated after inserting a canonical message but before
the receipt; both rolled back, and retry committed successfully.

## Exact bytes still matter

The snapshot hash covers the same canonical JSON representation: sorted object keys,
unchanged Unicode/escaping rules and ordered table rows. The new encoder yields one
row at a time into SHA-256 instead of building a whole-scope JSON string. A directed
test compares its exact bytes with the existing serializer, including Unicode,
newlines, quotes, backslashes, booleans and nulls.

Source rows are ordered by primary key in staged projections. A prepared offer binds
the complete hash and object manifest. Release regenerates that same projection under
the same source state. Receiver frames enforce table order, sequence, columns and row
bounds. Every table must be complete before sealing; the recomputed final hash must
match the accepted offer. A frame acknowledgement explicitly says `committed: false`.

Existing code then validates citations, review targets, ownership, learner ID remapping,
current permission, permanent retirement and complete regrant coverage. Canonical
content and its receipt commit together. A changed receiver, truncated stream,
altered body or out-of-order frame cannot obtain a content receipt.

The final directed test caught a narrower race. After the last chunk was encoded,
the sender could withdraw permission before sending the separate commit request.
The overall command subsequently refused completion, but the receiver had already
committed that body. The test therefore checks body absence as well as command failure.
The sender now rechecks the outgoing offer immediately before writing either a chunk
or the final commit request. Both injected boundaries leave the receiver without the
body. This closes the reproduced gap; it does not create a simultaneous transaction
across two machines. Remote changes after the last checked boundary still require
the ordered control/retry protocol.

## The larger test found a second limit

The first installed large run transferred successfully, then returned `cleanup_pending`
for withdrawal. Its receipt recorded `footprint_limit`. This was a useful refusal:
the implementation did not claim erasure it had been unable to prove.

The old withdrawal rehearsal retained every first-before-image body in memory and
limited the cumulative trace to 32 MiB. The new transport had outgrown that assumption.
Merely increasing the limit would have restored the same full-body memory problem.

The corrected callback hashes each first-before-image immediately and retains its
table/key/version binding. After the simulated purge rolls back, matching retention
facts are queried under the same writer lock. The first image still wins when a
foreign key changes a row before a later delete. Shared pure binding code keeps this
equivalent to normal retention hashing. Unknown/local history still prevents automatic
erasure; overflow still yields incomplete cleanup.

Trace and fact budgets now accommodate the staged scale. Hash and ID metadata still
grow with affected-row/fact counts. No constant-memory or arbitrary-history guarantee
follows. The corrected installed run passed withdrawal, fresh regrant and forgetting.

## Measurements and their practical limits

The projection diagnostic runs one fresh process per cell. These are fictional legacy
message rows; the native exporter/SSH lifecycle lesson is a separate workload. Peak RSS
includes fixture creation. Timing covers projection and encoded-size measurement,
excluding transport and the receiving transaction.

| Messages / raw body size | Representation | Result | Time | Peak process RSS |
|---|---|---|---|---|
| 512 / 8.5 MiB | Small snapshot | 8.6 MiB encoded | 88.4 ms | 93.9 MiB |
| 512 / 8.5 MiB | Staged | 8.6 MiB encoded | 118.9 ms | 40.0 MiB |
| 3,072 / 51.0 MiB | Small snapshot | Refused | 18.0 ms | 36.4 MiB |
| 3,072 / 51.0 MiB | Staged | 51.5 MiB encoded | 674.7 ms | 42.4 MiB |

For the successful small case, staging used less process memory and took longer.
The large comparison establishes that the new path can process a previously refused
scope. Refusal time is not successful throughput. These single samples do not rank
database engines, prove constant memory, or measure retrieval usefulness.

## Explicit compatibility and resource boundaries

Live protocol v2 is required on both endpoints. An old v1 live peer is refused before
binding or content. Stored historical v1 acceptances and receipts remain recoverable;
that does not permit replaying an old body under current rules. The schema remains46.

Only the typed `SnapshotTooLarge` refusal selects staging. Other validation failures
do not fall back to a less strict transport. The original small path remains available.

Current bounds are one GiB encoded per staged scope, one million rows, eight MiB raw
per selected source row and 32 MiB encoded per staged row. A chunk targets four MiB or
1,024 rows, allowing one larger bounded row. The frame cap remains 33 MiB; a connection
has four GiB/4,096-request bounds and an absolute checked 120-second deadline. Multiple
scopes/directions may reach a connection bound and require another invocation.

These finite limits do not imply all datasets within them meet a latency or memory
target. Metadata sets, retained receipt history, repeated hash passes and complete
scope validation still cost work. Incremental row deltas and resumable incomplete
transfers remain open. Source/receiver checks describe explicit boundaries, not a
globally atomic instant across two machines and externally edited configuration.

## Run the stage

Use the checkpoint in [STAGES.md](../STAGES.md) and a fresh output directory. The SSH
lesson requires local OpenSSH binaries; the diagnostic does not contact a peer.

```sh
uv run python -m experiments.evidence_context.scalable_transfer.runner --output /tmp/stage39-demo
open /tmp/stage39-demo/walkthrough.html
uv run python -m experiments.evidence_context.scalable_transfer.benchmark --output /tmp/stage39-measurements
uv run pytest packages/agent-session-tools/tests/test_replica_staging.py packages/agent-session-tools/tests/test_replica_content.py packages/agent-session-tools/tests/test_replica_coordinator.py packages/agent-session-tools/tests/test_replica_ledger.py -q
```

To test the installed standalone package, build its wheel into a new directory, install
it in a fresh Python3.13 environment, then pass that environment's Python to both
runners. The SSH runner's `--require-installed` verifies the actual console entrypoint,
site-packages import and absence of StudyLoop. The observed installed run used this path.

See [OBSERVED-RESULTS.json](OBSERVED-RESULTS.json) for exact verification boundaries.
The next delivery work includes incremental transfer/receipt scale, complete full-store
forgetting and managed restore, followed by remaining ownership, shared setup/doctor
and installed consumer acceptance. Earlier learning checkpoints and saved exercises
remain preserved; this checkpoint does not close the full production goal.
