# Implementation Tasks

Every task is TDD: the RED test is named and committed before the production edit. Every task has a
definition of done (DoD) a reviewer can tick from command output. Tasks in the same phase with no shared
files run in parallel in separate worktrees; a task never edits a file another in-flight task owns.
Council review gates are marked ⚖. Decisions cited as D-n are in
`docs/architecture/plan-integration/council/arbitration-plan-round1-2026-09-15.md`.

Branch: `fix/plan-integration-bugs` (RED at `3a4f6b01`). §5 stream: `feat/lexical-or-fallback` off `main`.

## Phase 0 — Bug B (D-1) · owner: agent A · files: `planning/evaluation.py`

- [x] **T0.1** (`c16ffa35`) Honour `record_checkpoint`'s boolean in `evaluate_and_record`; append the existing string
      `"checkpoint not saved to the database"` when it is `False`. Keep the `except` for a raise.
      DoD: `uv run --group dev pytest packages/studyloop/tests/test_planning_evaluation.py -q` → all pass,
      including `test_failed_checkpoint_db_write_is_reported_as_a_warning` and
      `test_successful_checkpoint_db_write_adds_no_warning`. One commit `fix(planning): …`.

## Phase 1 — #8 seam + Bug A (D-2, D-3, D-4) · owner: agent A · files: `planning/{errors,views,intents,application}.py`, `planning/__init__.py`, `cli/_plan.py`, `web/routes/plans.py`, new tests, specs, docs

- [x] **T1.1** (`fd385cd7`) RED `tests/test_plan_application.py`: `test_browse_filters_by_status_deterministically`,
      `test_inspect_unknown_id_raises_plan_not_found`, `test_create_unready_active_raises_plan_not_ready`,
      `test_transition_unready_to_active_raises_plan_not_ready`,
      `test_replace_unready_active_document_raises_and_does_not_persist`,
      `test_create_transition_replace_refusal_payload_is_identical`, `test_replace_preserves_id_and_created`,
      `test_multiple_ready_active_plans_are_valid`, `test_create_duplicate_id_without_overwrite_raises_conflict`,
      `test_prepare_planning_returns_interview_seed_and_summaries`, `test_views_are_immutable_and_json_fresh`.
      DoD: the module imports fail or the tests fail on `3a4f6b01`; committed as `test(planning): RED …`.
- [x] **T1.2** (`c113983c`) Implement `errors.py`, `views.py`, `intents.py` (`CreatePlan`, `ReplaceDocument`,
      `TransitionLifecycle` only), `application.py` (`browse`, `inspect`, `prepare_planning`, `apply` for
      those three intents). Re-export views/intents/errors from `planning/__init__.py`.
      DoD: T1.1 green; `uv run --group dev pyright packages/studyloop/src/studyloop/planning` → 0 errors.
- [x] **T1.3** (`e16340ca`) Migrate `web/routes/plans.py` list/detail/create/PATCH-status/PATCH-markdown to the seam;
      delete the route-local readiness gate; map errors per design §2.
      DoD: `pytest packages/studyloop/tests/test_web_plans.py -q` → **all** pass (the two RED go green, every
      pre-existing assertion unchanged); `rg -n 'readiness\(' packages/studyloop/src/studyloop/web/routes/plans.py`
      → 0 hits.
- [x] **T1.4** (`1d071758`) Migrate `cli/_plan.py` list/show/status to the seam (`_print_readiness` consumes
      `ReadinessView`; exit codes and output unchanged).
      DoD: `pytest packages/studyloop/tests/test_cli_plan.py -q` → all pass, assertions unchanged.
- [x] **T1.5** (`3fe51ebf`) Cross-surface parity RED+GREEN `tests/test_plan_surface_parity.py`:
      `test_activation_refusal_is_identical_via_cli_and_web` (same blockers, no mutation).
- [ ] **T1.6** Delta specs: `openspec/changes/plan-application-seam/specs/{web-ui,cli-surface,
      active-learning-decisions}/spec.md` — requirement "Activation is readiness-gated on every entry path"
      with scenarios for create-with-status, document replacement, status transition. Public doc:
      `docs/study-plans.md` gains an "Activation" paragraph; the "does not do yet" list is **not** edited
      until the corresponding phase ships.
- [x] **T1.7** (gates run at `2ca6bdb0`: `just lint` 0, `just typecheck` 0 errors, plan-filtered pytest 346 passed exit 0,
      full suite 4576 passed / 4 skipped exit 0) Commit in logical steps (`feat(planning): …`, `refactor(web): …`, `refactor(cli): …`,
      `docs(spec): …`). DoD: `just lint && just typecheck` exit 0; `pytest packages/studyloop/tests -q -x
      -k "plan or planning"` exit 0.
- [ ] ⚖ **Council review 1** (`openai.gpt-6-astra`, `grok-4.6`, `qwen3-coder`): diff `3a4f6b01..HEAD`,
      test output, T1.6 spec text. Findings addressed or dispositioned in
      `docs/architecture/plan-integration/council/review-1-*.md` before Phase 2 starts.
- [x] ⚖ **Council review 1 corrections (F1–F6)** — `705ba58b`…`182c82f9` (one commit per finding: F1/F1b
      `705ba58b`, F4 `5326b663`, F3 `b761141b`, F2 `dc7de0be`, F5 `f812500b`, F6 `182c82f9`). F1 (🔴) brought
      `RevisePlan` forward from Phase 2: a compound `PATCH` is one intent, judged on the resulting document,
      persisted in one write; the route holds no store write (`rg 'readiness\(|save_plan'` → 0). F4: identity
      and conflict before readiness on every create door. F3: `inspect` translates the late `load_plan_text`
      store error; CLI `_fail_for` maps all six domain errors and `plan list` goes through it. F2:
      `PlanningBrief` deep-freezes in `__post_init__` and refuses non-JSON leaves. F5: import identity is
      explicit id > frontmatter id > unique title slug; `_load` pins the storage id so no write path files a
      second document under a frontmatter id. F6: `tests/test_plan_recording_failures.py` on an isolated
      checkpoint DB; the history test seeds its own DB. Delta specs (web-ui, cli-surface) and
      `docs/study-plans.md` "Activation" updated to the bounded wording (GPT Astra §3).

## Phase 2 — #9 mutations, assess, guidance, guard (D-3, D-6) · owner: agent A (after Phase 1) · files: as Phase 1 plus `tests/test_architecture_plan_seam.py`

- [x] **T2.1** (`9285260a`, seen failing at collection on `a4862301`: `ImportError` for the seven planned
      symbols) RED: `test_set_milestone_done_is_idempotent`, `test_set_unknown_milestone_raises_invalid_milestone`,
      `test_delete_without_confirm_raises_invalid_field`, `test_delete_retains_checkpoint_history`,
      `test_assess_preview_writes_neither_sink`, `test_assess_db_failure_reports_failed_sink_and_returns_evaluation`,
      `test_assess_document_failure_reported_independently`, `test_malformed_plan_browse_matches_store_list`,
      `test_active_guidance_one_per_active_plan_with_match_keys_and_urgency`, plus
      `test_set_milestone_negative_index_raises`, `test_delete_returns_delete_result_and_document_gone`,
      `test_assess_record_true_reports_both_sinks_saved`, `test_active_guidance_orders_by_plan_id_and_skips_non_active`,
      `test_active_guidance_completion_action_when_all_done`, `test_active_guidance_target_urgency_buckets` (8 cases)
      in `tests/test_plan_application_mutations.py` and `tests/test_plan_guidance.py` (45 tests). Adapter REDs:
      `tests/test_web_plans_seam.py` (`ccfe1d17`, 6 failed / 4 passed on `fed155c1`), `tests/test_cli_plan_seam.py`
      (`8fed6129`, 14 failed / 2 passed on `da0026f9`), `tests/test_mcp_plan_record_seam.py` (`95d74a84`, 3 failed /
      3 passed on `6251e930`). Line-level pyright suppressions on the RED import/access lines only; all removed in GREEN.
      (`test_revise_preserves_id_and_created_and_bumps_updated` landed with the review-1 corrections.)
- [x] **T2.2** (seam `fed155c1`; web `da0026f9`; cli `6251e930`; mcp `45ea1fce`) Implement `SetMilestone`,
      `DeletePlan`, `AssessPlan`/`assess`, `get_active_guidance`
      (`RevisePlan` already shipped in the review-1 corrections, including `learning_record`; the Web field/
      milestone `PATCH` is already on it, and the toggle is a full-list `RevisePlan` to be replaced by
      `SetMilestone`). Migrate remaining CLI (`new|interview|evaluate|milestone`) and Web
      (`POST evaluate`, toggle → `SetMilestone`, `DELETE`) paths. Migrate
      `mcp/tools.py:record_plan_learning` to `RevisePlan(learning_record=…)` — the only `tools.py` edit in
      this phase — and then fold `store.record_learning`'s validation into the seam's one copy.
      **As landed:** `apply` returns `DeleteResult` for `DeletePlan` (typed via `@overload`; `PlanDetailIntent`
      is the rest of the union); `AssessPlan` is not in `PlanIntent` — it goes to `assess()`; `AssessmentResult`
      carries `PlanEvaluationView` (`to_json_dict() == PlanEvaluation.to_dict()`, plus the rendered `markdown`)
      and `db_write` / `document_write` read back from the two Bug-B warning strings — no second checkpoint
      writer, no `PartialRecording`. The learning-record rule's single copy is the **store's**
      (`store.append_learning_record`, pure, on an in-memory plan; `record_learning` wraps it; the seam calls
      it and translates `ValueError` → `InvalidField`) because the store cannot import the seam; the seam's
      duplicate is deleted. `PlanDetail.learning_record_matching(spec)` lets CLI/MCP report `created` without
      a copy of the identity rule. Also migrated: `cli/_exercise.py from-milestone` (→ `inspect`) and
      `cli/_brain.py _selected_plan_ids` (→ `browse`), which the guard would otherwise fail. Deviations from
      design §1, each reported: `PlanApplication.reindex()` (so `plan reindex` needs no index import, D-6);
      `get_active_guidance(*, today=None)` keyword for frozen-clock callers; Web `POST evaluate` body gains
      `db_write` / `document_write` and an honest `recorded` (additive keys, still `201`); CLI `evaluate
      --record` prints the failed sink instead of an unconditional "Checkpoint recorded."; `InvalidMilestone`
      message is `No milestone at index N (plan has M)` so the CLI's pre-seam wording survives `_fail_for`.
      **Owner's eye:** `tests/test_plan_record.py`'s `_seed` fixture now builds a *ready* active plan
      (assertions byte-identical, `git diff 3a4f6b01 -- tests/test_plan_record.py | grep assert` → 0): the old
      fixture made an active plan with no success criteria or milestones directly through the store, and
      the record paths now run the resulting-document gate (F1b), so a legacy/hand-edited active-but-unready
      plan has `plan record` / `plan milestone` / `record_plan_learning` refused with the blockers until it is
      paused or repaired. That is the decided invariant applied consistently — flagged for council review 2,
      not changed unilaterally. Parser finding, out of scope: a concept literally containing `)` (e.g.
      `RANK()`) does not round-trip through the milestone concepts regex.
- [x] **T2.3** (`5693e35c`) Architecture guard `tests/test_architecture_plan_seam.py` per design §6, including the
      planted-violation test. DoD: passes on the real tree; the planted copy fails. **As landed:** 24 tests —
      0 violations over 67 adapter modules; 14 planted bypasses each rejected (module, `import … as`, package
      name, submodule name, mixed, relative, whole-package, dynamic string, nested-in-function); 8 allowed forms
      not flagged; the explicit forbidden-name list is checked against what `studyloop.planning` actually
      re-exports from the four modules. RED evidence: the same checker over the `a4862301` adapters → 21
      violations. `rg` invariant from the brief → 0 hits. `plans_dir` is the one store re-export allowed
      (location resolver, no read/write; `plan path`).
- [x] **T2.4** (`dcb11771`; gates at `5693e35c`: full suite 4730 passed / 4 skipped exit 0 in 5m24s, plan-filtered
      exit 0, `just lint` 0, `just typecheck` 0, `openspec validate plan-application-seam` valid, `--specs --all`
      25 passed) Specs/docs deltas for mutation, idempotent milestone set, confirmed delete, partial
      recording. DoD: `just lint && just typecheck`; `pytest packages/studyloop/tests -q` exit 0. New delta
      `specs/mcp-server/spec.md`; the guidance view is spec'd as **not yet consumed**; `docs/study-plans.md`
      "does not do yet" list untouched (still true until #10).
- [x] **T2.5** Archify: author `docs/architecture/plan-integration/plan-integration.architecture.json`,
      `validate --quality showcase`, `deliver`, `visual-check`; record the delivery receipt here.
      **Receipt** (archify skill 2.17, `node ~/.kiro/skills/archify/bin/archify.mjs`):
      `validate architecture … --quality showcase` → ok, 9/9 artifact checks, composition `showcase` pass,
      0 errors / 0 warnings. `deliver architecture … plan-integration.html --quality showcase` → **ok: true**;
      specification sha256 `173a4bb0d2356aa3e827151a450c83252347bf5a30edadb14e278696701a95ae` (7558 bytes);
      artifact sha256 `20546d4981181eb4000a2afd908b2eb5988a2d46784b4a9b507bda9d59e81ea7` (720967 bytes);
      validation `checksPassed 9/9`, `compositionStatus pass`. `visual-check plan-integration.html` → exit 0,
      `status: pass`, containment ok at 1440×900, 1600×1000, 1920×1080, 2048×1320 (scrollHeight == innerHeight
      at each), light + dark captures written; `visualReview: pending` by contract — perceptual review done by
      the implementing agent from the 1440×900 light capture: balanced, no edge through an unrelated node,
      labels clear after one `labelDx` nudge on `seam-index`. The `.html` and `.visual-check.*` sidecars are
      gitignored and regenerate from the spec. Diagram: CLI / Web routes / MCP tool inside the D-6 guard
      boundary → `PlanApplication` (six operations named on the node and in a card) → `authoring` (readiness
      on the resulting document) / `store` (atomic Markdown write → `study-plans/*.md`) / `evaluation` →
      `index` → `sessions.db`; `now engine` dashed to `get_active_guidance()`, labelled "not yet wired".
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
