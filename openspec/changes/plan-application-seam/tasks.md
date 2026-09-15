# Implementation Tasks

Every task is TDD: the RED test is named and committed before the production edit. Every task has a
definition of done (DoD) a reviewer can tick from command output. Tasks in the same phase with no shared
files run in parallel in separate worktrees; a task never edits a file another in-flight task owns.
Council review gates are marked ⚖. Decisions cited as D-n are in
`docs/architecture/plan-integration/council/arbitration-plan-round1-2026-09-15.md`.

Branch: `fix/plan-integration-bugs` (RED at `3a4f6b01`). §5 stream: `feat/lexical-or-fallback` off `main`.

## Phase 0 — Bug B (D-1) · owner: agent A · files: `planning/evaluation.py`

- [ ] **T0.1** Honour `record_checkpoint`'s boolean in `evaluate_and_record`; append the existing string
      `"checkpoint not saved to the database"` when it is `False`. Keep the `except` for a raise.
      DoD: `uv run --group dev pytest packages/studyloop/tests/test_planning_evaluation.py -q` → all pass,
      including `test_failed_checkpoint_db_write_is_reported_as_a_warning` and
      `test_successful_checkpoint_db_write_adds_no_warning`. One commit `fix(planning): …`.

## Phase 1 — #8 seam + Bug A (D-2, D-3, D-4) · owner: agent A · files: `planning/{errors,views,intents,application}.py`, `planning/__init__.py`, `cli/_plan.py`, `web/routes/plans.py`, new tests, specs, docs

- [ ] **T1.1** RED `tests/test_plan_application.py`: `test_browse_filters_by_status_deterministically`,
      `test_inspect_unknown_id_raises_plan_not_found`, `test_create_unready_active_raises_plan_not_ready`,
      `test_transition_unready_to_active_raises_plan_not_ready`,
      `test_replace_unready_active_document_raises_and_does_not_persist`,
      `test_create_transition_replace_refusal_payload_is_identical`, `test_replace_preserves_id_and_created`,
      `test_multiple_ready_active_plans_are_valid`, `test_create_duplicate_id_without_overwrite_raises_conflict`,
      `test_prepare_planning_returns_interview_seed_and_summaries`, `test_views_are_immutable_and_json_fresh`.
      DoD: the module imports fail or the tests fail on `3a4f6b01`; committed as `test(planning): RED …`.
- [ ] **T1.2** Implement `errors.py`, `views.py`, `intents.py` (`CreatePlan`, `ReplaceDocument`,
      `TransitionLifecycle` only), `application.py` (`browse`, `inspect`, `prepare_planning`, `apply` for
      those three intents). Re-export views/intents/errors from `planning/__init__.py`.
      DoD: T1.1 green; `uv run --group dev pyright packages/studyloop/src/studyloop/planning` → 0 errors.
- [ ] **T1.3** Migrate `web/routes/plans.py` list/detail/create/PATCH-status/PATCH-markdown to the seam;
      delete the route-local readiness gate; map errors per design §2.
      DoD: `pytest packages/studyloop/tests/test_web_plans.py -q` → **all** pass (the two RED go green, every
      pre-existing assertion unchanged); `rg -n 'readiness\(' packages/studyloop/src/studyloop/web/routes/plans.py`
      → 0 hits.
- [ ] **T1.4** Migrate `cli/_plan.py` list/show/status to the seam (`_print_readiness` consumes
      `ReadinessView`; exit codes and output unchanged).
      DoD: `pytest packages/studyloop/tests/test_cli_plan.py -q` → all pass, assertions unchanged.
- [ ] **T1.5** Cross-surface parity RED+GREEN `tests/test_plan_surface_parity.py`:
      `test_activation_refusal_is_identical_via_cli_and_web` (same blockers, no mutation).
- [ ] **T1.6** Delta specs: `openspec/changes/plan-application-seam/specs/{web-ui,cli-surface,
      active-learning-decisions}/spec.md` — requirement "Activation is readiness-gated on every entry path"
      with scenarios for create-with-status, document replacement, status transition. Public doc:
      `docs/study-plans.md` gains an "Activation" paragraph; the "does not do yet" list is **not** edited
      until the corresponding phase ships.
- [ ] **T1.7** Commit in logical steps (`feat(planning): …`, `refactor(web): …`, `refactor(cli): …`,
      `docs(spec): …`). DoD: `just lint && just typecheck` exit 0; `pytest packages/studyloop/tests -q -x
      -k "plan or planning"` exit 0.
- [ ] ⚖ **Council review 1** (`openai.gpt-6-astra`, `grok-4.6`, `qwen3-coder`): diff `3a4f6b01..HEAD`,
      test output, T1.6 spec text. Findings addressed or dispositioned in
      `docs/architecture/plan-integration/council/review-1-*.md` before Phase 2 starts.

## Phase 2 — #9 mutations, assess, guidance, guard (D-3, D-6) · owner: agent A (after Phase 1) · files: as Phase 1 plus `tests/test_architecture_plan_seam.py`

- [ ] **T2.1** RED: `test_set_milestone_done_is_idempotent`, `test_set_unknown_milestone_raises_invalid_milestone`,
      `test_delete_without_confirm_raises_invalid_field`, `test_delete_retains_checkpoint_history`,
      `test_revise_preserves_id_and_created_and_bumps_updated`,
      `test_assess_preview_writes_neither_sink`, `test_assess_db_failure_reports_failed_sink_and_returns_evaluation`,
      `test_assess_document_failure_reported_independently`, `test_malformed_plan_browse_matches_store_list`,
      `test_active_guidance_one_per_active_plan_with_match_keys_and_urgency`.
- [ ] **T2.2** Implement `RevisePlan`, `SetMilestone`, `DeletePlan`, `AssessPlan`/`assess`,
      `get_active_guidance`. Migrate remaining CLI (`new|interview|evaluate|milestone`) and Web
      (`POST evaluate`, `PATCH` fields/milestones, toggle → `SetMilestone`, `DELETE`) paths. Migrate
      `mcp/tools.py:record_plan_learning` to `RevisePlan(learning_record=…)` — the only `tools.py` edit in
      this phase.
- [ ] **T2.3** Architecture guard `tests/test_architecture_plan_seam.py` per design §6, including the
      planted-violation test. DoD: passes on the real tree; the planted copy fails.
- [ ] **T2.4** Specs/docs deltas for mutation, idempotent milestone set, confirmed delete, partial
      recording. DoD: `just lint && just typecheck`; `pytest packages/studyloop/tests -q` exit 0.
- [ ] **T2.5** Archify: author `docs/architecture/plan-integration/plan-integration.architecture.json`,
      `validate --quality showcase`, `deliver`, `visual-check`; record the delivery receipt here.
- [ ] ⚖ **Council review 2** (code seats) before Phase 3.

## Phase 3 — parallel: #10 ∥ #11 ∥ #13a (D-5, D-7, D-8, D-10)

### #10 Now guidance · owner: agent B · files: `learning/decision.py`, `cli/_now.py`, `web/routes/now.py`, `learning/recap.py` (render only), tests, golden
- [ ] **T3.1** Capture golden `tests/golden/now_plan_no_active.json` on the pre-#10 tree with frozen clock and
      an isolated empty DB. Commit alone.
- [ ] **T3.2** RED `tests/test_now_plan_guidance.py`: `test_no_active_plans_json_byte_identical_to_golden`,
      `test_matching_due_concept_outranks_unrelated_same_urgency`,
      `test_unrelated_more_urgent_due_outranks_new_milestone`, `test_one_action_keeps_every_matching_plan_ref_ordered`,
      `test_milestone_without_concepts_does_not_substring_match`, `test_energy_below_floor_defers_new_milestone_keeps_repair`,
      `test_fully_checked_active_plan_emits_completion_not_candidate`,
      `test_synthesizes_milestone_when_no_candidate_represents_it`,
      `test_preserves_one_plan_backed_action_when_energy_allows`,
      `test_additive_keys_present_only_when_active_plans_exist`.
- [ ] **T3.3** Implement per design §3. DoD: T3.2 green; `test_learning_decision.py`, `test_web_now.py`,
      `test_recap_mastery_voice.py` unchanged and green.
- [ ] **T3.4** Human rubric receipt (D-16): five frozen scenarios scored "would I do the primary?", committed
      as `docs/architecture/plan-integration/receipts/now-rubric-2026-09-*.md`.
- [ ] **T3.5** (last, after #11 and #12 have landed in `tools.py`) `get_next_action(..., interleave="off")`.

### #11 six MCP tools · owner: agent C · files: `mcp/tools.py` (append only), `tests/test_mcp_plan_tools.py`, mcp-server spec
- [ ] **T3.6** RED `tests/test_mcp_plan_tools.py`: schema present for six; each delegates to a monkeypatched
      `PlanApplication`; `PlanNotReady` → ToolError containing blockers; duplicate create → conflict;
      `set_study_plan_status` retry idempotent; `overwrite` absent from `create_study_plan` schema.
- [ ] **T3.7** Implement. DoD: T3.6 green; `test_mcp_stdio_smoke.py` **unchanged** (still 26) — inventory
      moves in #12.

### #13a purpose + resolver · owner: agent D · files: `web/routes/session/_models.py`, `_start.py` (+ ACP path), `agent_launcher.py`, `tests/test_session_start_purpose.py`
- [ ] **T3.8** RED: `test_planning_purpose_selects_plan_architect_persona_with_brief_section`,
      `test_default_purpose_is_focus_and_unchanged`, `test_planning_launch_creates_no_plan_and_no_plan_id`,
      `test_purpose_persisted_for_reconnect_label`, `test_brief_failure_releases_session_claim`,
      `test_pty_and_acp_use_one_resolver` (fake agent, no paid calls).
- [ ] **T3.9** Implement per design §5 (`brief=` keyword, `persona_mode_for`, purpose on state). DoD: T3.8
      green; `test_web_session_start_pty.py`, `test_web_session_start_acp.py`, `test_web_session_ws.py` green
      and unchanged; `rg -n 'build_canonical_persona\("focus"' packages/studyloop/src/studyloop/web` → 0.
- [ ] ⚖ **Council review 3** across the three streams before Phase 4.

## Phase 4 — parallel: #12 ∥ #13b

- [ ] **T4.1** (#12, agent C) RED: stdio inventory asserts the nine names; `set_study_plan_milestone` retry
      idempotent; `evaluate_study_plan` preview writes nothing, record reports sinks; `delete_study_plan`
      without `confirmed=True` refused. Implement three tools. DoD: `test_full_handshake_list_tools_and_call`
      lists 35.
- [ ] **T4.2** (#13b, agent D) `agents/shared/personas/plan-architect.md`: prefer the nine MCP tools, CLI
      fallback. DoD: persona test asserts the tool names appear in the rendered persona when `purpose=planning`.

## Phase 5 — #14 Web architect journey · owner: agent D

- [ ] **T5.1** RED browser journey next to the existing web session browser tests: one "Plan with architect"
      click → console labelled planning; brief structure present (not wording); refresh keeps label; manual
      New Plan still works; one WebSocket; no plan row created; structured conflict error.
- [ ] **T5.2** Implement the Plans-view affordance + labels. DoD: T5.1 green; `just test-web` green.

## Phase 6 — #15 reconcile and verify

- [ ] **T6.1** `docs/study-plans.md` "does not do yet" list reduced to what is still true; `docs/agent-install.md`
      and installer text name the nine tools and the planning purpose; normative specs promoted from deltas.
- [ ] **T6.2** `scripts/verify/plan_integration.py` per design §8; receipt committed.
- [ ] **T6.3** Combined journey test: planning-purpose web session + MCP plan tool call in one run; no
      nested-event-loop error.
- [ ] ⚖ **Council review 4** (docs seats). Then close #7–#15 with evidence comments.

## §5 stream — `feat/lexical-or-fallback` (D-12, D-13) · owner: agent E · files: `agent-session-tools` only, ADR-0011

- [ ] **S.1** RED `packages/agent-session-tools/tests/test_query_planner_or_fallback.py`:
      `test_explicit_fts_prefix_is_verbatim`, `test_uppercase_operator_outside_quotes_is_verbatim`,
      `test_quoted_operator_is_not_explicit`, `test_prose_or_quotes_embedded_quotes_and_strips_controls`,
      `test_prose_or_drops_tokens_without_alphanumerics`, `test_pre_planner_golden_unchanged`.
- [ ] **S.2** Pre-registration receipt `docs/architecture/session-memory/receipts/lexical/preregistration-2026-09-15.md`
      (corpus sha256, gold sha256, seed, five arms, metrics, thresholds) committed **before** any run.
- [ ] **S.3** Planner-variant arms in `eval/arms.py`; run on DEV gold; write
      `receipts/lexical/or-fallback-dev-2026-09-15.json` + `.md` reading with the adopt/reject field.
- [ ] **S.4** If adopt: one commit swapping only the OR-widen; new golden for the widen path; pre-planner
      golden untouched. If reject: receipt only.
- [ ] **S.5** ADR-0011 amendment per D-13. Tag `archive/feat-knowledge-proof-2026-09-15` at `464a8cdc`, push
      the tag, close PR #19 with the disposition comment, delete the remote branch.
- [ ] ⚖ **Council review §5** (`openai.gpt-6-astra`, `grok-4.6`, `deepseek-r1`) on the receipts.
