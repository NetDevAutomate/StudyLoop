# Stage36: permission withdrawal needs current evidence

This stage implements a bounded local withdrawal and regrant protocol. It adds the
permission decision that Stage35 deliberately left unimplemented. The complete product
goal in [GOAL.md](../delivery/GOAL.md) remains active: a real sync coordinator, managed
restore, full-store propagation and operator reconciliation are still required.

The useful distinction is between **having received a copy**, **being allowed to expose
it now**, and **having enough evidence to erase or restore it**. These are different
questions, with different evidence requirements.

## Follow the six-step lesson

The lesson parses a fictional Codex archive, transfers it between two disposable
databases and calls the actual standalone memory APIs. No model decides its labels.

1. **Committed copy.** The mini receives a conversation from the laptop. Its permission
   generation is zero; the content receipt and exact row contributions are durable.
2. **Withdrawal.** The laptop sends a body-free control at generation one. Every row
   affected by the mini's purge has only the laptop's matching delivery history. The
   mini evicts that copy and compacts its canonical database. It creates no permanent
   retirement IDs. Replaying the old content receipt or rereading the native archive
   does not restore the conversation.
3. **Fresh regrant.** A control at generation two changes the permission to granted,
   but leaves known objects awaiting content. The database stays empty until a fresh
   offer and content transaction at generation two restore the source.
4. **A local addition.** The mini adds a message that the laptop has never supplied.
   A later withdrawal cannot safely call the entire conversation an exclusive peer
   copy. It retains the bytes, hides context access and reports incomplete cleanup.
5. **Insufficient regrant.** The laptop grants access again and sends its current copy.
   That copy lacks the mini's extra message. Reopening the session would expose material
   outside the new receipt, so the whole receive transaction rolls back. The local
   addition remains retained and hidden.
6. **Permanent forgetting.** The user can still explicitly forget a quarantined source
   within its configured scope. The source disappears and native replay is suppressed.

All 18 checks passed in a freshly installed standalone wheel with StudyLoop absent.
All six evidence disclosures were opened in the browser; the layout fit the viewport
and the rendered result was inspected. The one local withdrawal took 25.363 ms,
including compaction. This is one small fictional run, not a throughput, engine or
answer-quality benchmark.

## Why a generation number is necessary

Imagine a delayed network packet from before a route was withdrawn. Its old sequence
cannot establish that the route is usable now. The same issue occurs with stored
conversations: an old accepted transfer may arrive after permission changes.

The protocol keeps separate incoming and outgoing generations for each peer and scope.
The default is generation zero, granted. A withdrawal advances the generation and
blocks outgoing content. A regrant advances it again. A new offer must match the
current granted generation at both endpoints. Gaps, wrong instances and a first control
that claims to regrant without prior withdrawal are refused.

Retries return durable packets or historical receipts. They do not undo later states.
A historical content receipt means that a transaction committed then; it does not
assert that the same body exists now. Concurrent preparation of the same withdrawal
returns one control at one generation.

The receiver includes all accepted incoming offers for the scope, even if the acceptance
response never reached the sender. That lost-response case matters: the sender's history
can be incomplete while the receiver already knows which IDs must remain withheld.
Outgoing control selection uses outgoing accepted offers, rather than treating the
shared peer/object index as if it recorded only one direction.

## Why withdrawal differs from permanent forgetting

| Operation | Body access | Canonical bytes | Later native replay or transfer |
|---|---|---|---|
| Permanent forget | Denied | Purged, cleanup tracked separately | Same retired identities remain rejected |
| Eligible withdrawal | Denied | Evicted, cleanup tracked separately | Fresh explicit regrant and content required |
| Ambiguous withdrawal | Denied | Retained in quarantine | Regrant alone is insufficient |
| Regrant control | Known withdrawn objects still hidden | Unchanged | Fresh generation-bound content must cover exposure |

Using permanent tombstones for withdrawal would make legitimate later regrant impossible.
Merely stopping new transfers would leave earlier copies readable. Keeping separate
denial state avoids both outcomes.

Quarantine is intentionally conservative. The absence of a known local contribution
does not prove there was none. Nor do two immediate delivering peers prove independent
upstream origins. This stage does not yet offer a general adoption or reconciliation
command. Until that exists, ambiguous copies remain unresolved; that availability cost
is explicit and prevents a production-readiness claim.

## Why trace a reversible purge instead of guessing its dependencies

Deleting a session affects more than its `sessions` row: evidence, observations,
annotations, learner owners, notes, references and indexes may depend on it. A second
handwritten dependency walker could drift away from the real deletion logic.

The preview therefore executes the actual purge inside a SQLite savepoint, observes
its changed canonical rows, then rolls it back. The caller retains its `BEGIN IMMEDIATE`
write transaction through the subsequent decision. Temporary triggers capture the
first old version of each affected primary key into bounded Python memory. They do
not write files, contact peers or mutate the observed row.

Recording the first version matters when a foreign key first sets a field to NULL and
a later step deletes that row. The retention ledger must be checked against the version
that existed before the simulated cascade. Session removal also selects learner IDs
before SET NULL can detach them.

SQLite documents that [ROLLBACK TO restores the savepoint without ending the surrounding
transaction](https://www.sqlite.org/lang_savepoint.html). It permits only
[one writer and gives other connections a committed read snapshot](https://www.sqlite.org/lang_transaction.html).
[TEMP triggers on main tables run only for their creating connection](https://www.sqlite.org/lang_createtrigger.html#temp_triggers_on_non_temp_tables).
The runtime tests exercise those properties rather than inferring them from model votes.

The trace covers the fixed canonical content tables. FTS and embedding copies are
rebuildable derivatives, not independent origin records. This is not a promise to trace
arbitrary future tables or external files. Schema changes must update the lifecycle
contract. The trace stops at 100,000 unique rows or 32 MiB of traced JSON; repeated
changes count toward the byte budget. Exceeding a bound produces an unresolved result,
not a partial proof of exclusive ownership. Journaling mode OFF is rejected.

## Two different checks use the same affected-row trace

**May this peer withdrawal erase the copy?** Every affected canonical row version must
have matching history, and every matching fact must be a committed delivery from this
peer. Unknown history, local capture and another peer contribution prevent that result.

**May this fresh regrant expose a retained copy?** Every affected row that would become
visible must have a contribution bound to this exact new offer. Older contributions do
not establish coverage. The content transaction records the new row facts, checks the
complete retained footprint, and commits releases and its receipt only if that check
passes. Another peer's unresolved denial continues to block exposure.

The second check does not require that the new sender owns every historical origin.
It requires that the fresh packet actually covers the body being reopened. These two
questions must not be collapsed into a single label such as “trusted source.”

## What the failures taught us

The transaction-abort test found a real cleanup defect. SQLite can roll back the whole
transaction rather than only the failing statement. Temporary tables and savepoints
then disappear. Cleanup tried to drop or roll back those missing objects, while the
eviction-mode reset opened a new transaction. That masked the original failure.

Cleanup now respects transaction state, uses `DROP IF EXISTS` and preserves the original
error. A directed test first failed against the earlier code, then passed after the
fix. Real process exits after preview deletion, after actual deletion and before receipt
insertion leave no partial body or permission changes. Foreign-key refusal likewise
rolls back the withdrawal and returns an error rather than a success receipt. That failed
control must be retried after its cause is resolved; it is not recorded as applied.

The runnable lesson found a separate access issue: ordinary visibility filtering also
hid quarantined sessions from explicit forgetting. The fix keeps ordinary body reads
denied, while a narrowly named internal selection checks current scope for the forget
operation and returns only IDs/counts. A test proves wrong-scope forgetting is still
refused and that quarantined source-owned learner records are purged correctly.

Physical cleanup has its own completion boundary. An open reader can retain an older
snapshot, so the first cleanup receipt remains incomplete until that reader closes.
A regrant arriving between compaction and receipt creation also prevents a cleanup
acknowledgement for the older generation.

## Evidence and remaining work

See [OBSERVED-RESULTS.json](OBSERVED-RESULTS.json) for exact run counts and
[COUNCIL-DECISION.md](COUNCIL-DECISION.md) for the reviewers' objections and arbitration.
These tests establish bounded local protocol behavior. They do not establish complete
network synchronization, recovery from arbitrary backups, all hot/full consumers,
independent upstream ownership, or improved semantic answer quality.

SQLite remains canonical because these decisions need exact row identities and one
transaction spanning permission, content and receipts. This stage adds no evidence that
a separate graph engine improves answers. Useful relationships still need correct
direction, source binding and current applicability whichever engine stores them.

The next product step is explicit reconciliation of ambiguous retained copies, with
an inspectable reason and a deliberate choice that does not infer permission from a
model's prose. Then integrate the authenticated coordinator and full-store lifecycle
against the same contract. These are part of the existing delivery goal, not new scope.

## Run the independently preserved stage

Use a fresh output directory and the stage checkpoint in [STAGES.md](../STAGES.md).

```sh
uv run python -m experiments.evidence_context.permission_withdrawal.runner --output /tmp/stage36-demo
open /tmp/stage36-demo/walkthrough.html
uv run pytest packages/agent-session-tools/tests/test_replica_ledger.py experiments/evidence_context/tests/test_permission_withdrawal_lesson.py -q
```

For a fresh standalone runtime:

```sh
uv build --package agent-session-tools --wheel --out-dir /tmp/stage36-wheels
uv venv /tmp/stage36-runtime --python 3.13
uv pip install --python /tmp/stage36-runtime/bin/python /tmp/stage36-wheels/agent_session_tools-0.1.0-py3-none-any.whl
uv run python -m experiments.evidence_context.permission_withdrawal.runner --python /tmp/stage36-runtime/bin/python --require-installed --output /tmp/stage36-installed
```

No provider calls, owner databases, real peers or existing native archives are needed
for this lesson. Earlier stages and saved exercises remain separate.
