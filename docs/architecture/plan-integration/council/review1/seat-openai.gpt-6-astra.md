## 1. Verdict

**REJECT** — mixed status-and-field PATCH requests gate and persist the old document before applying edits, so Phase 1 still permits active-but-unready plans and introduces a two-write operation where the previous route used one.

## 2. Findings

### 🔴 F1 — Mixed PATCH bypasses the resulting-document gate and splits persistence

**Location:** `web/routes/plans.py::patch_plan`; `planning/application.py::_transition`.

For a ready draft, this request succeeds:

```json
{"status": "active", "milestones": []}
```

`TransitionLifecycle` checks the existing milestones and saves `active`; the route then removes the milestones and saves again without a gate. Conversely, an unready draft supplied with sufficient milestones in the same activation request is refused before those milestones are considered.

Field-only `{"milestones": []}` against an already-active plan also bypasses the seam. The latter predates this change, but contradicts the new resulting-document requirement.

Validating `_field_updates` first prevents malformed fields from following a committed transition; it does **not** restore atomicity. Failure of the second save leaves the status change persisted. Individual atomic file replacements do not make two saves one operation.

**Fix:** Bring the necessary `RevisePlan` functionality forward: load once, validate and apply all requested edits to the candidate, check its resulting active state, then save once. The route must delegate the whole PATCH operation, not compose a persisted transition with direct mutation. Do not restore a route-local gate.

**RED tests:** Add to `tests/test_plan_surface_parity.py`:

- `test_patch_activation_with_removed_milestones_refuses_without_write`: ready draft, combined request above, 422, original bytes unchanged.
- `test_patch_activation_with_added_milestones_checks_resulting_document`: otherwise-ready draft lacking milestones, combined activation and milestone addition, 200 and ready active result.
- `test_patch_active_plan_cannot_remove_all_milestones`: field-only destructive edit, 422 and original bytes unchanged.
- `test_combined_patch_save_failure_does_not_commit_status`: fail persistence and assert original bytes remain unchanged.

Add a public-`apply` test in `tests/test_plan_application.py` asserting a successful compound revision invokes persistence exactly once.

**Arbitration error:** Deferring all field revision while migrating only the status component of a compound PATCH was not a safe phase boundary.

### 🟡 F2 — Deep immutability is factory-dependent, not a property of every view

**Location:** `planning/views.py::PlanningBrief`, `PlanningBrief.build`, `_freeze`.

Seam-produced views use tuples and expose no mutable `StudyPlan`, `Mission`, or `Milestone`. Their ordinary JSON projections build fresh containers.

However, `PlanningBrief` legally accepts a mutable mapping through its generated constructor:

```python
seed = {"notes": ["before"]}
brief = PlanningBrief(interview=(), evidence_seed=seed, existing_plans=())
seed["notes"].append("after")
```

The view changes despite being frozen. Only `build()` freezes the seed, contrary to the statement that it is “deep-frozen on construction.” `_freeze` also returns unsupported mutable leaf objects unchanged; whether production seeds contain such objects is **not established by the brief**.

**Fix:** Freeze and defensively copy `evidence_seed` in `__post_init__`, using `object.__setattr__`. Define an allowed JSON-like seed value type and reject unsupported leaves rather than returning arbitrary objects unchanged. Keep `build()` as a convenience factory.

**RED tests:** In `tests/test_plan_application.py`:

- `test_planning_brief_direct_constructor_defensively_freezes_seed`
- `test_planning_brief_nested_seed_mutation_cannot_change_view`
- `test_planning_brief_json_calls_do_not_share_nested_containers`
- `test_planning_brief_rejects_unsupported_mutable_seed_leaf`

The existing `test_views_are_immutable_and_json_fresh` is useful but does not exercise `PlanningBrief` construction or nested seed aliasing.

### 🟡 F3 — Domain exception translation has uncovered paths

**Location:** `planning/application.py::inspect`, `_replace`, `_transition`; `cli/_plan.py::plan_list`.

The Web `_http_error` mapping covers every specified domain exception correctly. Its inclusion of `plan_id` in the 422 detail preserves the old implementation.

The seam translates store errors in `_load` and `_persist_new`, but `inspect` subsequently calls `store.load_plan_text` outside translation. If that call raises `PlanNotFoundError` after the first load succeeds, it escapes both adapters’ `except PlanError` handlers. Actual concurrent-deletion behavior is **not established by the brief**, but the unwrapped call is visible.

Likewise, which declared store exceptions `save_plan` can raise is **not established by the brief**; translation completeness for replacement and transition is therefore unproven. Do not turn arbitrary operational failures into domain validation errors.

CLI `show` and `status` map their expected seam refusals, including activation blockers. `plan_list` calls `browse` without a `PlanError` handler. Whether Click prevents every invalid filter is **not established by the shown diff**.

**Fix:** Translate declared store domain errors consistently at every seam storage boundary. Route CLI `browse` refusals through `_fail_for`. Preserve unexpected failures as operational failures rather than falsely reporting invalid input.

**RED tests:**

- `tests/test_plan_application.py::test_inspect_markdown_translates_store_not_found_after_initial_load`
- A new CLI seam test module: `test_plan_list_domain_refusal_exits_without_traceback`
- Parameterized public-`apply` translation tests for any declared domain errors from `save_plan`.

### 🟡 F4 — Conflict precedence contradicts the unconditional duplicate-ID scenario

**Location:** `planning/application.py::_persist_new`; `specs/web-ui/spec.md`, “Duplicate id without overwrite.”

The gate runs before conflict detection. An existing ID plus an unready active create raises `PlanNotReady`, producing 422 rather than the scenario’s unconditional 409. The existing conflict test uses a ready draft and misses this intersection.

Both outcomes preserve the document, but the API precedence is unspecified in one place and asserted unconditionally in another.

**Fix:** Honor the stated duplicate-ID scenario: validate identity and detect an existing explicit ID before readiness, while retaining the store’s final conflict check for races. If readiness-first is intentional, obtain an explicit contract amendment instead of claiming exact spec conformance.

**RED tests:** Parameterize create and import in:

- `tests/test_plan_application.py::test_duplicate_unready_active_create_reports_conflict`
- `tests/test_plan_surface_parity.py::test_duplicate_unready_active_post_returns_409_without_write`

Include malformed explicit import IDs to pin whether identity validation precedes readiness.

### 🟡 F5 — Import identity allocation and successful active document paths are insufficiently pinned

**Location:** `planning/application.py::_import`, `_persist_new`; `tests/test_plan_application.py`.

`ReplaceDocument` explicitly preserves the loaded plan’s ID and `created`; `test_replace_preserves_id_and_created` verifies incoming-frontmatter mismatch handling.

`ImportDocument` deliberately lets the explicit ID override frontmatter. It does not explicitly implement its documented final fallback—an ID derived from the title—and removes the route’s former `unique_plan_id` call. Whether `parse_plan` or `store.create_plan` supplies equivalent unique allocation is **not established by the brief**.

The successful import test covers only a frontmatter ID. Refused imports do not prove the overridden ID is used for persistence. Incoming import `created` preservation is also untested. Import creates a new document; it should not silently inherit replacement’s preservation rules.

**Fix:** Make import identity precedence explicit and test it: explicit ID, otherwise frontmatter ID, otherwise unique title-derived ID. Allocate the final ID before readiness so refusal views identify the candidate correctly. Document overwrite timestamp semantics separately.

**RED tests:** In `tests/test_plan_application.py`:

- `test_import_explicit_id_overrides_frontmatter_without_creating_old_id`
- `test_import_without_id_allocates_unique_title_slug`
- `test_import_preserves_document_created`
- `test_import_overwrite_unready_active_preserves_existing_bytes`
- `test_ready_active_import_succeeds`
- `test_ready_active_replacement_succeeds`

For a mismatch between a stored filename and its own frontmatter ID, store loading semantics are **not established by the brief**. Add `test_replace_keeps_requested_storage_identity_when_frontmatter_disagrees`; the done-criterion is one updated target document and no second file.

### 🟡 F6 — Persistence-failure and database-isolation evidence is incomplete

**Location:** `planning/evaluation.py::evaluate_and_record`; new test fixtures.

The Bug B implementation correctly handles both `False` and exceptions, adds one warning, and leaves the independent Markdown branch reachable. It satisfies D-1 without introducing `PartialRecording`.

The Bug B RED tests are not included, so their coverage is **not established by the brief**. The new fixtures isolate the plans directory, but not visibly the checkpoint database. In particular, `test_inspect_carries_markdown_and_history_only_on_request` assumes history for `"demo"` is empty. A repository-wide DB fixture may establish that; its existence is **not established by the brief**.

**Fix:** Supply the Bug B regression coverage and explicitly establish isolated checkpoint storage for the new tests. Add tests in a new file rather than modifying the three protected legacy test files.

**RED tests:** `tests/test_plan_recording_failures.py`:

- `test_record_false_warns_and_still_attempts_markdown_append`
- `test_record_exception_warns_and_still_attempts_markdown_append`
- `test_record_success_adds_no_database_warning`
- `test_markdown_failure_does_not_discard_successful_database_recording`

Each should assert the returned evaluation and independent write outcomes. History tests should seed and query an isolated database, including a nonempty history and `history_limit`.

### Additional contract checks

- **Dispatch/type hints:** The closed four-member `PlanIntent` union, `isinstance` narrowing, and terminal `assert_never` are sound for statically typed callers. They do not validate arbitrary runtime objects; that is not a defect in this typed API. The reported zero pyright errors are credible evidence of static consistency, not proof of runtime input safety.
- **Intent immutability:** `CreatePlan.answers` remains caller-mutable despite `frozen=True`; `dict(intent.answers)` copies only its outer mapping. This is a future ownership hazard, not evidence that returned views leak models.
- **Test approach:** Existing new tests primarily assert through public seam methods or public adapters, not private application helpers. Legacy store use for setup and byte-level persistence assertions is appropriate. Cross-surface refusal equality and unchanged-document assertions are strong. Passing legacy assertions does not cover compound PATCH semantics.
- **Gate coverage:** Create, import, replacement, and status-only transitions visibly use the shared gate. CLI `new --activate` retains a separate readiness decision and direct write, but does not visibly bypass readiness. Therefore “one seam every adapter goes through” describes a target architecture, not this phase.

### Six reported deviations

| Deviation | Decision | Reason |
|---|---|---|
| 1. Add `ImportDocument`; honor explicit import ID | **Accept, with F5 tests** | Raw Markdown is an activation door. Explicit-ID handling is a separate behavior correction and needs successful persistence coverage. |
| 2. Widen view fields | **Accept** | D-3 requires preserving existing bodies. The old route confirms document checkpoints, notes, resources, and learning records belong in the detail projection. |
| 3. No `plans_dir` constructor argument | **Accept** | Keeping established directory resolution avoids introducing a second configuration mechanism; database isolation remains a separate concern. |
| 4. Unsuffixed domain errors and N818 exemption | **Accept** | Matches arbitration and keeps domain errors distinguishable from existing store exceptions. |
| 5. Validate fields, transition, then edit/save | **Reverse** | F1 is a correctness failure, not merely changed 400/422 ordering. Validate one resulting candidate and persist once; separately pin any deliberate error-precedence change. |
| 6. Migrate additional read paths | **Accept, with coverage** | These belong behind the seam, but exact nonempty history serialization and optional-fetch behavior need tests. `get_interview` now also browses plans only to discard `existing_plans`; avoid that extra work if it becomes material. |

## 3. Spec/doc review

**The delta spec does not exactly match the code.**

- Its central phrase, **“the resulting document,”** is violated by mixed PATCH and field-only edits to active plans.
- “Every Web API path that can leave a study plan in the `active` state” also encompasses deferred mutation paths, not merely four named activation doors. The specification cannot simultaneously make that universal promise and exempt direct field writers.
- “Duplicate id without overwrite” promises 409 without accounting for readiness-first precedence.
- The ready-plan scenario omits successful raw-Markdown import, despite import being part of the requirement.
- The displayed 422 object is the **`detail` payload**, not the complete HTTP response body. Express the response as `{"detail": {...}}`; preserve `plan_id` because the old route included it. The shorter design §2 sketch should be corrected rather than used to remove a legacy key.
- Summary/readiness projections have direct equality tests. Exact nonempty detail/history compatibility is **not established by the supplied tests**.

Add compound-PATCH scenarios corresponding to F1, a ready active import scenario, conflict/readiness precedence, and successful import-ID mismatch handling.

**The public paragraph is overbroad.** The statement “a plan never appears active while it cannot be tracked” is false for the destructive PATCH examples and is not guaranteed for externally edited Markdown.

After fixing F1, bound the paragraph to application-mediated writes, for example:

> Creating, importing, replacing, or revising a plan through supported Web operations checks the resulting document before saving it as active. CLI activation commands also refuse plans missing a mission why, success criteria, or milestones. Refused activation writes nothing. More than one plan may be active.

Until all relevant writers migrate, do not claim that every surface uses the same application seam.

## 4. Phase 2 hazards

| Area | Hazard and measurable done-criterion |
|---|---|
| `RevisePlan` | Must own compound status/field updates and resulting-state validation. One load/candidate/save operation; F1 tests pass with no direct PATCH `save_plan` call. |
| `SetMilestone` | Define invalid-index semantics, including negative indices, and resulting-active readiness. `test_set_milestone_invalid_index_preserves_document` raises `InvalidMilestone`; Web maps it to 404. |
| `DeletePlan` | `apply() -> PlanDetail` does not naturally represent deletion. Introduce an explicit frozen deletion result or separate operation; test that deletion removes the document while preserving checkpoint history. |
| `assess` / `AssessPlan` | No assessment result view exists yet. Introduce a frozen evaluation result carrying warnings and immutable evidence. Preserve Bug B’s independent DB/Markdown outcomes; do not invent `PartialRecording`. |
| `get_active_guidance` | Multiple active plans are explicitly supported. Return deterministic guidance for all selected active plans, not an arbitrary singleton; test two active plans and an empty collection. Treat plan/history content as data, not agent instructions. |
| Intent ownership | Snapshot or normalize nested `CreatePlan.answers` before introducing queues, retries, or deferred application. Test that later caller mutation cannot change an accepted intent’s meaning. |
| Read costs | `inspect` always builds readiness/detail, even for Markdown/history-only routes; `prepare_planning` always browses existing plans. Keep optional expensive work explicit and test that default inspection does not call checkpoint history or load raw text. |
| Boundary validation | `history_limit` is constrained by Web `Query`, not by `PlanApplication.inspect`. Define equivalent seam constraints before exposing it through MCP; test rejected limits with no database query. |
| MCP overwrite | D-4 protects the external schema, not merely the intent. Ensure neither create nor any future import tool exposes or indirectly forwards `overwrite`; add schema and existing-plan-preservation tests. |
| Migration claims | `planning/__init__.py` still exports legacy writers. Retain compatibility as needed, but add adapter dependency tests proving migrated handlers no longer call them; a search for `readiness(` alone cannot detect the F1 bypass. |

## 5. Process finding

**Recommend (iv): a narrowly scoped, temporary RED-test exemption.** Keep tests under pyright, but allow line-level missing-symbol suppressions only for planned imports or accesses in a clearly identified RED commit; require their removal in GREEN and require the completed branch to pass normal checking without them. The reported file-level directive was pragmatic and its verified removal is acceptable here, but it suppressed unrelated attribute errors throughout that test file. Exempting all tests permanently loses useful checking, while squashing RED+GREEN removes the visible test-before-code evidence. The merge criterion should include an actual recorded pytest failure caused by the missing behavior—not merely a type-check failure—and zero temporary RED suppressions in the merge candidate.
