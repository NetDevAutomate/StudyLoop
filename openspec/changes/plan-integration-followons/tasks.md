# Implementation Tasks — plan-integration follow-ons

Every task is TDD: the RED test is named and committed before the production edit. Every task has a
definition of done (DoD) a reviewer can tick from command output. Items 1–4 touch overlapping files
(`cli/_plan.py`, `web/routes/session/_start.py`, the persona) and run **sequentially in this checkout**, not
fanned out. Council review gates are marked ⚖. Decisions D-A…D-J are the owner's
(`docs/architecture/plan-integration/HANDOFF-2026-09-16.md` §2); D-n are the archived arbitration's.

Branch: `fix/plan-integration-bugs` (handover at `1565234a`). Protected files (byte-identical to their bases —
see `scripts/verify/plan_integration.py`) and the `now` golden
(`tests/golden/now_plan_no_active.json`, sha `ec451ce8857c8a72e398e3054e3c060cd3b5b13ecb29e29cba3822dc192503c0`)
do not move.

## Item 1 — Kiro/Claude MCP grants (D-A) · files: `agents/kiro/study-plan-architect.json`, `agents/kiro/study-mentor.json`, `agents/claude/study-plan-architect.md` (frontmatter only), `agents/manifest.json`, `.secrets.baseline`, `tests/test_install_agent_contracts.py`, `tests/test_plan_architect_persona.py`, `docs/agent-install.md`, `agents/mcp/README.md`, spec delta `agent-adapters`

- [x] **T1.0** (`222db4a3`) Probe receipt `receipts/kiro-agent-tools-probe-2026-09-16.md` (visibility = `tools`, trust =
      `allowedTools` in `@server/tool`; `mcp_server_tool` inert on kiro-cli 2.21.4). DoD: committed with this change.
- [x] **T1.1** (RED `b620a7c8`: 5 failed / 30 passed) RED `tests/test_install_agent_contracts.py`:
      `test_kiro_architect_carries_the_studyloop_server_and_exactly_the_plan_tools` (mcpServers has `studyloop`
      → `studyloop-mcp` and `session-db` → `session-db-mcp`; `tools` ⊇ {`@builtin`, `@studyloop`, `@session-db`};
      the `@studyloop/…` entries of `allowedTools` == exactly `PLAN_TOOL_NAMES` + `LEARNING_RECORD_TOOL`; no bare
      `@studyloop`; no `mcp_studyloop_*` spelling), `test_claude_architect_allowlists_exactly_the_plan_tools`
      (frontmatter `tools:` carries `mcp__studyloop__<name>` for exactly the ten and no other `mcp__` entry),
      `test_installed_kiro_architect_resolves_its_prompt_and_servers` (replaces the `"mcpServers" not in
      definition` assertion at :701 — docstring cites D-A), `test_kiro_mentor_grants_use_the_spelling_the_cli_honours`
      (mentor: `@studyloop` in `tools`; no `mcp_` entry in `allowedTools`; the twelve as `@server/tool`).
      DoD: the four fail on `1565234a`; committed `test(agents): RED …` (pyright: no missing-import suppression needed).
- [x] **T1.2** (GREEN `f5c2057d` mentor fix, `8a80c7d5` grants; targeted run 297 passed) GREEN: edit the three definitions; regenerate `agents/manifest.json`
      (`uv run python scripts/update-agent-manifest.py`, then revert `updated` on entries whose hash did not move —
      the repo's convention); refresh `.secrets.baseline` if hashes moved (`detect-secrets==1.5.0`); update
      `test_kiro_allowlist_and_servers_match_the_instruction` to the working spelling; persona projections stay
      byte-identical (frontmatter is stripped before comparison).
      DoD: `uv run --group dev pytest packages/studyloop/tests -q -p no:cacheprovider -k "install_agent or architect or persona"` exit 0.
- [x] **T1.3** (`fb48a8ba`; `just lint` clean, `just typecheck` 0 errors, full suite 5079 passed / 4 skipped exit 0 in 397 s, `mkdocs --strict` clean, `openspec validate plan-integration-followons` valid) Docs: `docs/agent-install.md` boundary paragraph → the granted state (keeps `purpose=planning`, both
      filenames, no "T6.1"/"Phase 6"; names the `@server/tool` vs `mcp_server_tool` difference); update
      `test_install_docs_disclose_architect_fallback_limits` to pin the granted wording (Kiro, Claude, the ten,
      "prompt" for session-db); `agents/mcp/README.md` `~/.grok/config.toml` → `$GROK_HOME/config.toml` (default
      `~/.grok`) — the `user-settings.json` sentence is correct and stays. Spec delta
      `specs/agent-adapters/spec.md`: ADDED "Harness-launched architects carry the plan tools" (scenarios: Kiro
      shape; Claude shape; nothing else from the server; mentor spelling).
      DoD: `just lint`; `just typecheck`; full suite `-x` exit 0; `openspec validate plan-integration-followons`.

## Item 2 — #14 brain-dump handoff + abandon-mid-flight (D-B) · files: `web/routes/session/{_models,_start}.py`, `web/static/index.html`, `web/static/js/components/{plans-panel,session-timer}.js`, `tests/test_session_start_purpose.py`, `tests/test_web_plan_architect_journey.py`, `tests/js/plan-architect-launch.test.js`, `docs/study-plans.md`, spec deltas `web-ui`, `live-session-orchestration`

- [x] **T2.1** (RED `71a74894`: TestBrainDump 8 failed / 2 guards; JS 4 failed / 13; browser brain-dump test RED, abandon test green on the existing End path) RED `tests/test_session_start_purpose.py`:
      `test_brain_dump_travels_in_the_brief_as_its_own_section_and_is_one_lined` (section `### Learner's brain
      dump` present only with a dump; every dump line rendered as `> …`; a hostile `## …` line cannot open a
      heading), `test_brain_dump_is_absent_from_topic_and_from_session_state` (topic is `Study plan`; text absent
      from the state file and `GET /api/session/state`; on ACP present in `persona_text` only),
      `test_brain_dump_over_limit_is_a_structured_422` (over `BRAIN_DUMP_MAX_CHARS` → 422 before the handler; slot
      free), `test_brain_dump_on_a_focus_start_is_ignored`. JS `tests/js/plan-architect-launch.test.js`: the
      textarea travels in the request detail and the POST body as `brain_dump`, omitted when blank. Browser
      `tests/test_web_plan_architect_journey.py::test_abandoning_a_launch_mid_flight_leaves_no_session_and_no_plan`
      and `::test_brain_dump_reaches_the_architect_persona`.
      DoD: RED committed; the two JS `deepEqual` pins updated in the same commit.
- [x] **T2.2** (GREEN `9a132aea`: purpose tests 35 passed; JS 133/133 clean exit; browser journey 10 passed `-m e2e`; docs contract 25; full suite 5089 passed / 4 skipped exit 0 in 413 s; lint + pyright clean) GREEN: model field (`max_length`), renderer section + containment, UI textarea + wiring, docs
      paragraph (docs/study-plans.md 102–110 and 237–241: the door carries the brain dump to the architect as
      evidence; still never decomposed by StudyLoop), spec deltas (`web-ui` "Plan with architect journey"
      MODIFIED: the POST body's `brain_dump`, the fourth brief section, the abandon scenario, persona-text
      compliance as the CI level per D-B; `live-session-orchestration` "Session purpose" MODIFIED: the dump is
      delivered in the persona only, never persisted).
      DoD: `just test-js`; `uv run --group dev pytest packages/studyloop/tests/test_web_plan_architect_journey.py -m e2e -q`
      (8 + 2 green); full suite; the close-out draft's #14 row flips to met with "one question at a time" recorded
      as persona-text-verified by D-B.

## Item 3 — Husk discovery + `plan repair <id>` (D-C) · files: `planning/{application,views}.py`, `cli/{_plan,_doctor,_study}.py`, `session/start.py`, `agent_launcher.py`, `doctor/*`, `web/routes/plans.py`, `web/static/{index.html,js/components/plans-panel.js}`, `agents/shared/personas/plan-architect.md` (+ projections + manifest), tests, `docs/study-plans.md`, spec deltas `cli-surface`, `web-ui`, `health-and-diagnostics`

- [x] **T3.1** (RED `20546465`: 17 failed / 120 passed across the five files, each on the intended missing symbol /
      unknown command / missing key; ruff + pyright clean; also pins `build_canonical_persona(brief_intro=)` in
      `tests/test_plan_architect_persona.py` and the doctor pass/info/registration rows) RED: `tests/test_cli_doctor.py::test_doctor_names_each_active_but_unready_plan_with_its_blockers`;
      `tests/test_cli_plan_seam.py::test_plan_list_marks_husks` (marker, `--husks`, `--json` `ready`);
      `::test_plan_repair_launches_the_architect_with_the_blockers_in_the_brief_and_creates_nothing` (fake
      `start_session`; brief section `### Repair: what this plan is missing` lists exactly `readiness.blockers`;
      plans dir unchanged); `::test_plan_repair_on_a_ready_plan_says_nothing_to_repair`;
      `::test_husk_refusal_names_both_pause_and_repair`; `tests/test_plan_application.py::test_husks_lists_only_active_unready_plans`;
      `tests/test_web_plans_seam.py::test_plan_list_payload_carries_ready`.
      DoD: RED committed (pyright suppressions only where a symbol does not yet exist).
- [x] **T3.2** (GREEN `b6af366a`: 17 RED → green; six-file targeted run 167 passed; full suite 31 failed / 7211
      passed / 4 skipped / 14 errors in 1009 s, and `comm` over sorted failure ids against a clean `6f05be5b`
      control worktree run in parallel gave item3 − control = ∅ and control − item3 = exactly the 17 REDs, so the
      45 shared ids are the recorded sandbox-environmental class (journeys world guards, acceptance isolation,
      harness matrix live mechanics, brain CLI, one agent-session-tools eval arm); `just lint` clean, `just
      typecheck` 0 errors, `mkdocs build --strict` clean, `openspec validate` valid; hooks passed first time)
      GREEN: `PlanSummary.ready`; `PlanApplication.husks()`; `check_study_plans` doctor checker; `plan list`
      marker/`--husks`; `plan repair`; `brief=` threaded through `study → _handle_start → start_session →
      build_canonical_persona` with the wrapper sentence parameterised; refusal text; sidebar marker in the Plans
      view; persona "Repairing a plan" subsection (projections + manifest regenerated); docs; spec deltas.
      DoD: full suite; `tests/test_architecture_plan_seam.py` green; `just lint && just typecheck`.

## Item 3b — mission writer for `update_study_plan` (design §3b; filed and **built** 2026-09-17) · files: `planning/{intents,application}.py`, `mcp/tools.py`, `web/routes/plans.py`, persona (+ projections + manifest), tests, `docs/{study-plans,agent-install}.md`, spec deltas `mcp-server`, `web-ui`

Why: `readiness()` has three blocker classes but `RevisePlan` had no mission fields, so the architect
`plan repair` launches could not itself repair the commonest husk (no mission) — it dictated the edit. One
writer, through the existing gate, closes that. Kept out of item 3 so item 3's finish stayed countable.

- [x] **T3b.0** (owner, 2026-09-17: "Do 3b first, MCP and Web only") No CLI `plan revise`; the persona's CLI
      fallback row keeps saying no CLI command edits an existing plan's fields.
- [x] **T3b.1** (RED `35d890ef`: 10 failed / 195 passed across `test_plan_application.py` (mission fields on a
      draft flip readiness without activating; `None` leaves as is / list replaces whole; partial mission on a
      husk refused with the one remaining blocker and nothing written, both fields in one call saved once and
      the husk gone; bare string for a list field `InvalidField` before any write — built in the body so a
      missing field fails one test, not collection), `test_mcp_plan_tools.py` (four fields reach `RevisePlan`;
      omitted → `None`), `test_web_plans_seam.py` (PATCH partial → 422 with the remaining blocker; whole → 200,
      list row `ready`; string for a list → 400). Each failure the intended missing field / unexpected kwarg /
      silently-dropped body key.) DoD: RED committed.
- [x] **T3b.2** (GREEN `653e825b`: 10 RED → green; twelve-file run 478 passed; full suite 31 failed / 7219
      passed / 4 skipped / 14 errors in 1023 s, `comm` against a clean `35d890ef` control run in parallel:
      item3b − control = ∅, control − item3b = exactly the 10 REDs, the 45 shared ids byte-identical to the
      item-3 environmental set; `just lint` clean, `just typecheck` 0 errors, `mkdocs build --strict` clean,
      `openspec validate` valid; hooks first time. Contract changes recorded at their pins: schema +4
      properties; the review-5 agent-install pin flipped with its schema premise and was renamed.)
      GREEN: `RevisePlan.why/success/constraints/out_of_scope`, `_revise` applies them before the gate (and the
      duplicate-record short-circuit sees them); MCP + Web expose them; persona repair table drops "no tool
      writes the mission"; docs; spec deltas.
      DoD: full suite; `tests/test_architecture_plan_seam.py` green; `just lint && just typecheck`.

## Item 4 — `plan close <id>` (D-G) · files: `learning/decision.py`, `cli/{_plan,_now}.py`, `learning/recap.py`, `web/static/js/components/today-panel.js`, `web/static/index.html`, persona (+ projections + manifest), tests, `docs/study-plans.md`, spec delta `active-learning-decisions`, `cli-surface`

- [x] **T4.1** (RED `14c8938b`: 7 failed / 57 passed across the two files, each on the intended reason — missing
      `CompletionAction` attributes, `assess` never called, no warning, no `close` command; ruff + pyright
      clean; hooks first time; golden sha unchanged. Seventh test, added on the owner's 2026-09-17 decision:
      `test_completion_review_does_not_count_new_topic_rows_as_due`; the seam launch test's due fixture carries
      a new-topic row beside the real one and still asserts a count of 1. Landed name of the first test drops
      one redundant word: `…_proposes_extend_when_concepts_are_due` — no def line in the repo exceeds 100
      chars.) RED `tests/test_now_plan_guidance.py`:
      `test_completion_action_carries_the_end_assessment_and_proposes_extend_when_plan_concepts_are_due`,
      `test_completion_action_proposes_close_when_the_assessment_is_clean`, `test_completion_never_changes_status`
      (document bytes and status unchanged after `build_now_plan`; no checkpoint row written),
      `test_completion_assessment_failure_keeps_the_sentence_and_warns`; `tests/test_cli_plan_seam.py::test_plan_close_launches_the_architect_with_the_assessment_in_the_brief`,
      `::test_plan_close_on_an_unfinished_plan_refuses`; golden byte-identity test still green.
      DoD: RED committed.
- [ ] **T4.2** GREEN: `CompletionAction` fields + `_PlanContext.build` preview assessment; renderers (CLI `now`,
      recap, Today `completionNotes`); `plan close`; persona "Extend or close" subsection; docs; spec deltas.
      DoD: full suite; golden sha unchanged; `just test-js`.
- [ ] **T4.3** Rubric: add row **4b** to `receipts/now-rubric-2026-09-16.md` (do not overwrite row 4) with the
      re-run primary and the proposal; verdict column `PENDING` for the owner.

## ⚖ Council review 6 — items 1–4

- [ ] **T6.1** Brief `council/brief-review6-2026-09-16.md` (shape of `brief-review4-…`): decisions, the probe
      receipt, diff summary `1565234a..HEAD`, test output, spec deltas, the rubric row 4b.
      `uv run --group dev python scripts/council/run_council.py --brief <brief> --system scripts/council/system-seat.md
      --out docs/architecture/plan-integration/council/review6 --seat openai.gpt-6-astra --seat grok-4.6 --seat qwen3-coder
      --max-tokens 40000 --timeout 1700`. Re-run any seat with empty content or `finish_reason=length` alone
      (keep `*.run1.json`).
- [ ] **T6.2** Reproduce every 🔴/🟡 by probe or RED test before accepting; arbitration
      `council/review-6-arbitration-2026-09-16.md` ends `GATE: ACCEPT|FAIL`; corrections one commit per finding.
- [ ] **T6.3** `scripts/verify/plan_integration.py --out docs/architecture/plan-integration/receipts/verify-<sha>.json`
      → all registered checks ok (29 + the new ones; never skip).

## Item 5 — energy demand + body-doubling floor (D-F) · own round

- [ ] **T5.1** Design §5 reviewed against the code (`_struggle_candidates`, `_score_candidates`, rule 3) — amend if
      the code contradicts it.
- [ ] **T5.2** RED `tests/test_now_plan_guidance.py`: `test_live_struggle_repair_defers_at_low_energy_like_new_work`,
      `test_recovered_repair_stays_eligible_at_low_energy`, `test_body_double_candidate_is_synthesised_when_nothing_plan_related_fits`,
      `test_body_double_is_a_proposal_not_a_filter`, `test_body_double_never_appears_without_an_active_plan`,
      golden byte-identity still green.
- [ ] **T5.3** GREEN: `energy_demand`, rule 3 extension, `body_double` synthesis, CLI/Today "sit with the plan" line.
- [ ] ⚖ **T5.4** Council review 7 (`review7`, same seats or `kimi-k2-thinking` third); arbitration; corrections.
- [ ] **T5.5** Rubric row **3b** for the owner (`PENDING`); the change is archived only after the owner scores 3b and 4b.

## Item 6 — proposals (no code)

- [ ] **T6.4** `docs/architecture/plan-integration/proposals/2026-09-16-context-derived-plan-bias.md` (D-D) and
      `…-overdue-nudge-and-retire.md` (D-E); both become issues at the push step.

## Item 7 — push step (owner present; HANDOFF §3 item 7)

- [ ] **T7.1** Not run unattended. Ruleset D-I; tokens D-J.
