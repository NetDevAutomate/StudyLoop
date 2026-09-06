# Stage32: preserve meaning when context crosses a replica boundary

This stage implements and tests the **content phase** of scoped replication in the
standalone memory package. It is not complete synchronization. Its return value says
`sync_complete: false` and `lifecycle_reconciled: false`; the production coordinator,
deletion reconciliation and legacy-state coverage remain required work.

The full objective is unchanged: [GOAL.md](../delivery/GOAL.md). The selected transport
design and its unresolved obligations are in
[SCOPED-TRANSPORT-DESIGN.md](../delivery/SCOPED-TRANSPORT-DESIGN.md). The original
`session-sync` SSH/SQL path has not been replaced by this internal phase yet and must
not be described as protected by it.

## Why a filtered copy was not enough

Stage31 made a useful slice of history cheap to read. Replication adds a different
problem: the receiving database must preserve the meaning of the slice it receives.

The old sync code filters session rows but also exports global learning tables, can
seed a complete DB file, and omits new ownership and correction tables. A report could
arrive without the dependencies that control its visibility. An annotation-only update
could also be missed by a native-session timestamp comparison.

Think of routing updates: receiving a route without its origin, policy and withdrawal
semantics leaves the recipient with an incomplete picture. Here, an observation's text
travels with its declared source/owner dependencies and correction links. That does not
make the text true; it preserves the basis on which a reader can evaluate it.

## A concrete walkthrough

The independently runnable lesson creates a laptop and a mini database with different
local project roots. Both configure the same stable personal project identity. The
laptop also holds a work-only marker. The mini already has an unrelated local learning
record numbered 1.

1. **Negotiate the boundary.** Both configured peers name one another, explicitly allow
   personal scope, and agree on the personal project IDs/scopes. No transcript or report
   body is read to form this announcement. Unknown protocol/schema, mismatched project
   maps, non-reciprocal identities and a duplicated DB instance are refused.
2. **Select the dependencies.** Scope-filtered SQL identifies sessions, messages, native
   sources, assertions with all citations, relations with both endpoints, owned learner
   records and observations with their additional dependencies. Only then are their
   bodies materialized. The excluded work marker is absent from the staged JSON.
3. **Map local IDs.** The incoming learning row was numbered1 on the laptop. It becomes
   row2 on the mini because row1 is already occupied. Its stable owner UUID and report
   binding remain unchanged. The original local row remains intact.
4. **Try a conflicting edit.** The mini changes the shared record while the laptop adds
   another message. The subsequent content phase refuses the divergent record and rolls
   back the whole transaction, including the earlier attempted message insertion.
5. **Revoke the old grant.** Reassigning the laptop session to work invalidates the old
   negotiation. Reusing it returns no new content snapshot.

The probe checks the destination DB/WAL files for the work marker as well as inspecting
the staged JSON. That is concrete evidence for this fixture, not a proof that every
possible input is handled. The broader tests exercise additional invalid graphs,
configuration changes, review bindings and corruption cases.

## Why these implementation choices

| Choice | Why it helps | Cost or limit |
|---|---|---|
| Versioned structured rows instead of incoming executable SQL | The receiver controls allowed tables, columns, ownership checks and parameterized writes | Needs an explicit schema/compatibility contract |
| Stable project IDs with different local roots | The same project can live in different directories without confusing identity and location | Peers must explicitly agree on project IDs/scopes; this phase does not silently create missing project policy |
| Scope supplied internally from reciprocal peer policy | A background transfer is governed by configured peer grants, independent of the interactive agent's current scope | The internal helper is a trusted administrative boundary, not a model-supplied scope override |
| Complete typed dependencies | A visible native owner cannot override an excluded additional learner/source dependency | More joins and validation; legacy unowned classes require separate handling |
| Immutable source/report bindings preserved | A copied report keeps its source identity, text, authority and correction history | Hash checking proves consistency, not semantic truth or remote attestation |
| Stable owner UUID plus local integer remapping | Avoids accidental collisions between two databases' surrogate keys | Does not resolve independently created owners for the same older sync key |
| Identical-or-new import; divergence fails atomically | Avoids overwriting a conflicting interpretation or mutable record | Refusal is not convergence; useful conflict remediation remains required |

SQLite remains the canonical store. This is a richer information contract, not evidence
for a different database engine. No equal-information engine comparison is performed
in this stage.

## Two kinds of identity

A local integer primary key answers “where is this row in this database?” A stable
owner identity answers “which record are we talking about across these replicas?”
The importer uses the second to find or allocate the first. It also preserves existing
`sync_key` fields where present. If an older row with the same sync key was independently
assigned a different owner UUID, import refuses that unresolved identity conflict.

Copying a UUID does not establish that two edits agree. Two versions can share an
identity and disagree in content. The current content phase deliberately refuses this
case and preserves the original replicas; it does not invent a newer-is-truer rule.
Normal native metadata changes can therefore also produce a refusal in this strict
initial phase. The coordinator must provide an appropriate merge/conflict outcome
before full sync can be claimed production-ready.

The receiver also refuses a peer assignment that differs from an existing local
session's ownership, including an unassigned local session. A configured peer cannot
silently reclassify an already present source merely by sending a label.
The same restriction applies to an existing learner row without the incoming owner:
identical contents do not authorize the peer to assign that row a scope.

One schema detail surfaced when testing all six learner tables: SQLite stores the
teach-back total as a generated column. It is readable but cannot be supplied to an
`INSERT`. The projection now explicitly selects the writable schema columns, and the
receiver computes the total from the five original scores. The round-trip test checks
the calculated value as well as all stored fields, ownership and study-parent links.

## What a binding actually proves

The receiver verifies native hashes, exact citation slices, immutable observation
bindings, and review target hashes. Review validation reconstructs the exact assertion
or relation that was reviewed. The result remains an attributed assessment, not proof
that the change was valid.

The council prompted another concrete test. A review can have a valid quote and a
self-consistent hash while its declared input list omits the quoted source. The
receiver now requires every structured review citation and every target source to be
in the observation's declared captured inputs. A packet with that omission is rejected
before received bodies are written.
The sender also checks those declared source IDs in SQL before materializing any
payload. A corrupted local review that cites a work source under a personal-only input
list fails at that earlier boundary. A learner record's native and study-session foreign
keys are additional dependencies; project ownership does not erase them.

Generic report prose can still mention arbitrary things. Such text is not an access
capability, an automatic graph edge or proof that the mentioned source was inspected.
Only the typed dependencies participate in ownership and source lineage. We make no
claim that SQL can detect every semantic reference hidden in prose.

The hash is not a signature. A local owner with permission to rewrite a database could
forge new data and matching hashes. This product's native provenance remains trusted
local-parser provenance. The future SSH coordinator must authenticate the configured
peer and preserve the code-owned import boundary; signing a statement would not by
itself establish that the statement was true.

## Transaction and access checks

Export reads one SQLite snapshot. The announcement includes schema, configured peer
policy, DB instance/access generation and file identity. Export verifies the expected
state before selection and again through a fresh read connection afterward. In-memory
peer configuration changes are checked too.

Import obtains `BEGIN IMMEDIATE`, validates the receiver announcement, checks incoming
table/column shape, ownership and dependency closure, then inserts rows. It checks
bindings and foreign keys and rechecks supplied peer configuration before committing.
Failure rolls back the content phase. Tests inject divergence and configuration changes
after earlier inserts and verify that no partial phase remains committed.

These helpers receive a configuration object. They do not reread an external config
file automatically and do not implement SSH authentication. The coordinator must load
fresh configuration and guard the final exposure/commit boundary. The current content
announcement is not a signed durable grant for offline packet replay.

## Limits that still matter

The snapshot has a 100,000-row and 32 MiB cap. SQL counts/sizes selected bodies before
loading them; the encoded envelope also has a size check. An oversized snapshot fails;
it is not truncated and reported as complete. Temporary selected-ID sets, DB scans,
Python allocation, transport and wall time are not bounded by a hard deadline here.
Large-history incremental transfer still needs measurement and design.

The projection covers the fixed native/evidence/observation/owned-record tables named
in `replication/snapshot.py`. Its `legacy_owned_table_gaps` reports some visible unowned
learner rows; an empty map is **not** a complete legacy-state census. Old global concept,
aggregate, archive and other unowned state is not silently declared safe to transfer.
Full coverage and lifecycle controls must be implemented before a coordinator reports
successful synchronization.

This phase retains selected correction links and annotation retirement markers, but
does not reconcile source/observation/learner deletion histories, scope withdrawal,
exporter reimport, stale peer packets or managed backup restoration. No claim of
forgetting across machines follows from the current round trip. The explicit false
completion fields exist to prevent that mistake while integration continues.

## Run the preserved lesson

Use the Stage32 checkpoint in [STAGES.md](../STAGES.md) and a fresh output directory:

```sh
uv run python -m experiments.evidence_context.replica_content.runner --output /tmp/stage32-demo
open /tmp/stage32-demo/walkthrough.html
uv run pytest packages/agent-session-tools/tests/test_replica_content.py experiments/evidence_context/tests/test_replica_content_lesson.py -q
```

The lesson calls actual package APIs against fictional real-schema databases. It does
not call a new replica CLI or an SSH peer. This distinction is deliberate: those paths
remain to be implemented and tested, not inferred from the helper tests.

For a standalone installed-wheel run, with StudyLoop absent from the child runtime:

```sh
uv build --package agent-session-tools --wheel --out-dir /tmp/stage32-wheels
uv venv /tmp/stage32-runtime --python 3.13
uv pip install --python /tmp/stage32-runtime/bin/python /tmp/stage32-wheels/agent_session_tools-0.1.0-py3-none-any.whl
uv run python -m experiments.evidence_context.replica_content.runner --python /tmp/stage32-runtime/bin/python --require-installed --output /tmp/stage32-installed
```

See [OBSERVED-RESULTS.json](OBSERVED-RESULTS.json) for exact test scope and
[COUNCIL-DECISION.md](COUNCIL-DECISION.md) for arbitration. Next, integrate lifecycle
controls and the real peer/SSH path, guard every unsafe fallback, and prove that a
completed `session-sync all` outcome includes those obligations. The full production
goal remains active.
