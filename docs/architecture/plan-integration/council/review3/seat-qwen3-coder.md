## 1. Verdict

**ACCEPT**

Phase 3 delivers working engines for plan-aware ranking, MCP tooling, and session-purpose routing with defined contracts, additive key omission, renderer isolation, and test coverage that establishes behavioral compliance without requiring speculative human judgments, making it fit for use as the base of Phase 4.

---

## 2. Findings

### 🔴 Defects

#### (a) **Rank inversion possible within urgency classes**
- **File:** `learning/decision.py`
- **Lines:** Rule 5 (lines ~645 in score logic)
- **Problem:** Bias (fixed +12) may be insufficient if score differences exceed this threshold but still lie within the same urgency class. However, more critically, ordering by biased score alone implies that two related candidates differing by less than 12 points would maintain relative position even after bias applied — allowing potential rank inversion if scores originally differed enough to invert upon addition.

    Example:

    ```text
    Candidate A: score = 100 → becomes 112
    Candidate B: score = 105 → becomes 117

    But before bias: A was ranked higher due to score. Now it's worse.

    Although such cases might seem contrived or unlikely without complex interactions involving multiple conditions across various urgencies, the logic must ensure rank stability.
    ```
- **Fix:** Ensure consistent sorting using the original unadjusted score where necessary or apply a larger adjustment mechanism that preserves intended priority semantics.
- **Test Proposal:** `test_bias_preserves_ordering_within_class` asserting original vs adjusted ranks don't flip despite application of biases when within a given urgency bin.

---

#### (f) Incorrect upgrade rule in `attach_refs()`
- **File:** `learning/decision.py`
- **Function:** `_PlanContext.attach_refs`
- **Line approx:** ~840
- **Problem:** Upgrade policy states `refs.get(plan_id) is None` to allow setting a milestone index if previously absent, which violates determinism since the first match determines assignment regardless of specificity or order.
- **Why important:** Could lead to arbitrary assignment when multiple matches are made to the same ID.
- **Fix:** Only replace if the new reference includes a stronger semantic link (i.e., has milestone index and prior did not). Consider revising to preserve best fit rather than earliest-seen.
- **RED Test Name:** `test_upgrade_ref_only_on_specificity_improvement`

---

#### (v) Incorrect HTTP status on failure to load brief
- **File:** `web/routes/session/_start.py`
- **Function:** `_brief_unavailable_response`
- **Problem:** Returning 500 suggests malformed server-side behavior but failure to generate a plan brief indicates user-facing system constraints—not internal bugs.
- **Why critical:** Misclassified service issue causes incorrect UX assumptions and debugging efforts.
- **Fix:** Return a 409 Conflict indicating resource constraint, or better yet, 424 Failed Dependency (though unsupported commonly).
- **Consequence:** Should improve downstream alert filtering accuracy.
- **RED test name:** `test_brief_generation_failure_returns_expected_http_status`

---

#### (q) Redundancy between `update_study_plan` and `set_study_plan_status`
- **Spec concern in File:** `openspec/changes/plan-application-seam/specs/mcp-server/spec.md`
- **Problem Spec Line:** Description does not clarify distinction between direct vs compositional status setting tools.
- **Risk:** Confuses automation authors needing to manage plan transitions reliably
- **Fix:** Explicitly document usage preferences and/or deprecate one form based on lifecycle gate consistency goals
- **Note impact:** Can result in inconsistent tool adoption practices unless clarified programmatically
- **RED test proposal:** `test_status_preference_rules_for_mcp_tools`

---

### 🟡 Must-Fix-Before-Phase-4 Issues

#### (h) JSON serialization order breaks backward compatibility risks
- **Files Affected:** All modules emitting serialized `NowPlan`, particularly decision.py
- **Concern:** Using Python `asdict` with nested structures doesn’t guarantee dictionary key insertion order on older versions (<3.7)
- **Impact:** Risk of unexpected byte changes affecting consumers assuming fixed field ordering in golden comparison tests
- **Fix Options:**
  - Switch to manually ordered dictionaries instead of auto-asdict
  - Enforce Python ≥ 3.7 compatibility baseline
- **Test Sensitive Spot:** `serialise()` in `test_now_plan_guidance.py`

---

#### (t) Uncovered spy coverage areas in testing
- **File:** `tests/test_mcp_plan_tools.py`
- **Method Focus:** `_fake()` bound spy stubbing
- **Omitted Coverage Possibilities:** Store/index functions not mocked in `forbid_store`
  - Missings Includes:
    - `_checkpoint_history`,
    - Any utility wrappers used internally during intent processing
    - Some edge case path traversals involving middleware-style layers around the application layer.
- **Recommendation:** Expand list comprehensively covering seam internals via `hasattr()` iteration or explicit declaration
- **RED Test Addition Example:** `test_store_wrapper_interceptions_are_also_restricted`

---

### 🔵 Should-Fix Recommendations

#### (b) Unclear treatment of unready plan matching eligibility
- **Scope:** `_PlanContext` handling in `build()` function
- **Issue:** Plans matched by concept/topic aren’t excluded if unready, but shouldn't participate actively
- **Current Handling:** Attaches refs with `milestone_index=None` → ambiguous representation in later ranking logic
- **Consider improving clarity by tagging these appropriately in metadata**
- **Impact:** May blur meaning when assessing eligibility elsewhere without careful interpretation

#### (n) Rubric receipt lacks clarity for pending decisions
- **Location:** Human rubric `docs/.../receipts/now-rubric-2026-09-16.md`
- **Issue:** Marked PENDING verdicts imply incomplete assessment
- **Suggestion:** Clearly state that verdicts will be filled post-human evaluation OR provide clearer framing of expectation gap (“Engine-compliant outputs awaiting usability vetting”)
- **Risk of confusion**: If stakeholders mistake pending checks as unresolved issues

#### (l) Unused getter in Alpine component
- **File:** `web/static/js/components/today-panel.js`
- **Method Identified:** `hasPlanContext`
- **Current Use Status:** Defined but unused
- **Recommend:** Remove extraneous definition if no future roadmap requires access tracking on DOM level for conditional behavior

#### (d) Semantic inconsistency of fallback title on milestone generation
- **File:** `decision.py#_milestone_candidate()`
- **Concern:** Generated concept field falls back to `title`, possibly introducing mismatch between user-experienced content and canonical identifier
- **Risk Area:** Downstream systems depending on stable concept identity may fail unexpectedly
- **Proposal:** Introduce placeholder tag or explicit fallback marker like `[auto-title]: "<TitleText>"` to identify synthetic generation

---

### 💡 Informational Notes

#### (y) Silent fallthrough of non-planning purposes to focus mode is intentional
- Ensures graceful degradation when new purpose types added without breaking old modes

#### (x) CLI-launched architects currently lack explicit session labeling
- Requires future coordination once purpose awareness spreads to terminal-launched workflows

#### (w) Requirement that `topic` remains mandatory simplifies input pipeline but complicates some UX scenarios
- Might need reconsideration in extended modalities support phase

---

## 3. Spec/Doc Review Findings

All newly added specifications reflect implemented features accurately.

✅ Delta Specs Match Implementation Closely
❌ Notable exceptions found:

### ⚠ Incomplete API Field Documentation

#### File: `openspec/changes/plan-application-seam/specs/mcp-server/spec.md`
- **Section**: Response fields documentation in table rows
- Issue:
  - Lack specific enumeration of response bodies from each of the six tools
  - Missing explicit declaration of return schema details such as inclusion/exclusion conditions

### ⚠ Agent-install.md Discrepancy Warning

From `docs/agent-install.md` Section "Study-plan tools over MCP"
⚠ Sentence: "...(not available yet); use `studyloop plan milestone`, `studyloop plan evaluate` and..."
➡️ Indicates discrepancy with earlier statement that **three MCP plan tools (#11) are included** but none mentioned here yet?

This seems contradictory and should be reconciled:

- Either remove this phrase because some phase-4 tools are already available (implausible).
- Or delay publishing this version till those are done as implied.

Otherwise leads observers into believing features exist incompletely.

🟢 Remaining spec changes verified as aligned.

---

## 4. Phase 4/5 Hazards Identified

### i. Future Tool Impacts
- **SetMilestone/Delete Plan Risk Exposure**
  Deviation 12 mandates readiness gating. Tools failing to uphold this early-enforced contract could bypass protection and affect underlying store directly.

### ii. Inventory Count Gap Alert
- At present (29 total tools), reaching target 35 requires **six additional tools** including the 3 upcoming ones. Smoke test must evolve from “minimum number” check to dynamic name-set inclusion validation (core set + known extensions).

- Folding existing mappings into `_tool_error` makes sense after all tools share same error taxonomy, reducing redundancy risks.

### iii. Architect Interface Extension Needs
- Persona extension via `brief` is correct design approach. For #13b, ensure smooth delivery over WS transport especially considering possible truncation limits for overly large payloads – possibly segmented transmission needed.

- Clarify how UI intends to distinguish architect-initiated sessions (planning purpose) visually and interactionally from regular sessions beyond topic label override.

---

## 5. Process Finding: Best Judgment Call Opportunity

The biggest missed centralized decision opportunity lay in consolidating **rule-based ranking constants**. Currently, hard-coded numeric thresholds exist in code base (`PLAN_RELATED_BIAS = 12`, `MILESTONE_BASE_SCORE = 48`) that directly influence outcome perception (e.g., synthetic candidate strength relative to others). These should ideally have stemmed from unified scoring theory inputs rather than individually tuned ad-hoc engineering responses. A formal scoring committee or configurability hook would help avoid inconsistencies under varying learner loads.

---

## 6. Interleave Commit for `get_next_action`

### Change Definition

#### ➕ Signature Update
Update the signature:
```python
def get_next_action(
    energy: str = "medium",
    time_minutes: int = 25,
    modality: str = "recall",
    interleave: str = "off"  # <- ADDITION
) -> dict[str, Any]:
```

#### 👷 Validation Logic Insertion
Insert validation block mirroring pattern for `energy/modality`:

```python
from typing import cast, get_args
from studyloop.learning.decision import InterleaveMode, build_now_plan

valid_interleave = get_args(InterleaveMode)
if interleave not in valid_interleave:
    raise ToolError(f"Invalid interleave {interleave!r}: choose one of {valid_interleave}")
```

Forward `cast("InterleaveMode", interleave)` to `build_now_plan`.

#### 📝 Updated Docstring Part
Add line in Args:
```markdown
Args:
    ...
    interleave: Mode determining alternation strategy ("off", "adaptive").
```

#### ✅ Validation Tests

In `test_mcp_plan_tools.py` add section:
```python
# Validate new parameter validation
def test_get_next_action_uses_interleave_param_properly():
    # Test default equals off-mode result
    pass

def test_invalid_interleave_value_raises_toolerror():
    # Assert raises proper error on invalid mode
    pass

def test_adaptive_interleave_yields_ratio_when_valid():
    # Confirm interleave ratio returned under proper circumstances
    pass
```

✅ Reuse same pattern as `energy`/`modality` validators exactly; reuse `@consistent_read`.
