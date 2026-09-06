# Scoped transport: design decision after Stage31

Status: **design selected; transport implementation and acceptance remain open**.
This document does not claim that current `session-sync` is protected. Stage31 is
preserved at `f1883d7b`; it changes annotation reads, not transfer behavior.

## Why this is the next delivery boundary

The production inventory found three concrete gaps in `sync.py`:

1. `_seed_remote_db` copies a complete consistent DB snapshot. Consistency does not
   filter work/personal content for the recipient.
2. `_build_dump_queries` exports global learning tables and a row archive independently
   of its selected session IDs. Filtering `messages` cannot protect that derived text.
3. The old table lists omit modern evidence, observation ownership, correction history
   and retirement controls. An annotation-only correction can also be invisible to the
   session-timestamp delta calculation.

This is analogous to distributing routing entries without the policy and withdrawal
messages that give them meaning. A replicated claim needs its ownership, dependencies,
correction history and deletion instructions. Copying its words is insufficient.

## Decision and alternatives

Use a **versioned structured protocol over SSH**, implemented by the installed memory
component on both ends. The receiving component performs parameterized local writes;
it does not execute SQL supplied by its peer. Keep SQLite canonical and the existing
user-facing `session-sync` commands. Do not create a second memory service or database
engine to hide an unresolved replication contract.

| Alternative | Useful property | Reason for this decision |
|---|---|---|
| Extend generated SQL and invoke remote sqlite3 | Reuses established transport | Every evolving ownership/deletion rule would need to be encoded in exported SQL; the recipient has no versioned application-level policy boundary |
| Structured protocol with installed sender and receiver | Both ends can enforce the same typed contract and explicit capabilities | Selected; more importer/identity work, but that work is required for correctness regardless of encoding |
| Physical per-scope DBs plus a coordinator | Stronger accidental separation by file | Adds migration, cross-file dependency and coordinator obligations to a product already using one canonical DB; no measured need yet |

A structured payload is not automatically safe. A sender could still select an excluded
body too early, omit a dependency, or supply a divergent record under a valid ID. Those
are required negative tests, not properties inferred from using JSON.

## Protocol requirements to implement

- Use explicit configured peer identity and allowed scopes. Establish the reciprocal
  identity, protocol/schema support and scope/project-ID agreement **before any body**.
  Machine-local project roots need not match; stable project IDs and scope assignments
  do. Do not overwrite local project policy from a peer's labels.
- Select a dependency-complete representation under the sender's current policy. A
  report with a hidden contributing record cannot travel simply because its native
  session is visible. Apply the recipient's permitted scope on the sender before staging.
- Bind the transfer to its negotiated peers, scopes and access state. Check sender state
  again before exposure and receiver policy again before committing. A stale handshake
  is not a continuing grant. An incompatible or unknown peer must not trigger a SQL or
  whole-DB-copy fallback.
- Import atomically, applying accepted retirement controls before content and rechecking
  immutable bindings, exact citations, owner exclusivity and dependency closure. A
  failed transfer must leave no half-imported current view. FTS is rebuilt/maintained
  locally from accepted content, never copied as independently authoritative data.
- Distinguish immutable history from mutable application projections. Source and report
  identities retain their exact original binding. Preserve proposed relations and
  competing current observations; no timestamp or model-vote rule establishes truth.
- `all` retains the requested phase ordering: attempt every configured push, then every
  configured pull, report failures accurately, and do not report annotation-only work as
  up to date from native session timestamps alone.

## Identity mapping is not conflict resolution

Existing learner rows use mixed keys. `teach_back_scores`, `knowledge_bridges` and
`parked_topics` already have stable `sync_key` values because integer primary keys
collide across machines. `study_notes` has a local integer key. The owned-record layer
has its own UUID plus `(table_name, local_row_id)`. A receiver must map local row keys
and retain stable ownership/dependency identities. It must never rewrite a content
binding simply to make a foreign key fit.

Two independently bound copies of an older row can have different owner UUIDs. Two
edits of an already shared row can have the same identity and different content.
Neither issue is solved by adding UUIDs. The implementation must separately test:

- unrelated local integer collisions;
- the same stable row arriving through two peers;
- repeated identical import;
- divergent ownership for the same stable identity;
- concurrent mutable edits, with neither silently overwritten or declared converged.

An explicit conflict/refusal with both original replicas preserved is safer than an
invented winner. It is also not successful synchronization. The final product must
give a useful, scoped conflict outcome and a recoverable path, and its acceptance
report must distinguish converged records from unresolved edits. No assumption that
conflicts are rare is supported by the present data.

## Deletion routing needs evidence, not a slogan

Current source tombstones store session/deletion IDs and time; observation tombstones
store an ID and time. They do not all retain their former scope. Once a body and its
owner are deleted, a scope predicate cannot recover that information. A new sender
delivery ledger also cannot reconstruct every transfer made by the old SQL tool.

The lifecycle implementation therefore needs durable control identity/ownership and
acknowledged delivery information, plus an explicit treatment for old unrouteable
controls. Investigate receiver-known identity intersection for legacy reconciliation;
do not broadcast every excluded source ID under an unsupported anonymity claim. Hashes
are not automatically private when their inputs are predictable. Do not infer an old
work/personal boundary from the harness or machine.

Reclassification withdrawal and forgetting must remain distinct. A record that moves
out of a peer's allowed scope must be removed there, including dependencies and indexes;
that is not necessarily a permanent source deletion at every other replica. A peer
that was offline cannot receive a revocation before communication resumes. Define and
test the actual guarantee at acknowledgment/reconciliation, rather than promising
instant deletion on an unreachable machine.

Do not declare P08 complete until a stale bundle, native exporter replay, derived-index
rebuild and managed old-backup restore all respect the active retirement controls.
Original external transcripts/backups remain a separately documented retention boundary.

## Concrete implementation and acceptance sequence

1. Inventory current schema identities and ownership/deletion dependencies on disposable
   real-schema databases. Add fail-closed guards to unsafe legacy paths together with
   protocol capability negotiation, so neither side falls back after a mismatch.
2. Implement the scoped exporter/importer with native evidence, exact citations,
   observation history and learner-owner identity mapping. Persist the retirement and
   transfer state needed for replay/withdrawal handling. Do not silently omit eligible
   classes of data while reporting full success.
3. Exercise actual CLI/SSH-process boundaries on isolated replicas, inspecting the staged
   payload for excluded markers. Cover both transfer orders, same-ID divergent content,
   scope changes during export/import, malformed dependency graphs, importer failure,
   identical retries and annotation-only updates.
4. Extend the same production paths through forget/reimport/rebuild/restore and explicit
   per-peer scope withdrawal. Record unresolved legacy-control gaps rather than granting
   them an inferred scope. Re-run council review on the observed results and code.
5. Preserve the runnable stage and its guide, then continue file/live ownership, shared
   setup/doctor/skills, installed startup and the full P01–P15 acceptance audit.

## Council arbitration

The gateway was healthy. Meta (`llama4-maverick`), Qwen (`qwen3-coder`) and Mistral
(`mistral-large-3`) all responded and preferred the structured protocol. Comparison
Markdown/JSON and all raw responses were inspected. Private artifacts are in
`studyloop-private/reviews/2026-09-06-stage32-scoped-transport/design-council`.

Accept the protocol boundary, explicit negotiation, transactional validation and
dependency completeness. Reject Mistral's implication that UUID remapping resolves
mutable conflicts; those are different problems. Treat receiver-ledger deletion
propagation as a proposal to test, not an established guarantee: historical scope and
delivery information is missing. Reject assumptions about rare conflicts or negligible
migration cost. Qwen's suggestion that another ordering guarantee might allow content
before tombstones supplies no mechanism here; retain retirement-first import.

The reviewers did not supply a complete replication algorithm. Their agreement helps
choose the boundary, but the failure traces above must drive the implementation. No
performance, convergence, scope or production-readiness result is claimed from this
design review alone.
