## Why

Study Plans exist, persist, activate and evaluate — but the product surfaces learners actually use do not
know they exist. `docs/study-plans.md` says it plainly under "What a plan does not do yet": an active plan
does not bias `studyloop now` or Today; the Web UI cannot launch the planning architect; one MCP tool
(`record_plan_learning`) is the entire agent write surface. GitHub issues #7 (parent) and #8–#15 specified
the fix on 2026-09-04 and nothing landed.

Worse, the current shape has already produced two confirmed bugs, pinned by failing tests at `3a4f6b01`:

1. **Activation readiness bypass.** `web/routes/plans.py` gates `PATCH status=active` on `readiness()`, but
   `POST /plans` with `status=active` and `PATCH` with a whole-document `markdown` replacement do not. The
   API returns `201` with `"status":"active"` and, in the same body, `"readiness":{"ready":false,...}`.
2. **Silent partial checkpoint recording.** `planning/index.py:record_checkpoint()` swallows its own
   failures and returns `False`; `planning/evaluation.py:evaluate_and_record()` discards the boolean, so a
   failed database write yields `warnings == []` — complete recording claimed after a partial one.

Both bugs exist for the same reason: lifecycle policy lives in adapters (one route door got the gate, two
did not) instead of in one application seam every adapter must pass through. The test suite is large and
green because it encodes what the code does, one test per feature, rather than the spec's invariant, one
test per door.

A second, independent stream closes the last loose end from the retired knowledge-proof programme (PR #19):
the `plan_prose_query` phrase-token OR planner, the one retrieval lift that programme established (+0.142
DEV, +0.168 SEALED), was never evaluated on `main` despite the semantic-layer plan-brief committing to do so.

## What Changes

### A. One `PlanApplication` seam (issues #8, #9)

New `planning/{errors,views,intents,application}.py`. Immutable views; a closed union of typed intents;
domain exceptions with no CLI/HTTP/MCP types; one `apply()` writer that validates readiness before any
canonical write; one `assess()` that reports each checkpoint sink's outcome. CLI and Web adapters become
thin. An AST-based architecture test forbids adapters from importing `planning.{store,index,authoring,
evaluation}`. Bug A is closed by the seam (no route-local gates remain); Bug B is fixed first, alone, in
`evaluate_and_record`.

### B. Plan-aware `now` (issue #10)

`build_now_plan` consumes `PlanApplication.get_active_guidance()` and biases — never filters — the
existing ranking. `NowPlan`/`LearningRecommendation` gain additive fields emitted only when non-empty, so
the no-active-plan output stays byte-identical to a committed golden. CLI, Web `/api/now`, Today, recap and
MCP `get_next_action` remain delegates; `get_next_action` gains `interleave`.

### C. Nine MCP lifecycle tools (issues #11, #12)

Thin adapters over the six seam operations: `list_study_plans`, `get_study_plan`, `get_planning_interview`,
`create_study_plan`, `update_study_plan`, `set_study_plan_status`, `set_study_plan_milestone`,
`evaluate_study_plan`, `delete_study_plan`. Deletion requires explicit confirmation; `overwrite` is not
exposed to agents. Inventory 26 → 35.

### D. `planning` session purpose and the Web architect journey (issues #13, #14)

`StartSessionRequest.purpose: Literal["focus","planning"] = "focus"`; one `persona_mode_for(purpose)`
resolver replaces the hard-coded `"focus"` for both PTY and ACP; the planning brief is rendered as its own
persona section. Starting a planning session creates no plan and stores no plan id. The Plans view gains
"Plan with architect" beside the manual form; one console, one WebSocket.

### E. Reconcile and verify (issue #15)

Normative specs, public docs and installer language agree with the shipped boundary; a verification script
writes a receipt a reviewer can tick from command output alone.

### F. `plan_prose_query` measured, ADR-0011 amended (PR #19 close-out; separate branch)

Pre-registered planner-variant arms through the existing eval harness on the committed 91-item DEV gold;
adopt/reject by frozen thresholds; the explicit FTS door and the pre-planner golden are protected. ADR-0011
gains a dated disposition section. PR #19 is closed, its tip tagged.

## Non-goals

Everything #7 lists as out of scope, unchanged: no plan id on live-session state; no auto-selection of a plan
at session start; no automatic checkpoints or milestone completion from session events; no hard-blocking of
off-plan study; no single-active-plan rule; no second session authority or transport; no revival of PR #19's
retired storage/ontology code; no replacement of Markdown as the source of truth.

## Decision record

Design decisions D-1 … D-17 and the rejected alternatives are recorded, with the council seats that argued
each, in `docs/architecture/plan-integration/council/arbitration-plan-round1-2026-09-15.md`. This change does
not repeat them; `design.md` cites them.
