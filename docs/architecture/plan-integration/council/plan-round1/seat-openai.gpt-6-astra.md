## 1. High-level plan

**Ship the correctness seam first, not nine new tools around the existing bypasses.** Treat §5 as an independent experiment, not a dependency of plan integration.

Paths below are repository-relative. New files and test names are proposals; existing files are identified from the brief. No results are claimed beyond the supplied observations.

| Phase | Scope and goal | Parallel ownership | Exit gate |
|---|---|---|---|
| P0: contract | Reconcile ambiguous invariants; add OpenSpec proposal/design/tasks and a ticket-to-test matrix. Inventory existing adapters, serializers and architecture artifacts. | Contract/test owner; §5 experiment owner can start independently. | Reviewed contracts; three supplied failing tests reproduced in a committed receipt. |
| P1: correctness kernel, #8 | Introduce `PlanApplication`, immutable read views, errors and activation validation. Route all three Web activation doors through it. Close Bug B in the shared checkpoint-recording implementation. | Views/read adapters and checkpoint fix can proceed separately after interface agreement. One owner integrates `application.py`. | Supplied RED tests green; public-seam activation matrix and checkpoint failure matrix green. |
| P2: complete seam migration, #9 | Centralize remaining mutations, assessment and planning preparation. Migrate CLI, Web and existing `record_plan_learning`. Enforce adapter boundary. | CLI and Web migrations run concurrently against the fixed seam; MCP learning-record migration is separate. | Architecture guard passes; cross-surface parity, identity preservation and history retention tests pass. |
| P3a: recommendations, #10 | Integrate static guidance once in the decision engine; render additive fields; expose MCP `interleave`. | Guidance/engine owner; renderer owner after JSON contract stabilizes. | Ranking scenarios and frozen no-plan output comparisons pass. |
| P3b: discovery/authoring, #11 | Add six MCP tools. | Concurrent with #10. | Schemas, delegation, errors and real stdio registration pass. |
| P4a: progression, #12 | Add remaining three tools. | After #11; concurrent with #13. | All nine new tools callable through MCP; complete inventory pinned. |
| P4b: launch, #13 | Add planning purpose to existing session launch, resolve persona/protocol, deliver brief. | After #9 and #11; session/backend owner. | Fake-agent PTY/ACP tests pass; no plan or plan binding created. |
| P5: journey, #14 | Add Plans affordance, labels, reconnect and manual fallback. | Backend-independent browser fixtures can be prepared earlier; implementation follows #13. | Browser journey, conflict and single-launch assertions pass. |
| P6: release, #15 | Reconcile specs/docs/installer, integration journeys and evidence. | Reviewers can audit completed slices continuously. Final gate waits for #10, #12 and #14. | Programme checklist in §5 passes. |
| K: lexical experiment | Measure the surviving OR planner, amend ADR-0011, archive PR #19. | Independent of P1–P5. | Adopt/reject receipt, ADR amendment and verified archive tag. |

**Dependency critical path:** #8 → #9 → #11 → #13 → #14 → #15. Without effort estimates, this is a dependency path, not a defensible calendar forecast; #10 could dominate elapsed time.

**Deviations from the parent’s serial delivery order:**

- Pull Bug B forward from #9 into P1. Known silent data-loss reporting should not wait for complete adapter migration.
- #8 must migrate the create/import activation doors—not merely list/inspect/status—or it cannot satisfy its own readiness acceptance criteria.
- Run #10 and #11 concurrently, as their declared edges permit. Do not make Web architect work wait for unrelated ranking work.
- Archive/amend §5 independently. Neither the retired claims store nor a lexical-search adoption decision belongs on the plan programme’s critical path.

Every slice updates its OpenSpec delta, affected normative capability specs and public docs. Structural slices also update an Archify spec and delivered HTML. Prefer the existing relevant diagram; if none covers these boundaries, add `docs/architecture/plan-integration.architecture.json` and adjacent HTML.

## 2. Implementation plan

### P0–P2: one application boundary

Add under `packages/studyloop/src/studyloop/planning/`:

- `application.py`: `PlanApplication`; orchestration and persistence policy.
- `views.py`: frozen, recursively immutable views; tuples rather than mutable lists/dicts.
- `intents.py`: typed explicit changes.
- `errors.py`: transport-independent errors.

Proposed public API:

```python
class PlanApplication:
    def browse(
        self, *, status: PlanStatus | None = None
    ) -> tuple[PlanSummaryView, ...]: ...

    def inspect(
        self,
        plan_id: str,
        *,
        include_markdown: bool = False,
        include_history: bool = False,
    ) -> PlanDetailView: ...

    def prepare_planning(
        self, *, topic: str | None = None
    ) -> PlanningBriefView: ...

    def active_guidance(self) -> ActiveGuidanceView: ...

    def apply(self, change: PlanChange) -> PlanDetailView | DeleteResultView: ...

    def assess(
        self,
        plan_id: str,
        *,
        phase: CheckpointPhase = "start",
        record: bool = False,
        study_id: str = "",
        append_to_plan: bool = True,
    ) -> AssessmentView: ...
```

`PlanChange` is a closed discriminated union, not `action: str` plus arbitrary payload:

| Intent | Required semantics |
|---|---|
| `CreatePlan` | Typed authoring inputs; duplicate refusal; validate requested active result. |
| `RevisePlan` | Typed patch with explicit omitted-versus-cleared fields; supports appending a `LearningRecord` for the existing MCP tool. |
| `ReplacePlanDocument` | Parse Markdown, preserve persisted `plan_id` and `created`, validate resulting document. |
| `TransitionPlan` | Validate lifecycle value and active readiness. |
| `SetMilestone` | `milestone_id`, `complete: bool`; repeated identical request does not rewrite the document. |
| `DeletePlan` | Explicit confirmation; remove canonical document and derived listing, retain checkpoint history. |

Do not expose an `overwrite=True` option to agent tools. Privileged overwrite needs an actual trusted application entry point or capability, not a user-supplied boolean. Until that authority is defined, reject duplicate creation.

Views include:

- `ReadinessView(ready, blockers, nudges)`.
- `PlanSummaryView`, `PlanDetailView`, `MilestoneView`, `CheckpointView`.
- `PlanningBriefView`: ordered interview, evidence seed, existing summaries.
- `ActivePlanGuidanceView`: plan summary, optional next milestone, normalized matching keys, target urgency, energy floor, completion action.
- `ActiveGuidanceView`: all active guidance plus structured malformed-document warnings.
- `AssessmentView`: evaluation, per-sink write outcomes and warnings.
- `PlanReferenceView(plan_id, milestone_id: str | None)`.

Views provide `to_json_dict()` returning fresh JSON-compatible containers. They never contain a mutable `StudyPlan`, `Mission` or `Milestone`.

Domain errors: `PlanNotFound`, `InvalidPlanId`, `PlanConflict`, `InvalidPlanField`, `PlanNotReady`, `InvalidMilestone`. Represent partial recording as a structured result with code `partial-recording`, not an exception that hides the successful sink.

**Bug A implementation, after activation RED tests:**

1. `application.py::apply()` constructs the final candidate document.
2. A single validation path checks status and readiness before any canonical write.
3. `web/routes/plans.py` maps `PlanNotReady` to the existing 422 detail shape.
4. Create, status PATCH and Markdown PATCH all call this path.
5. CLI activation and future MCP creation/status/replacement use the same path.

Do not add three route-local readiness checks.

**Bug B implementation, after sink-outcome RED tests:**

- Change `planning/evaluation.py::evaluate_and_record()` to inspect `record_checkpoint(...)`’s boolean.
- Keep the existing public function compatible so the committed RED test exercises the actual fix.
- Have `PlanApplication.assess()` use the same recording implementation, not a second checkpoint writer.
- Distinguish each sink as `not_requested`, `saved` or `failed`; `record=False` writes neither sink.
- `recording_complete` means every requested sink succeeded. Database failure does not prevent the document attempt, or vice versa.
- On document failure, do not return a view claiming the checkpoint exists in canonical Markdown.
- Keep `index.py::record_checkpoint()`’s boolean contract unless a later independently tested cleanup changes it.

This is deliberately a fix **below and used by the seam**, not a warning synthesized by an HTTP adapter.

Migrate:

- `cli/_plan.py`: all reads/writes and `_print_readiness` consume views.
- `web/routes/plans.py`: payload parsing, HTTP mapping and response rendering only.
- `mcp/tools.py::record_plan_learning`: `RevisePlan`, preserving current public behavior.
- `planning/store.py`: remains internal atomic-document persistence.
- `planning/index.py`: derived-index refresh remains best effort; ordinary refresh failure must not turn a committed canonical write into a reported total failure.

**Done:** activation and recording matrices, unchanged existing CLI/Web assertions, cross-surface contracts and import-boundary test pass.

### P3a: guidance and ranking

Files:

- `planning/application.py`: `active_guidance()`; static extraction only.
- `learning/decision.py::build_now_plan()`: fetch guidance once, preserve existing candidate generation and scoring ownership.
- The defining module of `LearningRecommendation`, located during P0: add typed plan references.
- `cli/_now.py`, `web/routes/now.py`, actual Today/recap templates identified in P0: render new information without introducing ranking.
- `mcp/tools.py::get_next_action`: add `interleave` using exactly the engine’s existing default.

Proposed additive `NowPlan` fields:

```python
active_plans: tuple[PlanSummaryView, ...] = ()
energy_deferred_milestones: tuple[DeferredMilestoneView, ...] = ()
completion_actions: tuple[CompletionActionView, ...] = ()
warnings: tuple[PlanWarningView, ...] = ()
```

Recommendations get `plan_refs: tuple[PlanReferenceView, ...] = ()`, not a single reference: one action may match several plans.

Pipeline:

1. Obtain guidance without scanning session history or invoking a model.
2. Normalize topic/course/concept keys consistently; use equality, not substring matching.
3. Annotate candidate eligibility internally; do not suppress due recall or repair below a plan’s energy floor.
4. Synthesize eligible next-milestone work when unrepresented.
5. Score in the engine using explicit urgency precedence and within-class plan bias.
6. Dedupe, then attach the union of references from represented candidates.
7. Select primary/alternates, reserving an alternate slot for eligible plan-backed work where necessary without displacing a globally more-urgent primary.
8. Sort references by target urgency, descending update time, then plan ID.

Use an explicit legacy path when guidance is empty. The serializer omits empty new keys and recommendation references on that path; otherwise “additive keys” and “byte-identical no-plan output” conflict.

**Done:** frozen-clock no-plan serialized output equals the captured baseline; all ranking fixtures pass; guidance cost receipt records plan count, duration and index/document reads.

### P3b–P4a: MCP adapters

Keep the local `@tool()` registration mechanism in `mcp/tools.py`.

| Tool | Application operation |
|---|---|
| `list_study_plans` | `browse` |
| `get_study_plan` | `inspect` |
| `get_planning_interview` | `prepare_planning` |
| `create_study_plan` | `apply(CreatePlan(...))` |
| `update_study_plan` | `apply(RevisePlan(...))`; explicit import mode can select replacement |
| `set_study_plan_status` | `apply(TransitionPlan(...))` |
| `set_study_plan_milestone` | `apply(SetMilestone(...))` |
| `evaluate_study_plan` | `assess` |
| `delete_study_plan` | `apply(DeletePlan(...))` |

Define schemas and error mappings once. MCP errors must retain machine-readable domain codes and readiness blockers.

**Done:** `test_full_handshake_list_tools_and_call` verifies the original inventory plus nine—35 tools if the stated 26-tool baseline remains unchanged—and representative successful/refused calls. No policy duplication in tools.

### P4b–P5: planning-purpose launch

In `web/routes/session/_start.py`:

```python
class StartSessionRequest(...):
    ...
    purpose: Literal["focus", "planning"] = "focus"
```

Thread:

```text
request purpose
  → existing one-session claim
  → planning brief, only for planning
  → shared purpose-to-persona resolver
  → build_canonical_persona("plan-architect" | existing focus mode, ...)
  → existing PTY or ACP launcher
```

- Modify `agent_launcher.py` to share purpose resolution and context assembly across transports.
- Load `agents/shared/personas/plan-architect.md` and the actual shared protocol located in P0.
- Supply the structured planning brief as context, not by overloading `topic`.
- Treat history-derived evidence as data, not executable instructions.
- Preserve normal focus behavior, including its current fallback; do not silently “fix” that persona mapping in this change.
- On brief/persona preparation failure, release the existing session claim through the existing cleanup path.
- Persist only purpose for labels/reconnect. Do not add a session `plan_id`.
- Reuse existing console and WebSocket. Add “Plan with architect” beside manual creation.
- Update the architect instructions to prefer available MCP lifecycle tools and use CLI fallback.

**Done:** fake-agent PTY and ACP journeys prove correct context, unchanged focus launch, claim cleanup, conflict behavior, reconnect labeling and zero plan creation.

### Contract decisions required before implementation

1. **Readiness during revisions:** apply validation to resulting active documents, including already-active imports. Verify that a fully completed active plan remains valid; otherwise readiness and completion guidance contradict each other.
2. **Urgency/time:** target urgency thresholds, undated-plan ordering, milestone duration and “time permits” are unspecified. Freeze explicit rules and fixtures before scoring changes.
3. **Malformed plans:** ordinary plans must produce deterministic views; malformed files must be skipped or represented consistently with warnings. Do not silently erase warnings in `browse` while guidance reports them. This may require a `PlanListView` envelope instead of the tuple signature above.
4. **Retries:** idempotent boolean milestone setting is defined; checkpoint recording is not retry-safe without a request key. Do not claim all nine tools are idempotent.
5. **Concurrent writes:** atomic replacement is not lost-update prevention. Define conflict behavior before multi-agent authoring; avoid implying `PlanConflict` already solves revision races.

## 3. Test plan

For each row, commit the named RED tests **before** its implementation. Public-seam behavior tests are primary; monkeypatching a public persistence dependency is appropriate for fault injection.

| Phase / module | RED tests and assertions |
|---|---|
| P1, existing `tests/test_web_plans.py` | `test_create_refuses_an_active_status_on_an_unready_plan`: 422 and no active document; `test_markdown_replacement_refuses_an_unready_active_document`: 422 and unchanged existing document. |
| P1, existing `tests/test_planning_evaluation.py` | `test_failed_checkpoint_db_write_is_reported_as_a_warning`: false DB result produces database warning. Retain the successful-write companion unchanged. |
| P1, new `tests/test_plan_application.py` | `test_all_activation_intents_refuse_same_unready_plan`: parametrized create/transition/replacement return the same error code/blockers and leave canonical bytes unchanged; `test_ready_activation_succeeds_through_every_intent`: no route is merely disabled. |
| P1, new `tests/test_plan_application_assessment.py` | `test_recording_reports_each_sink_outcome`: all four success/failure combinations; `test_preview_writes_neither_sink`; `test_unrequested_document_sink_is_not_failure`. |
| P2, `tests/test_plan_application.py` | `test_views_are_recursively_immutable`; `test_revision_and_import_preserve_identity`; `test_repeated_milestone_set_preserves_document_and_updated`; `test_duplicate_create_is_conflict`; `test_delete_requires_confirmation_and_retains_history`; `test_multiple_active_plans_are_valid`; `test_index_failure_preserves_canonical_success`. |
| P2, new `tests/test_plan_surface_equivalence.py` | `test_activation_refusal_matches_cli_and_web`: same code/readiness and no mutation; extend to MCP in #11. `test_record_learning_uses_application_policy`: existing tool cannot bypass validation. |
| P2, new `tests/test_plan_architecture.py` | `test_adapters_cannot_bypass_plan_application`: deliberate forbidden-import fixture fails the guard. |
| P3a, new `tests/test_now_plan_guidance.py` | `test_no_plan_output_matches_legacy_bytes`; `test_matching_due_work_wins_within_urgency_class`; `test_urgent_unrelated_review_beats_new_milestone`; `test_deduped_action_retains_all_plan_refs`; `test_milestone_without_concepts_is_synthesized`; `test_low_energy_defers_milestone_not_due_recall`; `test_completed_plan_emits_only_lifecycle_guidance`; `test_short_topic_does_not_substring_match`; `test_eligible_plan_action_survives_alternate_selection`. |
| P3a, new `tests/test_now_surface_parity.py` | `test_cli_web_mcp_delegate_same_inputs`: same normalized recommendation JSON; `test_mcp_interleave_reaches_engine`; `test_today_and_recap_do_not_rerank`. |
| P3b/P4a, new `tests/test_mcp_plan_tools.py` | `test_plan_tool_schemas_are_typed`; `test_domain_errors_preserve_codes`; `test_milestone_retry_is_idempotent`; `test_assessment_preview_does_not_write`; `test_delete_requires_explicit_confirmation`. Test delegation here, not every readiness rule again. |
| P3b/P4a, existing `tests/test_mcp_stdio_smoke.py` | Extend `test_full_handshake_list_tools_and_call` to pin added inventory and exercise real calls. |
| P4b, new `tests/test_web_planning_session.py` | `test_planning_purpose_delivers_persona_protocol_and_brief`, parametrized PTY/ACP; `test_default_focus_launch_is_unchanged`; `test_planning_launch_creates_no_plan_or_binding`; `test_brief_failure_releases_claim`; `test_second_launch_returns_existing_conflict`; `test_reconnect_retains_purpose`. |
| P5, new `tests/test_web_planning_journey.py` | `test_architect_journey_uses_one_launch_and_socket`; `test_refresh_reconnects_to_labeled_console`; `test_manual_creation_still_works`; `test_structured_launch_error_is_visible`. Use the repository’s browser fixture, not a paid model. |
| P6, new `tests/test_plan_integration_journey.py` | `test_mcp_authored_plan_appears_in_web_now`; `test_web_and_stdio_journeys_run_independently_and_together`: no nested-event-loop error or session-authority duplication. |

### Mechanical architecture guard

Use a static import graph rooted at CLI, Web and MCP adapter modules:

- Parse `Import` and `ImportFrom`; resolve relative imports and aliases.
- Reject direct imports of `planning.store`, mutable planning models and policy/persistence modules such as `index`, `authoring` and `evaluation`.
- Follow local re-exports/wrappers so an adapter cannot bypass the rule through an innocently named helper.
- Stop traversal at the approved application/view/intent/error boundary.
- Reject dynamic imports of restricted planning modules and star imports in relevant adapter code.
- Test the checker against small source-string fixtures covering aliases, relative imports and re-exports.

This architecture test is the explicit exception to “do not test file layout”; it enforces dependency direction, not an incidental directory listing.

### Fixtures and compatibility evidence

Use isolated plan directories and SQLite databases; freeze clocks and IDs. Include:

- Ready/unready draft plans, two active plans, a completed active plan.
- Exact and near-match topics, Unicode/case/whitespace variants, named concepts.
- Undated and overdue targets, tied updates, malformed Markdown.
- All energy levels, short/adequate time budgets, duplicate candidate sources.
- Independent DB and canonical-write failures.
- Fake agent executables capturing launch inputs and transport events.

Preserve existing assertions in `tests/test_web_plans.py`, `tests/test_planning_evaluation.py` and the existing CLI/Now suites found in P0. Record their exact node IDs in the test matrix rather than guessing filenames.

**Byte identity applies to artifacts, not pytest logs:**

- No-plan `NowPlan` JSON and corresponding existing no-plan surface snapshots, with volatile inputs frozen.
- Canonical Markdown after refused changes and idempotent milestone retries.
- `tests/golden/session_search_pre_planner.json` until an explicitly approved lexical adoption changes selected cases.

The MCP inventory is intentionally changed; its old snapshot cannot remain byte-identical.

## 4. §5 plan for `plan_prose_query`

### Pre-register before running comparisons

Add an OpenSpec change and `docs/evidence/prose-query/preregistration.json` recording:

- Repository revision, candidate implementation hashes and query-planning configurations.
- Committed 91-item DEV gold checksum.
- Session DB/corpus census checksum, relevant FTS configuration and gold coverage.
- Metric definitions, bootstrap seed/unit, adoption thresholds and complete arm list.
- A prohibition on tuning against the previously observed SEALED results.

The old SEALED result is historical evidence for prioritization, **not a fresh confirmation set**.

Keep `retrieval.py::plan_query()`’s explicit-FTS routing in front of all natural-language arms. Do not import the retired `learning_memory` package.

### RED tests first

New `tests/test_query_planner_prose_or.py`:

- `test_phrase_or_preserves_short_and_stopword_terms`: branch-compatible token policy.
- `test_phrase_or_quotes_embedded_quotes_and_controls`: quoted FTS terms with Cc/Cs removed.
- `test_phrase_or_drops_non_alphanumeric_tokens`: punctuation-only input cannot generate malformed FTS.
- `test_empty_natural_language_query_is_safe`.
- `test_explicit_fts_bypasses_every_natural_language_arm`: `fts:` and uppercase operators outside quotes remain verbatim.
- `test_quoted_operator_is_not_explicit_syntax`.
- `test_default_planner_matches_pre_planner_golden`: unchanged baseline before adoption.

Then implement a pure planner in `packages/agent-session-tools/src/agent_session_tools/query_planner.py`, leaving explicit routing in `retrieval.py`.

### Arms and evaluation

Do not overload the existing `mcp|cli|hybrid|frozen` transport arms. Add an orthogonal planner-variant configuration in `eval/arms.py` and record it in `eval/receipt.py`.

| Planner variant | Purpose |
|---|---|
| Shipped | Current STOP/short-token filtering; AND then OR only on zero hits. |
| Filtered OR-first | Isolate query-combination order. |
| Unfiltered AND-first | Isolate retention of stopwords/short terms. |
| Unfiltered phrase-token OR | Exact surviving candidate; both differences enabled. |
| Shipped AND, candidate OR fallback | Test the literal fallback commitment. |

The last arm must predefine fallback triggering—initially zero AND hits, matching shipped behavior. An “under five results” trigger would be another pre-registered arm, not a post-hoc adjustment.

Use `gold.py`, `census.py`, `metrics.py` and `receipt.py`. Run all variants against the same fixed corpus and retrieval budget. Report:

- Recall@5 primary; precision@5 and reciprocal rank as guardrails.
- Zero-result rate, result counts and explicit-query invariance.
- Paired confidence intervals over gold-defined query units; cluster dependent queries if the gold contains them.
- End-to-end median/p95 latency under a declared repeated warm/cold protocol.
- Per-query results, not just aggregates.

Proposed adoption rule, frozen before execution:

- Candidate DEV recall@5 improvement ≥ **0.03**, with paired 95% lower bound above zero.
- Precision@5 and reciprocal-rank deltas each ≥ **−0.02**.
- No explicit-query regression.
- p95 latency ≤ **1.10×** baseline under the registered protocol.
- Complete gold coverage; missing corpus evidence invalidates rather than improves the score.

The phrase-token OR arm is the pre-specified primary candidate. Other arms diagnose the effect; promoting a different exploratory winner requires an amended registration and fresh confirmation, not unreported multiple-comparison selection.

If the primary candidate fails, retain shipped behavior and commit the rejection receipt. An honest rejection closes the deferred evaluation obligation.

**Golden protection:** never regenerate the whole golden file to make tests pass. Adoption must include a reviewed per-query semantic diff; explicit cases remain unchanged. Preserve the pre-adoption file as a historical fixture.

### ADR-0011 amendment

Append a dated “Disposition after semantic-layer completion” section to `docs/adr/0011-retire-okf-ontology-and-concept-sidecar.md`:

1. The claim-centric store did not merge; the earlier renumber-on-merge statement is superseded.
2. The semantic-layer programme completed without that store; “prerequisite” is no longer an accurate dependency claim.
3. Cite the Stage F fused-arm regression receipt and the final semantic-layer disposition.
4. Separate the portable lexical planner hypothesis from the retired storage/ontology architecture.
5. Link the new measured adoption/rejection receipt.
6. Preserve historical text with explicit supersession rather than silently rewriting the record.

Before closing PR #19, verify `archive/feat-knowledge-proof-2026-09-15` resolves to its exact tip and that primary receipts remain readable through that tag. Do not merge unrelated branch infrastructure.

## 5. Definition of done

Add a small verification command, proposed as `tools/verify_plan_integration.py`, which executes checks, records exit codes/test counts, hashes artifacts and emits a committed JSON/Markdown receipt. It must not turn missing checks into “not applicable” successes.

Reviewer checklist:

- [ ] `uv run --group dev pytest` exits 0; no new unexplained skips or xfails.
- [ ] `uv run --group dev ruff check .` exits 0.
- [ ] `uv run --group dev ruff format --check .` exits 0.
- [ ] `uv run --group dev pyright` exits 0.
- [ ] `uv run --group dev pre-commit run --all-files` exits 0, including detect-secrets and bandit.
- [ ] The three supplied RED node IDs and all public activation doors pass; rejected operations leave canonical bytes unchanged.
- [ ] Checkpoint sink matrix passes; every partial recording reports the failed sink.
- [ ] Adapter architecture guard passes, including its deliberate-bypass fixtures.
- [ ] Existing CLI/Web behavior tests pass without weakened assertions.
- [ ] Frozen no-plan compatibility tests show zero byte differences.
- [ ] Plan-aware ranking fixtures pass, including multi-plan references, urgent unrelated work, low energy and completed plans.
- [ ] Real stdio handshake lists the original tools plus all nine additions; `get_next_action` accepts `interleave`.
- [ ] Fake-agent PTY/ACP and browser journeys pass independently and together.
- [ ] Launch/reconnect tests show one session authority, one launch, one console/WebSocket, no created plan and no live-session plan ID.
- [ ] A machine-checked matrix maps every #7 invariant and #8–#15 acceptance item to passing test IDs and spec/doc paths.
- [ ] OpenSpec deltas and normative specs agree; strict docs build and the repository’s Archify render/check command pass. P0 must record the actual renderer command; do not invent one.
- [ ] Public docs remove only limitations actually closed; installer/persona/tool descriptions match shipped behavior.
- [ ] §5 has a reproducible adopt/reject receipt, explicit-query invariance output, reviewed golden disposition and ADR amendment.
- [ ] Archive tag target and historical receipt reachability are verified by command output.
- [ ] `git diff --check` passes and `git status --porcelain` is empty after committing evidence.
- [ ] Commit history uses conventional prefixes, separates logical changes and explains why.

Suggested evidence command:

```bash
uv run --group dev python tools/verify_plan_integration.py \
  --output docs/evidence/plan-integration/final.json
```

The receipt identifies the tested source revision and environment. A subsequent evidence-only commit must not masquerade as the source revision tested.

## 6. Risks and pushback

### Scope and contract pushback

- **Six methods can still become a god object.** Keep `PlanApplication` orchestration-focused; retain parsing, authoring, evaluation and indexing internally. Do not create a parallel domain model or generic command bus.
- **“Behavior-preserving migration” has explicit exceptions:** activation bypasses and silent partial recording must change. Document those as intended corrections.
- **One optional plan reference is insufficient.** Multiple matching plans require a typed collection.
- **Unconditional additive JSON contradicts exact no-plan compatibility.** Conditional emission is necessary unless the compatibility requirement is relaxed.
- **“All tools idempotent” is unsupported.** Explicit milestone set is idempotent; assessment append is not. Add request keys only if retry-safe recording is required now.
- **Privileged overwrite lacks an authority model.** Cut it from agent-facing schemas rather than labeling a boolean “privileged.”
- **Atomic writes do not prevent lost updates.** Measure concurrent revision behavior. If multiple authoring agents are supported, specify expected-revision conflict detection and serialization before claiming safe concurrent editing.
- **Index recoverability needs proof.** Test whether `reindex_all()` reconstructs the promised checkpoint history from canonical checkpoints. Deleted-plan history is different: after deletion, retained SQLite history cannot be rebuilt from a missing document. Document backup/retention limits.
- **A fake agent cannot prove model adherence to a one-question protocol.** It can prove correct persona/protocol/context delivery and UI behavior. Do not assert generated prose as deterministic correctness.
- **Do not revive PR #19’s retired architecture** to extract a small lexical function.

### Fan-out and merge control

Likely hotspots:

| Hotspot | Control |
|---|---|
| `mcp/tools.py`: #9, #10, #11, #12 | One integration owner; separate commits for legacy-tool migration, `interleave`, authoring tools and progression tools. |
| `planning/application.py` | Freeze signatures before adapter fan-out; one owner applies implementation changes. |
| `NowPlan` and recommendation serializers | Contract fixture reviewed before CLI/Web/MCP rendering work. |
| Session start/launcher/templates | #13 owns resolver and launch contracts; #14 consumes them without adding another launch path. |
| Normative specs and tool inventory | Slice-specific deltas; serialize promotion to normative specs and inventory updates. |

Sub-agents use separate worktrees, commit only their owned logical changes and provide test-output receipts. Parallel execution is not permission for simultaneous edits to shared files.

### Evidence of learner benefit

Ranking compliance is necessary, not proof of usefulness.

Before broad rollout, pre-register a reversible comparison between legacy and plan-aware ranking for consenting users with active plans. Randomize at user or session level to limit contamination; keep off-plan study available.

Primary measures:

- Fraction of recommendation impressions leading to a started action.
- Fraction of started actions completed within the offered time budget.
- Time from opening Today to starting study.

Guardrails:

- Completion/delay of globally urgent reviews.
- Abandonment, repeated refresh and off-plan override rates.
- Low-energy completion and reported overload.
- Distribution of exposure across multiple active plans.

Use checkpoint or delayed-recall outcomes as longer-term measures, not raw milestone-checkbox counts. Do not equate increased plan adherence with learning.

Commit a privacy-minimized analysis receipt containing denominators, assignment method, confidence intervals and adverse outcomes. Until that exists, release claims should say **“plan-aware guidance with tested ranking rules,” not “better learning.”**
