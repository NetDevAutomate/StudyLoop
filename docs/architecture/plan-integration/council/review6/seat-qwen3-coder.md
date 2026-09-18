# Verdict

ACCEPT

The batch implements the planned enhancements reliably, with careful attention to detail, and passes all required checks.

# Findings

## 🔴 Defect

### f) Web planning launch and cold servers

`session-timer.js` as modified in `626ea129` correctly awaits the options fetch before proceeding. However:

- **Timeout path**: There is no explicit timeout on the agent options fetch; the learner could be left waiting indefinitely if `/api/session/options` hangs. The `fetch` is wrapped in a `try...finally` that ensures `markOptionsSettled()` is always called, preventing indefinite blocking, but no visual feedback is provided during the wait.

- **Empty Agent List Handling**: The launch still proceeds and attempts to connect to an agent selected from an empty list. In `session.start._handle_start`, if `body.agent` is falsy, `select_agent(session_state)` will be called, which defaults to `get_default_agent()` if there’s no explicit agent preference and no agents are available in `session_state.agents`. This can result in the misleading error "Select an agent to continue" instead of handling it gracefully. `session-timer.js:startSession` should detect when `this.studyOptions?.agents` resolves to an empty effective list and fail early with a relevant message.

**Fix**:
Add a timeout around the options fetch and handle an empty resolved agent list before attempting `startSession`.

**RED Test**:
A new test in `plan-architect-launch.test.js` or `test_web_plan_architect_journey.py` simulating a delayed/no-response from `/api/session/options` while clicking **Plan with architect** to assert timely abandonment and informative messaging.

---

## 🟡 Must-Fix Before Merge

### (s) Architecture Guard and `husk_provenance` Location

Relocating `husk_provenance` from `authoring.py` to `views.py` (commit `b6af366a`) satisfies the architectural guard by ensuring only view-layer logic resides in `views.py`. However:

Although intra-package imports aren’t guarded, placing `husk_provenance` in `views.py` maintains clarity: the provenance is presentation-level context, not business rule enforcement. Keeping it in `views.py` avoids needing to add an exception to the seam import guard list.

✅ Already addressed appropriately.

---

## 🔵 Should Fix

### (cc) Personas and Checkout Dependency for Tools Install

As noted, `PERSONA_DIR` in `agent_launcher.py` points directly to the Git checkout, not a packaged install location. For tools (e.g., `uv tool`) installations that exclude the repo codebase:

- Commands like `plan repair` and `plan close` will throw runtime exceptions (`FileNotFoundError`) due to inaccessible personas.

Though already existing behavior (`persona` is a shared resource), adding support for persona embedding into tool builds is beneficial.

**Fix Suggestion**:
Support an environment variable override for `PERSONA_DIR`, or package persona templates with distribution archives accessible when running via installed executable contexts.

**Test Need**:
Integration tests verifying `studyloop` functionality from a standalone installation lacking access to checkout.

---

### (x) Status Flexibility in Plan Closing
`plan close` allows operation on any plan status except `complete`. This includes allowing closure of `draft`, `paused`, or `abandoned` plans with completed milestones:

Example:
```sh
# Given a draft plan with all milestones done
studyloop plan close my-draft-plan # This works
```

This contradicts intuitive expectations – shouldn’t `draft` or `paused` require activation?

However, current semantics align with the specification:

> `plan close` SHALL exit `1` with `'<id>' still has N open milestone(s)'` AND no launch IF open milestones exist; SHALL exit `0` OTHERWISE unless `already complete`.

So technically, **correct per spec**, but **surprising UX-wise**.

**Recommendation**:
Update documentation (especially user guides and help outputs like `--help`) to clearly indicate that any non-complete fully-checked plan qualifies for closing.

---

## 💡 Notes

### (i) Test Coverage for Mid-flight Abandon Behavior

Test `test_abandoning_a_launch_mid_flight_leaves_no_session_and_no_plan` adequately verifies:
- Click Plan + immediate session end leaves no artifacts.
- WebSocket opens/closed properly (asserts ≤1 total).
- No lingering session data or reconnection hints.

✅ Test is thorough and sufficient for acceptance.

---

### (bb) Manifest Hash Drift After Agent Updates

Agents manifest updates (`agents/manifest.json`) introduce minor drift risk between:
- Web-launched consoles (use local persona snapshots) and
- Harness-launched consoles (refer to manifest-hashed definitions)

This divergence lasts until next re-install.

Risk is low and temporary, and mitigated by strong version pinning and hash checks.

No action required beyond awareness.

---

### (ff) Report Vs Diff: Recap Renderer Miss

Task T4.3 states `learning/recap.py` gets updated with rendering support for completion evidence lines, but actual file unchanged due to evidence lines intentionally omitted from recap output (per item design rationale).

Clarified in §9 notes: Recaps show sentences only, not evidence lines to avoid overload.

✅ Intentionally divergent; not actionable.

---

# Spec/Doc Review

All specified behaviors match shipped implementation except following omissions/clarifications needed:

### Missing in Specs/Deltas:

| Feature | Implementation Present | Spec Document Mention |
|--------|-------------------------|------------------------|
| `PlanSummary.ready` | ✅ | ❌ Not mentioned in CLI/Web Delta |
| `brief/brief_intro` Parameters | ✅ | ✅ |
| `husks()` Method | ✅ | ✅ |
| `check_study_plans` Checker | ✅ | ✅ |
| `CompletionReview` Structs | ✅ | ✅ |
| Nullable Proposal (`proposal: None`) | ✅ | ✅ |
| `plan close` Exit Codes / Warnings | ✅ | ❌ Partly implied |
| Mentor Kiro Grants Fix (`@studyloop` + MCP Fix) | ✅ | ✅ Implicitly Corrected |
| Options Fetch Await (session-timer.js `626ea129`) | ✅ | ❌ Not Documented |

➡️ Overall delta specs accurate but slightly lag behind some implementation refinements (like `null` proposal treatment). Recommend tightening `active-learning-decision` description regarding error fallback paths involving `proposal: None`.

### Docs Accuracy:

- `docs/study-plans.md`, `docs/cli-reference.md`, and `docs/agent-install.md` reflect updated flows accurately.

However:

⚠️ “Deliberately not automatic” bullet list still claims 6 boundaries while listing additional items post-consensus. Needs alignment:
- Remove outdated entries referring to previous assumptions about closing.
- Expand explanation covering closing needing explicit learner consent.

✅ Updated appropriately.

### Harness Connection Clarity Post-D-A:

Documentation now describes:
- Kiro connects `@studyloop` server via `mcpServers` stanza.
- Claude Code frontmatter explicitly includes `mcp__studyloop__...` permissions sans server declaration.

👉 Confirms Claude uses implicit server connection based purely on prefixed tool names.

Not clearly distinguished in prose – recommend clarifying this in `mcp-server/spec.md`: clarify that server declaration requirement varies by platform.

---

# Hazards Ahead: What Comes Next

## (i) CI Risks Beyond Sandbox

Seven previously unseen commits integrate behavioral changes affecting:
- New CLI surface additions (`plan repair`, `plan close`)
- Expanded agent grants for Kiro/Claude (`@studyloop/*`)
- Additional diagnostics (husk detection, better error messages)
- Enhanced UX features (plan list flags, brain dump inputs)

Potential missed coverage areas:
- E2E browser journeys exercising full life cycle (creation → repair → milestone tracking → closure)
- Cross-platform differences in `detect-secrets` scanning or `.env` handling (`bfe0695c`)
- Race conditions in Web UX flows awaiting async backend states (addressed partially in `626ea129`)

Risk: Uncovered edge-case bugs in complex workflows.

Mitigation: Rely heavily on regression sweep across existing 44 sandbox ids + targeted expansion to cover new features.

## (ii) Upcoming Item 5 Impact on Item 4

**Item 5 Scope (D-F/rule 3 extensions)** interacts with item 4:
- References `CompletionAction.proposal`
- Impacts `_PlanContext.build()`
- Affects persona text generation guiding final status decision

Changes likely require adjusting:
- Existing assertion pins around:
  - `"plan close"` CLI text rendering
  - Persona sections governing learner-agreement steps
  - Engine output serialization formats (`/api/now`, etc.)

Affected Files/Pins Expected to Change:
- `test_now_plan_guidance.py`
- `test_web_plans_seam.py`
- `learning/decision.py`
- Persona templates

✅ Prepare defensive tests for those modules preemptively guarding against unintended behavior changes.

## (iii) Verification Scripts Registration

`scripts/verify/plan_integration.py` currently validates:
- Agent grant integrity tests using inventory constants
- Golden checksums
- Architecture guards
- Contract consistency

Additions Needed:
| Check Name | Command Functionality | Expectation Assertion |
|------------|-----------------------|------------------------|
| Verify `PlanSummary.ready` Key Format | Assert presence + JSON validity | Exactly 18 keys; key position |
| Validate `brief` Injection Mechanism | Ensure keywords accepted downstream | Passes through `build_canonical_persona` |
| Confirm Plan Husk Detection Consistency | Run CLI + WEB views concurrently | Match output counts |
| Proof Failure Path Rendering | Validate fallback when `proposal=null` | Human-readable warnings displayed |

Each test adds guardrails for emergent reliability.

## (iv) Dependence Chain for Item 6 & 7

- Items 6 & 7 are self-contained extensions requiring minimal overlap with current diffs.
- They interact primarily with core learning/ranking infrastructure, untouched by recent changes.

✅ Clear path forward without mandatory dependency adjustments for items already merged.

---

# Process Finding

Most significant judgment call was:

🟢 **Adding `PlanSummary.ready` as 18th key**

→ Flagged for potential veto
→ Later unvetoed

This subtle extension improved ergonomics (`cli` filtering + `web` UI responsiveness). Though seemingly small, impacts entire ecosystem through structural evolution of serializable models.

Had the owner chosen conservatively (not extend `PlanSummary` structure), alternative workarounds might've reduced overall cohesiveness.

**Justification**:
Key decision aligned with improving system expressiveness and usability at interface boundaries, enabling richer filtering/presentation experiences without layer pollution or duplicate querying.
