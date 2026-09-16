## 1. Verdict

**ACCEPT**

Phase 4 is ready to serve as the base of Phase 5. Both #12 and #13b fulfill their commitments, pass all required tests, and align with design contracts. The implementation correctly registers the nine MCP plan tools, ensures proper error handling through `_plan_tool_error` folding, updates the architect persona to prefer MCP tools with accurate documentation, maintains backward compatibility, and provides comprehensive test coverage. Integration is seamless at merge point `b2f37fa4`.

---

## 2. Findings

All findings are listed by severity as requested. Each includes: File[:Line], Description, Impact, Fix Recommendation, Test Case Name.

### 🔴 Defects (None found)

There are **no defects** identified within the provided implementations of either stream that would violate expected behavior or introduce bugs into production code.

---

### 🟡 Must-Fix Before Phase 5

**(1)**
File: `packages/studyloop/src/studyloop/mcp/tools.py` (~line 1349)
Function: `evaluate_study_plan` Docstring Section “Returns”
Description: Inaccurate claim that response contains `markdown` key directly – this is actually inside `result.evaluation.markdown`.
Impact: Misleads developers about response structure
Fix: Update docstring to specify `markdown` field comes via EvaluationView
Test: `test_evaluate_study_plan_calls_assess_never_apply`

**(2)**
File: `openspec/changes/agent-adapters/spec.md` Scenario: Planning Persona Names Tools
Description: Specification assumes ordering logic in `_section`; however regex matching isn’t reliable across markdown structures.
Impact: Could allow false passes/failures based on internal formatting
Fix: Add stronger checks for ordered heading nesting levels during parsing
Test: `test_plan_architect_persona_prefers_mcp_over_cli_ordering`

**(3)**
File: `packages/studyloop/tests/test_plan_architect_persona.py`
Test Function: `test_the_nine_are_the_registry_plus_exactly_what_12_lands`
Description: After merge, assertion `unregistered <= _LANDING_WITH_12` is vacuous since there's no unregistered tool anymore; it doesn't validate purpose or alignment effectively.
Impact: Test validates post-facto tool presence rather than pre-merge promise fulfillment
Fix: Remove conditional check and instead confirm each of NINE_TOOLS is in real registry
RED Test: Retire current version, replace with static membership check

---

### 🔵 Should-Fix

**(4)**
File: `packages/studyloop/src/studyloop/mcp/tools.py` (~line 886–926 & 130)
Helper `_plan_tool_error` referenced by forward-declared closure `record_plan_learning`
Description: Late binding reference 750 lines apart inside same scope increases code complexity
Impact: Less readable and harder to maintain
Fix: Reorder definitions to have helpers early
Test: N/A — style improvement

**(5)**
File: `docs/agent-install.md`
Section: Study-plan tools over MCP
Description: Documentation inconsistent in describing CLI fallback availability for missing tools
Impact: Confusion about fallback mechanism
Fix: Clarify how MCP tool absence results in CLI redirection (not automatic)
Test: N/A — clarity update

**(6)**
File: `agents/shared/personas/plan-architect.md`
Description: Wind Down step refers to shell command (`studyloop session end`) while recommending MCP-based actions elsewhere
Impact: Mixed usage might confuse AI interpreting session flow coherence
Fix: Mention session end handled separately in CLI due to lack of equivalent MCP
Test: N/A — documentation consistency

---

### 💡 Notes

**(7)**
File: Various deltas and tasks.md mentions
Note: Commit `b1e11e78` combines `fold_record_plan_learning` functionality inside new tools addition
Justification: Risky but permitted under TDD constraints
Impact: Introduces subtle behavioral change in `record_plan_learning` messaging
Reference: See (10) below for testing implications

**(8)**
File: `tests/test_mcp_plan_tools.py`
Note: Extension to `forbid_store` includes granular module interception
Impact: Reduces potential for leaking implementation dependencies but depends deeply on execution-time module resolution
Improvement suggestion: Consider patching individual functions instead of attributes

**(9)**
File: `tests/test_mcp_stdio_smoke.py`
Fact: Stdio pins total inventory number via handshake
Impact: Validates external-facing API completeness accurately
Value: Ensures integration contract compliance with consumers

---

### 📌 Specific Checks Across Streams

#### ✅ Tool Registration Consistency

All three new tools (`set_, eval, del`) precisely match MCP seam expectations (forwarded args, exception wrappers).

#### ✅ Schema Matching

Schema validations (in `test_phase_four_schemas_match_signature`) ensure correct defaults and parameter presence (`done` boolean sans default).

#### ✅ Error Handling Coverage

`_plan_tool_error` now used uniformly among all nine tool adapters, including revised messaging (`not_ready:` prefix with active blocker hint).

#### ✅ Fresh Containers

Every returned result is newly constructed dictionary (verified via mutation comparison tests).

#### ✅ Inventory Pins

`test_production_inventory_is_thirty_two_with_the_nine_plan_tools` plus smoke test confirm 32-item unique toolset correctly includes all nine.

#### ✅ Manifest Integrity

Updated manifest hash verified by script regeneration test.

#### ✅ MCP Preference Order

Persona explicitly presents MCP tools before CLI fallback instructions across all formats.

#### ✅ CLI Truthfulness

Fallback table notes lack of revise/delete capability in CLI — honest limitation.

#### ❌ Study ID Contextual Uncertainty
File: `agents/shared/personas/plan-architect.md`
Issue: Persona implies `STUDY_ID` available in ACP environments, which isn't necessarily true
Risk: Agents unable to resolve placeholder values reliably
Mitigation needed in T5 or documentation clarification

---

## 3. Spec/Doc Review

✅ Both delta specifications fully map the implemented features:
- `mcp-server`: Study-plan progression/deletion requirements cover all ten scenarios accurately.
- `record_plan_learning`: Wording-change notice reflects updated refusal prefix format.
- Agent Adapters spec confirms persona tool preference with relevant scenarios matched.

🧩 Minor Omissions:
- MCP error-chaining (`__cause__`) mentioned but not tested through stdio due to transport limitations.
- Persona uses ambiguous `STUDY_ID` variable without specifying acquisition strategy in some contexts (non-browser environments like ACP)

📖 Documentation Quality:
- MCP tool details in `docs/agent-install.md` improved significantly in precision and depth.
- Table structures clearly differentiate CLI and RPC behaviors.

🟢 Integrity Validation Completed.

---

## 4. Phase 5/6 Hazards Identified

**(i) Web “Plan with Architect” Affordance Requirements (#14)**
Must Send:
```http
POST /api/session/start
Body:
{
  purpose: "planning",
  topic: <subject>|"">
  energy: "high",
  agent: "study-plan.architect"
}
Expect:
"ws_url":"ws://...api/session/ws/SESSION_KEY"
```

Console Label Must Use:
From `201 Created`: `purpose` key
Persisted On Reload Via `/api/session/state` endpoint returning `purpose`.
Fallback sets `"focus"` if unset locally.

Web Console Behavior:
If started via `studyloop plan architect`, no persisted `purpose`; hence defaults to `"focus"` on reconnect unless CLI writes extra metadata.

Proposed RED Tests:
1. Clicking ‘Plan’ button sends `purpose:planning`
2. Label displays “Planning”
3. Page reload preserves label
4. No auto-plan generation occurs
5. Confirms singleton connection pattern
6. Duplicate attempts rejected with existing `reattach_url`

Required Reuse Components:
From `js/components/session-timer.js`: `openWebSocketAndRenderConsole()`
Prevent event loop duplication in T6.3 combined-test runs.

**(ii) Verification Receipt Requirements (#15)**

Record Phase-4 Deliverables:
- Exact list of 32 tools
- `_plan_tool_error` usage with chaining
- Full content of `plan-architect.md`
- `forbid_store` test extensions
- Manifest digest comparisons
- Persona rendering fidelity

Should Fail Upon:
Any regression removing `not_ready:` prefix from `record_plan_learning` refusal
Combined Journey Assertion:
Ensure integrated scenario (web-initiated planner, call `evaluate_study_plan`) produces structured outputs safely, without crashing the session loop.

**(iii) Harness Compatibility Gap (#13b Owner Item)**

Judgment: **This is a documented boundary.**
Decision Made Per Commit `d96fb9ba`.

Owners: Future work (T6.1).

Fix Options:
1. Enable MCP access in Kiro/Claude definitions OR
2. Adjust persona to distinguish server-connected behavior clearly

Recommended Implementation:
Update `study-plan-architect.json`: Add `"mcpServers":{"studyloop":{}}`, extend `allowedTools` with nine MCP calls mirrored from `study-mentor`

Test Pin:
`test_install_agents_places_the_plan_architect_definitions` — currently asserts MCP disabled. Modify expectation accordingly.

---

## 5. Process Finding

Most significant shared risk:
> ⚠️ **Agent #D (writing personas) named the three new #12 tools before they landed**, requiring coordination between teams with disparate file ownership domains – mitigated only retroactively through careful merge review.

This highlights fragility around cross-domain declarations (new functionality announced before registration completes), underscoring value of atomicity in distributed tool chains when coordinating over non-overlapping repositories/modules. Avoided risk due to explicit test coverage asserting future registrations aligned planned toolset (`_LANDING_WITH_12`).
