# Stage34: knowing which replica received the evidence

Stage33 established a local purge and cleanup operation. Stage34 gives the standalone
memory package durable records of prospective recipients, committed content and
acknowledged permanent deletion. The runnable lesson uses two fictional databases,
actual Codex parsing, the actual local forget CLI and the production replica APIs.

The complete objective remains [GOAL.md](../delivery/GOAL.md). The real SSH/session-sync
coordinator, reversible permission withdrawal/regrant, full-store propagation and
managed restore remain open. Every control acknowledgement still reports
`sync_complete: false`. This is a tested protocol component, not a shipped network sync.

## The question a successful copy cannot answer

Suppose the laptop sends a source to the mini. The mini commits it, but the response
is lost. The laptop cannot infer whether the source arrived from that missing response.
If the source is then forgotten, its deletion must still reach the mini.

An ephemeral list of sent IDs disappears on process exit. A log written only after a
successful response misses the lost-response case. A sender-only log records intention,
but gives the receiver no durable evidence of a prospective delivery if the body itself
never arrives. That distinction matters when deciding whether an incoming deletion ID
belongs to an established peer boundary.

The chosen sequence records an offer and its acceptance before releasing the body.
Both replicas retain the identities accepted for that scope. The receiver then commits
the body and its data receipt in the same SQLite transaction. The resulting history
supports retries and narrowly routed permanent controls.

Think of a reliable message exchange: an outbound queue, a recipient's acceptance and
a committed processing receipt describe different events. None can substitute for the
others just because one machine printed a success message.

## Follow the five-view lesson

1. **Offer identities.** The laptop imports fictional personal and work archives. Its
   peer configuration permits only personal scope. A scoped content projection produces
   the offer's source/report identities and exact snapshot hash. The offer ledger holds
   no conversation text, and the work identities are absent.
2. **Register the recipient.** The mini validates the reciprocal plan and its current
   database/config state. It rejects any already-local offered identity outside that
   scope using SQL selection metadata. Accepted identities and the acceptance are stored
   before a body arrives. The laptop records the returned acceptance before releasing
   the exact snapshot.
3. **Commit and acknowledge.** The mini commits content and its receipt together. The
   lesson deliberately requests the receipt again, modeling a lost response, and checks
   that it is identical. The laptop records the acknowledgement.
4. **Forget at the source.** The actual local CLI removes the laptop's personal source
   and its dependent reports. A permanent-control batch contains only retired identities
   already recorded for the mini. The work source and its identifiers are excluded.
5. **Reconcile and try replay.** The mini applies the controls, purges bodies and completes
   canonical file cleanup. The laptop records that limited acknowledgement. Replaying
   the old content receipt does not recreate content; importing the unchanged personal
   native archive is suppressed. The original external archives remain unchanged.

The lesson has 20 checks. In the installed run the child runtime contains only the
memory wheel, with StudyLoop absent. Its `results.json` contains metadata and checks,
not the old snapshot body. Native fixture archives intentionally remain available so
you can understand the replay test and the external-retention boundary.

## The durable states

```mermaid
sequenceDiagram
    participant A as Laptop database
    participant B as Mini database
    A->>A: Persist scoped offer and snapshot binding
    A->>B: Offer identities
    B->>B: Validate boundary; persist acceptance and interest
    B-->>A: Acceptance
    A->>A: Persist recipient interest
    A->>B: Revalidated exact content
    B->>B: One transaction: content plus receipt
    B-->>A: Data receipt
    A->>A: Persist acknowledgement
    A->>A: Forget source; preserve permanent IDs
    A->>B: Controls for recorded recipient identities
    B->>B: Commit purge; finish canonical cleanup
    B-->>A: Limited retirement receipt
```

This diagram describes message order, not a distributed atomic transaction. Either
machine can stop between arrows. Local transactions and durable records make those
interruptions distinguishable and retryable; they cannot make an offline machine
delete instantly.

| Record | Meaning | What it does not establish |
|---|---|---|
| Outbound prepared offer | Sender selected an exact snapshot under a recorded plan | Recipient acceptance or body delivery |
| Accepted offer | Recipient durably registered these prospective identities/scope | Body persistence or continuing permission after policy changes |
| Data receipt | Receiver committed that snapshot | Current existence of the body after a later forget |
| Permanent-control receipt | Receiver committed the deletion and reports cleanup state | Every peer, full database, external archive or backup is clean |
| Sender acknowledgement | Sender durably received the receipt | No later control or unrelated cleanup work can exist |

Schema42 pins both local and remote database instances and the local node name for each
configured peer. A node rename or replacement database must not inherit the old history
silently. A changed binding is refused for managed reconciliation. Hostnames/IP addresses
are transport locations, not evidence identities.

Offer identities, their accepted metadata and data receipts are immutable. Allowed
status transitions are enforced in SQLite. Permanent peer/object interest remains after
body purge so deletion can flow back to a sender or onward to another previously known
recipient. This retained metadata is sensitive and must not be treated as anonymous.

## Why the offer step survived review

Mistral proposed removing it and logging a single content transfer at the sender. That
would reduce an exchange and some metadata. It does not provide the recipient-side
record used here to authorize a control before a body has arrived.

We tested the distinguishing case: the receiver accepts an offer, its response is lost,
and the registered source is retired before body delivery. Retrying acceptance recovers
the durable response. After the sender records it, retirement feedback can flow back
and prevents the old body from being released. Another test kills a real process after
body insertion but before receipt writing; both roll back, and a retry succeeds.

Those tests justify the mechanism for these failure cases. They do not measure how often
lost responses happen on the owner's network or prove this protocol is the fastest
possible design. The implementation regenerates the accepted snapshot before release,
adding a second selection pass. The lesson reports one local timing, excluding SSH;
it is not a throughput or storage-engine comparison.

## Handling changing boundaries

New bodies need mutually permitted current scope and matching project maps. Permanent
controls instead use previously recorded peer/object scope. This lets a still-configured
peer with an empty current `allowed_scopes` list receive deletion controls without
authorizing new bodies. A removed peer stays unresolved; no removed address is used
silently. A future coordinator must display that pending state.

An offered ID which already exists locally under an excluded scope is rejected before
registering interest. An incoming control with no recorded peer/object boundary is
rejected before any controls are applied. These checks protect against a packet turning
an arbitrary existing work ID into a personal deletion target.

Old tombstones have no trustworthy historical peer/scope information. An offer touching
such a retirement is unavailable unless the necessary prior peer knowledge exists.
The implementation does not invent a historical scope from the incoming claim or send
the entire tombstone list as allegedly anonymous hashes. Explicit legacy reconciliation
remains a production integration obligation.

These are local single-owner application rules, not a multi-user security system.
The coordinator must authenticate the supplied peer argument independently of packet
labels and load fresh local configuration at each boundary. Those real transport checks
are not implemented by these library APIs. A hash binds exact bytes; it is neither a
signature nor proof that a peer's claim is true. Signing would not establish native
source authority or the physical state of a remote disk by itself.

## The cleanup receipt race

Stage33 fixed the revision captured during compaction. This stage introduced a later
boundary: compaction can return successfully, then another deletion request can arrive
before the retirement receipt is written.

The result council asked for concurrency evidence. A directed test retires a second
source in that interval. Replaying the pre-review function returns a complete cleanup
receipt even though the new source still needs purging. The repaired function checks
the durable pending table inside its receipt write transaction and returns
`cleanup_pending_before_receipt`. The sender refuses to acknowledge completion; retry
reconciles the new request and succeeds.

This is why cleanup cannot be summarized as a boolean copied from an earlier call.
SQLite compaction and receipt writing are separate phases. A guarded pending state
connects them without pretending they form one atomic operation.

## Current limits and next integration

The fixed object manifest covers sessions, native evidence, assertions, relations,
observations and stable learner owners. Content/dependency closure still comes from the
Stage32 engine. This stage extracts its application into a caller-owned transaction so
the receipt can commit atomically with it; the older content-only API remains available
and explicitly reports incomplete synchronization.

The final ledger tests also retire evidence, assertions, relations, observations and
learner owners individually, then perform another allowed transfer. All five typed
identities remain retired. This verifies artifact suppression; it does not imply that
retiring one artifact erases every independently retained conversation representation.
The public local forget command operates on the whole session.

Per-envelope limits remain 100,000 rows and 32 MiB. Retained offer/control history can
grow over time; aggregate storage quotas and safe history compaction are not established
by those envelope limits. Unknown historical deliveries remain unknown. Mutable native
or learner conflicts are still refused by the content phase rather than merged.

Permission withdrawal needs a separate durable denial/regrant mechanism. A permanent
tombstone cannot stand in for a reversible permission change. Full-store propagation,
managed restore, hot/full consumers and the actual configured SSH/session-sync command
must still be wired to these records and tested end to end. No owner database, native
archive, scope setting, hook or network peer was modified for this stage.

## Run the preserved stage

Use the Stage34 checkpoint in [STAGES.md](../STAGES.md) and a fresh output directory:

```sh
uv run python -m experiments.evidence_context.replica_lifecycle.runner --output /tmp/stage34-demo
open /tmp/stage34-demo/walkthrough.html
uv run pytest packages/agent-session-tools/tests/test_replica_ledger.py experiments/evidence_context/tests/test_replica_lifecycle_lesson.py -q
```

For an installed standalone child runtime:

```sh
uv build --package agent-session-tools --wheel --out-dir /tmp/stage34-wheels
uv venv /tmp/stage34-runtime --python 3.13
uv pip install --python /tmp/stage34-runtime/bin/python /tmp/stage34-wheels/agent_session_tools-0.1.0-py3-none-any.whl
uv run python -m experiments.evidence_context.replica_lifecycle.runner --python /tmp/stage34-runtime/bin/python --require-installed --output /tmp/stage34-installed
```

No provider calls are needed for the lesson. See
[OBSERVED-RESULTS.json](OBSERVED-RESULTS.json) for exact observed checks and
[COUNCIL-DECISION.md](COUNCIL-DECISION.md) for the advice and its arbitration.
