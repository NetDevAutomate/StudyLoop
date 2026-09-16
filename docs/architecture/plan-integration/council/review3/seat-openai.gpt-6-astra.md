## 1. Verdict

**ACCEPT-WITH-CORRECTIONS:** Phase 3 is a usable integration base, but Phase 4 must not proceed until collected-candidate eligibility, urgency ordering, immutable create intents, hostile-content handling and the missing acceptance evidence are corrected.

- **#10 — ACCEPT-WITH-CORRECTIONS:** energy/readiness currently gate synthesis, not all new-milestone recommendations; the ranking tests do not establish the promised urgency rules.
- **#11 — ACCEPT-WITH-CORRECTIONS:** the adapters are substantially sound, but the explicitly inherited `CreatePlan.answers` freeze requirement remains unmet.
- **#13a — ACCEPT-WITH-CORRECTIONS:** shared persona resolution and launch rollback are sound; raw history/plan text needs structural containment and adversarial tests.

Merged-tree test success is **not established by the brief**; the arbiter’s full-suite gate remains outstanding.

## 2. Findings

### F1 — 🔴 Collected new-milestone work bypasses energy and readiness gates

**Location:** `learning/decision.py::_PlanContext.build`, `milestone_candidates`, `attach_refs`, `_guarantee_plan_backed`.

Only `self.synthesise` excludes energy-deferred and unready plans. Existing candidates remain untouched, receive the plan bias and acquire a next-milestone index whenever their keys match that milestone’s concepts. Thus a collected practice/continuity candidate can recommend precisely the milestone that was deferred or that the seam refuses to tick.

The guarantee’s assertion that “every plan-backed candidate here is eligible on energy” is false: absence of synthesis does not establish eligibility of collected candidates.

**Fix:**
- Preserve candidate provenance sufficient to distinguish due recall/struggle repair from new work; do not infer this solely from modality.
- Apply energy/readiness eligibility to collected work before synthesis and ranking.
- Keep legitimate due recall and struggle repair available below the floor.
- An unready plan may retain general relevance, but must not advertise writable milestone advancement; use `PlanRef(plan_id, None)` for permissible repair and show the blockers.
- Make rule 8 check eligible actions, not merely nonempty refs.

**Important ruling:** a deferred plan’s genuine topic-matched repair with `milestone_index=None` **does satisfy** “eligible plan-backed action.” Rule 8 does not require new-milestone work.

**RED tests in `tests/test_now_plan_guidance.py`:**
- `test_collected_new_milestone_is_deferred_below_energy_floor`
- `test_unready_plan_never_recommends_tickable_milestone`
- `test_deferred_plan_due_recall_on_next_concept_remains_eligible`
- `test_deferred_plan_topic_repair_satisfies_plan_backed_guarantee`
- `test_ineligible_reference_does_not_suppress_eligible_alternate`

### F2 — 🔴 A constant score increment does not implement urgency-class ordering

**Location:** `learning/decision.py::_score_candidates`, `PLAN_RELATED_BIAS`, `_milestone_candidate`.

The binding rule says “within an urgency class plan-related beats unrelated,” not merely “wins a near-tie.” A `+12` increment cannot enforce that when the unrelated candidate’s otherwise-equivalent score advantage exceeds 12; it can also cross an urgency boundary whose score separation is smaller than 12.

A synthesized milestone starts at **60/63/66 after the plan bias**, before other scoring adjustments. The receipt establishes a modality-match adjustment of 18, so conversation preference must be included in boundary testing. The complete production due/repair score ranges are **not established by the brief**; consequently, neither “always below every due and repair class” nor a particular production inversion can be certified here.

Two plan-related candidates receive the same increment, so **the increment alone cannot invert their relative order**. Existing score adjustments and synthesis bonuses still need class-boundary protection.

**Fix:** establish explicit urgency classification and order by urgency first, plan relevance second within that class, then existing score and explicit deterministic ties. Preserve the pre-plan scoring/order path when no plan participates. Do not let renderer code compensate.

**RED tests:**
- `test_plan_related_wins_same_urgency_with_score_gap_above_twelve`
- `test_more_urgent_unrelated_wins_at_adjacent_class_boundary`
- `test_synthesized_milestone_stays_below_due_and_repair_across_preferences`
- `test_two_plan_related_actions_preserve_urgency_order`
- `test_equal_rank_is_independent_of_collector_input_order`

Use real collector provenance and parameterize energy, modality and interleave; the current injected scores 100 versus 48 prove only the selected fixture.

### F3 — 🟡 Ranking-contract evidence is incomplete

**Location:** `tests/test_now_plan_guidance.py`.

The ten engine tests establish valuable examples, not all nine rules:

| Rule | Evidence assessment |
|---|---|
| 1: one guidance read | Visible code makes one call, but no call-count, parse-count or history-exclusion test is supplied. |
| 2: unchanged collection | Existing collector calls remain; their implementations are not reproduced. |
| 3: energy eligibility | Synthesis and finished-concept repair are tested; collected new work is missing. |
| 4: normalized equality | Shared normalizer is used; course and punctuation/NFKC cases are missing. |
| 5: urgency | Two widely separated/near-tied examples are insufficient; see F2. |
| 6: synthesis | Ordinary synthesis passes; representation, no-concept and deduplication edge cases need coverage. |
| 7: refs after dedupe | Plan ordering is tested; loss of seeded refs through deduplication is not. |
| 8: preservation | Four high-scoring unrelated candidates exercise replacement, not eligibility/time boundaries. |
| 9: completion | Completion is tested against unrelated work, not a matching due candidate. |

**Fix:** add:
- `test_guidance_read_once_with_no_checkpoint_history_calls`
- `test_guidance_parses_each_document_once`
- `test_guidance_adds_no_session_history_scan`
- `test_course_and_punctuated_concept_match_by_normalized_equality`
- `test_dedupe_preserves_all_seeded_refs_for_conceptless_milestones`
- `test_matching_finished_and_next_concept_uses_next_index_once`
- `test_completion_plan_does_not_bias_matching_due_work`
- `test_plan_backed_guarantee_respects_time_limit`
- `test_collection_and_per_plan_warnings_are_preserved`

Scope the no-history assertion to **guidance consumption**, not existing evidence collectors: the design does not prohibit their established reads.

Assertions such as `score < primary.score` are appropriate for ordering contracts; replacing them with exact constants would make the tests more implementation-bound, not stronger.

### F4 — 🟡 Hostile plan content lacks required containment tests

**Location:** `learning/decision.py::_milestone_candidate`; `cli/_now.py::_render_plan`; `web/routes/session/_start.py::_render_planning_brief`, `_seed_entry`; `agent_launcher.py::build_canonical_persona`.

The required hostile-title/topic/milestone fixtures are absent.

Two concrete output boundaries need attention:

1. `_now.py` interpolates untrusted titles, milestones, warnings and reasons into Rich markup. Markup-looking content can alter rendering or trigger parsing errors.
2. `_render_planning_brief` inserts multiline plan titles, milestone text and history evidence directly into persona Markdown. A newline can introduce a forged heading or instruction outside its apparent list entry. The introductory “data … not instructions” sentence establishes intent, but does not structurally contain the content.

**Fix:**
- Escape untrusted Rich text or compose styled `Text` objects.
- Serialize history and existing-plan values into a clearly identified data region with escaped newlines and delimiter-safe encoding; place trusted interpretation instructions outside that region.
- Do not claim textual fencing guarantees model obedience.
- Verify command arguments from synthesized concepts/topics round-trip as literals. `_evidence_command`’s quoting implementation is **not established by the brief**, so a shell-injection defect there is not proven.
- Forbid lifecycle writes during recommendation and persona preparation.

**RED tests:**
- `test_hostile_plan_text_renders_literally_in_cli_now`
- `test_synthesized_evidence_command_round_trips_hostile_arguments`
- `test_hostile_guidance_content_performs_no_lifecycle_write`
- `test_planning_brief_contains_hostile_history_as_data`
- `test_planning_brief_title_cannot_create_trusted_persona_section`
- `test_planning_launch_never_mutates_existing_plan_bytes`

Alpine uses `x-text` at every added string sink shown, which is the correct HTML-safe choice; no added `x-html` sink appears in the supplied diff. Other rendering paths are **not established by the brief**.

### F5 — 🟡 Freeze `CreatePlan.answers` at the intent boundary

**Location:** `planning/intents.py::CreatePlan`; `mcp/tools.py::create_study_plan`.

The review-2 instruction was explicit: freeze the live mapping **before this tool lands**. Disjoint ownership explains why it was not done; it does not waive the requirement.

“Decoded per call and retained by no one” is not proven through FastMCP validation by these tests: they call registered `.fn` functions directly. Even a fresh outer dictionary does not establish recursive immutability or safe queued/replayed intents.

**Fix:** assign a seam owner to snapshot and recursively freeze supported answer values at intent construction. Prefer the intent boundary over an MCP-only copy; preserve authoring semantics and error mapping. Consider passing `overwrite=False` explicitly for readability, although the existing intent/default test already pins the behavior.

**RED tests in a new `tests/test_plan_intent_snapshots.py`:**
- `test_create_plan_snapshots_nested_answers_at_construction`
- `test_create_plan_answer_snapshot_cannot_be_mutated`
- `test_replayed_create_uses_original_answer_snapshot`

Add `test_mcp_create_captured_intent_isolated_from_caller_mutation` to `tests/test_mcp_plan_tools.py`.

### F6 — 🟡 The human rubric is honest but unfinished

**Location:** `docs/architecture/plan-integration/receipts/now-rubric-2026-09-16.md`; `tasks.md::T3.4`.

Leaving verdicts `PENDING` was correct; marking T3.4 completed is not supported by a requirement for a **scored human rubric**.

Row 2 presents a plausible urgent-review-first ordering, and row 3 demonstrates that low-energy repair remains available despite its penalty. Neither establishes that a learner would choose the primary, nor validates the entire score policy.

**Fix/done criterion:** after ranking corrections, regenerate affected emitted rows and show the owner the primary, duration, modality, rationale, alternatives and deferral/completion context for all five scenarios. Commit five `yes`/`no` judgments with explanations, reviewer identity and reviewed tree; a `no` becomes an explicit arbitration finding. Do not invent a five-yes acceptance threshold that D-16 does not specify.

A human judgment is not a RED unit test. A receipt-completeness check may detect `PENDING`, but cannot replace the judgment.

### F7 — 🟡 Session failure tests do not establish identical rollback on both transports

**Location:** `tests/test_session_start_purpose.py::test_brief_failure_releases_session_claim`.

`mock_start.call_count == mock_abort.call_count` permits both to be one; it does not prove the documented “no study row was created.” The failure test covers PTY only.

**Fix:** parameterize PTY/ACP; assert `mock_start.assert_not_called()` and `mock_abort.assert_not_called()`, no adapter setup/acquisition, all three response keys, empty reservation/state and successful following focus start.

**RED tests:**
- `test_brief_failure_precedes_db_creation_and_releases_claim`
- `test_focus_start_overwrites_stale_planning_purpose`

The existing parameterized resolver spy establishes that **both paths call the shared resolver exactly once**, rather than merely counting an unrelated function. The hatch and stub adapters appropriately avoid real launches; they do not prove actual ACP prompt delivery.

### F8 — 🟡 The ordinary recap renderer does not ship its advertised context

**Location:** `learning/recap.py::_plan_context`; `cli/_recap.py` rich panel.

JSON and spoken recap expose plan context, but the ordinary CLI recap does not. Ownership is not a reason to advertise the whole daily-recap surface as implemented.

**Fix:** authorize the small renderer change, with no second ranking call.

**RED test:** `test_cli_recap_rich_panel_shows_engine_plan_context`, plus a no-plan assertion preserving existing output. Keep protected tests untouched.

### F9 — 🔵 Guidance failures are resilient but insufficiently observable

**Location:** `learning/decision.py::_load_guidance`.

Graceful degradation is appropriate: corrupt/unreadable plans must not prevent study guidance. However, catching every `Exception` without logging also hides programming/import failures behind an ordinary warning.

**Fix:** retain the nonfatal warning contract, log the exception with traceback, and use narrower domain catches where they can preserve the required resilience.

**Tests:** `test_guidance_failure_warns_and_logs_without_failing_now`; `test_unreadable_document_preserves_other_plan_guidance`.

The warning text and readiness blockers are data for renderers, not permission to execute lifecycle actions.

### F10 — 🔵 Remaining engine and renderer edge contracts need precise boundaries

**Locations:** `decision.py::_order_plans`, `_milestone_candidate`, `attach_refs`, serializers; `_now.py`; `today-panel.js`.

- **Ordering:** three stable sorts correctly implement the stated precedence. ISO-string ordering is chronological only under a compatible canonical representation; every timestamp form the store writes is **not established by the brief**. Parse timestamps into a common instant, or pin a canonical storage invariant. Add `test_plan_ref_order_uses_chronological_updated_instants`, including equivalent instants with different offsets and malformed legacy values.
- **Ref upgrade:** `refs.get(plan_id) is None` intentionally treats absent and general refs alike, allowing upgrade to the next index. Matching both finished and next concepts reasonably chooses the next milestone. Eligibility restrictions from F1 must constrain that upgrade.
- **Course matching:** normalized equality over concept/topic/course conforms to the supplied contract. Do not substitute substring matching to mask the known `RANK()` parser bug.
- **Synthetic evidence:** the fallback command offers to record learning under a milestone title and possibly the generic topic `"study"`; it does not tick the milestone. Merely emitting it writes nothing. Exact downstream record semantics are **not established by the brief**. Add `test_conceptless_milestone_evidence_records_exact_label_without_ticking_plan` before treating arbitrary titles as good learning-record identifiers.
- **Serialization:** removing empty `plan_refs` and appending nonempty refs at the end preserves the old key sequence; `asdict` copying metadata is consistent with the previous implementation. The unchanged golden is good evidence for its frozen empty-world case, not every nonempty no-plan world.
- **Clock:** guidance date and `generated_at` derive from one `now` in this function. CLI/Web do not pass a clock in the shown interface; clocks inside existing collectors are not established here.
- **Defensive renderer reads:** acceptable for older test doubles/callers, though not required by the new concrete dataclasses. The conditional Plan column and displayed `plan.energy` are coherent.
- **Speech:** primary plan relevance is present; `now --speak` does not announce deferrals/completions. Either document that narrower contract or add `test_now_speech_names_energy_deferral`.
- **Today:** the notes block correctly avoids creating another action card. `hasPlanContext` is unused in the supplied HTML; use it or remove it, without changing ranking.

### F11 — 🔵 MCP adapters are sound, with limited duplication and test boundaries

**Location:** `mcp/tools.py` six new tools; `tests/test_mcp_plan_tools.py`.

- Each successful adapter performs one appropriate seam call; `list_study_plans` legitimately wraps a tuple of summary views.
- `PlanNotReady` first, fallback `plan_error`, and `raise ... from exc` are sensible. Error-class inheritance among `InvalidField` and `InvalidMilestone` is **not established by the brief**; the parameterized prefix test would expose a shadowing relationship for the supplied instances.
- Accept `history_limit` validation as a boundary safeguard for this phase. Move the common policy into `PlanApplication.inspect` in a separately owned correction, while retaining schema/boundary validation and zero history queries on refusal.
- Accept `update_study_plan(status=...)`: atomic repair-and-activate is not redundant with a dedicated transition command, and the descriptions distinguish them.
- `list_study_plans` correctly promises active-first. “Then by last update” is underspecified, not demonstrably a newest-first claim. Specify **oldest update first** to match `browse`; do not confuse storage-id-ordered guidance with browsing.
- Bound spies, prefix cases and real-seam journeys are useful. `forbid_store` does not forbid every index function, direct filesystem/SQLite access, or direct authoring/evaluation calls. Retain the architecture guard and extend targeted prohibitions for #12.
- Fresh-container tests mutate only the outer mapping; add nested mutation coverage.

**Tests:** `test_list_study_plans_documents_and_preserves_browse_order`, `test_plan_tool_nested_responses_are_independent`, `test_inspect_bounds_history_before_checkpoint_query`.

### F12 — 🔵 Purpose compatibility is narrower than universal architect labeling

**Location:** `_models.py::StartSessionRequest`; `_start.py::_launch_topic`, `_resolve_persona`; `_dashboard.py::get_session_state`.

- Missing `topic` still causes structural rejection; only an explicit blank planning topic becomes `"Study plan"`. The intended missing-topic HTTP behavior is not unambiguously established by the binding model excerpt. Document this request contract and have #14 send `topic: ""`, or explicitly authorize conditional omission support.
- Blank focus topics pass through unchanged; their downstream acceptability is **not established by the brief**. Do not silently change focus compatibility here.
- Blocking a planning launch on brief failure is defensible: the specified informed interview cannot be delivered. Structured HTTP 500 is appropriate for an unexpected server-side preparation failure; no known transient-failure classification justifies demanding 503.
- Both web paths explicitly persist the request’s purpose. However, a CLI architect session without `purpose` reconnects as **focus** under `setdefault`. That is the specified fallback, but not a correct architect label across all launch surfaces.
- `persona_mode_for`’s else-to-focus behavior exactly matches the binding helper; API validation already rejects unknown purposes.

**Tests:** `test_planning_start_topic_omission_contract`, `test_legacy_state_defaults_purpose_to_focus`, and, when the CLI writer is updated, `test_cli_architect_state_reports_planning_purpose`.

**Cross-stream assessment:** the ranker’s “pause or repair” warning and MCP’s active-unready hint agree in intent; F1 is the behavioral contradiction. `"Study plan"` agrees with the CLI label. The supplied delta excerpts are mutually readable, but full merged `tasks.md` coherence is **not established by the brief**; the T3.4 completion claim needs correction regardless of conflict-free merging.

## 3. Spec/doc review

| Document | Assessment and correction |
|---|---|
| `specs/active-learning-decisions/spec.md` | Overclaims universal energy deferral and urgency ordering; implementation only gates synthesis and adds a constant bias. “Listed and matched but never synthesised” must distinguish permissible repair relevance from unready milestone advancement. Daily-recap rendering overstates the rich CLI surface. Document the public `ActivePlanSummary` fields and the meaning of `eligible`—currently eligibility for new-milestone synthesis, not eligibility of all plan-related work. |
| `specs/mcp-server/spec.md` | Closely matches the six adapters, including extra `history_limit`, status revisions, prefixes and `plan_error`. “Forwards arguments unchanged” has an exception: `plan_id or None` converts explicit `""` to omission. Prefer forwarding the supplied value to the seam and pin `test_create_empty_explicit_id_is_not_silently_omitted`, or document an authorized normalization. |
| `specs/live-session-orchestration/spec.md` | Matches web purpose plumbing and structured `error`/`purpose`/`repair` failure. Explicitly distinguish blank from omitted topic and legacy fallback from accurate CLI architect labeling. Both-transport rollback is asserted more broadly than currently tested. |
| `specs/agent-adapters/spec.md` | Matches resolver mapping and separate brief insertion. Data framing exists but adversarial containment is untested. The focus test compares two calls to the new builder, not a pre-change artifact; add `test_focus_persona_matches_pre_brief_fixture` for the byte/hash promise. A repository-wide absence of literal focus calls beyond the shown paths is not established by the brief. |

Constants **12** and **48** need not become normative API requirements; specify and prove ordering invariants instead. Conversely, additive public view fields and eligibility semantics deserve documentation.

`docs/agent-install.md` correctly says the three remaining MCP tools are unavailable at this tree. Its blanket error-prefix promise covers `record_plan_learning`, whose inline mapping is not reproduced; exact equivalence is **not established by the brief**. The documented fallback should also mention `plan_error:` if listing possible prefixes exhaustively.

Removing the `docs/study-plans.md` “active plans do not bias now” bullet is factually correct: bias exists. I disagree that a pending rubric alone makes that deletion premature. What is premature is treating it as completed acceptance; add accurate capability wording—**“plan-aware guidance with tested ranking rules”** once corrected—and keep the human gate visible.

Correct every remaining inventory claim from **26 → 35** to **23 → 32**; do not manufacture three tools to reconcile mistaken arithmetic.

## 4. Phase 4/5 hazards

### #12: tools, assessment sinks and readiness

Implement the three existing seams without alternate policy paths:

| Tool | Required behavior and named tests |
|---|---|
| `set_study_plan_milestone` | One `apply(SetMilestone)`; reject invalid indices through the domain mapping; active-unready documents require pause/repair. `test_set_milestone_delegates_once`, `test_unready_active_milestone_refusal_preserves_document_and_history`. |
| `evaluate_study_plan` | Call `assess`, never `apply(AssessPlan)`. `test_evaluate_delegates_to_assess_not_apply`, `test_evaluate_dry_run_reports_no_sink_writes`. |
| `delete_study_plan` | Keep `confirmed: bool = False` in the schema; explicit true authorizes deletion through `DeletePlan`. `test_delete_defaults_to_unconfirmed_without_writes`, `test_delete_confirmed_delegates_once`. |

**Deletion ruling:** do not require the parameter at schema level or constrain the schema to literal true. That would contradict the binding default and remove the seam’s explicit unconfirmed-refusal path. Omission and false must never delete.

For `evaluate_study_plan(record=False)`, return the assessment view’s actual sink results: `db_write=False`, `document_write=False`, with no checkpoint or document mutation. `AssessmentResult`’s complete shape and recorded-mode refusal behavior are **not established by the brief**; #12 must not invent successful writes from the requested flag or flatten partial sink outcomes. Add `test_evaluate_reports_actual_sink_results` and `test_evaluate_recorded_unready_plan_obeys_deviation12`.

Extend the harness to forbid checkpoint append/index writes and document mutations during dry evaluation. Real-seam tests should compare document bytes and checkpoint rows; forbidden method names alone cannot establish absence of side effects.

### Inventory and error mapping

In production-default stdio mode, assert:

1. `len(tools_result.tools) == 32`.
2. All listed names are unique.
3. All **nine design-table plan tools** are present.
4. `record_plan_learning` and the existing `CORE_TOOLS` remain present.

Name the test `test_stdio_production_inventory_has_32_unique_tools_and_all_nine_plan_tools`. Exact count catches accidental additions; name assertions prevent a missing required tool being masked by an unrelated addition. Keep preview exercise tools outside this production pin.

#12 is the correct writer to fold `record_plan_learning` into `_plan_tool_error`, **provided** tests first pin its existing prefixes, blockers and chained causes. Use `test_record_plan_learning_error_mapping_is_preserved`; make any intentional wording change explicit rather than calling it a refactor.

### #13b/#14: architect launch journey

- Update `agents/shared/personas/plan-architect.md` to prefer the nine MCP tools, retain `record_plan_learning`, and explain CLI fallback. Add `test_architect_persona_names_nine_plan_tools_and_record_writer`.
- The `201` body and web state already expose purpose; no resolver rewrite is needed simply to update the persona body.
- #14 still needs the **“Plan with architect”** affordance, correct planning request, subject/default handling, structured failure display, console label and reconnect behavior.
- Add `test_plan_with_architect_launches_planning_session_without_creating_plan` and `test_planning_console_reconnect_preserves_purpose_label`.
- ACP `persona_text` is consistent with the existing transport contract. Maximum brief size, startup latency, context limits and guaranteed initial-prompt delivery are **not established by the brief**. Define a bounded brief policy and test that trusted persona content survives any truncation.
- Add `test_acp_planning_brief_sent_once_before_user_prompt`; a returned string alone does not prove delivery to the agent.
- Decide whether universal architect reconnect labeling requires the CLI state writer to persist purpose; never infer purpose from topic `"Study plan"`.
- Resolve the existing `RANK()` parser bug in its parser owner’s files with a round-trip test, not by weakening normalization or matching.

## 5. Process finding

**The human decision most needed was whether an unscored rubric could count as completed acceptance.**

The agent correctly refused to fabricate verdicts, but recording T3.4 as done blurred implementation evidence and human judgment. The owner should have reviewed the actual five primary recommendations, especially the low-energy hands-on repair, before signing that gate.

The documentation deletion itself accurately describes shipped behavior; the process error is conflating “implemented and mechanically exercised” with “human check completed.” Keep post-ship accept/skip logging separate, as D-16 requires.

The workspace-wide order-dependent failure in `agent-session-tools/tests/test_eval_arms.py::TestPlannerIsolation::test_planner_patch_restored_after_tool_error` also needs an assigned owner and a reproduced disposition during arbitration. Passing alone does not establish a green workspace, but the brief does not prove Phase 3 caused it.

## 6. Interleave commit for `get_next_action` (D-8, T3.5)

**Writer order:** finish #11 corrections, then #12 and its inventory work, then land #10’s isolated T3.5 RED/GREEN commits. No other part of `mcp/tools.py` may change in T3.5.

Keep both decorators, including `@consistent_read`, and extend the signature:

```python
@tool()
@consistent_read
def get_next_action(
    energy: str = "medium",
    time_minutes: int = 25,
    modality: str = "recall",
    interleave: str = "off",
) -> dict[str, Any]:
```

Add the docstring argument:

```python
        interleave: "off" (default) or "adaptive".
```

Extend the existing engine import:

```python
from studyloop.learning.decision import (
    EnergyLevel,
    InterleaveMode,
    Modality,
    build_now_plan,
)
```

After the current energy/modality validation, add:

```python
valid_interleave = get_args(InterleaveMode)
if interleave not in valid_interleave:
    raise ToolError(
        f"Invalid interleave {interleave!r}: choose one of {valid_interleave}"
    )
```

Forward it:

```python
plan = build_now_plan(
    energy=cast("EnergyLevel", energy),
    time_minutes=time_minutes,
    modality=cast("Modality", modality),
    interleave=cast("InterleaveMode", interleave),
)
```

**Reuse the existing validation pattern verbatim; do not factor it in this last-writer commit.** That minimizes scope and preserves existing error wording.

Add `tests/test_mcp_next_action.py` with:

| Test | Required assertion |
|---|---|
| `test_get_next_action_schema_adds_interleave_default_off` | Production tool schema includes a non-required `interleave` property with default `"off"`; existing fields/defaults remain. |
| `test_get_next_action_forwards_adaptive_interleave_once` | A seam spy sees exactly one `build_now_plan(..., interleave="adaptive")` call and the response equals its view JSON. |
| `test_get_next_action_adaptive_returns_nonempty_ratio` | Real engine, isolated fixtures, medium/high energy: response reports adaptive mode and the corresponding nonempty `INTERLEAVE_RATIOS` value. |
| `test_get_next_action_invalid_interleave_names_choices_without_engine_call` | Parameterize `"ADAPTIVE"`, `"random"` and `""`; each raises `ToolError` containing the invalid value and both choices; engine call count is zero. |
| `test_get_next_action_default_and_explicit_off_match_unchanged_golden` | Frozen clock and isolated empty world: omitted and explicit `"off"` serialize identically to the unchanged `now_plan_no_active.json`. |

Record RED before modifying the tool, then GREEN for the new tests, MCP suite and stdio smoke. T3.5 must neither change tool count nor move the golden; MCP interleave parity remains #10’s acceptance criterion, completed at its mandated post-#12 position.
