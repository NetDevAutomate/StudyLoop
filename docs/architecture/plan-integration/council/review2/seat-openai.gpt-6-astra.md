## 1. Verdict

**ACCEPT-WITH-CORRECTIONS** — retain the seam and adapter migrations, but block Phase 3 until no-op writes, checkpoint readiness, guidance consistency, operation-local learning-record outcomes, and the architecture guard are corrected and regression-tested.

## 2. Findings

### F1 — 🔴 Duplicate intents still change the persisted document

**Files/functions:** `planning/application.py::_set_milestone`, `_revise`, `_append_learning_record`; `tests/test_plan_application_mutations.py::test_set_milestone_done_is_idempotent`.

Both mutation methods unconditionally call `store.save_plan`, which bumps `updated`. A duplicate learning record also unnecessarily re-renders the canonical document and refreshes its index.

Consequences:

- Repeating `SetMilestone(..., done=True)` preserves milestone state, but not necessarily the **same document** required by the work order.
- CLI/MCP learning-record retries have lost the store wrapper’s byte-level no-op guarantee.
- CLI output saying “already recorded (no change)” can be false.
- Retry traffic can alter plan ordering through `updated`.

The milestone test explicitly weakens the contract to “the document’s meaning” and never checks the second save count or document bytes.

**Fix:** Detect actual changes on the loaded candidate. Still perform the required active-document readiness check before returning, but do not save an unchanged candidate. Preserve `append_learning_record`’s `created` outcome instead of discarding it. A combined revision containing a duplicate record and an actual field change must still save once.

**RED tests:**

- `test_repeated_set_preserves_bytes_updated_and_does_not_save`
- `test_duplicate_learning_revision_preserves_bytes_updated_and_does_not_save`
- `test_duplicate_record_with_changed_notes_saves_once`
- `test_noop_on_unready_active_plan_still_obeys_readiness_policy`

Use an advanced clock beyond the store timestamp’s resolution; immediate retries alone can conceal this bug.

**Done:** First effective mutation saves once; identical retries save zero times and preserve bytes and `updated`. Correct the delta spec’s “each application saves exactly once.”

### F2 — 🔴 Assessment document recording bypasses the active-document gate

**File/function:** `planning/application.py::PlanApplication.assess`.

An unready active document is refused by `SetMilestone` and learning-record revision, but `assess(record=True, append_to_plan=True)` sends it directly to `evaluate_and_record`, which re-saves that same active document with a checkpoint.

This contradicts the resulting-document policy used to justify deviation 12. Moving an operation outside `apply()` must not create an exception to that policy.

**Fix:** Before invoking either recording sink, run the one readiness gate when assessment will re-save an active plan document. Checkpoint append does not alter readiness-bearing fields, so checking this loaded candidate is sufficient. Preview and DB-only assessment need not be blocked: neither persists a resulting plan document. Do not run the gate after the database has already been written.

**RED tests in `tests/test_plan_application_mutations.py`:**

- `test_recording_to_unready_active_document_refuses_before_either_sink`
- `test_preview_of_unready_active_plan_is_allowed`
- `test_database_only_assessment_of_unready_active_plan_is_allowed`

Add Web/CLI tests proving the refusal maps to 422/exit 1 without a checkpoint in either sink.

**Done:** No active-document recording bypass; policy refusal causes zero sink calls. Operational failures after policy acceptance remain independent sink outcomes under D-1.

### F3 — 🔴 The Web toggle is not retry-idempotent

**Files/functions:** `web/routes/plans.py::toggle_milestone`; `tests/test_web_plans_seam.py`; Web delta spec.

The route recomputes the opposite state on every request. Replaying the same HTTP request therefore flips the milestone twice. The supplied test actually proves this:

```python
first["done"] is True
second["done"] is False
```

Two concurrent toggle requests can also read the same state and collapse two intended toggles into one update. An idempotent internal intent does not make the adapter’s read–invert–write operation idempotent.

**Fix for Phase 2:** Preserve the existing toggle contract, but remove the false retry-safety claims from route documentation, test documentation and the Web delta. Describe only repeated **identical `SetMilestone` intents** and CLI commands with explicit `--done/--undone` as idempotent.

If HTTP retry safety is required, add an explicit desired-state request or a genuine idempotency-key protocol. Do not silently change the legacy no-body toggle’s meaning.

**Test:** Rename/retain the existing test as `test_legacy_toggle_repeated_requests_flip_twice`. If adding an explicit-set API, first commit `test_replaying_explicit_milestone_set_keeps_desired_state` as RED.

**Done:** No claim that replaying `/toggle` is safe; any new retry-safe API has a replay test.

### F4 — 🔴 Learning-record `created` is inferred from a different read than the mutation

**Files/functions:** `cli/_plan.py::plan_record`, `mcp/tools.py::record_plan_learning`, `planning/views.py::PlanDetail.learning_record_matching`.

The adapters inspect, then the seam loads again. Another writer can insert the same record between those operations. The seam then performs a duplicate/no-op, but the adapter reports `created=True`.

The identity rule also still exists twice: in `store.append_learning_record` and `PlanDetail.learning_record_matching`. Delegating validation is real; centralizing the whole identity decision is not.

**Fix:** Return the append outcome from the mutation itself. For example, add optional frozen learning-record outcome metadata to `PlanDetail`, excluded from its existing JSON serialization. Populate it from `append_learning_record`’s `(record, created)` result. CLI/MCP can then remove their preliminary inspection and matching logic.

This eliminates this particular read-window bug; it does not by itself make concurrent filesystem writes transactional.

**RED tests:**

- `test_record_created_reflects_append_outcome_not_prior_inspection`
- CLI/MCP tests that arrange an intervening insert and require `created=False`
- `test_duplicate_identity_is_decided_by_one_helper`

**Done:** One seam mutation determines both persistence and `created`; existing adapter response keys remain unchanged.

### F5 — 🟡 Guidance must use storage identity, not untrusted frontmatter identity

**File/function:** `planning/application.py::get_active_guidance`.

`_load()` explicitly repairs the known filename/frontmatter mismatch. Guidance bypasses that repair by consuming `store.list_plans()`, then compares parsed `plan_id` values with filenames from `list_plan_ids()`.

For `alpha.md` whose frontmatter says `id: beta`, this can produce:

- guidance naming the wrong plan;
- a false warning that `alpha` could not be parsed;
- duplicate guidance IDs when `beta.md` also exists;
- a Phase 3 recommendation whose subsequent `inspect` targets another document.

**Fix:** Associate parsed results with canonical storage IDs. Prefer enumerating IDs once and loading each through the identity-pinning seam path, collecting expected read/parse failures as warnings. A store iterator returning storage identity and parse outcome would also work, but is not necessary for this phase.

**RED tests in `tests/test_plan_guidance.py`:**

- `test_guidance_pins_frontmatter_mismatch_to_filename`
- `test_guidance_keeps_distinct_files_with_duplicate_frontmatter_ids`
- `test_guidance_warnings_identify_actual_unreadable_files`

**Done:** Exactly one entry per readable active canonical document; unique canonical IDs; deterministic entry and warning order; no false parse warning for an ID mismatch.

Two directory scans alone are not a blocker. Comparing independently collected namespaces is the correctness problem, and also admits transient false warnings during concurrent edits.

### F6 — 🟡 Guidance carries two incompatible clocks

**File/function:** `planning/views.py::ActivePlanGuidance.from_plan`.

`target_urgency` uses supplied `today`; its embedded `PlanSummary.days_until_target` uses the real date. One returned entry can simultaneously say “soon” and expose a negative day count.

Documenting this inconsistency does not make a frozen-clock API deterministic.

**Fix:** Thread the same effective date through `PlanSummary.from_plan`, retaining the existing default for other callers. Resolve the default UTC date once per guidance call, rather than independently for each plan.

**RED test:** `test_guidance_summary_days_and_urgency_use_one_effective_date`, with supplied dates far from the real clock and assertions at −1, 0, 7 and 8 days.

**Done:** The complete guidance payload is equal for equal documents and equal supplied `today`, regardless of wall-clock date.

### F7 — 🟡 `frozenset` violates the binding tuple-only view contract

**File/field:** `planning/views.py::ActivePlanGuidance.match_keys`.

`frozenset` is immutable, but it is not tuple-only. The newly written delta and tests cannot override D-3.

**Fix:** Store sorted, deduplicated keys as `tuple[str, ...]`; serialize them as the existing JSON array. A consumer can build a set locally if needed.

**RED test:** `test_guidance_match_keys_are_sorted_unique_tuples`, including different input orders and duplicates.

**Done:** The field is a deterministic tuple. Existing accepted Phase 1 read-only mapping conventions need not be reopened to make this correction.

The normalization itself follows the supplied algorithm: NFKC, casefold, punctuation and `_` to spaces, then whitespace collapse. Urgency boundaries and the nonempty-all-done completion condition are correct. There is no supplied `decision.py` consumer to compare against yet.

### F8 — 🟡 The architecture guard misses a direct wildcard bypass

**File/function:** `tests/test_architecture_plan_seam.py::_check_module`.

This is not flagged:

```python
from studyloop.planning import *
```

Yet `planning.__all__` exports `save_plan`, `load_plan`, `evaluate_and_record` and the store error family.

The explicit forbidden-name list plus re-export self-check is a reasonable maintenance approach, but wildcard imports defeat it without dynamic strings or attribute tricks.

**Fix:** Reject package-level wildcard imports. Also reject literal dynamic imports of the whole `studyloop.planning` package, since static whole-package imports are already forbidden. Add a planted case for the straightforward transitive bypass `from studyloop.planning.application import store`, or explicitly constrain imports from the four allowed seam modules to their intended public names.

**RED planted cases:**

- `from studyloop.planning import *`
- `from ...planning import *`
- `importlib.import_module("studyloop.planning")`
- `from studyloop.planning.application import store`

**Done:** All planted cases are rejected and current adapters remain clean.

Non-literal dynamic imports and arbitrary attribute/data-flow analysis can remain out of scope. This guard is a regression tripwire, not a sandbox. Tests importing the store directly are appropriately outside D-6. The specific `plans_dir` re-export allowance is acceptable as a location resolver, not a blanket storage exception.

### F9 — 🔵 Sink reporting needs a complete failure matrix, not a second writer

**Files/functions:** `planning/application.py::assess`; `planning/views.py::AssessmentResult`; CLI and plans-panel recording messages.

For the supplied code, sink fields agree with the exact warning markers:

- no recording → both `not_requested`;
- recording → database failure follows `_DB_WARNING`;
- requested document recording → failure follows `_DOCUMENT_WARNING`.

This relies on the existing evaluator emitting those markers reliably and only for attempted sink failures. It is brittle coupling, but there is no demonstrated mismatch requiring an evaluator redesign in this phase.

**Fix:** Keep the single existing writer. Add missing contract coverage for database exceptions, both sinks failing, and DB failure with document recording disabled. Longer-term, put structured outcomes on the existing writer’s return value and preserve legacy warnings as presentation—not vice versa.

When both sinks fail, CLI/UI should say “Checkpoint not recorded,” not “partially recorded.”

**RED tests:**

- `test_assess_database_exception_still_attempts_document`
- `test_assess_both_sinks_failed_returns_evaluation_and_two_failures`
- `test_assess_database_failure_document_not_requested`
- CLI/JS `both_sinks_failed_is_not_called_partial`

`recording_complete=True` for a preview is acceptable as “all requested writes completed,” provided adapters do not translate preview success into “recorded.” The shown adapters do not. Preserving CLI JSON keys while carrying warnings, and additive Web sink fields with 201, are acceptable.

### F10 — 🔵 Tighten freeze and fixture coverage

**Files/functions:** `planning/views.py::_freeze_rows`; `tests/test_plan_application_mutations.py`; `tests/test_mcp_plan_record_seam.py`.

Ordinary mappings, lists and warnings are detached appropriately. However:

- The lenient fallback returns arbitrary `isoformat()` output without ensuring it is an immutable JSON scalar.
- The evaluation tests do not exercise nested row mutation or mutation of the original evaluation after view construction.
- The new MCP tests isolate the plans directory but show no checkpoint/index database isolation, although `_seed()` calls `store.create_plan`.

**Fix/tests:**

- Constrain date rendering to a string or recurse through a bounded, supported conversion.
- Add `test_evaluation_view_detaches_nested_rows_and_warnings`.
- Add `test_lenient_row_leaf_is_immutable_and_json_serializable`.
- Add the `STUDYLOOP_DB` temporary fixture to the MCP file, unless a verified global fixture already provides it.

**Done:** Mutating source objects or returned JSON cannot alter the view; serialization succeeds without `default=str`; MCP tests cannot touch a developer database.

### Required decisions and disposition of all deviations

| # | Ruling |
|---|---|
| 1 | **Accept.** Separate `assess()` result semantics and overloaded `DeleteResult` are appropriate. No `PartialRecording` exception is needed. |
| 2 | **Accept.** `reindex()` is a legitimate application operation and removes an adapter bypass. |
| 3 | **Accept `today`; reverse the split clock.** F6. |
| 4 | **Accept the store helper as an implementation exception.** It mutates only the private in-memory candidate and prevents two validation copies. A dependency-neutral domain helper would be cleaner later; making the store import the seam would be worse. Preserve its outcome under F1/F4. |
| 5 | **Reverse as the adapter outcome mechanism.** Before/after matching is racy and duplicates identity policy. F4. |
| 6 | **Accept.** Additive sink fields, honest `recorded`, and retained 201 preserve a usable evaluation response. |
| 7 | **Accept exit 0 and sink reporting.** Correct “partial” when no sink saved. |
| 8 | **Accept.** Capitalization to preserve the frozen CLI assertion is harmless; negative and out-of-range indices correctly originate as `InvalidMilestone` in the seam. |
| 9 | **Accept.** Full immutable warnings and vacuous completion are defensible with the stated adapter discipline. |
| 10 | **Accept lenient conversion in principle; harden and test it.** F10. |
| 11 | **Accept.** The extra CLI migrations are necessary for D-6; the narrow `plans_dir` exception is reasonable. |
| 12 | **Accept the fixture correction and retain the readiness gate.** Do not carve out `SetMilestone` or learning-record-only revision. Add real legacy-document regression tests rather than relying only on a ready fixture or mocked refusal. |
| 13 | **Accept deferral as a tracked parser bug, not dismissal.** Add a focused round-trip regression in a follow-up before claiming matching fidelity for parenthesized concepts. |

**Legacy-document ruling:** Pause or repair an unready active plan before persisting further changes to that active document. Deletion remains permitted because it leaves no resulting active document. Assessments need the consistent treatment in F2. The CLI refusal should explain “this active plan is incomplete; pause or repair it,” rather than only “Cannot activate,” which is confusing for an already-active plan.

**Other checked paths:** `_revise`, `_set_milestone` and confirmed deletion contain no demonstrated persistent write before their policy refusals. Negative indices are correctly rejected before indexing. `DeleteResult` is frozen; a false unlink result after load becomes `PlanNotFound`, not false success. Retaining checkpoint evidence while removing the document and derived index is the right pair. Add `test_delete_vanished_after_load_raises_not_found` to pin that explicit race branch.

**Inherited hazards:** `CreatePlan.answers` and nested `RevisePlan` inputs remain live mutable containers despite frozen dataclasses. This is not a demonstrated readiness bypass in the shown synchronous calls, so deep snapshots need not block Phase 2; they **must** precede queuing, asynchronous reuse or replay of intent objects. Test nested source mutation when implementing that change. Constructor injection is also desirable, but filesystem integration tests through temporary environment settings are not themselves grounds for rejection.

## 3. Spec review

The deltas mostly describe the migration accurately, but several encode implementation compromises as requirements:

- **Active-learning decisions:** “same document” conflicts with unconditional timestamp-changing saves; change “each application saves exactly once” to “each effective change saves once.” Resolve checkpoint readiness explicitly. Replace the unauthorized `frozenset` requirement and specify one guidance clock.
- **Web UI:** The retry-idempotency claim contradicts both the toggle implementation and its “flips and flips back” scenario. Preserve the scenario and correct the claim.
- **CLI surface:** Before/after matching is an implementation prescription that guarantees the wrong `created` outcome under an intervening write. Specify the mutation’s actual append outcome instead.
- **MCP server:** Make the same `created` correction. The shown tool edit otherwise matches the stated response keys and error mapping.
- **Failure reporting:** Document the all-sinks-failed outcome distinctly from partial success.

The “nothing consumes guidance yet” statements are clear. No supplied production adapter calls `get_active_guidance`; the helper’s docstring saying “the ranker applies this same function” should use future tense.

The claimed Archify deliverable has a commit reference but no supplied diagram source, so its content cannot be reviewed here.

The reported suite receipts and frozen-file checks are useful compatibility evidence. They do not establish contracts absent from assertions—particularly retry bytes, interleaved record creation, identity mismatches and frozen-clock consistency.

## 4. Phase 3 hazards

### #10 — `now` consumes guidance

- Resolve F5–F7 before building ranking logic around IDs, day counts or collection types.
- Import `normalise_match_key`; do not reproduce normalization in `decision.py`. Test equality rather than substring matching, punctuation collisions, full-width text and `_`.
- Keep plan titles, topics and milestone text as **data**. A title embedded in `completion_action` is not authorization to close or extend a plan. Add hostile-content fixtures and verify no lifecycle write occurs.
- Sort every ranking tie explicitly; never inherit set iteration order.
- Test incomplete guidance: one unreadable document must not suppress healthy plans.
- Establish a measurable read budget: one parse per canonical document, zero checkpoint-history calls, and no session-history scan for guidance.
- Do not let the known parentheses parser defect become an unexplained matching regression.

### #11 — six MCP tools

- Use only `PlanApplication`, frozen views/intents and domain errors; strengthen the guard before multiplying adapters.
- Centralize error rendering, including readiness blockers.
- Report mutation outcomes from the seam, not extra adapter reads.
- Keep destructive confirmation explicit and retain the existing prohibition on MCP create-overwrite.
- Snapshot mutable intent payloads before introducing async execution or retry queues.

### #13a — planning purpose

- Keep plan-static guidance separate from evidence-seeded `prepare_planning()`.
- Make “complete plan” a recommendation requiring an explicit learner action, not a lifecycle transition inferred from all milestones being checked.
- Add constructor-level ports or a small injectable application factory when introducing ranker tests; otherwise those tests will unnecessarily depend on global environment variables and real storage.
- Ensure preview, evaluation success and recording success remain distinct concepts in prompts and rendered responses.

**Gate receipt:** Commit failing regression tests before each behavioral correction, then provide passing targeted tests, unchanged protected-file/assertion checks, pyright 0, ruff clean, zero adapter invariant hits, and full Python/JS suites with updated expected totals and no regressions.

## 5. Process finding

**Deviation 12 is the judgment call that most needed human ownership.**

Applying the accepted invariant was technically defensible; changing the fixture was not an assertion edit. But it also removed the old legacy-active shape from the migration tests while changing the user-visible “record first” wind-down workflow. That operational consequence needed an explicit owner decision and a tested recovery path.

Keep the ready fixture, add real legacy CLI/MCP refusal tests, and document pause-or-repair recovery. Do not treat unchanged assertion lines as proof that this workflow remained unchanged.
