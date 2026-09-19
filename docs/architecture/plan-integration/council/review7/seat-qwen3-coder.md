## 1. Verdict

**ACCEPT-WITH-CORRECTIONS** — Item 5 correctly implements per-item energy demand for repair and introduces a body-doubling floor aligned with the owner's finding, but introduces behavioral changes to no-plan learners with live struggles that constitute scope creep without architectural justification.

## 2. Findings

### (a) Scope of deferral is plan-independent: creep without grounding

- **File:** `learning/decision.py` lines 1170-1186 in `_defer_repairs`
- **Issue:** Deferral logic explicitly checks only `capability >= required` with no requirement that an active plan exist (`plan = plans.first_match(candidate)` may be `None`)
- **Why it matters:** The owner's concern focused on recommending hands-on repair during low energy risking "compounding the struggle and damaging confidence (RSD)" — but this was framed as occurring *within the context of a plan.* Extending this protection outside all planning context breaks D-5’s byte-compatibility promise and shifts user experience without consent.
- **Concrete Fix:** Gate repair deferral on presence of matchable active plan OR revise all documentation/testing accordingly
- **Test Name:** `test_no_active_plan_live_struggle_not_deferred_at_low_energy`

🔴 Defect introduced by design choice inconsistent with root issue scope

---

### (b) Demand derivation boundaries

- **File:** `learning/decision.py` line 528 in `_energy_demand`
- **Issue:**
   - A weak teach-back (`last_teachback_score < 14`) on a non-`struggling` concept results in `"medium"` demand
   - `struggling` rows older than 14 days still labeled `"medium"` (consistent internally)
   - Unparsable `last_seen` defaults to `"high"` (intended behavior noted)
- **Why it matters:** No functional distinction exists between medium/high capabilities at runtime (both map to minimum 6), so maintaining the differentiation adds complexity without operational benefit. Additionally, unclear if using `assessment_recorded_at` rather than actual learner engagement reflects meaningful recency for learning state.

🟡 Must-fix – unnecessary behavioral partition that complicates implementation without outcome variance

💡 Note – 14 day window aligns with typical spaced repetition cycles but could be configurable long-term

---

### (c) Deferral mechanics interactions

- **Files:**
   - `learning/decision.py`: Lines 1167–1183 (`_defer_repairs`)
   - `test_now_plan_guidance.py`: Test cases including `test_recovered_repair_stays_eligible_at_low_energy`

- **Issue:** Due recall remains eligible even when concept also marked as `struggling`, leading to potential confusion where both ranked and deferred versions of same item appear. Example in test has overlapping ‘window function’ entries with distinct sources.

- **Why it matters:** Learners might perceive inconsistency in recommendation engine when seeing both deferral message and same-concept primary activity. Could mislead perception of whether effort was truly spared.

- **Concrete Fix:** Consider suppressing deferral note when identical concept ranked due to different source type (unless needed for audit trail)

🟡 Should-fix – clarity improvement in learner-facing output quality

---

### (d) Body double candidate structure

- **File(s):**
   - `learning/decision.py`: Constant definition and application in `_body_double_candidate()` function
   - Tests in `test_now_plan_guidance.py`

- **Issues Identified:**
   - Base score setting leads to ranking anomalies (e.g., penalized hands-on practices beat body-doubles under low energy)
   - Command generation relies solely on first-plan title; doesn't handle multi-plan situations gracefully beyond concept text change (`"Sit with Your Plans"`)

- **Why it Matters:** Violates documented promise ("any real candidate outranks it"), particularly concerning modality-based scoring adjustments. Might inadvertently promote idle participation over productive cognitive load.

🔴 Defect conflicting with core design principle

🔵 Should-fix – adjust ranking priority handling around modality penalties vis-a-vis base ordering

---

### (e) Interaction with Rule 8 slot preservation

- **Files:**
   - `learning/decision.py`: Implementation in `build_now_plan()`
   - Modified test `test_preserves_one_plan_backed_action_when_energy_allows` asserting body-double slot insertion

- **Issue:** Originally protected top candidates from losing spot due to energy constraint. Now inserts body-double alternative below second-best real candidate instead of letting third unrelated item occupy slot.

- **Why it Matters:** Improves energy-aware relevance of suggestions but transforms rule semantics subtly—no longer guaranteeing *preservation* of existing items in favor of introducing plan-aware proposal.

🟡 Must-fix – Clarify specification update to reflect revised policy intention

---

### (f) Honest Starter Adjustment Adequacy

- **Files:**
   - `cli/_now.py`: Rendering changes referencing starter reason text
   - `learning/decision.py`: Use of helper flag `after_deferral`

- **Issue:** Starter continues proposing generic recall (“one tiny loop”) even with known high-value concept(s) recently made inaccessible due to energy restrictions.

- **Why it matters:** Misses opportunity to scaffold learner gently back toward accessible aspects of deferred content. Might lead to mismatched motivational affordance relative to available context clues from deferrals.

🟡 Must-fix – Introduce optional fallback synthesis of gentle reviews on deferred concepts

---

### (g) Renderer Presentation Consistency

- **Files:**
   - `cli/_now.py`
   - `today-panel.js`
   - `recap.py`

- **Issues:**
   - CLI switches label from “Record evidence” to “Sit with the plan”, appropriately distinguishing session initiation modes.
   - Web frontend omits auto-fill into Body Double picker despite CLI providing direct link

- **Why it Matters:** Inconsistent UX across platforms undermines unified intent of co-study modality bridging. Failure to pre-populate decreases ease-of-use unnecessarily.

🟡 Should-fix – Align interface affordances for consistent access pathway coherence

🔵 Note – JSON key reuse (`evidence_command`) reasonable, although semantically ambiguous. Could extract clearer separation eventually.

---

### (h) Spec Compliance Review

- **File:** `specs/active-learning-decisions/spec.md` (MODIFIED Requirements Section)
- **Observations:**
   - Updated requirement accurately reflects implemented features including dual deferral keys and rule expansion points. Includes detailed usage scenarios.
   - Describes how body-double candidate synthesized based on no plan-relevant fit.
   - Covers substring matching exclusion explicitly.

🟢 Verified – Clear mapping between stated behaviors and resulting system state

🟢 All described scenarios validated with test coverage in modified module

---

### (i) Testing Completeness

- **Coverage:**
   - Comprehensive unit testing included covering each major derivation edge case (unready plans, deferred repair variations, multiplan situations).
   - String assertions dominate over structured comparison in some outputs like reasons. Risks brittleness upon language localization or minor copyediting.

🟡 Should-fix – Replace textual substring validations with deeper structural checks where possible

🟢 Most critical paths pinned effectively via integration assertions involving full stack operation (JSON payloads returned correctly, DOM manipulation verified through snapshot techniques)

---

### (j) Row 3b Validity for Owner Decisions

- **Review Area:** Documentation: `receipts/now-rubric-2026-09-16.md` Row 3b details

- **Evaluation Summary:**
   - Readings accurately represent engine’s response dynamics:
     - Case (a): Prioritized co-study over repair
     - Case (b): Prioritized unrelated due task with clear labeling
     - Case (c): Retains access to recovery-level review activities at appropriate cadence

🟢 Well-formed triage prompts tailored directly to original feedback concerns

🟡 Missing explicit ask regarding no-plan deferral consequences (should include prompt about acceptability of offering starter under such conditions in absense of plans)

## 3. Refutations

None identified; supporting materials thoroughly documented and cross-referenced throughout design documents and automated verification artifacts presented consistently.

All claims either confirmed through empirical validation provided or addressed within amendment history already integrated in working branch under version control scrutiny.

## 4. Gate

Minimal set necessary to convert rejection into acceptance:

| Correction | RED Test |
|------------|----------|
| Gating deferral on active plan availability | `test_no_active_plan_live_struggle_not_deferred_at_low_energy` |
| Adjust base scoring model ensuring body double ranked strictly beneath all active tasks regardless of penalty modifiers | `test_body_double_always_below_ranked_tasks_despite_modality_penalties` |
| Expand scenario coverage in 3b to include judgment query on appropriateness of starting with starter in no-plan environments post-deferral | Update `test_energy_deferred_scenario_cases_include_post_deferral_context_check` |
