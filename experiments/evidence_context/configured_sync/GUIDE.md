# Stage38: carry the local rules across a real connection

This stage connects the existing replica contracts to the actual `session-sync`
commands. The standalone package can push, pull and exchange configured canonical
databases over SSH. `all` pushes to every configured peer before pulling from each;
an offline peer does not prevent attempts against the others.

This is still a component checkpoint in the [active production goal](../delivery/GOAL.md).
Complete scopes currently have a 32 MiB transfer bound. Larger/incremental transfers,
full-store lifecycle and managed restore remain required, along with shared setup,
doctor, remaining ownership and installed StudyLoop acceptance. The command states
its canonical coverage and keeps `sync_complete` false.

## Follow the five views

The runnable lesson uses fictional conversations, two disposable databases and a real
loopback OpenSSH server. It runs the actual standalone CLI, including in an installation
where StudyLoop is absent. It neither contacts the MacMini nor changes owner SSH files.

1. **Establish the peer.** A dedicated client key reaches a locally pinned forced
   command. The client verifies the server against an explicit known-hosts file.
2. **Transfer permitted context.** A personal conversation moves to the mini; work
   content remains local. Both directions exchange controls before any body transfer.
3. **Retry with metadata alone.** An unchanged pair of source and committed receiver
   states skips retransmission. A lost receipt is recovered from durable metadata.
4. **Withdraw and regrant.** The CLI queues explicit permission intent. Sync delivers
   generations in order. Regrant requires fresh permitted content before re-exposure.
5. **Respect forgetting in either direction.** The mini forgets a source. A push-only
   command brings that retirement back to the laptop before considering new content.

The lesson also checks push-before-pull ordering, preserved other native history,
wrong-host-key refusal and rejection of a caller-requested command that tries to select
a different peer. Its JSON contains checks and metadata, not transcript text.

## Encryption and identity answer different questions

SSH encrypts the connection and authenticates keys. The application must still decide
which configured peer that connection represents. Accepting a `peer` field from a
packet would let a caller choose its own policy identity.

The receiving key therefore has a forced command containing a locally configured peer
name. The client sends only the fixed protocol marker; packet operations cannot supply
a different peer, database path, config file or SQL statement. OpenSSH documents both
[forced commands and the restrict key option](https://man.openbsd.org/sshd.8), and
[strict host checking and explicit identity selection](https://man.openbsd.org/ssh_config).

The transport uses a dedicated identity file, disables agent/port/X11 forwarding and
PTY allocation, and reads no ambient SSH client configuration. An unknown or changed
host key fails. This is an application boundary between configured peers; it is not
a sandbox against a machine owner who already has shell and database access.

The first isolated SSH rehearsal failed because the temporary authorized-key file was
under a group-writable ancestor in the code directory. OpenSSH correctly refused it.
Moving only that disposable file into a private temporary home directory made the test
pass with StrictModes still enabled. No existing directory permissions were changed.

## Why push still receives control information

| Phase | What moves | Why it must happen here |
|---|---|---|
| Hello and binding | Schema, local grants, project map and instance identity | Refuse wrong/replaced peers before data |
| Lost-response recovery | Opaque offer IDs, saved acceptances and receipts | Recover who already accepted an offer before selecting recipient controls |
| Permission and retirement exchange | Known IDs and ordered control generations, both directions | A destination may have forgotten content the source still holds |
| Stable control check | Both permission heads and each endpoint's sent control state | New controls arising during reconciliation need another round |
| Scoped content | Exact accepted snapshot, then atomic content receipt | Current permission and exact source version determine what can move |
| Completion check | Current control state | Refuse a completion claim if newer controls appeared during the operation |

In networking terms, sending cached routes without first processing withdrawals can
re-advertise a route that is no longer valid. A push-only database operation has the
same problem if it ignores deletion intent at its destination.

Control reconciliation repeats if an incoming change creates new outgoing work. Eight
rounds is a refusal bound, not a convergence promise. Continuously changing peers stop
before content and can retry from durable progress. Permission steps and recovery
attempts also have bounds. Empty retirement batches skip compaction when no cleanup
is pending. An older unresolved withdrawal does not override a later explicit regrant.

Retries provide idempotent effects and historical receipts. This is not an exactly-once
network-delivery claim: a packet or physical maintenance operation may run again.

## The real defect: permission revision is not content revision

An early implementation reused `context_access_state.revision` to decide whether a
body had changed. That counter was intentionally designed for access dependencies and
retirement. Adding a message does not invalidate an already-authorized read snapshot.

A directed test inserted a receiver message just before an unchanged confirmation.
The expected refusal did not occur. The test exposed an incorrect assumption about
the counter's meaning, rather than a problem with SQLite or SSH.

Schema46 now has a separate `context_replica_content_state.revision`. INSERT, UPDATE
and DELETE triggers cover the same fixed canonical table set used by snapshot export.
The peer state includes both counters. A new test verifies that appending source
content leaves the access revision unchanged, advances the content revision and causes
a fresh transfer. Receiver mutation invalidates an unchanged confirmation too.

This counter indicates that canonical rows were written. It is not a semantic hash,
validation label or proof of independent origin. It is deliberately conservative:
an unrelated scope or an unchanged-value UPDATE can also invalidate the shortcut.
Exact content hashes, identities and ownership checks remain responsible for the
transfer itself. New canonical tables require matching migration/trigger coverage.

The migration freezes its table names so a future projection cannot silently alter
an old upgrade. A coverage test compares the installed triggers with the current
projection. An overflow test verifies that the triggering body write rolls back;
an unrelated-work-scope test verifies conservative invalidation without work export.

The broad suite then caught a second consequence: compaction tried to copy the new
singleton into an already initialized destination, and archival comparison treated
different local counters as missing content. Compaction now preserves the new local
counter; archival proof still compares content rows while excluding local bookkeeping.
All six failing compaction/pruning cases passed after that correction.

The distinction is useful beyond replication. A routing policy version and the version
of the routes currently stored answer different questions; one cannot safely stand in
for the other merely because both are increasing numbers.

## How a lost response avoids a duplicate body

The receiver commits the conversation and its receipt in one transaction. Receipt v2
also records the receiver's committed access/content state in that transaction. The
sender can query the receipt by an already prepared offer ID after a connection fails.
No conversation body is needed to perform that recovery.

The next transfer may be skipped only if the current source hello matches the saved
source, the receiver matches the committed state, current controls still permit the
scope, and the receiver confirms that state. Old v1 receipts lack the content-state
evidence and cannot justify this optimization.

An accepted attempt with no receipt at the check is superseded by a fresh attempt.
Its original offer and recipient interest remain durable; the resolution does not
pretend it was delivered. Recovery of historical schema42–45 acceptance metadata is
allowed, while new content requires the current schema. Arbitrary backup restore is
still outside this guarantee and needs the pending managed-restore implementation.

## What “current” can mean across two machines

Each endpoint rereads local configuration before a phase, before ledger commits and
immediately before writing a result. A buffered source body also rechecks its source
and control state after encoding, before the first transport write. A scoped write
whose config changes before commit rolls back. If an earlier phase already committed,
a later refusal does not claim that the earlier event was undone.

These are explicit checked boundaries. They do not provide a globally atomic instant
across two machines and an externally edited config file. An edit after a valid reply
can require another exchange. The completion result therefore describes the checked
canonical operation, with full-store and full-product coverage still explicitly absent.

Framing uses nonblocking pipes and an absolute connection deadline. Each JSON frame
is bounded to 33 MiB including its envelope; a connection is bounded to 256 MiB and
1,024 requests. Duplicate JSON keys, nonfinite values, malformed/truncated frames and
unexpected operations are refused. Peer stderr and raw errors are not replayed into
logs or user output. That protects against accidental body disclosure but limits
diagnostics; useful sanitized doctor output remains a production requirement.

## Configuration and commands

The installer will own guided setup. At this checkpoint, dedicated-key setup is manual.
Both databases must already be current and have their explicit project policy applied.
Project IDs/scopes must agree across the shared scope; local roots may differ.

```yaml
memory:
  default_scope: personal
  projects:
    studyloop:
      scope: personal
      roots: [/absolute/local/studyloop]
  sync:
    node_id: laptop
    peers:
      mini:
        allowed_scopes: [personal]
        ssh:
          host: mini.example.invalid
          user: example
          port: 22
          identity_file: /absolute/private/client-key
          known_hosts: /absolute/private/known-hosts
```

The receiving key's locally installed authorization has this form. Replace the public
key and absolute executable path during deliberate setup; the example is not installed
by the experiment. The receiving local config identifies its node as `mini` and peer
as `laptop`. A custom config path can be set by its trusted forced-command wrapper.

```text
restrict,command="/absolute/bin/session-sync serve --peer laptop" ssh-ed25519 <public-key>
```

```sh
session-sync endpoints
session-sync push mini
session-sync pull mini
session-sync sync mini
session-sync all
session-sync permission mini --scope personal --action withdraw
session-sync all
session-sync permission mini --scope personal --action regrant
session-sync all
```

Permission output distinguishes a queued operation from an already acknowledged
generation and says that the queue command made no network attempt. Repeating the
same intent does not invent a new generation. Removed peer configuration blocks new
network operations; local quarantine inspection/discard remains a separate capability.

## Run this stage independently

Use the checkpoint in [STAGES.md](../STAGES.md), a fresh output directory, and a host
with `/usr/sbin/sshd`, `/usr/bin/ssh` and `/usr/bin/ssh-keygen`. The observed run used
macOS without root. The test authorization file is temporary under the user's home so
OpenSSH can enforce its normal ownership checks. Keys and daemon are removed afterward.

```sh
uv run python -m experiments.evidence_context.configured_sync.runner --output /tmp/stage38-demo
open /tmp/stage38-demo/walkthrough.html
uv run pytest packages/agent-session-tools/tests/test_replica_coordinator.py -q
```

For the fresh installed CLI/SSH rehearsal:

```sh
uv build --package agent-session-tools --wheel --out-dir /tmp/stage38-wheels
uv venv /tmp/stage38-runtime --python 3.13
uv pip install --python /tmp/stage38-runtime/bin/python /tmp/stage38-wheels/agent_session_tools-0.1.0-py3-none-any.whl
uv run python -m experiments.evidence_context.configured_sync.runner --python /tmp/stage38-runtime/bin/python --require-installed --output /tmp/stage38-installed
```

See [OBSERVED-RESULTS.json](OBSERVED-RESULTS.json) for exact run boundaries and
[COUNCIL-DECISION.md](COUNCIL-DECISION.md) for arbitration. SQLite remains canonical:
this experiment tests protocol correctness and metadata meaning, not semantic answer
quality or an advantage over graph engines. The next delivery work is scalable scoped
transfer and complete full-store/restore behavior, followed by the remaining setup and
consumer requirements. Earlier learning stages and saved exercises remain preserved.
