## 1. Verdict

**ACCEPT-WITH-CORRECTIONS** — the repair deferral implements D-F’s intent, but unsafe shell quoting, a violated final-ranking guarantee, and inaccurate compatibility claims prevent merging or treating this tree as final for row 3b.

## 2. Findings

Paths below are relative to `packages/studyloop/` unless stated otherwise.

### F1 — 🔴 The generated session command does not safely quote the plan title

**Location:** `src/studyloop/learning/decision.py::_body_double_candidate`

Replacing `"` with `\"` is not shell argument quoting. Inside double quotes, titles containing `$()`, backticks, or variable references still undergo shell expansion. Backslashes also complicate the attempted quote escaping.

The ranker does not execute this command, but it explicitly offers it for execution. Rich escaping protects presentation, not the shell.

**Fix:** Construct the command using proper shell argument quoting, such as `shlex.join(["studyloop", "study", first.title, "--mode", "co-study"])` for the documented POSIX shell surface. Update exact command assertions rather than preserving unsafe double-quote formatting.

**RED test:** `test_body_double_command_preserves_title_as_one_literal_shell_argument`

Parameterize spaces, quotes, backslashes, dollar signs, backticks, and harmless command-substitution syntax. Verify a stub executable receives the exact title as one argument and no expansion occurs. Merely asserting `shlex.split(command)` is insufficient to establish absence of shell expansion.

**Done:** Every tested title round-trips literally through the supported shell, with no extra command executed.

### F2 — 🔴 Base-score ordering does not implement “every real candidate outranks it”

**Location:** `learning/decision.py::BODY_DOUBLE_BASE_SCORE`, `_body_double_candidate`, scoring/ranking in `build_now_plan`

The supplied adjustments establish a concrete inversion:

- Body double: `30 + 12 = 42`.
- Unrelated hands-on practice without a topic switch: `48 − 14 = 34`.

Conversation modality can raise the proposal further. Therefore, comparing base scores does not establish the advertised final ordering.

Preferring body doubling over taxing practice could be a defensible product decision, but it is **not the approved “real candidates still rank above it” contract**. The unrelated-due test exercises only an easy case.

**Fix:** Enforce an explicit fallback ordering for `source="body_double"` after ordinary scoring and before final selection, preserving real-candidate ordering. Keep rule 8’s separately documented alternate-slot reservation. Do not rely on another unexplained base constant.

**RED test:** `test_body_double_ranks_below_real_candidates_after_all_adjustments`

Include practice, continuity, and due candidates; hands-on penalties; topic-switch penalties; and conversation modality.

**Done:** Every eligible real candidate precedes the proposal in the ranked sequence; rule 8 may still reserve the final displayed alternate without changing the primary.

### F3 — 🟡 The revised no-plan compatibility promise is still false

**Location:** repository-root `openspec/changes/plan-integration-followons/specs/active-learning-decisions/spec.md`, `design.md`, `docs/cli-reference.md`, `docs/study-plans.md`

“Without an active plan **and nothing deferred**, byte-identical” is disproved by the implementation:

- A no-plan `learning` repair at low energy is not deferred, but gains `metadata.energy_demand`.
- A no-plan live struggle at medium energy is not deferred, but gains the same metadata field.

The empty-world golden cannot detect either change. Additionally, the documentation’s “live struggle” exception is too narrow: older struggles and weak-teach-back-only rows also defer at low energy.

**Decision on scope:** Keep repair deferral **plan-independent**. Reintroducing an unsafe recommendation merely because the learner lacks a plan would contradict the rationale for D-F. The appropriate correction is an accurate compatibility contract, not an active-plan gate.

**Fix:** Explicitly document both changes:

1. Struggle candidates gain additive demand metadata at every energy.
2. Above-capability repairs defer regardless of plan membership.

Limit byte-identity claims to the actual unchanged payload cases, including the empty-world golden. Narrow the spec’s unconditional no-plan renderer scenario as well.

**Regression test:** `test_no_plan_eligible_repair_exposes_demand_without_deferral`

Parameterize `learning` at low energy and `struggling` at medium energy; assert demand metadata exists, deferral keys are absent, and no body double exists.

**Done:** No specification or user-facing documentation promises unchanged nonempty no-plan payloads contradicted by this test. Preserve the existing golden hash.

### F4 — 🟡 Important new decision boundaries and synthesis interactions are unpinned

**Location:** `tests/test_now_plan_guidance.py`

The real-collector fixture is a good choice, but the tests do not pin several claimed decisions:

| Missing invariant | Required RED test |
|---|---|
| Exactly 14 days is high; 15 days is medium; missing/invalid timestamps conservatively remain high | `test_energy_demand_recency_boundaries_and_unknown_dates` |
| `learning` takes precedence over a weak score; old `struggling` plus a weak score remains medium under the chosen policy | `test_energy_demand_confidence_and_teachback_precedence` |
| Low capability rejects medium and high demand; medium/high capability accepts both | `test_repair_demand_capability_matrix` |
| Deferring the sole representative permits an energy-eligible milestone conversation, not another hands-on repair | `test_deferred_repair_allows_only_eligible_milestone_conversation` |
| Two ready plans produce one proposal, deterministic references, both deferred milestones named, and the first plan’s correctly quoted door | `test_body_double_two_ready_plans_has_deterministic_context` |

**Assessment of the policy:**

- **Fourteen days:** a reasonable explicit heuristic, not an empirically established recovery boundary.
- **Recorded-at recency:** consistent with the available projection. Describe it as assessment/report recency, not the date of last session difficulty.
- **Old struggle plus weak teach-back:** medium is consistent with the design. Making it high changes the label but not eligibility at any current energy setting; there is no evidence here requiring that change.
- **Medium versus high demand:** worth retaining as explanatory state and required-capability information. Document that both currently require *at least medium self-reported energy*. “High demand” does not mean “high energy required.”
- **Unknown timestamps:** conservative high demand is appropriate.

**Done:** These parameterized tests pass through the collector/ranker where applicable, not merely through manually annotated candidates.

### F5 — 🟡 The CLI still says repair stays available immediately before reporting it deferred

**Location:** `src/studyloop/cli/_now.py::_render_plan`

The milestone sentence still ends:

> “Plan-related review and repair stay available.”

That is misleading in the exact row-3b fixture, where the next line explains that plan-related repair is unavailable.

**Fix:** Say “Due recall and gentle review stay available,” or explicitly qualify repair by its own energy demand. Check parallel renderer wording for the same obsolete assurance.

**RED test:** `test_cli_milestone_deferral_does_not_promise_live_repair`

Assert the complete relevant sentence and the separate repair line, not just the presence of “Deferred for energy” and a concept somewhere in the output.

**Done:** Row 3b’s rendered explanation contains no contradictory promise of repair availability.

### F6 — 🔵 Synthetic matching and multi-plan presentation need clearer semantics

**Location:** `learning/decision.py::_body_double_candidate`, `_PlanContext.attach_refs`; spec rules 5–6

The explicit body-double references cover ready plans, but subsequent matching can attach additional references through:

- The generated concept, such as `Sit with SQL Windows`.
- The first plan’s topic, including a matching unready plan.

Thus, “names ready plans only” is true of the constructed reason/title list, not necessarily of rendered plan relevance. The correction test expressly permits a husk reference.

**Fix:** At minimum, make the spec describe the actual two-stage behavior. Prefer treating the generated display label as presentation rather than a semantic concept match key for this synthetic source. Decide explicitly whether ordinary topic matching should add unready-plan references to the proposal.

**Tests:** `test_body_double_display_label_does_not_create_incidental_plan_match` and `test_body_double_unready_reference_policy`.

For two ready plans, using the first plan’s title as the CLI entry point is acceptable as a deterministic starting point, but it does not establish that both plans’ context reaches the session. The two-plan test in F4 should pin exactly what is promised.

### F7 — 🔵 The Web door loses the proposal’s named context

**Location:** `web/static/js/components/today-panel.js::startAction`, `viewForAction`

Navigation to `body-double` is the correct harness-neutral destination. It is not a session start carrying the recommendation: the user must select context again.

**Fix:** As a follow-on, pass the selected plan/topic through an existing navigation or picker-prefill mechanism. Do not create a session automatically or introduce another writer.

**RED test:** `test_body_double_navigation_prefills_recommended_plan_without_starting_session`

A browser journey should eventually verify the picker state. The present JS mapping test proves only view selection.

This is **not a merge blocker** for the agreed session-door scope. Documentation and receipts should say “opens the Body Double view,” not imply a context-preserving session launch.

### Remaining decisions

- **Due recall and deferred repair on the same concept:** Keep both. They represent different actions. Suppressing the deferral would hide why repair disappeared. Make the distinction explicit in the copy.
- **Metadata-driven deferral:** Acceptable with the current producer invariant. A future producer must not attach repair-demand metadata to due recall; an explicit repair-source guard would make that invariant less fragile.
- **Milestone conversation after repair deferral:** Acceptable only as the separately energy-permitted conversation specified by the design, not as a relabelled repair task. F4 must pin that distinction. Owner acceptance of “talk about it” is not established by the existing three readings.
- **Rule 8:** Accept. This is an explicit finite-slot reservation, not filtering the collected candidate set. It does displace one displayed real alternate; describe that honestly. The primary must remain unchanged.
- **No-plan starter:** Defensible as a conservative, generic retrieval offer. Do not synthesize recall on the deferred struggle merely to maintain topical relevance; that would invent an unvalidated lower-demand action. A more contextual no-plan floor can be reviewed separately.
- **Twenty-five-minute body double:** Not inherently incompatible with low energy; duration and cognitive demand differ. The existing estimate-clamping behavior should remain.
- **`evidence_command`:** Keep the existing additive-compatible field. The source-aware CLI label correctly distinguishes a session door from a write.
- **MCP disclosure:** `to_json_dict()` establishes transport, not agent understanding. No tool-docstring/persona diff is provided, so disclosure is unestablished. Add a concise explanation at the existing `get_next_action` documentation surface; avoid duplicating this policy across harness-specific personas.
- **Recap:** Direct `_plan_context` testing is appropriate for the supplied low-energy object. It does not prove that ordinary `build_daily_recap()` produces low-energy deferrals; the spec scenario should distinguish renderer capability from the production medium-energy path.
- **Row 3b:** The three readings cover both halves of D-F and the due-recall exception. Keep owner verdicts pending. Call reading (c) **“recorded as learning”**, not demonstrated recovery. Ask separately whether an eligible milestone conversation on a deferred live-struggle concept is acceptable; that behavior is absent from the walkthrough.

## 3. Refutations

1. **“42 < any real candidate.”** False after the documented scoring adjustments; F2 gives a concrete counterexample.
2. **“No active plan and nothing deferred remains byte-identical.”** False for eligible struggle candidates because demand metadata is always added.
3. **“The one plan-independent change is live-struggle deferral.”** Incomplete: older struggles and weak teach-backs also defer, and eligible repair payloads change.
4. **“Each GREEN decision is a test.”** Not established. No added test exercises the sole deferred representative of an otherwise eligible milestone or the two-ready-plan proposal.
5. **“The Today card starts it.”** Only navigation is established. The brief expressly states that the picker receives no plan-title prefill.
6. **“Zero regressions.”** The matched control establishes no **new failing test IDs** at GREEN. It cannot establish absence of defects outside those tests, and it is not a full-suite result for `6d5a2d0e`. The disclosed scoped verification after corrections is useful and appropriately limited.
7. **“Learning” means recovered.** Not established by the projection facts. It is the chosen low-demand proxy, subject to owner judgment.

## 4. Gate

1. **Quote the session command safely** — F1’s literal shell-argument test.
2. **Enforce the final fallback ordering** — F2’s post-adjustment ranking test; retain the existing rule-8 primary-preservation test.
3. **Correct the compatibility/spec claims** — F3’s no-plan eligible-repair test; unchanged golden hash.
4. **Pin the missing policy boundaries and synthesis cases** — the five tests listed in F4.
5. **Remove contradictory repair-availability copy** — F5’s exact renderer test.

Then run the affected Python/JS suites and obtain branch CI green on the final corrected tree. Record row 3b from that tree, leave its judgment to the owner, and do not archive before T5.5 is scored.
