# 1. Verdict

**ACCEPT-WITH-CORRECTIONS** — Phase 2 meets D-1/D-2/D-3/D-5/D-6 and T2.1–T2.5, but `ActivePlanGuidance` must expose readiness before `#10` consumes it, because deviation 12 just made active-but-unready a live, unwritable state the ranker will otherwise promote blind.

# 2. Findings

## 🟡 `ActivePlanGuidance` drops readiness — D-5 hole given deviation 12

`ActivePlanGuidance.from_plan` (`planning/views.py`) warns on no milestones, empty `match_keys`, and a non-date `target_date`. It does **not** surface `ReadinessView` blockers (missing why / success criteria). `PlanSummary` does not carry readiness either (`web/routes/plans.py` `_written` returns `detail.summary` and `detail.readiness` as sibling keys).

Deviation 12 correctly refuses `SetMilestone` / `RevisePlan` on an active husk (`test_set_milestone_on_unready_active_document_is_refused`). `get_active_guidance` still emits that husk with `warnings == ()` if it has topics and a milestone list. `#10` is specified to call this and nothing else; it cannot see that every write will `PlanNotReady` without a second `inspect` per plan, which defeats “parsed once, cheap”.

**Fix:** in `from_plan`, `ready = ReadinessView.from_plan(plan)`; put `ready.blockers` on the view (preferred: fields `ready: bool` and `blockers: tuple[str, ...]`, additive on `to_json_dict`; folding into `warnings` is acceptable). Do not filter the plan out — it is active; the ranker decides.

**RED:** `test_active_guidance_names_readiness_blockers_on_unready_active_plan` — hand-edit an `active` document with milestones + topics and no `### Why` / success list; assert it appears in `.plans` and the blockers are visible on that entry with no extra store read. Update the guidance requirement in `specs/active-learning-decisions/spec.md`.

## 🔵 `PlanSummary.days_until_target` ignores the pinned `today`

`ActivePlanGuidance.from_plan` computes urgency via `plan.days_until_target(today)` then nests `PlanSummary.from_plan(plan)` (real clock). Deviation 3 documents this. `#10` must use `target_urgency`, never `g.plan.days_until_target`. Thread `today` into `PlanSummary.from_plan` or stop exposing that field on the nested summary.

**RED:** same document, `get_active_guidance(today=d1)` vs `today=d2` straddling the target — `target_urgency` changes and `g.plan.days_until_target` agrees (or is absent). Current `test_active_guidance_defaults_to_the_real_today` is vacuous (offset +60 is `later` either way) and no test passes two different `today` values.

## 🔵 Two-read `created` can lie under concurrency

`cli/_plan.py` `plan_record` and `mcp/tools.py` `record_plan_learning` do `inspect` → `apply(RevisePlan(learning_record=…))` → `created = before.learning_record_matching(spec) is None`. `_revise` discards `append_learning_record`’s `(record, created)`. A same-spec writer between the two calls reports `created=True` on a no-op.

Not a document bug. Before `#11` grows more idempotent writes: return `created` from the seam (field on `PlanDetail`, or a small `ReviseResult`). Spies in `test_record_is_revise_plan_with_a_learning_record` / `test_retry_reports_created_false_through_the_seam` stay valid.

## 🔵 Sink status is parsed from two warning strings

`PlanApplication.assess` (`_DB_WARNING` / `_DOCUMENT_WARNING` membership). Correct today — `test_planning_evaluation.py` is frozen, so `evaluate_and_record` cannot grow structured outcomes. Fields cannot disagree with the warnings they are derived from. When that file is unfrozen, return sink enums from the writer; delete the string scrape. `recording_complete` vacuously true for a preview is acceptable (`test_assess_preview_writes_neither_sink`); CLI checks `record` before printing, Web POST always records.

## 🔵 No seam test that a learning-record-only `RevisePlan` on an unready active plan is refused

SetMilestone is pinned. The same `_revise` gate covers records, but the product decision in deviation 12 is not. Add `test_revise_learning_record_on_unready_active_is_refused` next to `test_set_milestone_on_unready_active_document_is_refused` (byte-identical document, `PlanNotReady`, zero `save_plan`). MCP `test_not_ready_refusal_is_a_tool_error_naming_the_blockers` mocks the exception and does not exercise the real document.

## 💡 `CreatePlan.answers` (and `RevisePlan.milestones`) stay live mappings

Do **not** freeze this phase — no adapter mutates them after construction. Freeze (MappingProxyType / tuple-of-pairs) before `#11` `create_study_plan` lands; an agent retaining the intent can otherwise mutate `answers` under a frozen dataclass.

## 💡 `PlanApplication` still uninjectable

Constructor takes no path; tests isolate via `PLANS_DIR_ENV` / `STUDYLOOP_DB`. Acceptable. Do not invent a DI seam in `#10`.

## 💡 Parser: concepts regex stops at the first `)`

Out of scope. `normalise_match_key("RANK()") == "rank"` only helps once the parser kept the token. Do not “fix” matching to paper over it.

---

### Checklist (a)–(k)

**(a) Write-before-refusal / gate bypass — clean.**
`_set_milestone`, `_revise`, `_persist_new`, `_replace`: `_assert_can_be_active` on the *candidate* then one save. `_delete` / `assess` are not doors into `active`. Web toggle/DELETE/evaluate, CLI six, MCP tool all go through `apply`/`assess`. `evaluate_and_record` is the only checkpoint writer. Pause (`TransitionLifecycle` → `status="paused"`) skips the gate and is the escape hatch for a husk.

**(b) SetMilestone.** Idempotent set, not toggle (`test_set_milestone_done_is_idempotent`). `not 0 <= index < total` refuses negative and past-end (`test_set_milestone_negative_index_raises`). First raiser of `InvalidMilestone`. Retry still calls `save_plan` (bumps `updated`); spec scenario says “each application saves exactly once” — meaning-idempotent, not byte-idempotent. Correct.

**(c) DeleteResult.** Load → confirm → `delete_plan`; `deleted == False` → `PlanNotFound` (vanished between load and unlink). Checkpoint log kept, index row dropped — right pair (`test_delete_retains_checkpoint_history`). Frozen `DeleteResult`, `to_json_dict() == {"deleted": True, "plan_id": …}`.

**(d) assess.** Sinks match warnings by construction. String scrape is the constrained-correct choice under the evaluation-test freeze. Vacuous `recording_complete` on preview: accept. Full warning list on the frozen view, not `PlanEvaluation.warnings`: accept (review-1). No `PartialRecording`.

**(e) get_active_guidance.** Ordered by `plan_id`, one entry per `active`, drafts/paused/complete/abandoned skipped. `normalise_match_key`: NFKC + casefold + `[^\w\s]|_` → space + collapse; `_` treated as punctuation (`"a.b_c"` → `"a b c"`) — what `#10` must call (exported). Urgency: `<0` overdue, `0..7` soon, `>7` later, `None` undated (`SOON_WITHIN_DAYS = 7`). Completion action only when `milestones and next is None`; empty milestones do not complete. Unparseable files: `list_plan_ids() - parsed` → collection `warnings`. Two directory scans: acceptable. Content-as-data: title goes into `completion_action` via `!r`; ranker must not treat that string as instructions. Readiness gap: 🟡 above.

**(f) Immutability.** Views frozen; `match_keys` is `frozenset`; `to_json_dict` fresh (leak tests in `test_assessment_result_is_frozen_and_matches_the_legacy_evaluation_dict`, `test_active_guidance_views_are_frozen_and_json_fresh`). Lenient `_freeze_rows` (`isoformat`/`str`): accept — CLI/DB already `default=str`; do not crash a successful evaluation.

**(g) Architecture guard.** Right shape: AST + explicit forbidden re-exports + planted-violation matrix + `__all__` self-check (`test_forbidden_name_list_covers_every_reexport`). Documented misses (attribute access on an allowed name, non-literal `importlib`) are acceptable — whole-package `import studyloop.planning` is banned, so `planning.store` is not reachable. Tests importing store are out of scope by design. `plans_dir` is not a hole: location resolver, no read/write; needed by `plan path` / the Created line. `cli/_exercise.py` and `cli/_brain.py` had to move or the guard fails — correct (deviation 11).

**(h) Learning-record fold.** Store-authoritative is the right direction. The store cannot import the seam; `record_learning` still exists for frozen `test_plan_record.py`; one pure function `append_learning_record`; seam translates `ValueError` → `InvalidField` (`test_learning_record_validation_is_the_stores_single_copy`). Tasks.md “one copy” is satisfied; “seam’s copy” would have duplicated or inverted the layers. Accept deviation 4.

**(i) Adapters.** All catch `PlanError` (MCP special-cases `PlanNotReady` then `PlanError`) — never the store family. Web toggle is read-then-`SetMilestone(opposite)`: a retried request cannot flip twice; two tabs can lost-update — acceptable for a checkbox. Honest `recorded` + additive `db_write`/`document_write`; `201` on partial (D-1). GET evaluate still has a FastAPI phase `Query` pattern; POST does not — matches the web-ui spec (POST only).

**(j) Tests.** Public seam, isolated `PLANS_DIR_ENV`/`STUDYLOOP_DB`, spies on `PlanApplication.apply`/`assess`/`inspect`/`browse`/`reindex`, planted guard, RED commits precede GREEN. Frozen files untouched as claimed. Gaps: the 🟡 readiness test, the 🔵 two-`today` test, the 🔵 learning-record-on-husk test.

**(k) Deviations — accept / reverse**

| # | Ruling | Why |
|---|--------|-----|
| 1 | **Accept** | `DeleteResult` vs `PlanDetail`; `AssessPlan` is a different verb. |
| 2 | **Accept** | `reindex()` is required by D-6. |
| 3 | **Accept** `today=`; **fix** nested `PlanSummary` clock (🔵). |
| 4 | **Accept** | Store is the only layer both callers can share. |
| 5 | **Accept** | Kills the adapter-side identity rule; two-read `created` is 🔵. |
| 6 | **Accept** | Bug B fix; additive keys; frozen web tests still pass. |
| 7 | **Accept** | Evaluation succeeded; exit 0 is D-1. |
| 8 | **Accept** | Frozen CLI `"No milestone at index 99" in output` constraint. Do not let capitalisation hacks spread. |
| 9 | **Accept** | Vacuous preview + full warning list are spec’d and tested. |
| 10 | **Accept** | Lenient row freeze matches existing `default=str`. |
| 11 | **Accept** | In D-6’s package list even if not in T2.1–T2.5. |
| 12 | **Accept — keep the gate** | See ruling below. |
| 13 | **Accept as note** | Parser bug, out of scope. |

### Deviation 12 ruling — keep the gate

Do **not** skip readiness for “writes that cannot change readiness”.

D-2 is the resulting document, not the field list. A skip-list is a second policy site (which fields affect readiness?) — the thing the seam exists to destroy. A learning record on a plan with no mission is not ADR-0010 “record first”; it is writing into a husk the system already cannot evaluate.

Escape hatch already works: `TransitionLifecycle(status="paused")` sets `candidate.status != "active"`, skips `_assert_can_be_active`, saves. Repair, then reactivate through the same gate. `test_set_milestone_on_unready_active_document_is_refused` stays; add the sibling RevisePlan test (🔵). Owner-visible consequence: a hand-edited / xTiles-imported active husk cannot `plan record` / `plan milestone` / `record_plan_learning` until paused or repaired. That is the right call.

# 3. Spec review

The four deltas match the shipped code.

- Guidance “**Nothing consumes it yet**” / `studyloop now` and the Today card unchanged: stated. Six MCP tools “**not yet registered**”: stated. Stdio inventory unchanged: stated.
- Learning-record “one copy” is specified as `store.append_learning_record` — matches deviation 4, not the original tasks.md wording; the spec was updated honestly.
- Web toggle keys, DELETE `{deleted, plan_id}`, evaluate `recorded`/`db_write`/`document_write` + `201` on partial, CLI `--activate` as one `CreatePlan`, milestone set, partial-record copy, `created` via `learning_record_matching`: all shipped.

**Shipped, underspecced (not a lie):** `normalise_match_key` NFKC and `_` → space; `today` keyword-only; `InvalidMilestone` message shape `No milestone at index N (plan has M)`; plans-panel.js “Partially recorded …” string (API is spec’d, JS is not).

**Not shipped, not claimed:** consumer of `get_active_guidance`; MCP `set_study_plan_milestone` / `evaluate_study_plan` / `delete_study_plan`.

**Must add with the 🟡:** guidance requirement does not mention readiness blockers. That omission is now wrong given deviation 12.

# 4. Phase 3 hazards

**`#10` (`now` ← `get_active_guidance`)**
- Consume `target_urgency` and `match_keys`, never roll a second normaliser and never read `g.plan.days_until_target` until the 🔵 is fixed.
- Call the exported `normalise_match_key` on candidates; equality on the key, no substring (`"rank"` ≮ `"frank"`).
- Honour collection `warnings` (unparseable files are otherwise invisible) and, once the 🟡 lands, per-plan unreadiness — do not recommend a next milestone the seam will refuse to tick.
- `completion_action` is English with a title in it — data, not a prompt.
- `energy_floor` is the raw document value (clamped on write only); a hand-edit of `0` or `99` will arrive as-is.
- Degraded entries (`next_milestone is None`, empty `match_keys`) are in-contract; the ranker must not assume a singleton or a healthy plan.

**`#11` (six MCP tools)**
- `AssessPlan` is not in `PlanIntent` — `evaluate_study_plan` calls `assess()`, not `apply()`.
- `DeletePlan` requires `confirmed=True` in the intent; the tool must take an explicit flag (HTTP DELETE is its own confirmation; MCP is not).
- `SetMilestone` is a set; do not ship a toggle tool.
- Copy `record_plan_learning`’s `PlanNotReady` → `ToolError` with blockers; do not invent a second mapping.
- Guard will fail the moment `tools.py` imports `store`/`record_learning`/the store error family.
- Freeze `CreatePlan.answers` before `create_study_plan`.

**`#13a` (purpose)**
- `match_keys` / `completion_action` / readiness blockers are learner-facing data. Purpose must not parse blocker strings as an API.

# 5. Process finding

**Deviation 12** — whether readiness-neutral writes on a legacy active-but-unready document skip the gate.

That is a product/ADR-0010 call (wind-down “record first” vs D-2), not a mechanical consequence of the work order. The agent chose consistency with D-2; I endorse it, and the pause-then-repair hatch is real. A human should have confirmed that imported xTiles husks may not record until paused *before* CLI/MCP started refusing them. Deviations 4 and 8 are layering and a frozen-assertion workaround; 12 is the one that changes what a learner can do tomorrow.
