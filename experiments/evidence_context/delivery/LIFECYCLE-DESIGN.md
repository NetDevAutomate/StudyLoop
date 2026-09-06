# Lifecycle implementation decision after scoped content

Status: local lifecycle implemented at Stage33 `389146b8`; durable known-recipient
permanent controls at Stage34 `1f5a5c56`. Actual SSH, reversible withdrawal/regrant,
full-store and managed restore implementation and acceptance remain open. Stage32 is
preserved at `b05e6b4c`. Its successful content transfer does not reconcile deletion.

## The concrete mismatch

Current observation deletion triggers create permanent observation tombstones and
subject retirement markers. Evidence deletion also deletes dependent assertions and
observations; record-owner deletion removes learner bodies and dependent reports.
Annotation retirement permanently suppresses older annotation shadows.

Those rules make sense for permanent forgetting. Applying them unchanged to a scope
withdrawal would also make that withdrawal permanent. Regranting access could then
restore the source but fail to restore its original reports. Removing tombstones to
work around that would risk undoing an actual forget.

At the Stage32 starting point, session tombstone insertion suppressed native reimport and removed some
owned derivatives, but there was no complete source-forget command. Stage33 now tests
local native/learner/observation purge and canonical cleanup. Replication is still open;
see the independently runnable `local_forgetting/GUIDE.md` checkpoint.

## Decision

Keep canonical SQLite and distinguish permanent retirement from reversible withdrawal
in the transaction that performs a purge. Use an explicit administrative lifecycle
operation with a transient, write-locked mode; review all affected triggers so only a
permanent forget emits permanent retirement controls. The default remains permanent
for existing deletion entry points. A failure rolls back both the mode and the purge.

Do not put reversible records into the existing permanent tombstone tables. Native
import suppression currently treats membership as permanent, without a mode column.
Instead keep durable withdrawal/receipt state separate, with an explicit fresh-policy
reconciliation required before regrant. A mode flag alone cannot establish these
semantics; its implementation must include durable intent, dependency closure and
replay guards.

| Durable information | Purpose and invariant |
|---|---|
| Permanent retirement identity and object kind | Suppress old source/report/record identities even after bodies and owners are gone; monotonic union, never a last-write-wins deletion flag |
| Prior delivery/receipt identity per configured peer | Route controls only to peers already known to hold the object; preserve after body purge |
| Withdrawal state per peer/object | Distinguish a removed permission from global forgetting; invalidate stale content and require a fresh permitted transfer to regrant |
| Transfer identity, policy binding and acknowledgement | Retry an interrupted phase without mistaking a planned transfer for acknowledged completion |
| Managed restore suppression state | Reapply current retirement/withdrawal intent before any restored content is served |

Exact DDL belongs with the implementation and its migration tests. These are required
identities and invariants, not a claim that a full protocol already exists.

## Transaction and exposure sequence to prove

1. Load explicit reciprocal peer policy and validate installed protocol capability.
2. Reconcile applicable retirement and withdrawal controls before offering content.
3. In one write transaction, set the administrative purge mode, remove the full typed
   dependency closure, record durable outcome and return mode to its ordinary value.
4. Recheck policy and source/receiver state at the actual exposure and commit boundary.
   An old announcement cannot authorize a new transfer after a withdrawal.
5. Preserve retry state until the peer acknowledges its actual committed result.
   Permanent deletion wins over stale content or a concurrent correction.
6. Regrant requires current explicit policy and a fresh eligible content projection;
   it never erases a permanent retirement.

This sequence is not an atomic transaction across two disconnected machines. A local
forget can complete locally while remote delivery remains pending. The operator must
see pending/offline acknowledgement rather than a false global completion claim.

## Legacy routing and physical retention

Old SQL deliveries have no ledger. Old tombstones lack historical scope. A new ledger
cannot recover those facts. Do not infer boundaries from harness/hostname or broadcast
all IDs/hashes as allegedly anonymous metadata. Receiver-known identity intersection
may assist reconciliation only after establishing an appropriate same-owner peer and
scope boundary; unknown coverage must be explicit and prevent a full-sync claim.

Database row removal does not prove byte removal from FTS shadow tables, WAL, free
pages, managed indexes or backups. The implementation must inspect these managed
artifacts, not just query the current view. External native archives and independently
copied backups remain outside physical-erasure claims; native reimport and managed
restore must nevertheless honor the retained suppression metadata.

## First discriminating tests

1. Forget a real-schema session through the production API/CLI: remove native bodies,
   citations, assertions, reports, learner dependencies and managed FTS results.
2. Replay the same native source through the actual exporter: no resurrection.
3. Exchange a stale snapshot in both directions after a forget: no resurrection.
4. Withdraw a received source: remove its derived closure without minting permanent
   tombstones; a fresh explicit regrant restores eligible content and original hashes.
5. Concurrent permanent forget and withdrawal/regrant: permanent retirement wins.
6. Interrupt a purge/transfer before commit and retry: no partial state, stuck mode or
   falsely acknowledged result; test an actual process interruption as well as exceptions.
7. Change peer policy during transfer: no new disallowed body exposed/committed; report
   unresolved remote withdrawal until it is acknowledged.
8. Restore a managed older backup and rebuild indexes: replay current suppression before
   serving, inspect managed artifacts, and report unresolved legacy-control coverage.

## Council arbitration

The healthy gateway returned three valid design reviews: Meta (`llama4-maverick`),
Qwen (`qwen3-coder`) and Mistral (`mistral-large-3`). Comparison Markdown/JSON and all
responses were inspected. Private brief/results are in
`studyloop-private/reviews/2026-09-06-stage33-lifecycle/design-council`.

All preferred a transactional distinction plus delivery tracking. Accept that narrow
direction and their requests for cascade, concurrency, crash and legacy tests. Reject
Mistral's suggestion to put withdrawal flags into the existing permanent tombstones:
the current exporter/insert guards would still suppress every matching ID. Also reject
the implication that a ledger automatically fixes unknown historical deliveries or
backup restoration. No such historical evidence exists.

The brief already distinguished offline acknowledgement from local completion and
explicitly included a ledger candidate; criticisms assuming otherwise do not change
the requirements. The responses supplied no complete algorithm or measured performance.
Their agreement is design input, not implementation evidence or release approval.


## Stage34 implementation evidence

The durable offer/receipt and permanent-control state machine is preserved in
`replica_lifecycle/GUIDE.md`. It pins both endpoint instances, records prospective
recipient scope before body exposure, commits content with its receipt and routes
permanent controls through that retained history. Empty current peer scopes can still
process previously known controls; new bodies remain disallowed. The result remains
`sync_complete:false`. This does not implement the withdrawal/regrant or real SSH
sequence described above, nor infer missing historical delivery knowledge.


## Stage35 evidence prerequisite

Schema43 records exact local native-evidence capture and committed peer row contributions
in local-only history. See `retention_history/GUIDE.md`. This is not withdrawal state.
Two delivering peers may share an upstream origin; counts cannot establish independent
retention authority. Existing untracked versions remain unattributed, new database
instances cannot borrow old local facts, and native recapture is not regrant.
The next withdrawal implementation must make its policy explicit and enforce denial
before transfer/native recapture; it cannot obtain permission from these fact labels.
