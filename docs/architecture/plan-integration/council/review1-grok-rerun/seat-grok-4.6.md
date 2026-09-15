## Verdict

ACCEPT-WITH-CORRECTIONS: the seam honours D-1–D-4 and closes every Web door into `active`, but `ImportDocument` does not implement its own id fallback and `patch_plan` splits one body across two saves — Phase 2 will copy both holes.

## Findings

🟡 `PlanApplication._import` — docstring and the pre-seam route both say the id is `plan_id` else frontmatter else title slug (`unique_plan_id`). The method only applies `intent.plan_id` and otherwise trusts `parse_plan(..., plan_id="")`. The old branch `if not payload.get("plan_id") and not plan.plan_id: plan.plan_id = unique_plan_id(plan.title)` is gone. `test_import_document_keeps_its_frontmatter_id_and_stays_draft` only covers a frontmatter id; an id-less document is untested. Restore the `unique_plan_id(plan.title)` fallback after the explicit-id override (and run `validate_plan_id` on an explicit id, matching `_create`). RED: `test_import_without_ids_slugs_the_title` (no write of `plan_id=""`; a second import of the same title gets `-2`).

🟡 `patch_plan` in `web/routes/plans.py` — the comment claims “nothing is written if any part of the body is unusable — the all-or-nothing the single `save_plan` used to give.” False: `TransitionLifecycle` saves, then `_load_or_404` + `save_plan` saves again. A failing second write leaves the status changed and the fields not. Collapse status+fields into one write (the future `RevisePlan`) or apply the transition in memory and save once. RED: `test_patch_status_and_title_is_a_single_write` (one `save_plan` / byte-identical rollback if the field save raises). Agent already noted the 400-vs-422 reorder is untested; add `test_patch_empty_title_plus_unready_active_is_400_not_422` and `test_patch_unknown_id_is_404_before_field_validation` (the spec now requires the latter).

🟡 `plan_new` in `cli/_plan.py` still drafts, `ReadinessView.from_plan`s, mutates `status`, and `create_plan`s itself. Same `readiness()` predicate, different policy site: a later change to `_assert_can_be_active` will not apply. D-2 said `CreatePlan` ships in this phase and “no third copy.” Point `--activate` at `CreatePlan(..., status="active")` and keep `_refuse_activation` only as the `PlanNotReady` mapper. RED: `test_cli_new_activate_unready_does_not_call_create_plan` (empty `list_plan_ids()`, same blockers as `POST /api/plans` with `status: active`).

🔵 `PlanApplication._import` assigns `plan.plan_id = explicit_id` with no `store.validate_plan_id`. `_create` validates first, so `CreatePlan(plan_id="../etc/passwd", status="active")` is `InvalidPlanId` while the same id on `ImportDocument` of an unready active doc is `PlanNotReady`. Validate before the gate.

🔵 `planning/__init__.py` re-exports both `PlanNotFound` and `PlanNotFoundError` (and the other store twins). The errors.py comment is right that a second family is a trap; Phase 2 `except` clauses will hit the wrong one. Do not add more store errors to `__all__`; prefer a one-line “adapters catch `PlanError`” note on the store names.

🔵 `PlanApplication.logger` is assigned and never used.

💡 `evaluate_and_record` now honours a `False` return and a raised fault. D-1 is met. No new test is in this pack; the pin lives only in unchanged `test_planning_evaluation.py` (RED commit `3a4f6b01`). That is acceptable if that file already asserts the warning on a `False` return — not re-established here beyond “file unchanged, suite green.”

💡 `str(payload.get("plan_id", "")).strip() or None` in `post_plan`: JSON `null` becomes the id `"None"`. Pre-existing shape; do not copy it into MCP.

**Checklist**

(a) No Web door into `active` bypasses the gate: `CreatePlan` / `ImportDocument` → `_persist_new`, `ReplaceDocument` → `_replace`, `TransitionLifecycle` → `_transition`, all call `_assert_can_be_active` before any write. `rg 'readiness\(' web/routes/plans.py` is 0. CLI `plan status` uses `apply`. CLI `plan new --activate` does not bypass *readiness*, it bypasses the *seam* (🟡 above). `create_plan` / `save_plan` remain public; unmigrated routes can still write, but none of them set `status`.

(b) Views are frozen dataclasses; collections are `tuple` (or `MappingProxyType` for `PlanningBrief.evidence_seed`). Every `to_json_dict` builds a new `dict` and `list()`s tuples; `test_views_are_immutable_and_json_fresh` pins leak-freedom.

(c) No view field is a `StudyPlan` / `Mission` / `Milestone`. `from_plan` / `from_mission` / `from_milestone` copy primitives and tuples.

(d) Web `_http_error` covers every `PlanError` subclass in design §2 (`InvalidMilestone` → 404 is dead until Phase 2; unknown `PlanError` → 500 + log). CLI `_fail_for` special-cases only `PlanNotFound`; `PlanNotReady` is handled at the `plan_status` call site; everything else is `str(exc)` / exit 1. Adequate for the migrated commands; incomplete once `new` / `record` move.

(e) `_replace` forces `current.plan_id` and `current.created`; `test_replace_preserves_id_and_created` covers a rename + rewritten birth date. Markdown / URL id mismatch is silent overwrite, not an error — correct. `ImportDocument` with `overwrite=True` is a clobber and will rewrite `created` (it is not `ReplaceDocument`).

(f) Seam writes happen after the gate. Mixed PATCH is not atomic (🟡). `_create` / `_import` refuse `PlanConflict` / `InvalidPlanId` after the gate; no file is created on refusal (`test_create_unready_active_raises_plan_not_ready`, `test_import_unready_active_document_raises_plan_not_ready`).

(g) `apply`’s `isinstance` chain + `assert_never(intent)` is a sound closed-union dispatch on `PlanIntent`. `_inspect(..., **options: Any)` drops the `include_*` types. `CreatePlan.answers` is a live `Mapping`; `_create` copies via `dict(intent.answers)` before `draft_plan`.

(h) `test_plan_application.py` asserts through `apply` / `browse` / `inspect` / `prepare_planning`, isolates via `PLANS_DIR_ENV`, and does not poke private helpers. `test_plan_surface_parity.py` pins the four Web doors and CLI/Web blocker order. Gaps: id-less import, mixed PATCH, 400-vs-422, CLI `new` still off-seam, `ImportDocument` + `overwrite`, traversal id on import.

(i) Deviations

1. `ImportDocument` — **accept**. D-2 named three intents and was wrong: `POST /api/plans` markdown is a fourth door into `active`. Without the intent the route keeps a local gate (forbidden) or stays ungated (Bug A).
2. Widened view fields — **accept**. D-3 (existing `summary()` / `readiness()` / GET body keys) outranks the sketch. `test_summary_and_readiness_views_match_the_legacy_dicts_exactly` plus `PlanDetail.to_json_dict` as the GET body are the right pins. `plan_id` on `ReadinessView` is why the 422 body kept its old shape; design §2 omitted that key and was incomplete.
3. No `plans_dir` ctor — **accept**. Isolation already lives in `store.plans_dir()` / `STUDYLOOP_PLANS_DIR`; a second knob would fork every fixture.
4. Unsuffixed error names + file-level `noqa: N818` — **accept**. D-3 fixed the spelling; the store already owns the `*Error` names.
5. PATCH order existence → field 400s → transition → edits — **accept the order, not the missing tests and not the two-save**. 400-before-422 is the better all-or-nothing; ship the two RED tests above.
6. Extra read migrations — **accept**. They delete adapter-local assembly without changing bodies (`get_interview` correctly drops `existing_plans`).

## Spec/doc review

The delta requirement matches the shipped Web code: four doors call `apply`, `web/routes/plans.py` has no `readiness(`, 422 shape is `message` + `ReadinessView.to_json_dict()`, refusals write nothing, several actives are legal (`test_multiple_ready_active_plans_are_valid`). Scenarios 1–5 are pinned by `test_every_web_door_into_active_refuses_with_the_same_body` and `test_activation_refusal_is_identical_via_cli_and_web`. Scenario “ready plan still activates on every door” is pinned at the seam, not with an explicit 201/200-per-door Web test — pre-existing `test_web_plans.py` is the only surface cover. “404 before any field of the body is validated” is implemented (`_inspect` before `_field_updates`) and not added as a new test. Error-mapping requirement matches `_http_error` exactly. List/detail/create/patch/interview key sets are unchanged by construction (`PlanSummary`/`ReadinessView` equality tests; interview drops `existing_plans`).

`docs/study-plans.md` is accurate and bounded: the four doors, same check on Web and CLI, no write on refusal, multiple actives allowed, no MCP claim. It undersells nudges (“list of blockers”) and does not mention the 422 / exit-1 shapes; that is acceptable for a learner doc.

## Phase 2 hazards

- `RevisePlan` must absorb today’s split PATCH (status save + field save) or the two-write hole becomes the field-edit contract. Include `notes`: it is writable today and absent from `PlanSummary` / `PlanDetail` except via `markdown`.
- `SetMilestone` must be the first raiser of `InvalidMilestone`; the 404 mapping is already wired and untested.
- `DeletePlan` / `ReplaceDocument` / `ImportDocument(overwrite=True)` disagree about `created` and history: replace preserves birth; import+overwrite will not. Pick one before MCP sees `overwrite` (D-4: never expose it).
- `plan new`, `interview`, `evaluate`, `milestone`, `record` and Web evaluate / toggle / DELETE still import `store` / `authoring` directly. `create_plan` stays in `__all__`, so a new adapter can bypass the gate by accident. Delete `_load_or_404` only after those paths move.
- `_refuse_activation` + `ReadinessView.from_plan` in `plan_new` is a second policy site; migrating `new` without deleting it leaves the third copy D-2 forbade.
- `AssessPlan` must wrap `evaluate_and_record` and put Bug B’s warning on a frozen view. Do not add `PartialRecording`. `PlanEvaluation.warnings` is a mutable list — do not return it.
- `get_active_guidance` cannot assume a single active plan; `browse(status="active")` and the public doc now guarantee many.
- `PlanningBrief.existing_plans` is computed then thrown away by `GET /plans/interview`. MCP `prepare` will want it; do not “fix” the Web route by adding the key (D-3).
- Two error families on the package; adapters must catch `PlanError`, never `PlanNotFoundError`, or a seam raise will 500 / traceback.
- `PlanApplication` is uninjectable (no store / dir). Phase 2 tests will keep hitting the filesystem via `PLANS_DIR_ENV`.
- Intents are frozen but not deep-frozen (`CreatePlan.answers` is a live mapping). Do not let `RevisePlan` hold a caller-owned `milestones` list as the source of truth.

## Process finding

(iv) Give `tests/` a pyright overlay that permanently disables only `reportMissingImports` and `reportAttributeAccessIssue`, and leave the rest of the hook on. That is exactly the pair the RED commit had to silence so a test can name `PlanApplication` / `CreatePlan` before the modules exist; making it per-tree removes the add-then-grep-remove ritual this cycle already needed (“0 hits now”). Cost: a misspelled production import inside a test will not fail the hook — catch that on the GREEN commit when the symbol must resolve in `src/`. (i) works only with perfect memory; (ii) drops useful test diagnostics; (iii) erases the RED-then-GREEN trail this review is for.
