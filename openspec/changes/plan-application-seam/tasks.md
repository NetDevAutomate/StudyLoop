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
- [x] ⚖ **Council review 2** (code seats `openai.gpt-6-astra` ACCEPT-WITH-CORRECTIONS, `grok-4.6`
      ACCEPT-WITH-CORRECTIONS, `qwen3-coder` ACCEPT; receipts `council/review2/`) — arbitration
      `docs/architecture/plan-integration/council/review-2-arbitration-2026-09-16.md`, **GATE: ACCEPT**. Every 🔴/🟡
      reproduced by hand before acceptance; one RED + one GREEN commit per finding group: F1 no-op writes
      (`18fb4f0f`/`979956d4`), F2 `assess()` gates the active document (`1381da2e`/`71d24023`), G1
      `ActivePlanGuidance.readiness: ReadinessView` — Grok's headline, the Phase-3 prerequisite (`b671f69e`/`3b23111a`),
      G2 one effective date through `PlanSummary.from_plan(today=)` (`5eef77a0`/`9a066ac0`), G3 `match_keys` sorted
      tuple per D-3 (`cdc4ab39`/`534e9595`), G4 guidance by storage id through `_load` (`68be59aa`/`2707d05f`), G5
      `PlanDetail.learning_record_outcome` replaces the two-read `created` and the `learning_record_matching` helper
      named in T2.2 above (`6bd2654c`/`e62487b3`), G6 toggle retry-safety claim withdrawn (`de745650`), G7 guard catches
      wildcard / whole-package string / transitive bypasses (`181ef517`/`59ab1e23`), G8 both-sinks-failed is "not
      recorded" (`2877ed77`/`def5c561`), G9 lenient row leaves are strings + delete-race pin (`a2923315`/`b65c6718`).
      Rejected: qwen's deviation-12 carve-out (2-of-3 seats keep the gate; pause-or-repair is the recovery path).
      Gate at `b65c6718`: full suite 4769 passed / 4 skipped exit 0; JS 107; `just lint`, `just typecheck` 0;
      `openspec validate` valid; protected files `git diff 3a4f6b01` → 0 lines. Owner decision recorded: deviation 12.

## Phase 3 — parallel: #10 ∥ #11 ∥ #13a (D-5, D-7, D-8, D-10)

### #10 Now guidance · owner: agent B · files: `learning/decision.py`, `cli/_now.py`, `web/routes/now.py`, `learning/recap.py` (render only), tests, golden
- [x] **T3.1** (`848f413b`) Capture golden `tests/golden/now_plan_no_active.json` on the pre-#10 tree with frozen clock and
      an isolated empty DB. Commit alone. **As landed:** captured from the unmodified engine at `0a20a796` (empty
      sessions DB, empty plans dir, empty content roots, no topics/focus, clock `2026-09-16T09:30:00+00:00`);
      sha256 `ec451ce8857c8a72e398e3054e3c060cd3b5b13ecb29e29cba3822dc192503c0`; the byte-equality test in
      `tests/test_now_plan_guidance.py` passed on that tree before any #10 change.
- [x] **T3.2** (`6e5af8c1`, seen 9 failed / 1 passed on `848f413b`: seven `ImportError: PlanRef`, one
      `AttributeError: completion_actions`, one JSON-key assertion; the golden test passed) RED
      `tests/test_now_plan_guidance.py`: `test_no_active_plans_json_byte_identical_to_golden`,
      `test_matching_due_concept_outranks_unrelated_same_urgency`,
      `test_unrelated_more_urgent_due_outranks_new_milestone`, `test_one_action_keeps_every_matching_plan_ref_ordered`,
      `test_milestone_without_concepts_does_not_substring_match`, `test_energy_below_floor_defers_new_milestone_keeps_repair`,
      `test_fully_checked_active_plan_emits_completion_not_candidate`,
      `test_synthesizes_milestone_when_no_candidate_represents_it`,
      `test_preserves_one_plan_backed_action_when_energy_allows`,
      `test_additive_keys_present_only_when_active_plans_exist`. Renderer RED `d2013380` (CLI panel, recap
      `plan_context`, Today-card helpers in `tests/js/today-panel-plan.test.js` 0/6; the two `/api/now`
      end-to-end tests passed already and are kept as the wire-contract proof).
- [x] **T3.3** (engine `0f1b3d08`; renderers `df33690b`) Implement per design §3. DoD: T3.2 green; `test_learning_decision.py`, `test_web_now.py`,
      `test_recap_mastery_voice.py` unchanged and green. **As landed:** `build_now_plan` reads guidance once through
      `PlanApplication().get_active_guidance(today=now.date())` (one clock with `generated_at`); `ENERGY_CAPABILITY`
      3|6|10; `PLAN_RELATED_BIAS = 12` inside today's scoring; synthesised milestone candidate (`conversation`, source
      `study_plan:<id>:<k>`, base 48 + overdue 6 / soon 3) so a plan with no evidence is the primary and
      `starter` is false; refs attached after `_dedupe` in urgency → `updated` desc → id order with the most specific
      milestone per plan; rule-8 swap of the last alternate only; fully-checked plans → `completion_actions`, neither
      matched nor synthesised; an unready active plan (review-2 G1) is matched but never synthesised, with a warning
      naming its blockers; unreadable plans → a warning, never a failure. `NowPlan.active_plans` is a compact
      `ActivePlanSummary` (not `PlanSummary`) so renderers get title, urgency, floor, eligibility and next-milestone
      index without the full summary. Renderers: CLI `Plan:` line + deferral/completion/warning lines + Plan column
      (only when plans exist); recap `plan_context` (omitted when empty; `cli/_recap.py`'s rich panel is outside #10's
      ownership and does not print it yet — `--json` and the spoken form do); Today card `planLabel` /
      `deferredNotes` / `completionNotes` with a notes block that is deliberately not a `.today-card` (the browser
      smoke test addresses the single action card by that class). `web/routes/now.py` needed no edit. Protected files
      `git diff 0a20a796 -- tests/test_learning_decision.py tests/test_web_now.py tests/test_recap_mastery_voice.py`
      → 0 lines.
- [ ] **T3.4** Human rubric receipt (D-16): five frozen scenarios scored "would I do the primary?", committed
      as `docs/architecture/plan-integration/receipts/now-rubric-2026-09-16.md`. **Receipt landed, scoring
      outstanding** (re-opened by council review 3, F6: a scored rubric is the DoD; an unscored one is not
      "done"). **As landed:** the five scenarios were
      run unattended and the emitted primary + rule-cited rationale recorded per row; the owner-verdict column is
      **PENDING** — no human was present and none was faked. Owner action: replace `PENDING` with yes/no + one
      line per row; a `no` on rows 1–4 is a council finding, not an agent edit. Delta spec: the guidance requirement loses "(not yet
      consumed)" and a new requirement "The now engine is plan-aware with tested ranking rules" carries nine
      scenarios. `docs/study-plans.md`: the now/Today "does not do yet" bullet removed; the learner-facing paragraph
      on plan-aware guidance is T6.1's.
- [x] **T3.5** (RED `4f7a5e60` 9 failed / 1 passed → GREEN `c30330a0`; parity-test follow-through `65bde13c`)
      `get_next_action(..., interleave="off")`: a plain string validated against `get_args(InterleaveMode)` with the
      existing `ToolError` wording, cast and forwarded to `build_now_plan`; `@consistent_read` kept; only that function
      moved, inventory still 29. Tests in the new `tests/test_mcp_next_action.py` (10): schema default, adaptive
      forwarded once with `INTERLEAVE_RATIOS[energy]`, invalid values refused with zero engine calls, default == the
      no-plan golden. Landed by council review 3 ahead of #12 (D-8 order note in the arbitration: #12 rebases onto it
      and must not touch `get_next_action`).

### #11 six MCP tools · owner: agent C · files: `mcp/tools.py` (append only), `tests/test_mcp_plan_tools.py`, mcp-server spec
- [x] **T3.6** (`484db041`, RED: 58 failed, every one `KeyError: Tool '<name>' not registered` against the
      23-tool inventory at `0a20a796`; spy-binding harness fix `eb28a1fb`) RED `tests/test_mcp_plan_tools.py`:
      schema present for six with the design §4 signatures; each delegates to a monkeypatched `PlanApplication`
      with the store and index forbidden underneath (`forbid_store`); `PlanNotReady` → ToolError
      `not_ready: plan is not ready to activate: <blockers>` (plus "pause or repair" when already active);
      duplicate create → `conflict:`; every subclass → one prefixed ToolError with the domain error chained;
      `set_study_plan_status` retry idempotent (same intent twice, same view, no error); `overwrite` absent
      from `create_study_plan`'s schema and description (D-4); `learning_record` absent from
      `update_study_plan` (D-9); `get_study_plan(history_limit)` outside 1..200 → `invalid:` with no seam
      call; every response is the view's `to_json_dict()` in fresh containers; real-seam journeys on an
      isolated plans dir + `STUDYLOOP_DB` (discover → inspect → create → revise → activate; refused
      activation writes nothing; duplicate create preserves the document).
- [x] **T3.7** (`5a03b094`) Implement. Six thin adapters appended after `log_struggle`, inside the production
      inventory: one seam call each (`browse` / `inspect` / `prepare_planning` / `CreatePlan` / `RevisePlan`
      / `TransitionLifecycle`), one mapping helper `_plan_tool_error` (`not_found` / `invalid_id` /
      `conflict` / `invalid` / `not_ready` / `invalid_milestone`, `plan_error` as the safety net); no plan
      policy in the adapter. `record_plan_learning` untouched (its inline mapping is a fold candidate for
      #12, the next `tools.py` writer). DoD: T3.6 green (58 passed); `test_mcp_stdio_smoke.py` **unchanged**
      and passing — it pins `>= 21` plus the core names, not an exact count, so the inventory moving 23 → 29
      (the file said 26; the production registry at `0a20a796` had 23) needs no edit here; retarget in #12.
      **Deviations, each reported:** (a) `history_limit` is bounded in the adapter to the Web route's
      `Query(ge=1, le=200)` range — the seam does not bound it and `application.py` is not in #11's file
      set; a seam-level bound would be the single copy (review-1 hazard "Boundary validation").
      (b) `update_study_plan` exposes `status` beside the field edits so repair-and-activate is one
      `RevisePlan` judged once (the F1 contract), while `set_study_plan_status` remains the dedicated
      transition tool; `learning_record` is deliberately not exposed. (c) The "freeze `CreatePlan.answers`"
      hazard lives in `intents.py`, outside #11's ownership; over MCP the `answers` object is decoded per
      call and retained by no one, so no snapshot is taken in the adapter. Delta spec: mcp-server requirement
      "Study-plan discovery and authoring tools" (seven scenarios); `docs/agent-install.md` gains "Study-plan
      tools over MCP" (the six plus `record_plan_learning`, one-line purposes, the refusal kinds);
      `docs/study-plans.md` "does not do yet" untouched (T6.1). **Gates at `bd919d51`+tasks:** `pytest
      packages/studyloop/tests -k "mcp or plan"` 756 passed exit 0; `pytest packages/studyloop/tests -x` 4826
      passed / 4 skipped exit 0 (5m36s); `just lint` clean; `just typecheck` 0 errors; guard 30 passed;
      `test_mcp_stdio_smoke.py -m integration` 2 passed; `openspec validate plan-application-seam` valid
      (`--specs --all` 25 passed); `mkdocs build --strict` clean; `git diff 0a20a796 -- mcp/tools.py` → 0
      deleted lines. Workspace-wide `pytest -q` (both packages): 6941 passed, 16 skipped, **1 failed** —
      `agent-session-tools/tests/test_eval_arms.py::TestPlannerIsolation::test_planner_patch_restored_after_tool_error`,
      order-dependent under the root config (it calls `monkeypatch.undo()` mid-test, which also undoes the
      autouse `STUDYLOOP_CONFIG` fixtures); passes alone and in the package-local run; outside #11's ownership,
      reported for the owner.

### #13a purpose + resolver · owner: agent D · files: `web/routes/session/_models.py`, `_start.py` (+ ACP path), `_dashboard.py` (reconnect default), `agent_launcher.py`, `tests/test_session_start_purpose.py`
- [x] **T3.8** (`0c4d9160`, 11 failed / 1 pin passed on `0a20a796`) RED:
      `test_planning_purpose_selects_plan_architect_persona_with_brief_section`,
      `test_default_purpose_is_focus_and_unchanged`, `test_planning_launch_creates_no_plan_and_no_plan_id`,
      `test_purpose_persisted_for_reconnect_label`, `test_brief_failure_releases_session_claim`,
      `test_pty_and_acp_use_one_resolver` (fake agent, no paid calls) — plus pins
      `test_planning_purpose_keeps_a_user_supplied_subject_as_the_topic`, `test_unknown_purpose_is_rejected_structurally`
      and `TestResolver` (resolver mapping; `brief=` renders its own section; no brief → no section). Fake agent:
      StubTransport factories, binary preflight bypassed through the `STUDYLOOP_TEST_*_CMD` hatch accessor.
- [x] **T3.9** (`4fc51250`) Implement per design §5 (`brief=` keyword, `persona_mode_for`, purpose on state). DoD: T3.8
      green (12 passed); `test_web_session_start_pty.py`, `test_web_session_start_acp.py`, `test_web_session_ws.py`,
      `test_agent_launcher.py` green and unchanged (91); `rg -n 'build_canonical_persona\("focus"' packages/studyloop/src/studyloop/web` → 0.
      **As landed:** `StartSessionRequest.purpose: Literal["focus", "planning"] = "focus"` (the only model change;
      `topic` stays required — a blank topic on `planning` resolves to `"Study plan"`, the label `776a9dc0` pins);
      `agent_launcher.persona_mode_for(purpose: str) -> str` and `build_canonical_persona(mode, topic, energy, *,
      previous_notes=None, brief=None)`, byte-identical output when `brief` is `None`. `_start.py`: one
      `_resolve_persona(body, topic)` both transports call — resolver → optional brief → persona + hash — and the
      `PlanningBrief → Markdown` renderer lives in the route (routes may import `planning.application|views`, D-6
      guard 30 passed). The persona is now built **before** the DB record, so a brief failure returns a structured
      500 (`error`/`purpose`/`repair`) from inside the claim's `try` with nothing to roll back but the reservation.
      `purpose` is always written to the state payload (never inherited through the read-merge-write) and
      `GET /api/session/state` echoes it (`setdefault("purpose", "focus")`, the `origin` pattern); the `201` body
      gains `purpose`. Delta specs: `live-session-orchestration` ("Session purpose"), `agent-adapters` ("Persona
      resolution by purpose"); `openspec validate` valid, `--specs --all` 25 passed. Gates: `-k "session or launcher or
      purpose or persona"` 651 passed; `just lint` clean; `just typecheck` 0 errors.
- [x] ⚖ **Council review 3** (code seats `openai.gpt-6-astra` ACCEPT-WITH-CORRECTIONS, `grok-4.6`
      ACCEPT-WITH-CORRECTIONS, `qwen3-coder` ACCEPT; brief `03ffd5d1`, receipts `council/review3/`) — arbitration
      `docs/architecture/plan-integration/council/review-3-arbitration-2026-09-16.md`, **GATE: ACCEPT**. Every 🔴/🟡
      reproduced by probe before acceptance; one RED + one GREEN commit per finding group: F1 refs on deferred/unready
      plans carry `None` (`05d5d73d`/`64dc09f7`); F4 Rich escape in `studyloop now` — reproduced as a MarkupError crash
      (`2eae3261`/`aafc3eb1`) and one-lined planning-brief values (`68ef8831`/`1a32492d`); F5 `CreatePlan.answers`
      snapshot (`0adc65e3`/`3880e302`); F7 brief-failure test on both transports (`ecbeba41`); F3 seven rule pins + F9
      logged guidance failure (`1dd97f59`/`5ba6be0d`); F8 `recap today` panel prints `plan_context`
      (`7302b883`/`e3859443`); F10 Today card shows warnings (`ac34c63e`/`014d69e3`); F6/F11/F12/F13 docs and spec
      corrections incl. inventory 23→32 and T3.4 re-opened (`c27a34d5`). Rejected: GPT F2 urgency-class redesign
      (pinned as calibration instead), qwen's four 🔴 (misreadings), 503 for a brief failure. Gate at `65bde13c`: full
      suite 4890 passed / 4 skipped exit 0; JS 115; `just lint`, `just typecheck` 0; `openspec validate` valid
      (`--specs --all` 25); protected files `git diff 3a4f6b01` / `0a20a796` → 0 lines; golden sha unchanged; guard 30.

## Phase 4 — parallel: #12 ∥ #13b

- [x] **T4.1** (#12, agent C; RED `1a56b858` 59 failed / 59 passed on `test_mcp_plan_tools.py`, stdio handshake
      "expected exactly 32 tools, got 29" → GREEN `b1e11e78`) RED: stdio inventory asserts the nine names;
      `set_study_plan_milestone` retry idempotent; `evaluate_study_plan` preview writes nothing, record reports sinks;
      `delete_study_plan` without `confirmed=True` refused. Implement three tools. DoD met:
      `test_full_handshake_list_tools_and_call` asserts exactly **32** unique names (`len(listed) == len(set)`),
      the nine design-§4 names, `record_plan_learning` and `CORE_TOOLS` over the real transport (`-m integration`
      2 passed); the in-process twin `test_production_inventory_is_thirty_two_with_the_nine_plan_tools` pins the same.
      **As landed** (`mcp/tools.py`, appended after `set_study_plan_status`): `set_study_plan_milestone(plan_id,
      index, done)` → `apply(SetMilestone)`, `done` a required boolean with no default, forwarded as given (no read,
      no toggle); `evaluate_study_plan(plan_id, phase, study_id="", record=False)` → `assess`, never `apply`, the
      `AssessmentResult` view returned with `db_write`/`document_write` as the seam reports them (a preview is
      `not_requested` on both and byte-identical document + empty `checkpoint_history`; a failed sink is
      `recording_complete: false` + the seam's warning, not a raise), `append_to_plan` not exposed;
      `delete_study_plan(plan_id, confirmed=False)` → `apply(DeletePlan)`, the boolean default kept in the schema
      (not required, no `const`/`enum`), the seam's `InvalidField` → `invalid: deleting '<id>' requires
      confirmed=True`, checkpoint history retained after a confirmed delete. **Fold:** `record_plan_learning`'s
      inline `PlanNotReady`/`PlanError` mapping replaced by `_plan_tool_error` in the same commit, after pinning
      (`test_record_plan_learning_*`: `not_ready:` prefix + blockers + pause-or-repair hint, `not_found:` /
      `invalid_id:` / `invalid:` / `conflict:` / `invalid_milestone:` / `plan_error:`, `__cause__` chained, success
      shape unchanged). This is an **intentional wording change, reported as such**: its refusals gain the kind
      prefix the other eight already carried and `docs/agent-install.md` already promised for every plan tool; the
      pre-fold tests (`test_plan_record.py::TestMcpTool`, `test_mcp_plan_record_seam.py`) match by substring and
      pass unchanged (the delta spec's `record_plan_learning` requirement text updated to the prefixed form).
      `forbid_store` extended first with `authoring.draft_plan/interview_spec/seed_from_history`,
      `evaluation.evaluate_plan/evaluate_and_record` and `index.record_checkpoint`. Delta spec: mcp-server
      requirement "Study-plan progression and deletion tools" (ten scenarios); `docs/agent-install.md` MCP list
      names the nine + `record_plan_learning`, drops "not available yet", documents the already-active hint and the
      failed-sink response. **Deviations, each reported:** (a) the `tools.py` section comment ("Six thin adapters …
      land in Phase 4") was reworded to nine — a stale comment, not code; (b) `_plan_tool_error` stays defined
      after `log_struggle` (no move — "append only"); `record_plan_learning` above it binds the closure late and
      resolves it at call time; (c) `RevisePlan.milestones`/`topics` snapshot recipe (review-3 F5 follow-on) not
      applied — `intents.py` is outside #12's file set and was not touched. **Gates at `b1e11e78`+docs:** `pytest
      packages/studyloop/tests -k "mcp or plan"` 875 passed exit 0; `pytest packages/studyloop/tests -x` **4949
      passed / 4 skipped exit 0** (6m05s); `just lint` clean; `just typecheck` 0 errors; guard
      `test_architecture_plan_seam.py` 30 passed; `test_mcp_stdio_smoke.py -m integration` 2 passed; `openspec
      validate plan-application-seam` valid (`--specs --all` 25 passed); `mkdocs build --strict` clean;
      `git diff 0a20a796 -- mcp/tools.py` → 10 deleted lines, all of them the folded inline mapping and the section
      comment. Inventory 29 → **32**.
- [x] **T4.2** (#13b, agent D; RED `60b14927` 3 failed / 6 pins passed on `205819c7`, GREEN `6ba76757`)
      `agents/shared/personas/plan-architect.md`: prefer the nine MCP tools, CLI fallback. DoD: persona test
      asserts the tool names appear in the rendered persona when `purpose=planning`.
      **As landed:** new `tests/test_plan_architect_persona.py` —
      `test_plan_architect_persona_names_the_nine_mcp_tools_when_purpose_is_planning` (renders
      `build_canonical_persona(persona_mode_for("planning"), …, brief=…)`; all nine design-§4 names; a `CLI fallback`
      section naming `studyloop plan interview|list|show|new|status|milestone|evaluate|record` and no
      `studyloop plan delete`, which does not exist), `test_plan_architect_persona_prefers_mcp_over_cli_ordering`
      (MCP subsection precedes and closes before the fallback; the nine are introduced inside it; no CLI recipe
      inside it), `test_mcp_section_states_the_lifecycle_guards` (readiness-gated activation, `confirmed=True`
      deletion, `record=False` preview vs `record=True`), `test_the_nine_are_the_registry_plus_exactly_what_12_lands`
      (the constant is grounded in `mcp._tool_manager._tools`: six registered, the unregistered set ⊆ #12's three —
      holds before and after that merge), `test_focus_persona_unchanged` (sha256 pin at `205819c7`, fixed session
      paths), `test_projected_personas_match_canonical` ×3 and
      `test_manifest_hashes_regenerate_byte_identically_for_the_architect_projections` (generator's own `hash_file`).
      Persona: one `## Tooling: prefer the plan tools, fall back to the shell` section — `### Plan tools over MCP
      (preferred)` table (nine tools in lifecycle order + `record_plan_learning`; lifecycle line; "missing from the
      inventory → that step's CLI fallback") then `### CLI fallback` table, honest that the CLI has no edit and no
      delete command; Session Start / Creating / End-of-Session protocols name the MCP call with the CLI in
      parentheses; interview text intact. Projections: `agents/claude/study-plan-architect.md`,
      `agents/opencode/study-plan-architect.md` (body after frontmatter), `agents/kiro/study-plan-architect/persona.md`
      (byte copy); `agents/manifest.json` two hashes moved (dates only where the hash moved, as `edc65322`);
      `.secrets.baseline` refreshed for those two digests. Delta spec: `agent-adapters` "Architect persona prefers
      the MCP plan tools" (3 scenarios — the report said 4; corrected by review 4); `openspec validate` valid. **Not changed (owner item):** Kiro's
      `study-plan-architect.json` is pinned to carry no `mcpServers` (`tools: ["@builtin"]`) and Claude's frontmatter
      lists `Read, Write, Grep, Bash` — in those two harnesses the architect takes the CLI fallback until the header
      question is decided (Phase 6 / T6.1 territory).
- [x] ⚖ **Council review 4** (code seats `openai.gpt-6-astra` ACCEPT-WITH-CORRECTIONS, `grok-4.6` ACCEPT,
      `qwen3-coder` ACCEPT; brief `e6d3b7d7`, receipts `council/review4/`) — arbitration
      `docs/architecture/plan-integration/council/review-4-arbitration-2026-09-16.md`, **GATE: ACCEPT**. Every
      🔴/🟡 reproduced by probe before acceptance; one RED + one GREEN commit per finding group: F1 the planning
      brief's delivery budget in `_render_planning_brief` — reproduced unbounded on all three axes (300 plans →
      40 KB; worst probe 15.6 MB), now ≤ 10 rows per evidence key, ≤ 20 plans, ≤ 120 chars per value with counted
      `… and N more` markers, byte-identical within the budget, plus the brief-travels-once pins on both transports
      (`f30ee11b`/`8f9b6011`); F4a/F4b/F5/F6 test-quality pins — exact nine-in-registry (`_LANDING_WITH_12`
      retired), the in-process inventory twin asserting `CORE_TOOLS` and own-name registration, the unbounded
      repo-root walk bounded (probed: 100 000 iterations at `/`), the 23+9 arithmetic (`5e085f0a`); F4c writer
      tripwires beside the byte-equality proofs (`aa463738`); F2/F3/F8–F11 the persona's runtime claims made true
      — table signatures pinned against the registered schemas, `STUDY_ID` provenance and the empty default, the
      ACP `end_session` path, pause-before-repair on an active husk, the active-create gate wording, the install
      doc's parity overclaim and the Kiro/Claude boundary disclosed with T6.1 as owner, the spec's delete shorthand
      and `__cause__` transport note, this T4.2 line's "4 scenarios" → 3 (`5ff48211`/`cf78be40`). Rejected: qwen's
      two misread 🟡 (`markdown` is top-level; `_section` is correct), moving `_plan_tool_error` (append-only),
      GPT's byte budget numbers (shape adopted, per-list caps chosen), F7 D-6 wording (design §6 allows the facade).
      **Decided for Phase 5:** a CLI-started architect's reconnect label derives `purpose` from the persisted
      persona `mode` through `persona_mode_for`, never from the topic; the Kiro/Claude header question is T6.1's
      (a permission-model decision), a documented boundary, not a Phase-4 defect. Gate at `cf78be40`: guard 30;
      inventory 32 (stdio 2 passed); JS 115; `just lint`, `just typecheck` 0; `openspec validate` valid (`--specs
      --all` 25); `mkdocs --strict` clean; protected files `git diff 3a4f6b01` / `0a20a796` → 0 lines; golden sha
      unchanged; full suite `-x` **4987 passed / 4 skipped exit 0** (6m01s).

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
- [ ] ⚖ **Council review 5** (docs seats; review 4 was the Phase-4 code review). Then close #7–#15 with evidence comments.

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
