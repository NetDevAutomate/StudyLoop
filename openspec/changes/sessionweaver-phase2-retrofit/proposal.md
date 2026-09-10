## Why

SessionWeaver's Phase 0/1 PoC proved that a tier-1 derived ontology and a
concept-only recall surface measurably improve retrieval (T3: concepts alone
0.64/0.50 recall@5/MRR@5 vs raw-text 0.48/0.38), while fusion with embeddings
moved the score by 0.04 — inside the PoC's own 0.10 noise band — and is not
data-supported. The design council resolved six open questions on this
evidence (`reviews/2026-09-07-phase2-design-council/ARBITRATION.md`, rulings
Q1–Q6): the ontology is derived and never synced (Q1); concepts are typed
`context_assertions` with an additive lifecycle, not a second store (Q2);
retrieval gets one new `memory_recall` surface plus an AND→OR planner on the
existing `session_search`, shipping no embeddings (Q3); wind-down is
code-enforced now with concept content explicitly labelled
model-proposed/unreviewed (Q4); fresh installs classify `memory.default_scope`
explicitly (Q5); and the acceptance gate is a two-level band on the
concept-only PoC row, not the fused one (Q6). A second council
(`reviews/2026-09-07-status-and-completion-plan/COUNCIL/ARBITRATION.md`,
rulings R1–R20) then found that B3 was heading into implementation with the
cross-machine conflict order for replicated concept events unresolved —
exactly the kind of decision ERRATA #5 forbids leaving to timestamp-only
resolution under time pressure (ruling R2) — and that migration safety,
recall-contract equivalence, and the fresh-scope diagnostic sites all needed
naming before code, not after (rulings R6, R7, R10). The exporter data-loss
class this retrofit's benchmark corpus depends on was already fixed and
committed (`7f9a19ec`, "preserve history and contain batch failures"), and
this change's design freezes the corpus-integrity precondition that
benchmark accordingly.

This proposal creates the OpenSpec change that freezes those decisions as
spec and design *before* any Phase B implementation task opens a worktree,
per `EXECUTION-ERRATA.md` execution-order correction #3 ("Create the
StudyLoop OpenSpec change before B1 code") and council ruling R2's
acceptance condition for this stage ("not `spec-check` alone" — an
independent design review must approve the standing order and its test
matrix). Owner decisions O1–O7 in `COMPLETION-PLAN.md` §6 govern how the six
downstream tasks (B1–B6) execute against this design: O3 places the
rescue-branch backlog ports (BL-1..BL-4) inside B5 rather than as a separate
stage; O6 records that the production exporter is presently a pre-fix pin,
so this design's migration and refresh-failure guarantees must hold
regardless of which exporter build is live; O7 confirms the standing
push-after-every-commit authority the downstream tasks rely on. This change
does not itself execute O1, O2, O4 or O5 (SessionWeaver release cadence, the
dead `v0.1.0` release link, the undone StudyLoop `0.3.0` tag, and the
`.gitignore` commit) — those are Stage 0/A7/R-SL housekeeping outside this
capability set.

## What Changes

- Freeze the **cross-machine standing order** for replicated concept
  lifecycle events (`lamport`/`machine_id`/`event_id` triple, append-only,
  duplicate-`machine_id` refused) and the **two-copy test matrix** it must
  pass, so B3 implements a specified algorithm instead of inventing one.
- Freeze two **additive, rollback-documented migrations**: v48 (tier-1
  ontology tables, derived and rebuildable, never present in either sync
  table list) and v49 (the concept sidecar: assertions-linked concepts,
  append-only lifecycle events, the per-database logical clock, and FTS).
- Freeze the **refresh-failure seam**: an incremental ontology rebuild
  invoked from `export_sessions._run_export` must never roll back a
  committed session capture; failure is a structured, non-fatal warning
  recoverable by `session-maint ontology-rebuild`.
- Freeze **seed sanitization**: seeding a fresh remote database strips
  ontology and ontology-build-state rows from the seed snapshot and triggers
  a destination-local rebuild, so derived data is never shipped as if it
  were replicated fact.
- Freeze the **fresh-install scope contract**: generated configuration
  writes `memory.default_scope: unclassified` while the runtime default
  stays unset; every one of the eight currently-unguarded
  `request_scope()` call sites (the source plan mislabels the list "seven") and both MCP servers return one structured
  diagnostic instead of an unhandled `ScopeError`/traceback.
- Freeze the **`memory_recall` contract** (concept-then-session shape,
  citations, provenance, AND→OR planner semantics) that B4 must implement
  byte-for-byte and that B4's acceptance requires be identical, hit-for-hit,
  to the already-measured library call on the same corpus and visibility.
- Freeze the **compatibility seams**: the `ConceptService` public surface is
  fixed before B4 depends on it, and a named cross-stage package/API
  compatibility gate spans A7, B6 and the two release stages.
- Add delta requirements to six existing capabilities
  (`harness-session-memory`, `data-store-and-sync`, `mcp-server`,
  `session-export`, `health-and-diagnostics`, `configuration-and-secrets`)
  describing this target behaviour; no capability is newly created.
- **Preserved, not changed by this or any downstream Phase B task**: no
  embeddings of any kind ship (concept or session); `proposed_state` on
  `context_assertions` remains execution state — concept kind and lifecycle
  standing live only in the sidecar; the tier-1 ontology is never added to
  `SYNC_TABLES` or `GLOBAL_SYNC_TABLES`; the original 25-question gold
  benchmark set is never edited.

## Capabilities

### New Capabilities
_(none — every capability touched by this change already exists under
`openspec/specs/`)_

### Modified Capabilities
- `harness-session-memory`: adds the recall surface, code-enforced wind-down,
  and concept lifecycle guarantees learners and harnesses can rely on when
  retrieving or recording session memory.
- `data-store-and-sync`: adds the v48/v49 migrations, the ontology's
  permanent absence from both sync-table lists, and the frozen cross-machine
  standing order plus two-copy test matrix for replicated concept events.
- `mcp-server`: adds the `memory_recall` and `memory_winddown` tools, the
  AND→OR planner semantics on `session_search`, and the structured
  `ScopeError` diagnostic contract for both MCP servers.
- `session-export`: adds the non-fatal incremental ontology-refresh seam at
  the end of `_run_export` and its recovery contract.
- `health-and-diagnostics`: adds ontology, concept-sidecar, and
  MCP-registration checks with an explicit fatal-vs-report-only
  classification.
- `configuration-and-secrets`: adds the generated-configuration requirement
  that `memory.default_scope` is written explicitly as `unclassified`,
  distinct from the runtime default that stays unset.

## Impact

- **Affected code (future, by task, not part of this change)**: `packages/
  agent-session-tools/src/agent_session_tools/{migrations.py, ontology.py
  (new), context/*, sync.py, export_sessions.py, mcp_server.py,
  config_loader.py}` and `packages/studyloop/src/studyloop/{settings.py,
  parking.py, mcp/tools.py, mcp/server.py}`. This change touches none of
  them — it is spec and design only, entirely under `openspec/`.
- **Affected reference implementation**: the SessionWeaver PoC modules being
  lifted (`ontology.py`, `concept_schema.py`, `concepts.py`, `okf.py`,
  `winddown.py`, `projection.py`, `safe_fs.py`) become the grounding for the
  migrations and the `ConceptService` surface this design freezes; they are
  read, not modified, by this change.
- **Affected downstream work**: Stage B1 (fresh-install scope), B2 (tier-1
  ontology migration), B3 (concept lifecycle + replication), B4 (recall
  surfaces + MCP registration), B5 (real-corpus validation, BL-1..BL-4,
  rescue-branch ports, Council B) and B6 (SessionWeaver re-pin) in
  `COMPLETION-PLAN.md` §3 all depend on this change's design being reviewed
  and approved before their worktrees open.
- **Affected process**: this is the first Phase B artifact; `just
  spec-check` becomes part of `just preflight` for every subsequent Phase B
  task, and an independent design review (not `spec-check` alone, per
  council ruling R2) gates B1's start.
