## 1. Verdict

**ACCEPT-WITH-CORRECTIONS:** the seam, preview-only assessment and mission writer are sound enough to retain, but item 4 must not merge or become item 5’s base until incomplete assessments cannot produce a “clean” close, the new briefs contain untrusted fields, the abandonment contract is reconciled, and the corrected head passes CI.

| Scope | Verdict | Qualification |
|---|---|---|
| 1 — MCP grants | ACCEPT-WITH-CORRECTIONS | Exact grants are implemented; Claude server registration and Kiro’s session-db prompting need evidence, and the mentor permission change needs user-facing disclosure. |
| 2 — brain dump | ACCEPT-WITH-CORRECTIONS | Delivery and state exclusion are tested; pre-attachment abandonment is not established by the supplied End-path test. |
| 3 — discovery/repair | ACCEPT-WITH-CORRECTIONS | Correct husk predicate and launch delegation; provenance overclaims history, and the repair brief lacks containment. |
| 3b — mission writer | ACCEPT | Existing intent and gate are widened coherently, without adding a CLI revision surface. |
| 4 — consensual completion | ACCEPT-WITH-CORRECTIONS | Successful assessments follow D-G; partial-read handling and learner-facing evidence presentation need correction. |
| `bfe0695c` — dotenv | ACCEPT | Narrow, discriminating import-crash fix. |
| `112c98bf` — exporter doctor | ACCEPT | Reasonable warning/failure policy, with both database-existence arms pinned. Its historical explanation is stronger than the evidence warrants. |
| `626ea129` — picker wait | ACCEPT-WITH-CORRECTIONS | Fixes the demonstrated race, but pending-request cancellation and timeout behavior need coverage. |

## 2. Findings

All proposed test names below are **new RED tests**, unless identified as existing. Source paths abbreviated below are relative to `packages/studyloop/src/studyloop/`; Python test paths are relative to `packages/studyloop/tests/`.

### F1 — 🔴 Partial assessments can be presented as a clean closing review

**Locations:** `learning/decision.py::_review_completion`, `_completion_sentence`; `planning/views.py::CompletionReview.from_evaluation`; `cli/_plan.py::plan_close`.

`_review_completion` forwards `result.warnings` but still constructs a non-null review. Three zero counts therefore produce:

> “the closing review is clean”

even when an assessment reader was unavailable. `plan_close` makes the same proposal and puts the gaps in a later section. A warning elsewhere does not make that affirmative claim true.

This contradicts D-G’s clean-review prerequisite and the stated rationale for `proposal=None`: unavailable evidence must not assert a clean slate. Learner consent is not a substitute for an honest proposal.

**Fix:** make assessment completeness part of the shared completion decision. At minimum, zero observed work plus data gaps must produce an unassessed/incomplete outcome, never `close` or “clean.” Reuse that decision in the engine and CLI. Positive observed work can still support `extend`, explicitly qualified as partial. Keep previews write-free.

**RED tests:**

- `test_completion_partial_assessment_never_proposes_clean_close`
- `test_plan_close_with_data_gaps_does_not_present_a_clean_proposal`
- Extend existing `test_completion_assessment_failure_keeps_the_sentence_and_warns` to assert `proposal is None`, zero-count sentinels, empty evidence and JSON `null`.

**Done:** a failed due or struggle reader with otherwise clean evidence cannot yield `proposal="close"` on any surface.

The outer-exception path is otherwise sensible. `completionEvidence()` returns no lines for its empty evidence, and the Today card prints the fallback sentence plus warnings. `plan_close` cannot render `Proposal: None` through the shown conversion: its review is non-nullable. `_assess`’s exact exception translation is **not established by the brief**; a returned assessment carrying warnings demonstrably reaches the problematic path.

### F2 — 🟡 Repair and closing briefs bypass the containment used by the Web brief

**Locations:** `cli/_plan.py::_render_plan_as_it_stands`, `_render_repair_brief`, `_render_closing_brief`.

Title, topics, timestamps, evidence strings and data-gap messages are interpolated directly into Markdown. Unlike `_render_brain_dump`, these renderers do not normalize embedded newlines or contain block markers. Imported or hand-edited plan fields and database text are evidence, not trusted prompt structure.

The fixed wrapper saying “data” is useful, but it does not prevent an embedded newline from creating a new `##` section. The repair path specifically targets documents outside the normal writer’s guarantees.

**Fix:** introduce shared, bounded prompt-data rendering outside the Web adapter. Preserve the required first section and four fixed count/proposal lines; normalize and quote dynamic values, escape block syntax and impose per-value and overall budgets.

**RED tests:**

- `test_repair_brief_contains_multiline_plan_fields_without_forged_sections`
- `test_closing_brief_contains_hostile_evidence_and_data_gaps`
- `test_repair_and_close_briefs_have_bounded_rendered_size`

**Done:** hostile titles, topics, evidence and warnings cannot add top-level headings, fences or forged review rows; required headings remain unchanged.

For the existing brain dump, leading `#`, backticks and the enumerated list markers are escaped. However, `_no_block_marker` does not cover ordered-list syntax such as `1. do this` or `1) do this`; those can remain lists inside the quote. Markdown containment also does not prove model resistance to semantic instructions.

Add `TestBrainDump::test_ordered_lists_and_setext_lines_remain_quoted_prose`, and narrow the documentation’s security claim to the structure actually guaranteed.

The 4,000-character limit is a useful finite input bound, not a token-budget proof. Per-line quoting expands rendered size, and the entire persona contributes to ACP’s first prompt. Add `test_brain_dump_worst_case_rendered_budget` using many short lines, Unicode and marker-leading lines; state the resulting byte bound rather than calling it a token guarantee.

### F3 — 🟡 The supplied abandonment test does not establish the design’s pre-attachment contract

**Locations:** `tests/test_web_plan_architect_journey.py::test_abandoning_a_launch_mid_flight_leaves_no_session_and_no_plan`; `web/static/js/components/session-timer.js::startSession`; `design.md §2`.

The design promises cancellation/navigation before attachment. The landed test waits for `201`, locates the visible End control, confirms End and observes release. Its docstring explicitly says navigation is **not** abandonment.

That is a useful planning-session regression test, even though it passed at RED time. It checks unchanged plans, purpose-label cleanup, one start event and **at most one observed WebSocket**. It does not force cancellation before attachment, while the POST is pending, or while options are held.

The new `_optionsReady` await makes the distinction more important: the shown code has no timeout or cancellation check after that wait. Whether other code invalidates a pending launch is **not established by the brief**.

**Fix:** distinguish:

1. cancelling a pending launch;
2. ending an accepted session;
3. navigating away from an attached session, which may deliberately detach.

Preserve reload grace behavior, but prevent cancelled pending work from launching later. Give options loading a bounded failure path and a recoverable status.

**RED tests:**

- JS: `cancelled planning launch never posts after options settle`
- JS: `options rejection releases architectLaunching and reports a recoverable error`
- JS: `options timeout leaves no deferred launch behind`
- Browser: `test_cancel_before_console_attachment_leaves_no_session`
- Browser: `test_navigation_during_pending_planning_launch_does_not_launch_later`, if navigation remains a cancellation promise.

**Done:** owner-approved semantics agree across design, spec and tests; cancellation before attachment is tested with an explicit barrier, not inferred from a fast End click.

For `626ea129`, a settled empty-agent result correctly reaches “Select an agent to continue”; the existing JS test pins it. Fetch rejection should settle through the described catches/finally, but that click-level outcome lacks a supplied test. A never-settling request is not covered by those catches.

### F4 — 🔴 Discovery text asserts history and future write success it cannot know

**Locations:** `planning/views.py:137 husk_provenance`; `cli/_doctor.py::check_study_plans`.

A creation stamp before the gate establishes neither that the plan “was never judged by it” nor when it became incomplete. A previously valid, post-gate-saved plan can later be hand-edited into a husk.

Similarly:

> “all ready — every write the gate judges will pass”

is false: a future write can remove required fields.

**Fix:**

- Provenance: “The document’s creation stamp predates the readiness gate (2026-09-15); the seam cannot tell when it became incomplete.”
- Healthy doctor result: “N active plans, all currently ready.”
- Remove causal history claims from `docs/study-plans.md`.

**RED tests:**

- `test_husk_provenance_does_not_infer_gate_history_from_created`
- `test_husk_provenance_invalid_and_boundary_dates_are_unknown`
- `test_doctor_ready_message_does_not_guarantee_future_writes`

**Done:** output describes current readiness and the recorded timestamp, not an invented write history.

Malformed documents are not husks: `husks()` catches load exceptions, logs and skips them. Consequently, doctor can report no active plans or “all ready” without naming a skipped unreadable document. A directory-level exception produces its warning row; an individual parse failure need not.

Add `test_doctor_reports_unreadable_plan_without_hiding_valid_husks`; return or propagate read warnings through the seam rather than silently treating unreadable files as absent.

### F5 — 🟡 Permission claims need installation evidence, not just definition tests

**Locations:** `agents/kiro/study-plan-architect.json`; `agents/claude/study-plan-architect.md`; `docs/agent-install.md`.

**Kiro session-db:** “visible, prompts” is an extrapolation from the studyloop probes. The brief explicitly says that combination was not probed. The current grants are appropriately narrow, but the observed claim should be qualified until tested.

**Claude:** its frontmatter allow-list names tools; it does not declare a server process. The supplied install documentation identifies global registration for OpenCode, Codex and Grok, but does not explain Claude’s server registration. Whether Claude is correctly connected or inert is **not established by the brief**.

**Fix:** provide installation-contract evidence identifying Claude’s actual registration file/scope and command. Add a session-db probe receipt, or explicitly label its prompt behavior as an expectation.

**Tests/receipts:**

- `test_installed_claude_architect_has_registered_studyloop_server`
- `test_kiro_architect_does_not_autoapprove_session_db`
- Versioned probe: session-db visible, no session-db allow entry, actual invocation requires approval.

The Kiro exact-set test is good: it derives expected names from `PLAN_TOOL_NAMES + LEARNING_RECORD_TOOL`, rejects extras, bare server grants and duplicates. A future inventory addition makes the unchanged configuration fail. Claude’s exact MCP-set test provides the corresponding protection.

The trusted shell is **not independently a defect against the accepted design**, which explicitly retains `execute_bash` and Claude `Bash`. This is least-privilege **MCP trust**, not a shell sandbox or technical ban on fallback. If D-A intended the latter, the owner must resolve that stronger interpretation; granting MCP alone does not enforce it.

**🔵 Disclosure follow-up:** `f5c2057d` activates twelve mentor grants, including six studyloop tools. The technical receipt and task log explain this, but user-facing mentor migration disclosure is not established. Add a dated note to `docs/agent-install.md`, pinned by `test_install_docs_disclose_mentor_grant_activation`.

Also put “rerun probes when upgrading kiro-cli” beside the versioned compatibility note. A doctor spelling check may detect known inert entries; making doctor execute live approval probes is unnecessary complexity.

### F6 — 🟡 Today’s evidence loses its plan association

**Locations:** `web/static/js/components/today-panel.js::completionEvidence`; `web/static/index.html` completion loops.

The page renders **all** completion sentences, then **all** flattened evidence lines. With two completed-milestone plans, evidence is neither nested under nor labelled with its owning plan. That weakens the contextual review D-G requires.

The green “Plan complete” label also describes plans whose status is still active, including those proposed for extension or not assessed.

**Fix:** render one keyed completion block per `plan_id`, containing its sentence and evidence; label it “Closing review” or “Milestones checked,” not “Plan complete.”

**RED tests:**

- JS/browser: `test_today_groups_completion_evidence_by_plan`
- `test_completion_surfaces_do_not_label_active_plan_complete`

**Done:** two actions with distinct evidence retain unambiguous associations, including one failed assessment.

Recap’s sentence-only presentation is acceptable; the active-learning spec does not require recap evidence lines. But the clean sentence does **not** print three numerical counts, contrary to the broad design/report claim. Either print explicit zeros or specify that “clean” summarizes zero counts.

### F7 — 🟡 Completion tests omit important outcome and boundary cases

**Locations:** `tests/test_now_plan_guidance.py`; `tests/test_cli_plan_seam.py`; `planning/views.py::CompletionReview`.

The seven REDs establish due-work extension, clean closure, new-topic exclusion, exception fallback, no plan writes and the principal CLI paths. They do not establish:

- struggle-only extension;
- unverified-milestone-only extension;
- evidence overflow;
- partial-reader outcomes;
- all documented no-launch exits;
- conversion failures inside the completion fallback boundary.

`_review_completion` catches `assess` exceptions, but `CompletionReview.from_evaluation(...)` executes **outside** that `try`. The blanket “now never fails on it” promise is therefore broader than the shown guard.

**Fix and RED tests:**

- `test_completion_struggle_only_proposes_extend`
- `test_completion_unverified_milestone_only_proposes_extend`
- `test_completion_evidence_cap_preserves_counts_and_overflow`
- `test_completion_review_conversion_failure_warns_without_failing_now`
- `test_plan_close_zero_milestones_refuses_without_assessment`
- `test_plan_close_complete_is_noop`
- `test_plan_close_unknown_id_is_named_refusal`

The struggles count includes **every** `evaluation.struggles` row, including rows with no concept. A topic-level real struggle is not automatically analogous to a synthetic new-topic due row. Existence of synthetic struggle placeholders and the evaluator’s precise concept/topic relevance contract are **not established by the brief**. Add `test_completion_topic_only_struggle_has_explicit_relevance_policy` before changing that behavior.

`unverified_milestones` is counted by sequence length, with one evidence line per title. That is a milestone-entry count, not a count of concept-evidence rows; uniqueness guarantees are not shown.

The count derivation really is shared: both CLI and engine consume `CompletionReview`. However, its “counts stay exact” comment conflicts with its admission that the evaluator caps due and struggle rows at ten. Clarify “returned assessment rows” versus total outstanding work. Test that excluding placeholders **after** an evaluator cap cannot conceal real due work beyond that cap; current ordering is not established.

### F8 — 🔵 Additional contract checks and accepted implementation choices

| Deliverable checks | Assessment and concrete action |
|---|---|
| **2(g), 2(j): ignored focus input and whitespace** | Structural 422 for an oversized focus dump is consistent with the explicit request schema: “ignored” applies after validation. Keep that rule and pin it with `TestBrainDump::test_over_limit_focus_dump_is_structurally_refused`. Client trim and server `strip()` both handle ordinary whitespace-only input; exact cross-language Unicode-whitespace equivalence is not established. |
| **3(k): husk predicate** | `plan list`, `--husks` and sidebar correctly require active **and** unready; drafts remain `ready:false` without a husk mark. The predicate is repeated, not defined once. Existing list tests pin Python behavior; add a sidebar rendering test for active-ready, active-unready, draft-unready and paused-unready. |
| **3(n): repair exits and launch options** | Exit 0 for a non-active unready plan is reasonable “nothing blocks” behavior, not a receipt of successful repair. Add `test_plan_repair_nonactive_unready_is_noop_with_pointer`. The fixed launch values match the established sibling chain and planning mode; no new invalid combination is shown. `ctx.invoke` does not replay command-line parsing, while callback validation still runs. A concrete agent-resolution/resume regression is not established by the brief. |
| **3(o): repair structure** | The launch test compares first-section items to `ReadinessView.blockers`, correctly pinning structural fidelity. `_HUSK_BLOCKERS` additionally pins exact fixture wording; that duplication is stricter than the launch contract requires. |
| **3(p): mission writer** | `why` is annotated as a string; the other three fields are sequences. `_revise` strips/coerces `why`, validates lists, applies them to the candidate, and includes all mission updates in `duplicate_record_only`. Add `test_duplicate_learning_record_with_mission_revision_still_saves_once`; the supplied tests do not directly pin that branch. |
| **3(q): schema pins** | `test_schemas_carry_the_design_signatures` pins the exact property set; the docs-contract test reads the registered schema. `test_mcp_table_signatures_match_the_registered_schemas`’ implementation is not supplied, so whether it forces every property into a persona row is not established. The persona’s `update_study_plan(plan_id, …)` is abbreviated, though its description names all four new mission fields. |
| **3(r): council-era pin inversion** | Legitimate: the old premise ceased to be true, and T3b.0 explicitly authorizes MCP/Web revision. Docs and CLI-fallback row still deny a generic CLI field-revision command. Add a direct `test_cli_fallback_does_not_promise_mission_revision` rather than relying on prose substring overlap. |
| **3(s), 3(t): seam placement and legacy summary** | `husk_provenance` is a view sentence using an authoring policy constant, so relocation is a real boundary, not an allow-list dodge. Growing both summary implementations does not make equality vacuous: it still detects divergent serialization. The explicit eighteen-key/readiness assertions additionally pin the intended contract change. |
| **4(w): cost** | One preview per fully-checked plan per build is already pinned; memoization within that build adds nothing absent duplicate callers. Two plans add roughly 640 ms at the supplied medians, not an established percentile guarantee. Record multi-plan end-to-end latency before considering cross-build caching and its staleness policy. |
| **4(x): status eligibility and flag** | `plan close` accepts checked draft/paused/abandoned plans and performs only a review launch. D-G does not explicitly forbid that, so it is not a demonstrated status-change defect. Document it and add `test_plan_close_nonactive_checked_plan_preserves_status`, especially for abandoned plans. `INDEX --done` matches the documented CLI spelling. |
| **4(z): preview proof** | Existing `test_completion_never_changes_status` does more than byte comparison: it captures `AssessPlan(..., "end", False)` and patches both recording writers to raise. This is strong preview-path evidence. |
| **4(aa): consent persona** | The persona reads evidence, proposes, asks and waits before status change; it offers learning-record and confidence logging. It handles Data gaps, but does not explicitly explain a null proposal received through `get_next_action`. Add `test_architect_treats_null_completion_proposal_as_unassessed`: retry assessment or disclose inability, never infer clean closure from zero sentinels. |

### F9 — 💡 Cross-item and outside-commit review

- **Installed versus checkout personas — checks (bb), (cc).** Stale installed agents are a real rollout boundary, not a new writer bug. `docs/agent-install.md` should give the reinstall/update step after merge and explain that a branch checkout persona is not proof of installed-harness parity. The supplied `build_canonical_persona` selects `_default_persona(mode)` when the checkout file is missing; it does **not** fail loudly at that point. Whether the fallback retains repair/closure rules is **not established by the brief**. Add `test_installed_wheel_plan_close_has_architect_consent_protocol`; packaging support may be separately fixed, but docs must not promise the full protocol for a checkout-free install without that proof.

- **Reconnect purpose — contradictory evidence.** Section 9 says CLI reconnects are labelled `focus`; the supplied Web tests/spec describe inferring `planning` from persisted `mode="plan-architect"`. These claims cannot both establish the same live path. Pin the real overlay with `test_cli_close_reconnect_infers_planning_without_explicit_purpose`, and correct the inaccurate receipt/reference statement.

- **`bfe0695c` — check (dd).** Catching `OSError` around `Path.is_file()` appropriately covers stat failures without swallowing arbitrary programming exceptions. The subprocess tests distinguish skipping a blocked candidate from continuing to a readable ancestor. Failures in `Path.cwd()` or reading a stat-able file are outside this fix; do not describe it as protection against every dotenv I/O failure.

- **`112c98bf` — check (dd).** Missing exporter plus absent database as `warn`, versus existing history as `fail`, is an acceptable diagnostic policy. Existing and added tests pin both arms. Database absence does not prove “nothing has ever been captured” or no attempted captures were lost; qualify those comments. Add `test_nonexecutable_exporter_without_database_is_warning`, since the branch also covers a present, non-executable file.

- **Test/CI commits.** Scoped `MonkeyPatch.context()` preserves hermetic configuration correctly. Selection markers prevent higher-scope browser fixtures from running first; they are evaluated during setup, not literally collection-time skipping. Waiting for the active card observes the state under test rather than a loading-state count. The increased job ceiling is supported by measured runs, although the comment’s “~1.6x” corresponds approximately to the timeout-killed run, not the 21m42s test duration.

- **RED rewriting — check (ee).** Rewriting unpushed RED commits to include the seventh test is acceptable: the resulting RED precedes GREEN and reportedly fails for the intended reasons. A second RED commit was not required.

- **Reports versus code — check (ff).** `learning/recap.py` is unchanged and inherits the new sentence; it was not newly edited to render evidence. `husks()` independently scans `store.list_plan_ids()` and `_load`, rather than being the advertised convenience over `get_active_guidance()`. The supplied mentor test validates spelling and declared servers, not the exact twelve-name set claimed in T1.1. T4.3 still says the verdict column is `PENDING` after recording the owner’s answers. Correct these reports rather than treating them as implementation proof.

## 3. Spec/doc review

### Delta specifications

| Spec | Review |
|---|---|
| `agent-adapters/spec.md` | Exact MCP grants, manifest regeneration and projection equality are represented. “SHALL attach” for Claude needs registration evidence; frontmatter alone is insufficient. “Frontmatter and JSON header are the only edits” is accurate for item 1, not the complete batch with canonical persona changes. |
| `live-session-orchestration/spec.md` | Brain-dump validation, planning-only rendering, state exclusion and ACP response placement match the supplied code/tests. Replace universal block-syntax and “never persisted” claims with their actual scope: session-state exclusion is proven; downstream agent/transcript persistence is not established. |
| `web-ui/spec.md` | Eighteen-key summaries, husk marker and mission PATCH are specified. End-after-201 is specified consistently with its test, but conflicts with design §2’s earlier abandonment promise. The options-settlement wait, timeout/cancellation outcomes and per-plan closing-evidence grouping are omitted. “Exactly one mark is present” should distinguish visible rendered marks from `x-show`-hidden DOM nodes. |
| `cli-surface/spec.md` | Internal brief keywords, repair handling and close exit codes are explicit. Add incomplete-assessment behavior, dynamic-field containment and the policy for checked non-active plans. “Writes nothing” should mean no **plan/checkpoint** writes: the launched session itself can create session state/history. |
| `health-and-diagnostics/spec.md` | Checker registration, category, warning rows and no-active info are covered. Add per-document parse-error behavior; otherwise “directory cannot be read” does not prevent silent omissions. Remove provenance-history implications. |
| `mcp-server/spec.md` | Mission fields, omission semantics, whole-list replacement and single-gate repair are coherent. The provided MCP mission test calls the Python tool function directly; transport-level validation/error formatting for malformed lists is not established by it. Add `test_mcp_stdio_update_mission_invalid_list_is_refused_without_write`. |
| `active-learning-decisions/spec.md` | Shared review, nullable exception fallback, evidence cap and no-plan compatibility are represented. It says “Rule 8” where code and rubric say rule 9. Partial assessment must not satisfy “else close.” Count-total wording must acknowledge evaluator truncation. Numeric counts in the clean sentence are promised but absent. |

The named items—`PlanSummary.ready`, internal brief threading, `husks()`, `check_study_plans`, `CompletionReview`, nullable proposal, close exits and mentor spelling—are substantially covered. The principal omissions are the picker wait lifecycle, incomplete-assessment decision semantics and bounded rendering of the new CLI briefs.

### Public documentation

- **`docs/study-plans.md`:** accurately distinguishes automated proposal from learner agreement and records the rubric results without erasing the original rejection. Correct “exactly as written”: the dump is trimmed, whitespace-normalized and escaped. Qualify “travels once” as one inclusion in the launch persona, not one-time transmission or assured deletion. Correct provenance and partial-assessment claims.
- **`docs/cli-reference.md`:** commands and `--done` spelling agree with the supplied material. Clarify `plan close`’s non-active-plan behavior and that its no-write guarantee concerns the plan, not launching a session.
- **`docs/agent-install.md`:** Kiro registration is concrete; Claude registration remains unexplained. Add the mentor migration note and post-merge reinstall instructions. “No CLI command edits fields” should mean no **generic revision command**: dedicated CLI status and milestone commands plainly exist.
- **`agents/mcp/README.md`:** `$GROK_HOME/config.toml` correction is supported; retaining the verified `user-settings.json` statement is appropriate.

The six-item `NOT_AUTOMATIC` list need not grow. Consensual-close prose beside it is sufficient, provided it describes the architect workflow rather than falsely asserting a universal API constraint. `update_study_plan(status=...)`, Web PATCH and CLI status already demonstrate that `set_study_plan_status` is not literally the sole status-writing door.

## 4. Hazards for what comes next

### (i) Merge and CI

Do not fast-forward `main` merely because `46262d23` was green. Its CI excludes the five item-4 commits and all review corrections.

CI can exercise fresh-install packaging, Linux behavior, browser scheduling, fixture isolation and the previously failing environmental tests that the sandbox could not validate cleanly. The matched-control receipt establishes **no additional failing IDs under that paired environment**; it does not prove all failing tests reached the newly changed behavior.

**Merge criteria:**

1. Corrected candidate head passes all required CI jobs.
2. Both still-running verifier full-suite checks have recorded final outcomes.
3. Any local residual failures match committed IDs; any new ID is investigated.
4. Preserve the golden SHA, 32-tool inventory and architecture guard.
5. Reconcile the receipt’s narrative “agent-session-tools eval arm” with its supplied shared-ID list, which names only studyloop paths.
6. Record differing skip/collection totals, rather than treating failure-set equality as complete execution equivalence.

### (ii) Item 5: D-F energy demand and body doubling

`learning/decision.py::_PlanContext.build` is the collision point: it classifies matchable plans, synthesizable milestones and completion actions. Item 5 must not accidentally make a fully-checked plan a study candidate or cause another assessment pass.

Keep these tests unchanged unless the underlying owner decision changes:

- `test_completion_never_changes_status`
- `test_completion_action_proposes_close_when_the_assessment_is_clean`
- `test_completion_action_carries_the_end_assessment_and_proposes_extend_when_concepts_are_due`
- `test_completion_review_does_not_count_new_topic_rows_as_due`
- `test_plan_close_launches_the_architect_with_the_assessment_in_the_brief`
- `tests/golden/now_plan_no_active.json` byte identity.

The precise existing rule-3 test names are **not established by the brief**. Identify them in item 5’s RED inventory rather than inventing replacements.

Proposed new pins:

- `test_low_energy_defers_recent_struggle_repair`
- `test_no_capable_plan_work_synthesizes_body_double_naming_deferred_items`
- `test_body_double_does_not_replace_completion_review`
- `test_energy_derivation_does_not_add_completion_assessments`

No item 1–4 pin inherently needs moving for D-F. `CompletionAction` should remain a separate review outcome; the architect’s close-consent protocol should not change merely because energy ranking changes. If the canonical persona changes, regenerate projections/manifest and retain `test_projected_personas_match_canonical`.

### (iii) Registered verifier checks

Use the verifier’s existing subprocess mechanism with explicit test node IDs. All checks below expect **exit 0** on GREEN; report individual names, not one undifferentiated broad suite.

| Check name | Command target / assertions |
|---|---|
| `architect-grant-kiro` | `pytest -q packages/studyloop/tests/test_install_agent_contracts.py::test_kiro_architect_carries_the_studyloop_server_and_exactly_the_plan_tools` |
| `architect-grant-claude` | Same file, `::test_claude_architect_allowlists_exactly_the_plan_tools`; expected names remain inventory-derived. |
| `architect-server-claude` | Proposed `::test_installed_claude_architect_has_registered_studyloop_server`. |
| `plan-repair-refusals` | `test_cli_plan_seam.py` nodes `test_husk_refusal_names_both_pause_and_repair`, `test_plan_repair_unknown_id_is_the_seams_not_found`, `test_plan_repair_on_a_ready_plan_says_nothing_to_repair`, plus the proposed non-active no-op test. |
| `plan-close-refusals` | Existing `test_plan_close_on_an_unfinished_plan_refuses`, plus proposed zero-milestone, already-complete and unknown-ID tests. |
| `plan-summary-readiness` | `test_plan_application.py::test_plan_summary_carries_ready_as_its_eighteenth_key` and `test_web_plans_seam.py::test_plan_list_payload_carries_ready`. |
| `planning-brief-containment` | `test_session_start_purpose.py::TestBrainDump`, plus F2’s repair/close containment tests. |
| `husk-doctor` | `test_cli_doctor.py::TestStudyPlansCheck`, including unreadable-document coverage. |
| `completion-assessment-integrity` | Existing preview/no-status-write test, strengthened null-proposal test and F1 partial-assessment tests. |
| `planning-launch-lifecycle` | Targeted JS cancellation/settlement tests and the deterministic pre-attachment browser test. |

Retain the existing golden, schema inventory, projection and architecture checks. These targeted registrations make the owner-critical contracts visible even when a broad suite changes its collection.

### (iv) Items 6 and 7

**Item 6:** D-D’s concept-edge proposal must define prerequisite scope for completion as well as ranking, without claiming item 4 already evaluates those edges. D-E’s retire/snooze proposal must define how those states affect completion due counts; hiding a card must not silently erase outstanding review evidence. Both need deterministic fixtures, not LLM tie-breaks.

Written proposals can proceed while corrections are reviewed, but implementation should use the corrected assessment and launch semantics.

**Item 7:** distinguish pushing a review branch to obtain CI from the final programme push. Review-branch CI must precede merge; final push should follow required reviews, committed receipts, docs and installed-agent update instructions. After successful push verification, the owner revokes tokens. No new credential requirement is justified by this batch.

## 5. Process finding

**The owner should have decided the abandonment boundary before the agent treated End-after-201 as satisfying “abandon mid-flight.”**

Unlike nullable proposal representation or internal keyword threading, this changes what a learner’s action means. The supplied design promises pre-attachment cancellation/navigation handling; the implemented spec and test instead declare navigation a detachable-session behavior and prove the existing End path. The added options wait creates another pending state where that distinction matters.

The checkpoint should have offered these alternatives explicitly:

1. **Pending launch:** cancel invalidates the request; late options/POST completion cannot launch or retain a session.
2. **Attached session:** navigation detaches for a stated grace period; End explicitly releases it.
3. **Simpler supported scope:** only accepted-session End is implemented now; pre-attachment cancellation remains an acknowledged unmet requirement.

Record the selected contract in `design.md §2` and require the barrier-based tests from F3.

T3b.0 was appropriately framed as a separate writer-capability decision rather than silently widening item 3. The new-topic exclusion was also supported by an observed scheduler row and preserves unverified milestones as the evidence gap. Neither owner approval, however, resolves partial-reader uncertainty: that remained a separate case the agent’s clean-versus-null reasoning should have carried through.
