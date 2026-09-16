## Verdict

ACCEPT — both streams meet T4.1/T4.2 and design §4/§5 on `b2f37fa4`, so Phase 5 can start here; the uncapped `### Evidence` brief and the Kiro/Claude MCP withhold are Phase-5/6 work, not rework of these adapters or the persona body.

## Findings

- 💡 `set_study_plan_milestone` / `evaluate_study_plan` / `delete_study_plan` (`tools.py` ~1138–1235). Each is one seam call with arguments forwarded unchanged — no `.strip()`, no `bool()`, no `plan_id or None`. `evaluate_study_plan` does not pass `append_to_plan`, so `AssessPlan`'s default `True` stands and is the right thing to hide (design §4 lists four arguments; `test_evaluate_study_plan_default_is_a_preview` pins it). The six of #11's normalisation, if any, is not established by the brief.

- 💡 `set_study_plan_milestone` docstring (~1148). The quoted refusal `not_ready: … — the plan is already active; pause it or repair the blockers before writing` is the tail of `_plan_tool_error` (line 918–921); the real string is `not_ready: {exc}: {blockers}{hint}`. Close enough for an agent-facing schema. `evaluate_study_plan`'s "`markdown` is the evaluation block to paste" is true for a preview: `AssessmentResult.to_json_dict()` always carries `markdown`, and `test_evaluate_preview_writes_neither_sink` asserts it non-empty. `Refusals:` lists omit `plan_error:` on all three and `conflict:` on milestone/evaluate/delete — correct, because `_set_milestone` / `assess` / `_delete` as shown raise `PlanNotFound` / `InvalidPlanId` / `InvalidField` / `InvalidMilestone` / `PlanNotReady` only. `PlanConflict` in `test_every_phase_four_refusal_maps_to_one_prefixed_tool_error` is a mapping-ladder pin, not a reachability claim.

- 💡 `delete_study_plan` docstring (~1210). "Ask the learner before passing it" is advisory; the tool cannot see the conversation. Schema is honest: `required == ["plan_id"]`, `confirmed` default `False`, no `const`/`enum` (`test_phase_four_schemas_carry_the_design_signatures`). 404-before-400 matches `_delete` and `test_delete_missing_plan_is_not_found_before_confirmation_is_judged`.

- 🔵 Fold of `record_plan_learning` (`tools.py` 168, GREEN `b1e11e78`). Message became `not_ready: plan is not ready to activate: <blockers>[ — the plan is already active; …]`. Arbitration ordered the fold in the same commit after the RED pin (`1a56b858`); `docs/agent-install.md` already promised the kind prefix; `test_plan_record.py::TestMcpTool` and `test_mcp_plan_record_seam.py` matching by substring is not established as a contract break by this brief (`wind-down-protocol.md` contents not shown). Still: a consumer that branched on the unprefixed lead-in would silently miss. Pin the prefixed lead-in in the verify receipt (see hazards ii), not a Phase-4 rework.

- 💡 Deviation (b): `record_plan_learning` (~168) late-binds `_plan_tool_error` (~886) inside `register_tools`. Legal, and "append only" forbade moving the helper. Leave it; a later cleanup can lift `_plan_tool_error` to module scope. Not a Phase-5 gate.

- 💡 `_plan_tool_error` isinstance ladder (886–926) with three new callers. `_delete`'s "vanished between load and unlink" is already `PlanNotFound` → `not_found:`. No new seam type is swallowed as `plan_error:`. An unwrapped `store` exception would still escape unmapped — same as #11.

- 💡 `forbid_store` (`test_mcp_plan_tools.py` ~146). Extending with `authoring.draft_plan/interview_spec/seed_from_history`, `evaluation.evaluate_plan/evaluate_and_record`, `index.record_checkpoint` is the right net: the seam calls `evaluation.evaluate_plan(...)` through the module attribute, so the monkeypatch fires. An adapter that only imported `PlanApplication` cannot reach those entry points. Still reachable and correctly not forbidden: `evaluation.CHECKPOINT_PHASES`, seam-internal `store.load_plan` (delegation tests never enter the seam). A `from evaluation import evaluate_plan` *inside* the tool function would still see the monkeypatched name.

- 💡 Real-seam journeys. `_ready_plan_on_disk` → `create_study_plan` + `update_study_plan`, then `store.load_plan_text` before/after plus `_database_checkpoints`, is the right "writes nothing" proof. `test_evaluate_partial_failure_surfaces_as_warnings_on_the_real_seam` returning `False` from `plan_index.record_checkpoint` is how the real sink fails: `assess` maps `_DB_WARNING` → `db_write="failed"`. `test_phase_four_responses_are_fresh_containers` is sound (mutate `first`, compare `second` to `pristine`).

- 🔵 `PRODUCTION_TOOL_COUNT = 32` is duplicated in `test_mcp_stdio_smoke.py` and `test_mcp_plan_tools.py`. Both assert exact count; only stdio also asserts `len(listed) == len(set(listed))`. The in-process twin relies on `_registry()` already being unique. Import one constant; add `len(_registry()) == len(set(_registry()))` to `test_production_inventory_is_thirty_two_with_the_nine_plan_tools`. All ten mcp-server scenarios have a named test; extra tests (fold pins, schema, delegation, `done=False` as set) are implementation pins the spec does not need.

- 🔵 `agents/shared/personas/plan-architect.md` MCP table. Signatures drift from the registered schemas and from `docs/agent-install.md`: table has `create_study_plan(title, answers, status="draft")` (omits `plan_id=None`); `get_study_plan` omits `history_limit`; `record_plan_learning(plan_id, title, body="")` omits `status="active"`. "Never replaces an existing plan: a taken id is a conflict" is true (D-4) even without `plan_id` in the row — a generated slug can collide. "missing from the inventory → that step's CLI fallback" is decidable only via `tools/list`; no test pins that sentence. Align the two tables on `plan_id` / `status` / `history_limit` in a docs-only follow-up.

- 💡 CLI fallback table is true at `b2f37fa4`: the group is `interview|list|show|new|status|milestone|evaluate|record|architect` — no edit, no delete. "revise in the Web UI — never by hand-editing" is consistent with "Markdown is the source of truth": the document is canonical, writes go through the seam.

- 🔵 Session Start / wind-down (`plan-architect.md` protocols). `evaluate_study_plan(..., study_id=STUDY_ID, record=True)` inherits the old `$STUDY_ID` hole: a Web PTY/ACP architect is not established by this brief to receive `STUDY_ID` in env or persona. An agent may pass the literal `STUDY_ID`. Wind-down step 6 is still `studyloop session end` (shell). Coherent for a PTY; an ACP agent without Bash must skip or fail that step. Phase 5 must inject the live session id into the brief or the console bootstrap, and decide the ACP end-session path.

- 💡 "never on a retry" on `delete_study_plan` is compatible with 404-before-400: a retried `confirmed=True` is `not_found:`, not a second delete.

- 🔵 Persona is slightly wrong about repair-while-active. "Activation is gated… nothing is written" is true for `set_study_plan_status`. `update_study_plan(status="active")` on an unready draft, and any write to an already-active husk (F1), are also refused — the Revise row does not say "pause first, then repair". Add one clause to the Revise row so the architect does not hammer `update_study_plan` on an active husk.

- 💡 `test_plan_architect_persona_names_the_nine_mcp_tools_when_purpose_is_planning`. Goes through `persona_mode_for("planning")` → `build_canonical_persona`, so it is the purpose path, not a raw file read. It would not silently pass via `focus.md`: `test_focus_persona_unchanged` pins sha256 `2d35c22a99ed72fbc91e8a79ad05312b04af2e36bbb5a7bb4d7ac4a0e9ef11e0` at `205819c7` with `STATE_FILE`/`TOPICS_FILE`/`PARKING_FILE` fixed, and `PERSONA_DIR` is the checkout. `_section` on `###` closing at the next `#`–`###` is correct for `### CLI fallback` then `## Session Start Protocol`.

- 🔵 `test_the_nine_are_the_registry_plus_exactly_what_12_lands`. After the merge `unregistered == ∅`; the test no longer says anything about the persona (other tests do). Retire `_LANDING_WITH_12` and assert `set(PLAN_MCP_TOOLS) <= registered`.

- 💡 Manifest test. `TRACKED_FILES` filtered to `study-plan-architect` covers Claude and OpenCode only — matching the manifest diff (two hashes, dates). Kiro `persona.md` is not in the manifest; `test_projected_personas_match_canonical["kiro/study-plan-architect/persona.md"]` is what stops drift. Leave it; do not pretend the manifest tracks Kiro.

- 💡 Cross-stream. No merge conflicts. `not_ready:` kind list, `record=False` preview / `record=True` sinks, and the ten-row tool list agree across persona, `_plan_tool_error`, evaluate docstring, and `docs/agent-install.md` except the `plan_id`/`status` signature drift above. `tasks.md` ticks and `.secrets.baseline` (two hex fingerprints + `generated_at`) are coherent.

## Spec/doc review

mcp-server "Study-plan progression and deletion tools" (ten scenarios) plus the amended `record_plan_learning` requirement match the shipped adapters and `test_mcp_plan_tools.py` / `test_mcp_stdio_smoke.py`. Nothing claimed there is unshipped. Shipped but only in tests, not spec: the fold's success-shape pin (`test_record_plan_learning_success_shape_is_unchanged_by_the_fold`), `done=False` as set-not-toggle, fresh containers. Fine.

`__cause__` is required by both mcp-server requirements and pinned in-process (`assert caught.value.__cause__ is error`). It is not a testable requirement over stdio: JSON-RPC does not serialise `ToolError.__cause__`. Keep the in-process pin; drop or qualify the stdio reading of that sentence.

agent-adapters "Architect persona prefers the MCP plan tools" (three scenarios) matches `test_plan_architect_persona.py`. Spec does not mention `STUDY_ID`, Session Start order, or harness `mcpServers` — correct. Spec *does* require "A tool missing from the connected server's inventory SHALL route to that step's CLI fallback"; that is an LLM instruction, pinned only as prose in the persona, not by a test. Acceptable if left as prose; do not pretend it is an executable contract.

`docs/agent-install.md` MCP section is accurate for the ten tools, the kind prefixes, the already-active hint, and the failed-sink response. It does not say which harnesses actually attach `studyloop` to the architect (Kiro `study-plan-architect.json` has no `mcpServers`; Claude frontmatter is `Read, Write, Grep, Bash`). A reader will assume every architect launch can call the nine. Add one sentence pointing at the T6.1 harness gap, or the install doc overclaims.

## Phase 5/6 hazards

**(i) #14 Web "Plan with architect".** The Plans-view control must `POST /api/session/start` with `purpose: "planning"`, `topic: ""` (or a chosen subject — never infer `"Study plan"`), plus the same `energy` / `agent` / `transport` the existing start picker already sends. Use the `201` `ws_url` as today's picker does; do not open a second socket. Console label reads `purpose` from the `201` body on first paint and from `GET /api/session/state` on refresh/reconnect — `setdefault("purpose", "focus")` in the state path means a missing key becomes `focus`, so the writer must persist `purpose` or the label flips.

CLI-started architect (`cli/_plan.py:479`, `topic="Study plan"`, `mode="plan-architect"`, no `purpose`) currently reconnects labelled `focus`. #14 must not infer `planning` from the topic string. Persist `purpose=planning` in the CLI writer (small, explicit); RED: `test_cli_plan_architect_persists_purpose_planning` — after `studyloop plan architect`, `GET /api/session/state` has `purpose == "planning"`. Until that lands, the Web console of a CLI-started architect staying `focus` is accepted behaviour, not a #14 bug.

RED tests, split by harness:

- TestClient + `STUDYLOOP_TEST_AGENT_CMD` / `STUDYLOOP_TEST_ACP_CMD`: `test_plan_with_architect_posts_purpose_planning` (one POST, `topic` `""` or the chosen subject, no plan row created); `test_plan_with_architect_201_carries_purpose_and_ws_url`; `test_plan_with_architect_conflict_is_existing_409_with_reattach_url`; `test_planning_brief_structure_has_interview_evidence_existing_plans` (H3 names only, not wording); `test_manual_new_plan_still_posts_without_purpose_planning`.
- Playwright (`web_server_fixture_factory` / `web_page_fixture_factory`, `pytestmark = e2e`): `test_plan_with_architect_click_labels_console_planning`; `test_planning_label_survives_reconnect` (reload, read label from `/api/session/state`); `test_one_console_one_websocket`.

Reuse `session-timer.js:230` / `components.js:3365` start picker and its WebSocket listener. `plans-panel.js` stays the only `api/plans` client — the new control belongs next to it but must call the existing start helper, not copy it.

Cap or summarise `### Evidence from the learner's history` in `_render_planning_brief` (`web/routes/session/_start.py`) as part of #14, without changing `_resolve_persona`'s shape. #13b could not do this in its file set. RED: `test_planning_brief_evidence_is_capped` (seed larger than N lines → brief Evidence section ≤ N / carries `…`) and `test_brief_is_sent_once_before_first_prompt` (ACP fake: `persona_text` contains one `### Interview` and no second copy on the first user prompt). The persona just grew 114 lines; shipping ACP without the cap is the token bomb review-3 named.

**(ii) #15 verification receipt (`scripts/verify/plan_integration.py`).** For Phase 4 record:

- `pytest test_mcp_stdio_smoke.py -m integration` — `len(listed) == 32 == len(set(listed))`, `PLAN_TOOLS` ∪ `{record_plan_learning}` ∪ `CORE_TOOLS` ⊆ names.
- `test_production_inventory_is_thirty_two_with_the_nine_plan_tools`.
- `tests/test_plan_architect_persona.py` (the whole module).
- `test_architecture_plan_seam.py` — 30 passed.
- golden `tests/golden/now_plan_no_active.json` sha256 `ec451ce8857c8a72e398e3054e3c060cd3b5b13ecb29e29cba3822dc192503c0`.
- `git diff 3a4f6b01 -- test_web_plans.py test_cli_plan.py test_planning_evaluation.py` and `git diff 0a20a796 --` the seven protected files → 0 lines.
- `rg` on adapters: zero imports of `planning.store|index|authoring|evaluation`; zero `build_canonical_persona("focus"` under `web/routes/session`.
- `agents/manifest.json` hashes for `claude/study-plan-architect.md` and `opencode/study-plan-architect.md` equal `hash_file` (`c4ae64c9c86f9235`, `e455bb970b1e4fc7` at this tree).
- Fail if `record_plan_learning` on a `PlanNotReady` no longer starts with `not_ready:` (call the in-process tool or assert `test_record_plan_learning_not_ready_refusal_is_prefixed_with_blockers_and_cause`).

T6.3 combined journey: one process, `TestClient` `POST /api/session/start` `{purpose:"planning", topic:""}` then an in-process `evaluate_study_plan` (or `list_study_plans`) via the same `FastMCP` registry. Assert `201` + `purpose=="planning"`, the tool returns a view (not a `ToolError`), and the log/stderr contains no `This event loop is already running` / `Cannot run the event loop while another loop is running`. That is the nested-loop receipt.

**(iii) Kiro/Claude "architect takes the CLI fallback".** Documented boundary, not a Phase-4 defect. `d96fb9ba` sealed `study-plan-architect.json` with `tools: ["@builtin"]` and no `mcpServers`; `test_install_agent_contracts.py:701` pins that; Claude frontmatter `tools: Read, Write, Grep, Bash` is an allow-list. #13b was right not to touch either — T4.2 is the persona body, and a Web-launched architect reads `agents/shared/personas/plan-architect.md` regardless. The persona now *promises* nine MCP tools those two harness launches cannot see; that is a T6.1 owner item, not a Phase-4 correction.

Fix, owned by T6.1: Kiro — add `studyloop` (`command: studyloop-mcp`) to `mcpServers` and the nine `mcp_studyloop_*` names plus `mcp_studyloop_record_plan_learning` to `allowedTools`, mirroring `study-mentor.json` (mentor today lists six non-plan tools). Claude — add the MCP tools to the frontmatter allow-list, or drop the allow-list so project `agents/claude/mcp.json` applies. Flip line 701 from `assert "mcpServers" not in definition` to `assert "studyloop" in definition["mcpServers"]` and add `test_kiro_architect_allows_the_nine_plan_tools` / `test_claude_architect_frontmatter_allows_mcp_plan_tools`. Do not do this in Phase 4; the pin currently encodes the sealed design.

## Process finding

Leaving the Kiro/Claude tool headers sealed while the persona prefers nine MCP tools. Two agents could not see that T4.2's text now over-promises on the two harness launches the install contract still withholds; a human should have decided "persona-only this phase, T6.1 wires the headers" (what landed) versus "T4.2 includes the headers" before the RED commits, not after the merge.
