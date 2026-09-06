# Stage37: recovery requires intent, not a new provenance label

Stage36 deliberately retained a withdrawn conversation when its receiver contained
an extra message the sender had never supplied. Regranting the sender's copy could
not authorize that extra material. Stage37 gives the local operator a bounded way
to resolve this: inspect the consequence, then explicitly discard the complete local
copy. Keeping quarantine remains the default and requires no command.

This is a component checkpoint in the active [production goal](../delivery/GOAL.md).
Authenticated sync, managed restore, full-store propagation and the complete installer
and consumer paths remain open. No owner database or live peer was changed.

## Follow the five-step lesson

The runner imports a fictional Codex archive and transfers it between two disposable
databases. Its installed mode invokes the real standalone `session-context` executable
with StudyLoop absent. The five expandable views show observed JSON, not model labels.

1. The receiver has two messages. One came from the sender and one was added locally.
   Withdrawal hides the conversation while retaining its ambiguous contents.
2. The CLI lists quarantined IDs and inspects one. The preview contains affected-table
   counts, version/history fingerprints, current scope, permission generations and
   database identity. It includes no conversation text and changes no durable rows.
3. Applying without acknowledging the loss of local additions fails. A permission
   change also invalidates the old preview, requiring inspection of the new state.
4. The operator supplies the exact new plan ID and explicit loss acknowledgement.
   The complete selected copy and its affected derivatives are removed. Its extra
   message is really lost. Withdrawal denials remain; no permanent retirement is added.
5. A fresh permitted content transfer restores the sender-covered copy. Retrying the
   old discard returns its historical receipt without deleting the restored copy.

All 18 lesson checks passed in the fresh standalone installation. The five disclosures
were opened and the rendered page inspected; the layout fit the viewport.

## Why this decision is not an origin claim

| Question | Evidence or authority required |
|---|---|
| Where did this exact version arrive from? | Native capture or committed delivery facts bound to the row version and local instance |
| May the agent expose it now? | Current configured scope, permissions, dependency visibility and retirement state |
| May the system automatically evict it after withdrawal? | Complete affected-row history establishing eligibility under the withdrawal contract |
| May the operator discard this retained local copy? | Current scope authorization, an exact inspected plan and explicit acknowledgement of local loss |
| Does an old discard receipt prove the body is absent now? | No; a fresh permitted transfer may have restored it |

Renaming an ambiguous copy “local” would not establish how it originated. Nor would
an operator's decision make two delivery paths independent. Schema45 therefore adds
a separate immutable local intent record. It does not add a capture fact, clear a
denial, change a review's authority or invent ownership history for existing rows.

The networking analogy is an administrator clearing a stale local cache entry. That
action says what the administrator chose to remove; it does not establish who
originated the route or whether a later advertisement is currently permitted.

## Why preview and apply must agree exactly

The preview reuses Stage36's actual purge under a rollback-only savepoint. It observes
the fixed canonical tables affected by cascades, including rows updated before they
are deleted. The plan binds those original row versions and all their matching
retention facts. A newly recorded fact invalidates the plan even when it did not
change the ordinary content revision.

Apply recomputes the plan while holding the writer transaction. A changed plan ID
refuses the discard. The plan also binds scope, policy classification, local database
instance/file, current revision and relevant denial generations. The actual config file
is reread before commit. A test changes that file during the purge and verifies that
the operation rolls back.

The plan hash is a consistency check, not a secret, signature or substitute for local
operator authorization. Request scope is checked separately from the project-policy
digest: the same project definitions can legitimately be queried in personal or work
scope without changing their classification fingerprint.

Preview has explicit refusal bounds: 100,000 unique affected rows, 100,000 matching
history facts and 32 MiB combined traced-row/history JSON. Repeated row changes consume
trace bytes. An incomplete trace never receives a usable fingerprint. The public plan
is at most 32 KiB; listing returns at most 100 IDs per page and refuses stale cursors.
At most 64 active peer denials are inspected for one root. These bound the returned
and traced data; they do not promise constant query work or a wall-clock deadline.

## Why inspection can see an ID while the agent cannot see its body

Ordinary visibility must continue to hide quarantine. Recovery nevertheless needs to
identify the objects that the operator is allowed to remove. The internal selection
can include withdrawn IDs while retaining configured scope, ownership dependencies
and permanent retirement checks. It does not collect or return their bodies.

Only the local quarantine boundary enables this private selection option. Public
session/evidence/observation/learner readers and content snapshots retain their default
denial checks. A directed test inspects all six object kinds, then confirms those
ordinary routes still withhold content. This covers the current entry points, not
every possible future API or a malicious process with direct filesystem access.

All six root types are supported: session, evidence, assertion, relation, observation
and learner record. Project-only records and observations are included; they need not
be artificially attached to a session. Removing one artifact does not assert that
every independent representation of its discussion has disappeared.

## Why logical deletion and physical cleanup have different receipts

The purge and immutable operator decision commit in one transaction. A real process
exit between the purge and audit insert leaves neither committed. A retry can safely
start again. Once committed, repeating the same decision never runs the purge again.

Canonical file maintenance follows separately. A pinned reader may prevent completion;
the command reports pending cleanup and a retry resumes maintenance without creating
a second decision. New pending work between compaction and receipt writing prevents
a false completion result. A changed scope or database boundary after logical commit
produces an explicit committed-but-unconfirmed error, rather than claiming rollback.

The receipt has separate `logical_discard_committed` and `canonical_file_cleanup`
fields. Completed cleanup is explicitly limited to the canonical database and WAL.
`current_body_absence` says that historical receipts do not assert current absence.
`sync_complete`, `permanent_forget` and `regrant` remain false. No promise is made to
erase native archives, backups, the full store or filesystem snapshots.

A removed peer configuration does not prevent local discard: this operation sends no
message and grants no remote authority. Re-adding that peer alone does not restore
content. The test requires a new regrant and transfer before the sender's copy returns.

## What we chose not to implement here

Adopting or extracting retained additions would require a separate ownership and
provenance contract. Automatically preserving selected parts under new identities
would be a semantic decision that this stage cannot justify. Instead, the operator
may preserve quarantine or deliberately accept complete local-copy loss. That loss
can be permanent for unsynced additions; the later transfer restores only sender data.

SQLite remains canonical. These tests benefit from one transaction across deletion,
scope checks and audit intent. They supply no new answer-quality measurement and no
evidence that another database engine gives better semantic results. Source grounding,
current applicability and explicit intent still need separate contracts with any engine.

The preserved implementation checkpoint is `801a33e0`; full commit lint, formatting,
secrets, Bandit and workspace source/test type checks passed.

The combined memory/experiment run passed 1,809 tests with one optional skip in
129.76 seconds. The later focused ledger/lesson run passed 94 tests in 16.57 seconds,
including six additional directed cases. StudyLoop passed 3,823 tests with four skips
and 704 deselections in 179.19 seconds against schema45. These are component and
regression results, not complete installed-product acceptance.

See [OBSERVED-RESULTS.json](OBSERVED-RESULTS.json) for run boundaries and
[COUNCIL-DECISION.md](COUNCIL-DECISION.md) for accepted and rejected reviewer claims.
The next product step is the authenticated configured sync coordinator, using these
existing local contracts rather than legacy whole-database transport.

## Run the preserved stage

Use the checkpoint in [STAGES.md](../STAGES.md) and a fresh output directory.

```sh
uv run python -m experiments.evidence_context.quarantine_recovery.runner --output /tmp/stage37-demo
open /tmp/stage37-demo/walkthrough.html
uv run pytest packages/agent-session-tools/tests/test_replica_ledger.py experiments/evidence_context/tests/test_quarantine_recovery_lesson.py -q
```

For a clean standalone installation:

```sh
uv build --package agent-session-tools --wheel --out-dir /tmp/stage37-wheels
uv venv /tmp/stage37-runtime --python 3.13
uv pip install --python /tmp/stage37-runtime/bin/python /tmp/stage37-wheels/agent_session_tools-0.1.0-py3-none-any.whl
uv run python -m experiments.evidence_context.quarantine_recovery.runner --python /tmp/stage37-runtime/bin/python --require-installed --output /tmp/stage37-installed
```

Source mode can invoke the CLI module if its environment has no console script.
Installed mode requires the actual installed executable; this distinction caught an
initial demo setup error and is now explicit. No model calls or real peers are needed
to replay the lesson. Earlier stages and the saved exercises remain unchanged.
