# Plan integration (#7–#15) — issue close-out DRAFT · 2026-09-16

**Status: DRAFT, not posted.** Written unattended by the Phase-6 agent for the owner to post in the
morning, and refreshed after council review 5 (`GATE: ACCEPT`,
`council/review-5-arbitration-2026-09-16.md`), the verification receipt and the archive. Nothing here has
been sent to GitHub: no issue closed, no comment left, PR #20 untouched. Every claim below names the
test node id, receipt or commit that backs it, and every criterion that is *not* met is marked so
rather than rounded up. Branch `fix/plan-integration-bugs`, local only.

**Shas this draft rests on.** Reconciled tree `e151885c` (review-5 corrections, GREEN); evidence test
`e67f1767`; council-5 artefacts + arbitration `fff69c65`; e2e isolation + first receipt `69740be5`; the
clean receipt `8c4ece48`; the archive `7f836f50`; this refresh is the commit that adds it. The
verification receipt was run on `69740be5`, the last tree whose code, tests, docs and installer text the
receipt's checks read — the three later commits add the receipt itself, move the change into the archive
(promoting the specs) and refresh this draft; `openspec validate --specs --all` and
`just release-consistency-shipped` were re-run on the archived tree (below).

Legend for the evidence column: `T:` a pytest node id or module under `packages/studyloop/tests/`;
`R:` a receipt under `docs/architecture/plan-integration/`; `C:` a commit on the branch;
`S:` a normative spec under `openspec/specs/` (promoted from the change's deltas by
`openspec archive plan-application-seam` at `7f836f50`; the deltas, design and tasks now live in
`openspec/changes/archive/2026-09-16-plan-application-seam/`).

Receipts that back several issues at once:

- `R: receipts/verify-69740be5.json` — the D-15 verification receipt: **29 required checks, 29 ok,
  exit 0** (`C: 8c4ece48`, written by `scripts/verify/plan_integration.py`, never edited). Beside it,
  `R: receipts/verify-fff69c65.json` — the first real run on the reconciled tree, **27/29, ok=false**,
  kept as evidence (`C: 69740be5`): `browser-journey-e2e` lost one test of eight to a 20 s start-POST
  timeout caused by the web app's background query-encoder warm under machine load ≈ 7.5 (A/B: warm on
  5/5 module runs fail, warm off 3/3 pass; the fixture now runs its isolated server with
  `STUDYLOOP_RETRIEVAL_MODE=lexical`), and `full-suite-studyloop` was 5042 passed / 0 failed with exit 1
  because the C8/R-49d guard saw another agent's `log_topic` append to the real
  `~/.config/studyloop/session-topics.md` mid-run. Neither was a plan-integration defect; the earlier
  run at `3159efe0` (28/28, discarded for empty node counts) is described in the archived `tasks.md` T6.2.
- `R: receipts/uat-plan-journeys-a69867bf.redacted.json` — the UAT strict **mechanics** sign-off over
  the three plan doors (browser architect launch, real stdio MCP lifecycle, Today with an active plan),
  3/3 required cells, fake agent, no criterion graded; private bundle digest `sha256:bdab3a53…`.
- `R: council/review-{1,2,3,4}-arbitration-*.md` — four code-review gates, all `GATE: ACCEPT`, every
  🔴/🟡 reproduced before acceptance; `R: council/review-5-arbitration-2026-09-16.md` — the docs/spec
  review: GPT REJECT → sixteen finding groups landed, Grok and kimi ACCEPT-WITH-CORRECTIONS,
  `GATE: ACCEPT` with T3.4b (the D-16 verdicts) carried open.

---

## #8 — Plan integration 1: Centralize reads and activation

| Acceptance criterion | Met | Evidence |
|---|---|---|
| Plan summaries and details are returned as immutable, serialization-ready views | yes | `T: test_plan_application.py::test_views_are_immutable_and_json_fresh`; `PlanningBrief` deep-freeze (review-1 F2, `C: dc7de0be`) |
| CLI and Web list, inspect, and activation paths use PlanApplication | yes | `C: e16340ca` (web), `C: 1d071758` (cli); `T: test_architecture_plan_seam.py` (30) — 0 violations over 67 adapter modules; verify checks `rg-plan-application-{cli,web-routes,mcp}` |
| Create-and-activate, lifecycle activation, and imported active documents enforce identical readiness rules | yes | `T: test_plan_application.py::test_create_transition_replace_refusal_payload_is_identical`; `T: test_web_plans.py::test_create_refuses_an_active_status_on_an_unready_plan`, `::test_markdown_replacement_refuses_an_unready_active_document` (the Bug A RED, `3a4f6b01`); `T: test_plan_surface_parity.py::test_activation_refusal_is_identical_via_cli_and_web`; review-1 F1 closed the compound-PATCH door (`C: 705ba58b`) |
| Markdown remains authoritative and index refresh remains best-effort and recoverable | yes | `T: test_plan_application.py::test_failed_index_refresh_keeps_the_document_and_reindex_recovers_the_row` (`C: e67f1767`: the refresh raises → the document is saved and readable, the index has no row; `reindex()` writes it back, bytes untouched); `T: test_cli_plan_seam.py::test_reindex_goes_through_the_seam`; `S: active-learning-decisions` "Activation is readiness-gated on every entry path" |
| Domain failures contain no CLI, HTTP, or MCP types | yes | `planning/errors.py`; `T: test_cli_plan_seam.py` (`_fail_for` maps six domain errors), `T: test_web_plans_seam.py` (status mapping in one place), `T: test_mcp_plan_tools.py` (`_plan_tool_error`) |

DoD: protected suites `test_web_plans.py`, `test_cli_plan.py`, `test_planning_evaluation.py` are
byte-identical to `3a4f6b01` (verify check `protected-files-3a4f6b01`, 0 lines); normative specs promoted
(`C: 7f836f50`); working tree clean at the tip (final section).

## #9 — Plan integration 2: Centralize mutations and checkpoints

| Acceptance criterion | Met | Evidence |
|---|---|---|
| CLI and Web no longer mutate Study Plans directly through the persistence layer | yes | `T: test_architecture_plan_seam.py` (guard + 14 planted bypasses rejected; `C: 5693e35c`, review-2 G7 `C: 59ab1e23`); `rg 'readiness\(|save_plan' web/routes/plans.py` → 0 |
| Plan identifier and creation time survive revisions and validated document replacement | yes | `T: test_plan_application.py::test_replace_preserves_id_and_created`, `::test_revise_preserves_id_and_created_and_bumps_updated` |
| Milestone changes set an explicit done value and are idempotent under retries | yes, for the explicit-state operations | `T: test_plan_application_mutations.py::test_set_milestone_done_is_idempotent`, `::test_set_unknown_milestone_raises_invalid_milestone`; the seam's `SetMilestone`, the CLI's `--done`/`--undone` and the MCP tool are sets. **Not** the legacy Web toggle request (`POST …/milestones/{i}/toggle`, read-invert-write) nor the no-flag CLI form — both documented as toggles (`S: web-ui` "The milestone checkbox is one SetMilestone; the toggle request is not replay-safe"; `docs/study-plans.md` "Recording, retries, and deletion") |
| Checkpoint results distinguish complete recording from partial Markdown or SQLite writes | yes | Bug B `C: c16ffa35` + `T: test_planning_evaluation.py::test_failed_checkpoint_db_write_is_reported_as_a_warning`, `::test_successful_checkpoint_db_write_adds_no_warning`; `T: test_plan_application_mutations.py::test_assess_db_failure_reports_failed_sink_and_returns_evaluation`, `::test_assess_document_failure_reported_independently`; review-2 G8 both-sinks-failed (`C: def5c561`) |
| Deletion retains checkpoint history and returns an immutable result view | yes | `T: test_plan_application_mutations.py::test_delete_retains_checkpoint_history`, `::test_delete_returns_delete_result_and_document_gone`, `::test_delete_without_confirm_raises_invalid_field` |
| Transport adapters map shared domain failures without reimplementing lifecycle policy | yes | `T: test_cli_plan_seam.py` (20), `T: test_web_plans_seam.py` (11), `T: test_mcp_plan_record_seam.py` (7) |

DoD: `T: test_plan_recording_failures.py` (6) covers partial checkpoint failures on an isolated DB;
store/evaluation/CLI plan/Web plan suites green in `verify: plan-suites` (464) and `full-suite-studyloop`.

## #10 — Plan integration 3: Make Now plan-aware end to end

| Acceptance criterion | Met | Evidence |
|---|---|---|
| No-active-plan recommendations remain backward-compatible | yes, for the frozen empty/draft world | `T: test_now_plan_guidance.py::test_no_active_plans_json_byte_identical_to_golden`; golden `tests/golden/now_plan_no_active.json` sha256 `ec451ce8…` unchanged (verify `golden-no-active-sha`). A plan that cannot be read adds a `warnings` entry — documented, not byte-identical by design (`S:` "The now engine is plan-aware…", rule 1) |
| Matching due work and synthesized next-milestone actions carry explicit plan and milestone references | yes | `::test_matching_due_concept_outranks_unrelated_same_urgency`, `::test_synthesizes_milestone_when_no_candidate_represents_it`; review-3 F1 refs on deferred/unready plans carry `None` (`C: 64dc09f7`) |
| Urgent reviews and fresh struggles can still outrank new milestone work | yes | `::test_unrelated_more_urgent_due_outranks_new_milestone`, `::test_weak_due_still_beats_overdue_synthesised_milestone` |
| Multiple active plans, exact normalized matching, completed plans, malformed plans, and low-energy deferral are deterministic | yes | `::test_one_action_keeps_every_matching_plan_ref_ordered`, `::test_milestone_without_concepts_does_not_substring_match`, `::test_fully_checked_active_plan_emits_completion_not_candidate`, `::test_energy_below_floor_defers_new_milestone_keeps_repair`, `::test_guidance_failure_warns_and_logs_without_failing_now`; `T: test_plan_guidance.py::test_malformed_plan_browse_matches_store_list` |
| At least one eligible plan-backed action remains among primary and alternates when constraints permit it | yes | `::test_preserves_one_plan_backed_action_when_energy_allows`, `::test_plan_backed_guarantee_respects_time_limit` |
| CLI, Web Today, recap, and MCP consume one additive recommendation contract | yes | `::test_api_now_carries_plan_guidance_end_to_end`, `::test_cli_now_renders_plan_relevance_and_energy_deferral`, `::test_recap_shows_plan_context_without_reranking`, `::test_cli_recap_rich_panel_shows_engine_plan_context`; `tests/js/today-panel-plan.test.js`; UAT cell `now_with_active_plan` (Today card "Advances plan: SQL Windows · milestone 2 …" through a real browser) |
| MCP get_next_action gains interleave parity with CLI and Web | yes | `T: test_mcp_next_action.py` (10; `C: c30330a0`) |

DoD: no surface reads plans independently (guard; `::test_guidance_read_once_with_no_checkpoint_history_calls`);
docs describe the behaviour with its eligibility qualifications (`docs/study-plans.md` "Plan-aware now",
`docs/web-ui-guide.md` Today, `docs/cli-reference.md`; pinned by `T: test_docs_plan_integration_contract.py`,
`C: bdc559d5`, `C: e151885c`). **Not met — owner action, blocking:** the D-16 five-scenario human rubric
(`R: receipts/now-rubric-2026-09-16.md`) has its "would I do the primary?" column **PENDING**; the
scenarios were run and recorded, the judgement was not faked. `tasks.md` T3.4a `[x]` is the engineering
receipt; **T3.4b `[ ]` is the owner's scoring** and is the one task the archive carried open. The
public page says the verdicts are pending, and the contract pin fails the day they are scored so the
sentence must move with the receipt. #10 is not done until T3.4b is.

## #11 — Plan integration 4: Add MCP discovery and authoring

| Acceptance criterion | Met | Evidence |
|---|---|---|
| Register the six tools | yes | `C: 5a03b094`; `T: test_mcp_stdio_smoke.py::test_full_handshake_list_tools_and_call` (real transport, exactly 32 names, the nine present) |
| Every tool delegates to PlanApplication and returns its immutable views | yes | `T: test_mcp_plan_tools.py` (121) with `forbid_store` under every delegation test |
| Readiness refusal and domain failures map to useful ToolError responses | yes | `T: test_mcp_plan_tools.py` (`not_ready:` with blockers + pause-or-repair hint; `conflict:`, `invalid:`, `not_found:`, `invalid_id:`, `invalid_milestone:`, `plan_error:`); `T: test_plan_journey_combined.py::TestCombinedJourney::test_mcp_refusal_after_a_web_start_is_a_structured_tool_error` |
| Structured revision is the normal agent mutation path; raw Markdown replacement is not required | yes | `update_study_plan` → `RevisePlan` over title, topics, target date, energy floor, cadence, notes, milestones, status; `overwrite` and raw Markdown not exposed (D-4, D-9 pins). **The mission (why / success) is not a field of any revision tool** — it changes only by editing the Markdown; the install doc says so (review-5 F4, `T: test_agent_install_doc_does_not_promise_mission_revision_over_mcp`, grounded in the live schema) |
| Tool schemas support deterministic discovery and do not expose storage paths or reindex administration | yes | schema pins in `test_mcp_plan_tools.py`; inventory is exactly the nine + `record_plan_learning` among 32 (`T: test_docs_plan_integration_contract.py::test_plan_tool_constant_is_exactly_the_registry_plan_tools`) |

DoD: the real stdio handshake lists the tools and *calls* them — `list_courses` in the smoke test, and the
plan tools themselves in the UAT `mcp_lifecycle` cell (create → activate → evaluate record → milestone →
history over real stdio). Docs: `docs/agent-install.md` "Study-plan tools over MCP" (discovery →
activation journey); `agents/mcp/README.md` "studyloop-mcp (Study tools)" lists all 32, pinned to the
registry; `S: mcp-server` "The studyloop-mcp inventory is published where the harness registration is"
(the stale "21 tools" / `docs/mcp.md` requirements were modified/removed at archive — review-5 F13).

## #12 — Plan integration 5: Add MCP progression and deletion

| Acceptance criterion | Met | Evidence |
|---|---|---|
| Register `set_study_plan_milestone`, `evaluate_study_plan`, `delete_study_plan` | yes | `C: b1e11e78`; stdio smoke asserts exactly 32 with the nine |
| Milestone changes accept an explicit done value and remain idempotent under retries | yes | `test_mcp_plan_tools.py` retry-idempotent pins; UAT `mcp_lifecycle` sets milestone 0 done over stdio and the document reads `- [x] **OVER clause**` |
| Evaluation distinguishes preview from record and accepts an optional study identifier | yes | `test_mcp_plan_tools.py` preview writes nothing / record reports sinks; `T: test_plan_journey_combined.py` step 4 (preview: both sinks `not_requested`, document bytes unchanged); UAT `mcp_lifecycle` (record: both `saved`, `recording_complete`) |
| Partial checkpoint writes return explicit warnings and never claim complete recording | yes, in-process | `test_mcp_plan_tools.py` failed-sink responses (`recording_complete: false` + warning) — a successful evaluation with incomplete recording, not a refusal. **Not exercised over the real stdio transport here:** the failing sink is a monkeypatched writer the subprocess cannot receive; a wire-level test would need a product-side fault hook, which nobody has authorised. The wire shape is the same `to_json_dict()` the in-process test pins |
| Deletion requires explicit confirmation and retains checkpoint history | yes | `test_mcp_plan_tools.py`; `T: test_plan_journey_combined.py` (refused without `confirmed=True`, document present; confirmed delete → Web 404) |

DoD: `record_plan_learning` folded onto `_plan_tool_error` (`not_ready:` prefix — an intentional, reported
wording change); `docs/agent-install.md` examples use the retry-safe operations.

## #13 — Plan integration 6: Launch planning-purpose agent sessions

| Acceptance criterion | Met | Evidence |
|---|---|---|
| Session launch accepts planning purpose while normal study remains the default | yes | `T: test_session_start_purpose.py` (25): `::test_default_purpose_is_focus_and_unchanged`, `::test_unknown_purpose_is_rejected_structurally`; `C: 4fc51250` |
| Planning purpose selects the architect persona, shared protocol, and evidence-grounded planning brief | yes, on the Web door | `::test_planning_purpose_selects_plan_architect_persona_with_brief_section`; brief budget (review-4 F1, `C: 8f9b6011`); `T: test_plan_journey_combined.py` (the MCP interview's prompts verbatim in the Web brief — one seed). A CLI/harness-started architect gathers the same material itself (`get_planning_interview` / `studyloop plan interview`) — the docs now say exactly that (review-5 F3) |
| PTY and ACP launch paths use one purpose/persona resolver | yes | `::test_pty_and_acp_use_one_resolver`; verify `rg-no-focus-literal-under-session-routes` (0 hits) |
| Starting an architect conversation creates no plan and stores no live-session plan identifier | yes | `::test_planning_launch_creates_no_plan_and_no_plan_id`; `T: test_web_plan_architect_journey.py::test_starting_the_architect_creates_no_plan`; UAT `architect_launch` (plan documents unchanged by the click) |
| Existing one-session conflict, reconnect, error, and cleanup behavior is preserved | yes | `::test_purpose_persisted_for_reconnect_label`, `::test_brief_failure_releases_session_claim` (both transports); `T: test_web_plan_architect_journey.py::test_conflict_returns_structured_error_and_offers_reattach`; protected transport suites byte-identical to `0a20a796` (verify `protected-files-0a20a796`) |
| The architect can use MCP authoring tools with the CLI retained as a harness fallback | **partly** | Persona: `T: test_plan_architect_persona.py` (17) — the nine named, MCP before CLI, lifecycle guards stated (`C: 6ba76757`); the fallback table no longer points at Web UI controls that do not exist (`C: e151885c`, review-5 F16). **Boundary:** the harness-launched Kiro (`study-plan-architect.json`, no `mcpServers`) and Claude Code (`tools: Read, Write, Grep, Bash`) definitions do not attach the `studyloop` server, so an architect started from those two takes the CLI fallback; a Web-launched architect uses whatever its agent process has. Disclosed in `docs/agent-install.md` as an **interim** boundary: the permission decision is the owner's (item 1 below) and has not been taken, so this is not yet a chosen outcome |

DoD: fake-agent tests, no paid calls (all of the above); reconnect state externally observable
(`GET /api/session/state.purpose`, also for a CLI-started architect via the persisted persona mode —
`::TestReconnectLabelFromPersistedMode`); `S: live-session-orchestration` "Session purpose" (now stating
the one reconnect precedence `web-ui` and `_dashboard.py` have — review-5 F8), `S: agent-adapters`
"Persona resolution by purpose" / "Architect persona prefers the MCP plan tools".

## #14 — Plan integration 7: Add the Web architect journey

| Acceptance criterion | Met | Evidence |
|---|---|---|
| The Plans view exposes a clear Plan with architect action | yes | `T: test_web_plan_architect_journey.py::test_plan_with_architect_action_posts_purpose_planning_and_navigates_to_console` (Playwright, real server, fake agent; `C: 7ad39941`) |
| Successful launch navigates to the existing live console and labels planning purpose correctly | yes | `::test_console_is_labelled_planning_and_label_survives_reconnect`; UAT `architect_launch` label "Planning session — study-plan architect" |
| The architect receives interview questions, evidence seeds, existing-plan summaries, and optional brain dump | **mostly — the brain dump is unimplemented** | `::test_brief_structure_present_not_wording` (the three brief sections in the persona the fake agent received). **The optional brain dump is not carried:** the Plans-view door takes an optional *subject* (the topic), not the free-text brain dump; the brain dump stays with the manual form. This is an unimplemented acceptance input, not an unverified one; `docs/study-plans.md` states it beside the boundary list |
| Refresh and reconnect preserve planning-purpose context | yes | the visible label after reload: `::test_console_is_labelled_planning_and_label_survives_reconnect` (dedicated browser test); the persisted purpose after reload: UAT `architect_launch`, which asserts `GET /api/session/state.purpose` post-reload — not the visible label (review-5 F11) |
| The manual create/edit/checkpoint interface remains fully functional | yes for create and checkpoints; edit is not a Web UI control | `::test_manual_new_plan_form_still_works` (browser: the manual form creates a plan); `T: test_web_plans.py` (25, byte-identical to `3a4f6b01`) for the routes. The Web UI's plan view offers create, activate, milestone checkboxes and preview/record checkpoints; **it has no edit-fields control** — field revision is the Web API's `PATCH` and the MCP `update_study_plan` (found in review 5's reproduction; the docs and persona were corrected). No browser test covers the checkpoint buttons; they are covered at the route level |
| Exactly one addressed console and WebSocket handle the planning session | yes | `::test_one_console_one_websocket`; `tests/js/plan-architect-launch.test.js` (14: one POST, one `study-session-start`, `init()` twice still one listener — the double-listener bug found and fixed in `C: 7ad39941`) |

DoD: browser tests cover launch, fallback, conflict, reconnect and structured errors; **cancellation is
not covered** — "a second click in flight is a no-op" (JS) and the existing end-session path are not an
abandonment mid-flight, and no browser test abandons the launch. Accessibility: `aria-busy`,
`aria-describedby`, `role="status" aria-live="polite"` status region, screen-reader label on the subject
input (`C: 7ad39941`; not audited with a screen reader). **The one-question-at-a-time protocol is not
proven by a live agent:** every journey uses the fake agent, so the protocol is asserted only as persona
text. `S: web-ui` "Plan with architect journey" (8 scenarios).

## #15 — Plan integration 8: Reconcile release contract and verify

| Acceptance criterion | Met | Evidence |
|---|---|---|
| Study Plans, Now, Today, Web, MCP, and installer language describe the implemented automatic boundaries accurately | yes, after review 5 | `C: bdc559d5` then `C: e151885c`: `docs/study-plans.md` ("Plan-aware now" with eligibility and the pending rubric; "Deliberately not automatic" — bold lead phrases == `studyloop.planning.boundaries.NOT_AUTOMATIC`, six automations, the door facts in prose; "Recording, retries, and deletion"), `docs/agent-install.md`, `agents/mcp/README.md` (32 tools == registry), `README.md`, `docs/index.md`, `docs/web-ui-guide.md`, `docs/cli-reference.md`, `docs/roadmap.md`; the installer prints the nine lifecycle tools + `record_plan_learning`, per-harness reach and the whole boundary from the same constants; the architect persona's fallback table matches; all pinned by `T: test_docs_plan_integration_contract.py` (25) and `T: test_plan_architect_persona.py` (17) |
| Active-learning, MCP, Web UI, agent-adapter, and CLI capability specs are synchronized | yes | promoted from the change's six delta specs by `openspec archive plan-application-seam` at `C: 7f836f50` (+28 added, ~1 modified, −1 removed, the CLI's own merge); review-5 F8 made the two reconnect-purpose statements one before promotion; `openspec validate --specs --all` 24 passed on the archived tree |
| CLI, Web, MCP, and architect journeys document both supported behavior and remaining live-session-binding exclusions | yes | "Deliberately not automatic" (six exclusions incl. no scheduled recurring planning sessions; same single session slot); `docs/acceptance-testing.md` scope note; the Archify spec's rose card (`C: dcfd44e4`) |
| Every acceptance area in parent issue #7 maps to completed child tickets and verification evidence | mapped; acceptance incomplete | this document + `R: receipts/verify-69740be5.json`. Incomplete: #10 (T3.4b), #13 (partly, item 1), #14 (brain dump unimplemented; cancellation untested) — see the parent section |

DoD: both package suites pass **independently** (verify `full-suite-studyloop` 5042 passed / 4 skipped /
800 deselected; `full-suite-agent-session-tools` 2146 passed) — not one workspace-wide run, because of
owner item 12; Web and MCP journeys independently (`combined-journey` 3, `browser-journey-e2e` 8) and
combined in one process **in both file orders** (`integration-combined`, `integration-combined-reverse`,
5 each) with no nested-event-loop regression (`T: test_plan_journey_combined.py` asserts the absence of
the three signatures); docs, installer output and capability matrices agree (docs contract); repository
status recorded in the final section. Unrelated local branches and worktrees are repository
administration (items 7–8), not this tree's cleanliness.

## #7 — parent: acceptance areas → children

| Area of #7 | Child | Verification |
|---|---|---|
| Shared plan application module, six operations, invariants | #8, #9 | `test_plan_application*.py`, `test_plan_guidance.py`, the guard, reviews 1–2 |
| Active-plan guidance and ranking, additive `NowPlan`, four consumers | #10 | `test_now_plan_guidance.py`, `test_mcp_next_action.py`, golden, review 3; UAT `now_with_active_plan`; **D-16 verdicts pending (T3.4b)** |
| MCP lifecycle parity (nine tools, confirmed delete, no raw Markdown for agents) | #11, #12 | `test_mcp_plan_tools.py`, stdio smoke, UAT `mcp_lifecycle`, review 4 |
| Web architect launch (purpose, one resolver, brief, no plan created, one console) | #13, #14 | `test_session_start_purpose.py`, `test_plan_architect_persona.py`, `test_web_plan_architect_journey.py`, JS, UAT `architect_launch`, reviews 3–4 |
| Reconcile docs, installer, specs; verification | #15 | docs contract, verify receipt, UAT redacted summary, review 5, this document |
| Out of scope stays out (no live-session binding, no auto checkpoints/milestones, no single-active rule, never a filter, no scheduled planning, Markdown stays authoritative) | all | `NOT_AUTOMATIC` ↔ docs ↔ installer; `test_planning_launch_creates_no_plan_and_no_plan_id`; `test_multiple_ready_active_plans_are_valid`; golden byte-identity |

**#7 requirements not fully verified or not met, stated plainly:** (1) the architect's
one-question-at-a-time protocol under a live model — persona text only; (2) the D-16 human rubric verdict
— **PENDING (T3.4b)**; (3) the Kiro/Claude harness-launched architects reach the plan tools only through
the CLI fallback until the owner decides item 1; (4) incomplete recording over the *real* stdio
transport — in-process only; (5) the Web door carries a subject, not the manual form's brain dump
(**unimplemented**, #14); (6) no browser test abandons an in-flight launch (#14 "cancellation");
(7) whether a CLI/harness-started architect *actually* calls `get_planning_interview` before interviewing
is persona instruction, not a launcher-path test.

---

## Proposed PR #20 description (replaces the "[in progress]" body)

**Title:** Plan integration: PlanApplication seam, plan-aware now, nine MCP tools, Web architect (#7–#15)

**Related: #7, #8, #9, #10, #11, #12, #13, #14, #15.** *(Owner: change to `Closes` per issue only as it
is satisfied or explicitly re-scoped — #8, #9, #11, #12 are met on the evidence above; #10 waits on the
D-16 verdicts (T3.4b); #13 waits on the Kiro/Claude header decision (item 1) or a re-scope; #14 waits on
the brain-dump handoff and the cancellation test, or a re-scope with a residual ticket; #15 and #7 close
after their children. A re-scope is an amendment to the issue's acceptance wording plus a residual
ticket, not a note in this description.)*

**What this branch is.** One `PlanApplication` seam replaces the per-door lifecycle policy that produced
Bug A (activation readiness bypassed on create-with-status and whole-document replacement) and Bug B
(a failed checkpoint DB write reported as complete). CLI, Web routes and MCP reach study plans only
through it (an AST guard enforces this, 30 tests incl. 14 planted bypasses). On that seam: the `now`
engine is plan-aware with tested ranking rules (a bias, never a filter; the no-plan output is
byte-identical to a committed golden); nine MCP plan tools plus `record_plan_learning` (32-tool inventory,
pinned over the real stdio transport); a `planning` session purpose with one persona resolver for PTY and
ACP and a budgeted planning brief; **Plan with architect** on the Plans view, into the existing console,
labelled and reload-safe, creating no plan. Public docs, installer output, the capability matrix and the
architect persona are pinned to code constants; the normative specs are promoted
(`openspec/changes/archive/2026-09-16-plan-application-seam/`); `scripts/verify/plan_integration.py`
writes the receipt.

**Evidence.** `docs/architecture/plan-integration/receipts/verify-69740be5.json` (29 checks, 29 ok, exit
0; the first run `verify-fff69c65.json` 27/29 is kept beside it with its two environmental causes
diagnosed); `receipts/uat-plan-journeys-a69867bf.redacted.json` (3/3 strict UAT **mechanics** cells:
browser architect launch, real stdio MCP lifecycle, Today with an active plan — fake agent, nothing
graded); four council code reviews, all ACCEPT (`council/review-{1,2,3,4}-arbitration-*.md`); the docs
review (`council/review-5-arbitration-2026-09-16.md`, GATE: ACCEPT after sixteen corrections). Both
package suites pass independently per the receipt; the `-m integration` combined run is green in both
file orders; `just lint`, `just typecheck`, `openspec validate --specs --all`,
`just release-consistency-shipped`, `mkdocs --strict` clean on the archived tree.

**Honest limits.** The architect's one-question-at-a-time protocol is asserted as persona text, never
under a live model; the D-16 rubric awaits the owner's five verdicts; Kiro/Claude harness-launched
architects take the CLI fallback until the owner decides their permissions; the Web door takes a subject,
not the manual form's brain dump; no browser test abandons a launch mid-flight; incomplete checkpoint
recording is proven in-process, not over stdio. Live-session binding, session-driven checkpoints and
milestone completion, a single-active-plan rule and scheduled planning sessions are out of scope by
design and documented as such. The Web UI has no control to revise an existing plan's fields or to
delete one — those are the Web API and the MCP tools — and the mission changes only in the Markdown.

**Merge.** Fast-forward onto `main`; the archive is already in the tree; tag per the release process
(`just release-consistency-shipped` passes on the archived change: "release tag pending: cut v0.4.0").

---

## Owner decisions still open (in one place)

1. **Kiro/Claude architect headers (review-4 boundary, blocks #13):** keep the two harness-launched
   architects CLI-limited (the install doc's disclosure is then the contract — reword "interim" to
   "chosen"), or grant them the `studyloop` server and the plan tools — Kiro: `mcpServers` + the nine
   `mcp_studyloop_*` names and `record_plan_learning` in `allowedTools` (mirroring `study-mentor.json`),
   flipping `test_install_agent_contracts.py:701` deliberately; Claude: a least-privilege explicit MCP
   allow-list. Review 4 ruled this a permission-model decision for a human.
2. **Score the D-16 rubric (T3.4b, blocks #10)** — `receipts/now-rubric-2026-09-16.md`, five yes/no
   verdicts with a line each and the tree sha; re-read row 3 against `64dc09f7`. A `no` on rows 1–4 is a
   council finding. Then update the status sentence in `docs/study-plans.md` "Plan-aware now" (the
   contract pin fails until it moves).
3. **#14 re-scope or finish:** implement the optional brain-dump handoff or amend #14's acceptance with a
   residual ticket (a subject field is not equivalent); add a browser test that abandons a launch
   mid-flight or record cancellation as out of scope; state whether persona-text compliance satisfies the
   one-question protocol or a live-agent run is required.
4. **Deviation 12** (review 2) — a legacy active-but-unready document must be paused or repaired before
   any write. Confirm or reverse (one policy change in `_assert_can_be_active`'s callers; the tests that
   would flip are named in review-2 F2/G1).
5. **Review-3 F2 design question** — should `now` grow explicit urgency classes (rank by class first,
   plan relevance second)? The council decided a bias with the constant pinned to today's bands; a future
   design option, not a Phase-6 acceptance question.
6. **Follow-on tickets, not acceptance:** the parser bug (deviation 13 — a milestone concept containing
   `)` does not round-trip); `_evidence_command` quoting (review 3, item 5 — `shlex`-safe rendering when
   the golden is next allowed to move); **the web app's query-encoder warm can stall request handling
   under load** (observed here: `POST /api/session/start` unanswered for > 20 s while the warm built a
   model in a fresh HOME; the plan-journey e2e fixture now opts out with
   `STUDYLOOP_RETRIEVAL_MODE=lexical`; the UAT plan-journeys fixture does not yet — same shape, same
   exposure, left for the next sign-off run); the `agent-session-tools` test
   `test_eval_arms.py::TestPlannerIsolation::test_planner_patch_restored_after_tool_error`, order-dependent
   under the root config (passes alone and in the package-local run; owner of `agent-session-tools`) — or
   formally accept the package-scoped verification boundary the receipt uses.
7. **`feat/clean-start`** — 7 commits not on origin; its tip equals the local tag
   `archive/feat-clean-start-2026-09-15` (also not on origin). Push the tag and delete, or discard.
8. **`feat/harness-tier-promotion`** — 10 unmerged commits (issue #21, 56 files, last commit 02:08 today),
   not on origin, checked out clean in the worktree `../studyloop-wt/harness-tier`. Merge, push, or
   discard: `git worktree remove ../studyloop-wt/harness-tier && git branch -D feat/harness-tier-promotion`.
   Not touched unattended: deleting it destroys work.
9. **`or_first_filtered`** (review 1, §5 stream) — a fresh registration with a new gold set, or close as
   "exploratory, not pursued".
10. **Repository ruleset for branch deletion** — the "Default" ruleset blocks deletion on all branches,
    so the remote `feat/knowledge-proof` (tip == tag `archive/feat-knowledge-proof-2026-09-15`, PR #19
    closed) cannot be deleted until the owner relaxes it (ADR-0011 §4).
11. **Token revocation** — named in the stage brief as an open owner item; its context is in the earlier
    stage reports, not in this repository's records. Listed so it is not lost; route privately.
12. **The GitHub writes this draft exists for:** post the evidence comments on #8–#15 as status reports
    now; close each issue only as items 1–3 resolve; replace PR #20's body with the text above; mark it
    ready for review when the `Related` line can honestly read `Closes`.

## Repository state at the tip (recorded, not asserted)

Measured on the tree this refresh was committed from (the tip minus this docs commit; the docs commit
changes no code, test or spec):

- `uv run --group dev pytest packages/studyloop/tests -q -p no:cacheprovider -x` → **5042 passed, 4
  skipped, 800 deselected**, exit 0 (374.9 s).
- `uv run --group dev pytest packages/agent-session-tools/tests -q -p no:cacheprovider` → **2146 passed**
  (520.8 s); the order-dependent `test_planner_patch_restored_after_tool_error` (item 6) did not fire in
  the package-local run.
- `-m integration` over `packages/studyloop/tests` → **204 passed, 2 failed, 86 errors, 3 skipped,
  1 xfailed**. Every plan-integration integration check passes (stdio smoke 2, combined journey 3, both
  orders 5 + 5). The 86 errors are all in four tmux/terminal modules (`test_study_integration.py` 35,
  `test_herdr_integration.py` 27, `test_study_lifecycle.py` 15, `test_uat_terminal.py` 9) and are one
  cause: those tests start a session in a **subprocess**, so the autouse in-process redirect of
  `session.orchestrator._claude_settings_path` does not reach it, the child pre-trusts the session dir
  in the real `~/.claude/settings.json`, and the real-home write guard fails the test at teardown.
  Pre-existing and shared with `main` (same guard, same write); the narrowing fix — pre-trust only for
  a Claude session — is `fe7534d6` on the unmerged `feat/harness-tier-promotion` (item 8). The 2
  failures are `test_uat_terminal.py::TestNestedTmux` (`OSError: [Errno 5] Input/output error` — nested
  tmux without a controlling terminal in the unattended shell). None is a plan-integration regression;
  none is in the verify registry or the #15 DoD's "representative Web and MCP journeys".
- `just lint` clean (ruff; 1036 files formatted); `just typecheck` 0 errors; `just spec-check`
  (`openspec validate --specs --all`) 24 passed; `mkdocs build --strict` exit 0;
  `just release-consistency-shipped` passes ("release tag pending: cut v0.4.0").
- `git status --porcelain` at the tip: empty except the untracked `.playwright-mcp/` scratch directory,
  which is not this branch's.

Scratch, recorded separately from durable evidence (review-5 F12/F13): the Archify `.html` /
`.visual-check.*` sidecars under `docs/architecture/plan-integration/` are gitignored, regenerable
deliverables — kept; the e2e and UAT `world` fixtures were `tempfile.mkdtemp` with **no cleanup step** —
thirty-nine `studyloop-architect-journey-*` / `studyloop-uat-plan-journeys-*` directories had
accumulated in `$TMPDIR` — both fixtures now `rmtree` their world in a `finally` (verified: a module run
leaves the count unchanged) and the thirty-nine were removed by hand, along with the e2e server logs
(`studyloop-web-18626-*.log`); the UAT durable bundle lives under `~/.local/share/studyloop/uat/`,
private, by the tier's design, and is not scratch. No branch or worktree was created by Phase 6.
