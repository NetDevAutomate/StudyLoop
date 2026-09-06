# Stage35: grounding retention labels in capture and delivery

This stage adds historical facts needed to make a future withdrawal decision. It does
**not** yet implement withdrawal or regrant. The complete delivery contract remains
[GOAL.md](../delivery/GOAL.md); the production goal is still active.

The distinction matters. We already know which peer accepted an offer. We did not yet
know whether a particular row was actually delivered by that peer, independently read
from a native archive on this database, or already present with unknown history. Treating
all three as equivalent would make a later deletion decision unreliable.

## Follow the runnable lesson

The five expandable views use two disposable databases and the actual standalone memory
package. An actual Codex-format archive is parsed; real replica APIs copy it; no model
supplies the labels. The installed run verifies that StudyLoop is absent from its child
runtime. Fifteen checks passed.

1. **Native capture.** The laptop's exporter records that it read this exact evidence
   version. That fact belongs to this local database instance. It says nothing about
   whether a user's reported test outcome is correct.
2. **Accepted offer.** The mini registers a prospective transfer. Its contribution count
   is still zero. Agreeing to receive a packet does not mean receiving its contents.
3. **Committed delivery.** The mini commits the rows, their contribution facts and the
   content receipt in one SQLite transaction. It records the laptop as a delivering peer.
   It does not copy the laptop's local-capture label into its own local history.
4. **Changed content.** We deliberately change one message while keeping its row ID.
   Its old receipt no longer describes this version. The new version has unknown history.
5. **Capture and forgetting.** Reading the same native archive on the mini adds a local
   capture fact. This is not a permission grant. Permanent forgetting still removes the
   source and suppresses a later archive replay; body-free history remains.

The small delivery measurement, 25.470 ms, is one fictional local observation. It
excludes SSH, network latency and realistic scale. It is not an engine comparison.

## Three different kinds of grounding

| Question | Evidence that answers it | What remains separate |
|---|---|---|
| Where did this interpretation come from? | Exact native source/version and citation | Whether the interpretation is correct |
| How did this database obtain this version? | Local capture event or committed peer contribution | Whether it may still retain it |
| May this replica retain it now? | Current scope, withdrawal/regrant state and sufficient origin/dependency evidence | Historical delivery alone is insufficient |

Think of network routing: hearing a route from two neighbors does not establish two
independent upstream paths. Both neighbors may be repeating the same advertisement.
Similarly, A → B and A → C → B produce two delivering peers at B, but may have only
one upstream source. The three-replica test deliberately constructs that topology.
The API reports both deliveries and says upstream independence is not established.

That is a substantive restriction on the design-council suggestion to preserve other
peer origins. Preserving genuinely independent permitted copies is desirable. Counting
immediate peers is not sufficient evidence of that independence.

## Why the receipt includes a content fingerprint

An identifier answers which row; it does not necessarily identify which version of a
mutable row. Schema43 therefore records:

| Field | Purpose |
|---|---|
| Table name | Distinguishes otherwise identical keys in different domains |
| Hash of the complete primary key | Handles compound identities without storing raw tag/body key text |
| Hash of the complete semantic row | Prevents another version borrowing this receipt |
| Origin kind | `native_capture`, `peer_commit`, or `unattributed` |
| Contributor | Local database instance or bound peer name |
| Receipt ID | Native evidence identity or accepted offer identity |
| Recorded time | Audit chronology, not a newest-wins authority rule |

Hashes bind bytes; they are not signatures or anonymization. Low-entropy inputs can be
guessed. The ledger avoids copying bodies and source paths, but it remains sensitive
local administrative metadata and is not exported in the scoped content packet.

Two local bookkeeping fields are excluded from row fingerprints: evidence's
`first_captured_at`, and project assignment's `assignment_kind`. The established
content protocol permits those fields to differ locally. Actual evidence content,
project identity, semantic metadata and dependencies remain bound.

Learner tables sometimes allocate integer IDs separately on each database. The fact
must bind to the **receiver's actual row after remapping**, not the sender's integer.
A test occupies integer 1 locally before delivery, then verifies that the incoming
learner record's receipt attaches to its new integer rather than the unrelated row.

## Why uncertainty is retained

Schema43 does not backfill origin labels from age, harness, hostname, source path or the
absence of earlier peer records. Each of those shortcuts could mistake a received
conversation for a local original.

If a previously untracked version is already present when its first recorded peer
delivery arrives, the import records both an `unattributed` fact and the peer's actual
contribution. The new receipt does not erase uncertainty about earlier retention.
Both writes share the content transaction; a failure rolls them back with the body.

Actual native recapture can establish the narrower fact that the exporter read those
evidence bytes locally. It cannot establish that the archive was never copied from
elsewhere, or that recapture is permitted after withdrawal. A future denial gate must
check permission before archive recapture or transfer can become an effective regrant.
Native evidence capture also does not attribute the whole session, its mutable legacy
projection, or locally authored derivative records. Those boundaries remain explicit.

Database replacement is another distinction: moving bytes to a new instance does not
make the prior instance's local receipt a receipt of capture by the new one. Facts are
filtered against the current database instance and peer binding. Managed restore still
needs a policy for retaining current controls before serving restored data.

## A dependency mistake corrected before implementation

An initial test expected forgetting a source-backed observation to delete an independently
project-owned learner record linked to it. That expectation reversed the stored edge.
The observation depends on the learner record; the link does not assert that the record
was derived from the observation. Removing the observation should preserve that record.

The invalid test was corrected, and no reverse deletion trigger was added. The passing
test now protects the intended behavior. The initial council brief containing the wrong
premise was superseded; its failure log is not presented as evidence of a product bug.

This is directly relevant to the original knowledge-graph question: an edge is useful
only when its direction and meaning are established. More relationships would not have
rescued an incorrect interpretation of this one.

## What the tests establish

- Actual native capture creates local evidence facts; received rows do not inherit them.
- Accepted offers create no contribution facts, while committed imports do.
- Old unknown history survives a new matching peer receipt.
- Changed content and replaced database instances cannot borrow prior facts.
- Learner integer remapping preserves the receiver's actual identity binding.
- Native-history write failure, content/receipt failure and process death roll back
  content and its new history together.
- Repeated receipts are idempotent, and permanent source forgetting still works with
  retained history.
- A → B and A → C → B are recorded as two deliveries without an independence claim.

The combined memory/experiment run passed 1,760 tests with one optional skip before
the final helper peer-binding check. The final focused run passed 42 tests, including
that check and the new lesson. Type checking of the changed production modules passed.
The standalone installed lesson passed all 15 checks; its five disclosures were opened
in the browser and the layout fit the viewport. These are component-level results,
not a production-release verdict or a semantic-answer-quality score.

## Why this remains SQLite, and what comes next

These facts need exact identities, indexes and atomic commit with existing source rows.
SQLite already provides those operations in the canonical database. Adding a second
engine here would introduce another transaction boundary without evidence of improved
answers. This stage makes no new engine ranking; the earlier equal-information storage
experiment remains the relevant comparison.

The next protocol work is still withdrawal and fresh regrant, with monotonic generations,
stale-offer suppression, native reimport guards and explicit treatment of unknown or
shared upstream origins. Merely withholding new transfers would leave old copies behind.
Permanently tombstoning every withdrawn source would prevent legitimate later regrant.
Both shortcuts fail different parts of the product requirement.

These origin facts are a prerequisite, not a replacement for that work. Local derivative
authorship, aggregate ledger growth limits, full-store propagation/restore, actual SSH
coordination, shared setup/doctor and complete StudyLoop acceptance remain open.

## Run the preserved stage

Use a fresh output directory. Earlier stages keep their own checkpoints in
[STAGES.md](../STAGES.md).

```sh
uv run python -m experiments.evidence_context.retention_history.runner --output /tmp/stage35-demo
open /tmp/stage35-demo/walkthrough.html
uv run pytest packages/agent-session-tools/tests/test_replica_ledger.py experiments/evidence_context/tests/test_retention_history_lesson.py -q
```

For the standalone installed runtime:

```sh
uv build --package agent-session-tools --wheel --out-dir /tmp/stage35-wheels
uv venv /tmp/stage35-runtime --python 3.13
uv pip install --python /tmp/stage35-runtime/bin/python /tmp/stage35-wheels/agent_session_tools-0.1.0-py3-none-any.whl
uv run python -m experiments.evidence_context.retention_history.runner --python /tmp/stage35-runtime/bin/python --require-installed --output /tmp/stage35-installed
```

No provider calls or owner databases are needed for this lesson. See
[COUNCIL-DECISION.md](COUNCIL-DECISION.md) and [OBSERVED-RESULTS.json](OBSERVED-RESULTS.json).
