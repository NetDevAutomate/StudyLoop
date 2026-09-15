# ADR-0011: Retire the OKF import, the tier-1 ontology and the concept sidecar

**Status:** Accepted · **Date:** 2026-09-10 · **Amended:** 2026-09-15 · **Deciders:** Andy Taylor (owner)
**Supersedes:** the IN-FLIGHT ontology and concept-sidecar claims in
`docs/architecture/session-memory/README.md` (2026-09-09 record) and the corresponding sections of
the branch ADR *0011-claim-centric-learning-memory* on `feat/knowledge-proof` (marked RETIRED there;
its claim-centric learning-memory decision itself stands and will be renumbered when merged).
[Superseded 2026-09-15: that decision was never merged and will not be. Decision: close PR #19 and
tag tip `464a8cdc` as `archive/feat-knowledge-proof-2026-09-15`. Executed 2026-09-15: PR #19 CLOSED at 2026-09-15T22:48:27Z;
tag pushed, resolving to `464a8cdc3d95`. See *Disposition after semantic-layer completion* below. The
sentence is kept as written.]

## Context

Between 2026-09-06 and 2026-09-10 three knowledge layers were built beside the session archive, all on
feature branches and none on `main`:

- a one-way **OKF (Open Knowledge Format) import** of a frozen PoC Markdown corpus;
- a **deterministic tier-1 ontology** (`ontology_*` tables, migration v48), rebuilt from the archive
  at $0 for diagnostics and typed queries, deliberately *not* a recall input;
- a **concept sidecar** (`context_concepts*`, migration v49) written at wind-down via
  `memory_winddown`, read by `memory_recall`.

The owner asked for a data-driven answer to one question: *is any of it used, and does the data say it
serves a purpose?* The answer is recorded in
`docs/architecture/session-memory/receipts/okf-removal-inventory-2026-09-10.md`:

- **No serving path on `main` reads any of it.** `mcp_server.py`: "No embedding or ontology store
  participates." Zero OKF code exists on `main`; the ~5,300 source lines live only on
  `feat/sessionweaver-phase2-retrofit` (PR #18), `feat/knowledge-proof` and `feat/b5-real-corpus`.
- **The value gates were never reached.** G3b "Not reached" (branch ADR-0011:302). The claims layer
  scored 0.129 against a 0.64 bar; **0 of 2,033** imported OKF concepts were citation-bound
  (`legacy-okf-import-report.json`: 2,035 scanned · 2,033 parsed · 0 bound).
- **The ontology did not improve recall.** PoC arm O 0.32; adding it to the fused arm moved recall
  **+0.00**. Its only demonstrated capability was typed inventory questions, which FTS can also answer.
- **The one retrieval win attributed to this work belongs elsewhere.** The +0.142 recall@5 on DEV came
  from replacing the shipped AND-first planner with the learning-memory phrase-token OR planner
  (F-B0-1), not from any knowledge layer (`council-stage4-2026-09-10.md`).
- **The live database holds 66,324 derived `ontology_*`/`context_concept*` rows**, all rebuildable
  from the archive except one non-derived `context_concepts` row, which is exported to prose before
  any `DROP` (Stage 6 of the 2026-09-10 plan, owner-gated).

## Decision

**Remove OKF, the tier-1 ontology and the concept sidecar entirely — code, tests, migrations,
registrations, documentation and (owner-gated) database objects — leaving no functional remnant.**
This clears the ground for a semantic layer designed from the measured data rather than layered onto
an unproven graph.

What is **kept**, because it is not OKF and the data supports it:

- the session archive and its FTS read path (`sessions`, `messages`, `messages_fts`);
- the StudyLoop **learning tier** (`history/concepts.py`, `learning/concept_quality.py`,
  `get_concept_context`) — a first-party concept store with its own contract, unrelated to the sidecar;
- the **evidence tier** and the **learning-memory** claims/evidence store on `feat/knowledge-proof`
  (ADR *claim-centric learning memory*) — the semantic layer's prerequisites;
  [Superseded 2026-09-15: the semantic-layer programme sealed without this store; see the
  disposition section below. The bullet is kept as written.]
- every **receipt** and evidence file that documents the experiment and this decision (immutable
  history, marked RETIRED where it describes the removed layers).

## Consequences

- `git grep -ilE 'okf|ontolog'` over `packages/` on `main` and `feat/knowledge-proof` returns only the
  two pre-existing benign hits (a minified vendor identifier; a learner-topic string in a fixture).
- The 2026-09-09 decision record's IN-FLIGHT ontology/sidecar claims are relabelled **RETIRED** with a
  dated retirement section; the GLOSSARY's ontology terms are kept as historical vocabulary under a
  RETIRED heading; the archify spec loses its `ontology`, `okf` and `concepts` nodes.
- PR #18's non-OKF half (capture/scope safety, MCP registration, planner, sync tests) landed on `main`
  by named cherry-pick (`48900c3d`); the OKF half is dropped; the PR is closed.
- The live-DB `DROP` of the derived tables is a separate, owner-confirmed step with a rehearsed backup
  (`.bak` via `VACUUM INTO`, integrity check, restore rehearsal) — never automatic.
- The 42/91 natural-language questions on which `main`'s shipped `session_search` still crashes
  (FTS5 syntax) is the next retrieval defect to fix; it is independent of this decision.

## Alternatives considered

- **Keep the ontology as a diagnostics-only graph.** Rejected: $0 to build but not $0 to carry —
  two migrations, six tables, a doctor check, a CLI, 5,300 lines and 5,500 test lines for a
  capability (typed inventory) that FTS already provides, with no serving path.
- **Keep the sidecar and fix the citation binding.** Rejected: 0/2,033 bound after the import; the
  writer paraphrased by design, and the claim layer scored 0.129 vs 0.64. Rebuilding it on the
  learning-memory evidence store is the semantic-layer question, not a repair.
- **Leave the code on branches "in case".** Rejected: unmerged branches rot, and the owner's failure
  mode is open tasks that never close. Tips are tagged `archive/*-2026-09-10` before deletion, so
  nothing is lost.

## Disposition after semantic-layer completion (2026-09-15)

Written under council decision D-13
(`docs/architecture/plan-integration/council/arbitration-plan-round1-2026-09-15.md`): this ADR is
amended, not rewritten. Everything above is preserved as written on 2026-09-10; the two statements
that no longer hold are marked superseded in place, and this section records what actually happened.

1. **The claim-centric learning-memory decision was not merged.** The header above says the branch
   ADR's "claim-centric learning-memory decision itself stands and will be renumbered when merged".
   It did not merge and will not: `feat/knowledge-proof` was never integrated into `main`, and its
   pull request is to be closed (item 4). The sentence is superseded; it stays in the header as the
   record of what was expected on 2026-09-10.

2. **The semantic layer did not need that store.** The *Decision* section keeps "the evidence tier
   and the learning-memory claims/evidence store on `feat/knowledge-proof` … — the semantic layer's
   prerequisites". The semantic-layer programme on `main` **sealed on 2026-09-15** without it
   (`docs/architecture/session-memory/receipts/semantic-layer/`; SEALED outcome recorded at
   `a0272a52`: G2 met, G1 not established, owner keeps the `mcp`/`web` hybrid default). No claim or
   evidence table participates in the shipped `session_search`; the "prerequisites" claim is
   superseded **for this shipped programme** — shipping and sealing without the store refutes its
   necessity here, and says nothing about whether claim-centric memory has some other useful role.
   It had already been contradicted by the branch's own data: **Stage F measured the fused claims
   arm at −0.140 recall@5** on DEV, below prose alone (recorded in
   `docs/architecture/session-memory/receipts/okf-removal-inventory-2026-09-10.md`, citing branch
   ADR-0011:301, which also records the fused arm "significantly *worse* than prose alone (−0.154,
   CI95 [−0.252, −0.065]), replicating DEV (−0.140)"). Measured, the tested fused-claims retrieval
   arm reduced recall relative to prose alone; those receipts compare retrieval configurations, not
   storage in isolation, so the loss is attributed to that arm and not to the store as such.

3. **The portable lexical hypothesis was separated from the retired architecture and measured on
   its own.** The historical retrieval improvement cited here (F-B0-1, *Context* above) was a
   planner construction — `plan_prose_query`'s quoted-raw-token `OR` — and owed nothing to the
   storage or ontology layers this ADR retired. It was ported to `main` as
   `agent_session_tools.query_planner.prose_or_query` and pre-registered (D-12) in its narrowest
   position, the `OR` *widen* step of the shipped planner:
   `docs/architecture/session-memory/receipts/lexical/preregistration-2026-09-15.md`. The verdict is
   `docs/architecture/session-memory/receipts/lexical/or-fallback-dev-2026-09-15.md`:
   **`adopt: false`** — DEV macro recall@5 paired delta −0.0101, CI95 [−0.0500, +0.0278]; clause 1
   (CI95 lower bound > 0) failed, the other three clauses held. The shipped planner is unchanged; the
   helper and its tests stay as measured code. The historical +0.142 (*Context*) was measured against
   the Stage 1 planner and a different corpus; that lift was not established for the pre-registered
   narrow widen placement on this DEV corpus against the Stage 2 planner. The two `OR`-only arms the
   same receipt reports were not the registered hypothesis and are neither adopted nor disproved by
   it.

4. **Branch disposition.** Decision: close PR #19 and tag tip `464a8cdc` as
   `archive/feat-knowledge-proof-2026-09-15`. **Executed 2026-09-15**, command output:
   `gh pr view 19 --json state,closedAt` → `CLOSED at 2026-09-15T22:48:27Z`; the disposition comment is on the PR;
   `git rev-parse 'archive/feat-knowledge-proof-2026-09-15^{commit}'` → `464a8cdc3d95b7221dd35de1c0cdcc0a339f46c9`
   (tag pushed). The remote branch `feat/knowledge-proof` remains until the repository ruleset
   ("Default": deletion + non-fast-forward blocked on all branches, no bypass actors) is relaxed
   by the owner; its tip is the tagged commit, so nothing is unreachable meanwhile.
   Once tagged, the branch's primary receipts (Stage F, the claims-layer gate results cited in
   *Context*) stay reachable via that tag. Nothing from the branch is to be deleted from history.
   *(Reworded 2026-09-15 after council review: an earlier wording stated the closure and the tag as
   done before either had been executed.)*

5. **No renumbering.** An ADR that was never merged is not renumbered. `0011` on `main` is this
   document; the branch ADR *0011-claim-centric-learning-memory* remains what it is — a record on an
   archived branch, cited above by its branch line numbers.
