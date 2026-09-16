## 1. Verdict

**ACCEPT-WITH-CORRECTIONS** — #12 is acceptable, but #13b does not close review 3’s explicit bounded-evidence and once-before-first-prompt requirements, so Phase 5 should start only after those omissions are corrected and the arbiter verifies the merged tree.

- **#12: ACCEPT.** The three adapters, shared error mapping, schemas and real-seam journeys satisfy the progression-tool contracts.
- **#13b: ACCEPT-WITH-CORRECTIONS.** The persona preference and projection work is sound; its GREEN result does not establish completion of the inherited delivery safeguards.

## 2. Findings

### F1 — 🟡 Missing inherited prompt-budget and delivery safeguards

**Location:** `web/routes/session/_start.py::_render_planning_brief`, `_resolve_persona`; `tests/test_plan_architect_persona.py`.

Review 3 explicitly required: “cap or summarise `### Evidence` in #13b” and “add a test that the brief is sent once before the user's first prompt.” The diff contains neither delivery changes nor such a test. Rendering with `brief="- interview item one"` exercises neither a large seed nor ACP delivery.

**Why it matters:** Naming MCP tools does not prevent an oversized first prompt; projection equality does not prove correct injection timing. I disagree with treating T4.2’s narrow persona-name test as closing this handover.

**Fix:** Assign a correction owner permission to change the renderer/delivery tests without changing `_resolve_persona`’s interface. Define a deterministic budget and truncation marker; limit evidence and account for the existing-plans contribution rather than merely limiting each individual value. A proposed acceptance budget is **8 KiB of UTF-8 evidence and 16 KiB for the complete planning brief**, excluding the canonical persona body; these are proposed limits, not existing design requirements.

**RED tests**, in a new `tests/test_web_planning_persona_delivery.py`:

- `test_large_planning_brief_is_bounded_and_keeps_three_sections`: oversized history and many plans; bounded output, all three headings retained, explicit omission marker.
- `test_acp_planning_brief_is_sent_once_before_first_user_prompt`: fake ACP captures the delivery sequence; one brief precedes prompt one and is absent from subsequent injections.
- `test_focus_launch_does_not_receive_planning_brief`: preserve the default-purpose path.

### F2 — 🔵 Persona runtime instructions assume capabilities and session identity

**Location:** `agents/shared/personas/plan-architect.md`, Session Start and End-of-Session protocols.

`study_id=STUDY_ID` is Python-like pseudocode, but the supplied persona does not explain where the actual session ID comes from. Its shell commands also remain unconditional outside the fallback table. Whether a particular ACP agent has a shell, or receives `$STUDY_ID`, is **not established by the brief**; ACP itself does not establish either capability.

**Fix:** Explain that the argument is the actual live-session ID, never the literal `"STUDY_ID"`; if unavailable, use the tool’s documented empty default rather than inventing an ID. Make shell-only steps conditional on shell availability. Where an MCP alternative such as `end_session` is available, use its actual registered schema; that schema is not supplied here.

**RED tests:**

- `tests/test_plan_architect_persona.py::test_session_protocol_handles_missing_shell_and_session_id`.
- `tests/test_web_planning_persona_delivery.py::test_planning_agent_receives_actual_session_identity`, if #14 promises session attribution.

Synchronise all three projections and regenerate the tracked hashes after the wording change.

### F3 — 🔵 Public fallback documentation overstates parity

**Location:** `docs/agent-install.md`, “Study-plan tools over MCP,” introductory sentence; persona CLI fallback table.

The documentation says agents unable to reach MCP “can do the same work” through the CLI. The persona correctly admits that the CLI cannot revise existing plan fields or delete a plan. Those statements conflict. The shown documentation also does not disclose that the harness-started Kiro and Claude architect definitions currently restrict access to MCP.

**Fix:** State that CLI fallback covers only supported commands; point field revision and deletion to the Web UI or an MCP-enabled session. Add a harness-capability note distinguishing harness-started agents from Web persona rendering.

**RED test:** `tests/test_plan_architect_persona.py::test_install_docs_disclose_architect_fallback_limits`, asserting the two unavailable operations and the Kiro/Claude boundary.

This is a documentation correction, not a reason to invent CLI commands or expand sealed harness permissions during #13b.

### F4 — 🔵 Test names and assertions overstate some guarantees

**Locations:** `tests/test_mcp_plan_tools.py`, `tests/test_plan_architect_persona.py`.

1. `test_production_inventory_is_thirty_two_with_the_nine_plan_tools` does **not** assert `CORE_TOOLS`, despite the report calling it the stdio pin’s twin. `_registry()` is keyed by names, so uniqueness there is structural; it cannot reveal overwritten duplicate registrations. The stdio test correctly checks uniqueness of the advertised list, exact count, nine names, `record_plan_learning` and `CORE_TOOLS`.

   **Fix/test:** Extend the in-process test to assert `CORE_TOOLS`; demonstrate RED by substituting an inventory of the correct size missing one core name. Keep the independent transport test.

2. `test_the_nine_are_the_registry_plus_exactly_what_12_lands` still permits any of #12’s three tools to be absent after the merge. It tests the test constant against the registry, not persona content.

   **Fix/test:** Replace it with `test_all_nine_persona_tools_are_registered_after_phase_four`, asserting no missing names; remove `_LANDING_WITH_12`. The stronger MCP inventory tests already prevent this becoming a merged-tree functionality gap.

3. The planning-persona test exercises `persona_mode_for("planning")` and the builder, but not the Web purpose route. It could pass under the hypothetical wrong resolver described in the brief.

   **Fix/test:** Add `test_planning_purpose_resolves_to_plan_architect`, explicitly asserting the mode, and retain a separate route/delivery test.

4. Byte-equal document contents do not prove that a file was never rewritten, and an empty checkpoint log is weaker than proving existing rows remain unchanged.

   **Fix/tests:** Add `test_milestone_retry_does_not_call_save_plan` with a failing save spy after the initial mutation; extend preview testing with `test_evaluate_preview_preserves_existing_checkpoint_rows` and writer tripwires. Preserve the existing real-seam content assertions.

Duplicating `PRODUCTION_TOOL_COUNT = 32` in two independent test files is acceptable. One test module should not import another merely to share this integer.

### F5 — 🔵 Repository discovery can hang outside the expected checkout

**Location:** `tests/test_plan_architect_persona.py`, module-level `_REPO_ROOT` loop.

At a filesystem root without `agents/manifest.json`, `.parent` stops changing and the loop never terminates. This is a concrete test-collection defect, although the normal repository checkout supplies the marker.

**Fix:** Search a finite sequence of parents and raise an actionable exception if the marker is absent.

**RED test:** `test_find_agent_repo_root_fails_when_marker_is_absent`, against a small extracted discovery helper.

The fixed session paths make the focus hash a reasonable checkout-based regression pin. Portability outside a repository, or across checkout newline transformations, is not established by the brief.

### F6 — 🔵 Inventory commentary repeats the arithmetic error

**Locations:** `tests/test_mcp_stdio_smoke.py`, comment above `PRODUCTION_TOOL_COUNT`; `tests/test_mcp_plan_tools.py`, corresponding comment.

Both comments say “23 … plus the nine … less `record_plan_learning`.” That arithmetic is 31; `record_plan_learning` is not one of the nine being added.

**Fix:** Write: “23 original tools, including `record_plan_learning`, plus nine new plan tools = 32.” Similarly, the folded tool’s references to the “other eight” should say **nine design-§4 tools** where that is what they mean.

**Test:** The existing `test_full_handshake_list_tools_and_call` pins the correct executable result. This is prose-only; no additional RED runtime test is warranted.

### F7 — 💡 D-6’s literal wording and the demonstrated public facade need reconciliation

**Location:** `mcp/tools.py`, imports inside all three new adapters and `_plan_tool_error`; binding D-6 description.

The code imports public symbols from `studyloop.planning`, while the binding wording says adapters import only `studyloop.planning.{application,views,errors,intents}`. Those are not literally the same import spelling. Conversely, the guard reports 30 passes, and the supplied code imports no storage, authoring, evaluation or index internals.

**Disposition:** Do not report a demonstrated seam bypass. Clarify whether the public facade’s allowed re-exports satisfy D-6; if literal submodule imports are required, align the adapters and guard deliberately. The actual facade export/guard implementation is **not established by the brief**.

**Pin:** `tests/test_architecture_plan_seam.py::test_mcp_public_seam_import_policy`, explicitly accepting or rejecting the facade form according to the clarified rule.

### #12 adapter audit — no additional blocking defect

- **Delegation and normalisation:** `set_study_plan_milestone` makes one `apply(SetMilestone)` call; `evaluate_study_plan` makes one `assess(AssessPlan)` call; `delete_study_plan` makes one `apply(DeletePlan)` call. Their bodies do not strip, coerce or replace caller arguments. Required plan IDs do not need optional-ID normalisation such as `plan_id or None`. The exact normalisation bodies of #11’s six tools are not reproduced, so a line-by-line comparison is not established.
- **Hidden evaluation option:** Leaving `append_to_plan=True` at the seam default is correct: the exposed operation means preview or recording to both sinks. Exposing database-only recording would introduce a new adapter contract.
- **Milestone refusal wording:** The quoted `not_ready: …` is an abbreviated template. Its already-active suffix matches `_plan_tool_error`; the unchanged domain message still says “not ready to activate,” followed by the corrective already-active hint. Tests explicitly pin this combination.
- **Preview Markdown:** It exists. `AssessmentResult` carries `markdown`, and `test_evaluate_preview_writes_neither_sink` asserts non-empty output. `recording_complete=True` on a preview correctly means no requested write failed, not that anything was saved.
- **Refusal lists:** They omit the generic `plan_error:` fallback. A shared “other domain refusals retain their kind, otherwise `plan_error:`” sentence would make schema documentation complete. The fake `PlanConflict` cases test mapping robustness; they do not prove a real conflict path. No explicit `PlanConflict` raise appears in the supplied `_set_milestone`, `_delete` or `assess`; other load/storage behaviour is not established.
- **Delete confirmation:** The schema honestly makes `confirmed` an optional ordinary boolean defaulting to false. The seam enforces the boolean, not human consent. “Ask the learner” is advisory agent policy, appropriately strengthened by the persona’s specific-plan confirmation requirement.
- **Error fallback:** The vanished-before-unlink path explicitly becomes `PlanNotFound`, hence `not_found:`, not `plan_error:`. The six errors are siblings, so the ladder order introduces no masking. A non-`PlanError` storage exception would not be swallowed by the generic domain fallback; exhaustive storage exception behaviour is not supplied.
- **Shared helper placement:** Late binding is legal because tools execute after registration completes, and the helper is defined before the production return. A 750-line forward reference is less readable but acceptable under “append only.” Moving it was not required for correctness.
- **Fold compatibility and history:** The prefix change is observable, but it was requested by arbitration, reported explicitly, documented and pinned before GREEN. The supplied old tests remain compatible. Whether any unsupplied consumer parses the old complete string—including `agents/shared/wind-down-protocol.md`—is not established. Calling this a *silent* change is unwarranted. A separate GREEN commit might ease review, but RED-before-GREEN was satisfied and arbitration requested the fold in the same commit.
- **Scope/read decorators:** `_guard_scope` remains applied through `tool()`. Absence of `@consistent_read` matches #11 and is not a demonstrated defect; no binding requirement here demands it for these operations.

### #12 test audit — coverage is strong, with bounded claims

- `forbid_store` now blocks the named authoring/evaluation writers. Patching `evaluation.evaluate_plan` catches the supplied seam’s module-qualified lookup. It would **not** catch a previously captured `from … import evaluate_plan` alias.
- The fixture is not a general access sandbox: reading constants such as `CHECKPOINT_PHASES` is not trapped, and coverage of `store.load_plan_text` cannot be established because the original fixture’s full name list is omitted. The architecture guard complements these runtime tripwires.
- Creating fixtures through `create_study_plan` and `update_study_plan` is appropriate integration coverage rather than circular proof: assertions inspect persisted state and seam results. F4 distinguishes unchanged observable state from zero writer invocation.
- Returning `False` from `plan_index.record_checkpoint` demonstrably exercises the seam’s failure-reporting path. Whether all real operational database failures become that return value is not established; the test does not prove exception conversion inside the real writer.
- `test_phase_four_responses_are_fresh_containers` soundly proves fresh top-level mappings. It does not prove nested independence; add nested mutation coverage if the view contract is not already pinned elsewhere.
- All ten mcp-server scenarios have corresponding tests. Tests additionally cover schema restrictions, unknown phases, fallback errors and unchanged learning-record success shape; these fit the normative requirements and need not each become a scenario.
- A useful additional test is `test_evaluate_document_failure_reports_saved_database_and_failed_document`: inject the document-sink failure and assert retained checkpoint rows, `document_write="failed"`, warnings and `recording_complete=False`. The supplied real-seam failure test covers only the opposite direction.

### #13b persona and projection audit — preference is not capability provisioning

- The nine lifecycle rows plus separate `record_plan_learning` correctly describe **ten available plan-related tools**, without changing D-9.
- Omitting optional `plan_id`, `history_limit` and learning-record `status` creates valid abbreviated call examples, not incompatible signatures. Label them as examples if full schemas are not intended.
- “A taken id is a conflict” agrees with the binding no-overwrite contract. No `overwrite` argument was introduced.
- Tool-list membership is a decidable selection rule when the harness exposes available tools. It is not permission to reinterpret runtime refusal or temporary failure as “missing” and retry through the CLI.
- The stated CLI inventory supports the fallback limitations: `milestone` changes completion, not arbitrary milestone definitions. Requiring the seam or Web UI for edits is consistent with Markdown being canonical storage; canonical does not mean unrestricted hand-editing.
- “Do not create as `active` to skip the gate; the seam refuses it” should be narrowed to “the same readiness gate still applies.” Whether every ready active-create request is refused is not established, and that blanket interpretation should not be taught.
- The persona correctly describes readiness-gated activation. It must not imply that `update_study_plan(status="active")` bypasses resulting-document validation or that an unchanged status exempts an active husk; that is the inherited contract.
- “Never on a retry” is conservative deletion policy, not a claim of idempotent delete success. After an uncertain outcome, inspect/reconcile; do not automatically replay a destructive call. The seam’s `not_found:` on a confirmed repeat is compatible with that advice.
- `_section` closes a level-three section at the next level-one, -two or -three heading, correctly handling this layout.
- Projection equality protects all three bodies. The manifest test covers only entries returned by `TRACKED_FILES`; whether Kiro’s directory copy is among them is **not established by the brief**. Only Claude and OpenCode hash changes are shown, so the manifest test should not be credited with Kiro coverage without evidence.
- The two streams agree on refusal prefixes, preview semantics and recorded sink results. The persona’s shorthand “persists” should point agents to `recording_complete` and warnings rather than promise unconditional durable success.
- `tasks.md` was shared integration bookkeeping; `.secrets.baseline` belongs to #13b and is not shown as jointly edited. Its reported changes concern public projection digests, not demonstrated credentials. The supplied merged checks establish compatibility, not a merged full-suite result.

## 3. Spec/doc review

| Item | Assessment and correction |
|---|---|
| mcp-server progression/deletion requirement | Matches the supplied adapter implementations: one call, explicit milestone state, preview default, hidden `append_to_plan`, ordinary optional confirmation and retained checkpoint history. |
| Ten scenarios | Covered. The preview scenario should explicitly begin with empty history before requiring empty history afterward; otherwise “unchanged” is the correct general assertion. |
| “Rewrites nothing” | The supplied seam short-circuit implements it, but the integration test’s content equality alone does not prove it; add F4’s writer-spy test. |
| Amended `record_plan_learning` requirement | Correctly documents prefixes, blockers, already-active hint, chained cause and unchanged success shape. Fix “other eight” terminology. |
| Delete result example | Replace malformed shorthand ``{"deleted": true, "plan_id"}`` in the table with ``{"deleted": true, "plan_id": "<id>"}``. |
| Agent-adapters requirement | The shipped persona meets MCP-before-CLI ordering and enumerates supported CLI fallbacks. The provided delta has **three scenarios**; the agent’s “4 scenarios” report is inaccurate. |
| “Activation … the seam refuses it” | Clarify that readiness is enforced regardless of entry point; do not imply an unsupported blanket ban on ready active creation. |
| Missing-tool routing | Make the exception explicit: when no CLI equivalent exists, offer the Web UI or explain the missing capability. Do not mandate a nonexistent fallback command. |
| Projection/manifest scenario | Correct if “every projection it tracks” remains explicit. There is no projection generator, and manifest coverage must not be conflated with the separate three-body equality test. |
| `STUDY_ID` and shell commands | Shipped instructions whose runtime prerequisites are not specified by these delta requirements; resolve as F2 before claiming a complete ACP journey. |
| Duplicated count constants | Test organisation, not an externally observable requirement; no spec addition needed. |
| Public install documentation | Tool names and progression semantics are accurate; F3’s capability/parity correction remains necessary. |

`__cause__` is testable **in process**, as the refusal tests demonstrate. It is not serialised through stdio, so the spec should distinguish:

- Python adapter requirement: `ToolError.__cause__` is the original domain error.
- MCP transport requirement: an error result carries the prefixed refusal text.

The transport test must not be required to recover an exception object or chain that the protocol does not transmit.

## 4. Phase 5/6 hazards

### #14 — launch, attach and reconnect through one session path

**Request contract:** The Plans-view affordance in `web/static/js/components/plans-panel.js` must initiate one existing session-start flow with:

```json
{
  "purpose": "planning",
  "topic": ""
}
```

A real selected subject may replace `""`; `topic` must not be omitted. Preserve the current picker’s validated **energy, agent and transport** selections/defaults. Their concrete permissible values and defaults are **not established by the brief**, so #14 must not invent or hard-code a new combination.

On `201`, consume the returned `ws_url` through the existing console/connection owner. Do not construct an alternate socket URL or let both the Plans panel and timer attach listeners.

**Reuse:** `plans-panel.js` should invoke the shared start/attach flow currently reached from `session-timer.js:230` and `components.js:3365`. Extract a shared orchestration function if necessary; do not duplicate POST handling, conflict handling, console creation or WebSocket subscription logic in the Plans panel.

**Purpose label:**

- Initial launch: read `purpose` from the `201` response.
- Refresh/reconnect: read persisted `purpose` from `GET /api/session/state`.
- Legacy sessions: retain `_dashboard.py`’s default `"focus"`.
- Never infer planning from `"Study plan"` or another topic string.

**CLI correction:** At this base, `cli/_plan.py:479` starts an architect without writing purpose, so reconnect labels it **focus**. #14 should explicitly fix the CLI writer to persist `purpose="planning"` through the session-state path. Do not teach the dashboard to infer it.

Add new tests rather than modifying the protected legacy modules:

| RED test | Appropriate evidence |
|---|---|
| `test_plan_with_architect_click_posts_once_with_planning_purpose` | Playwright using `tests/_playwright_helpers.py`; capture request count and payload. |
| `test_planning_console_label_survives_reload` | Playwright with real session state; initial label, reload, reattachment label. |
| `test_architect_launch_uses_one_console_and_one_websocket` | Playwright instrumentation; one console instance and one connection/listener owner per active attachment. A refresh necessarily replaces the connection. |
| `test_manual_new_plan_still_works` | Playwright regression of the existing manual flow. |
| `test_planning_launch_conflict_preserves_409_reattach_contract` | FastAPI `TestClient` for response shape; browser test for following `reattach_url` without creating another session. |
| `test_planning_start_delivers_structured_brief_without_creating_plan` | `TestClient` plus `STUDYLOOP_TEST_AGENT_CMD` / `STUDYLOOP_TEST_ACP_CMD`, parametrised by transport; assert three headings, purpose, zero new plan documents/rows. |
| `test_cli_architect_persists_planning_purpose_for_web_reconnect` | CLI launch fixture plus state endpoint; verify explicit persisted purpose. |
| `test_focus_topic_study_plan_is_not_relabelled_planning` | `TestClient`; topic text cannot override focus purpose. |

Use a new browser module, for example `tests/test_web_plan_architect_browser.py`, marked `e2e`. These tests are deselected by default, so the verification receipt must show an explicit browser run. Browser DOM assertions alone cannot prove ACP prompt ordering; F1 needs the fake agent’s captured protocol.

### #15 — verification receipt and combined journey

`scripts/verify/plan_integration.py` should record the reviewed revision, each command, exit status and relevant measured output. It should fail on a failed required check rather than merely write a receipt.

For Phase 4, include:

1. **Real stdio inventory:** exactly **32 unique advertised names**, all nine design-§4 tools, `record_plan_learning` and `CORE_TOOLS`. Record the actual name list. The in-process twin is supplementary, not a substitute.
2. `tests/test_mcp_plan_tools.py`, `tests/test_plan_architect_persona.py`, `tests/test_mcp_next_action.py`, and the correction tests. Explicitly retain the learning-record prefix/cause tests; losing `not_ready:` must fail verification.
3. `tests/test_architecture_plan_seam.py`: 30 accepted-base tests, plus any agreed correction to the facade policy.
4. Golden SHA-256:
   `ec451ce8857c8a72e398e3054e3c060cd3b5b13ecb29e29cba3822dc192503c0`.
5. Protected-file diffs against their designated bases:
   - `3a4f6b01`: `test_web_plans.py`, `test_cli_plan.py`, `test_planning_evaluation.py`.
   - `0a20a796`: `test_learning_decision.py`, `test_web_now.py`, `test_recap_mastery_voice.py`, `test_web_session_start_pty.py`, `test_web_session_start_acp.py`, `test_web_session_ws.py`, `test_agent_launcher.py`.
   - Each must have zero changed lines.
6. Adapter-scoped import invariants: zero forbidden `planning.store|index|authoring|evaluation` imports, covering both import spellings; zero literal `build_canonical_persona("focus"` calls under `web/routes/session`. Retain the architecture guard because text searches are not a complete semantic proof.
7. Projection equality and manifest verification. At `b2f37fa4`, the shown hashes are Claude `c4ae64c9c86f9235` and OpenCode `e455bb970b1e4fc7`; regenerate and record new hashes if corrections change the persona.
8. Merged-tree full suite, explicit stdio integration, explicit browser tests, JS tests, lint/typecheck, OpenSpec validation and strict documentation build. The branch-only 4949-pass report is not a merged-tree receipt.

**T6.3 combined journey:** Add `tests/test_plan_integration_journey.py::test_planning_web_session_and_mcp_authoring_share_one_journey`.

In one isolated scope and asynchronous test flow:

- Start a planning-purpose Web session and observe `201`, purpose and attachment.
- Verify structured, bounded brief delivery before the first user prompt.
- Assert session start alone creates no plan.
- Connect a real MCP client to the same isolated scope; call `get_planning_interview`, then `create_study_plan` for a draft.
- Verify the returned plan is visible through the Web Plans API.
- Preview an evaluation; assert both sinks `not_requested` and unchanged document/history.
- Reconnect and retain the planning label.
- Clean up client/session tasks; assert no nested-event-loop exception and no second console/session.

Simply launching unrelated Web and MCP tests in the same command would not prove integration.

### Harness-started Kiro/Claude — documented boundary, owned by Phase 6 T6.1

**Decision:** This is a **documented capability boundary**, not a Phase-4 implementation defect.

The persona explicitly conditions MCP use on inventory availability and supplies fallback guidance. Kiro’s no-server pin predates #13b and was sealed “by design”; #13b had no mandate to rewrite those permissions. The documentation nevertheless needs F3’s disclosure. Web rendering the canonical body does **not** itself establish MCP connectivity.

**Owner:** Phase 6 T6.1’s harness/install-contract owner, with a human permission decision.

If T6.1 promises MCP-capable harness-started architects:

- `agents/kiro/study-plan-architect.json`: add the `studyloop` server using `studyloop-mcp`, and configure the nine `mcp_studyloop_*` plan-tool names using the harness’s permission mechanism. Also decide access for retained `record_plan_learning`; do not accidentally leave wind-down on a different capability path.
- Preserve explicit learner confirmation for deletion; transport/tool permission is not user authorisation.
- `agents/claude/study-plan-architect.md`: prefer a least-privilege explicit MCP tool allow-list over dropping the list wholesale.
- Update `tests/test_install_agent_contracts.py:701` deliberately, not by silently removing the assertion.
- Preserve projection bodies, installation symlinks and manifest/doctor checks.

**RED tests:**

- `test_install_kiro_architect_connects_studyloop_and_allows_plan_tools`.
- `test_install_claude_architect_allows_plan_mcp_tools`.
- `test_installed_architect_can_discover_and_call_get_planning_interview`.

Configuration assertions prove shipped permissions; the final smoke test proves actual tool availability where harness integration testing is supported. If the product decision is to retain CLI-only architects, keep the pin and document their revision/deletion limitations instead.

## 5. Process finding

**The human-owned judgment should have been whether harness-started architects gain MCP mutation permissions.**

Leaving the headers untouched was the correct local ownership decision, but the programme needs an explicit capability decision: keep Kiro/Claude architects intentionally CLI-limited, or grant authoring, lifecycle and destructive-operation tools under a defined permission model.

That decision changes user-visible reachability and security posture, unlike harmless temporary `_LANDING_WITH_12` scaffolding or public-hash baseline maintenance. Record it in T6.1 with named ownership, supported-harness expectations, deletion-confirmation policy and the install/smoke tests above.
