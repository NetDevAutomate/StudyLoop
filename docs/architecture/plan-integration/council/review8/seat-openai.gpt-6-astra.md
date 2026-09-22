<!-- verified_model: openai.gpt-6-astra -->
<!-- finish_reason: stop · 59.4s · usage: {"completion_tokens": 3337, "prompt_tokens": 23930, "total_tokens": 27267, "completion_tokens_details": {"reasoning_tokens": 849}, "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 23928, "cache_creation_tokens": 23928}} -->

## 1. Verdict

**ACCEPT-WITH-CORRECTIONS** — the recommendation carriage is coherent, but the move can become detached from its material through picker edits or a second hand-off, and the resolver can report an indexed miss without searching.

## 2. Findings

Repository execution and test bodies are **UNVERIFIED** here; findings below use the supplied diffs. RED names are proposed tests, not claims about existing coverage.

### F1 — 🔴 Editing the material leaves the previous material’s authoritative move and button

**Location:** `index.html`, `#bd-activity-input`; `session-timer.js`, first-move state and topic-input handling.

The Body Double input binds directly to `activity`, while its first-move fields are cleared only on another hand-off or successful end. Receiving a Frames proposal, replacing the activity with an unrelated task, and starting therefore retains the Frames sentence and lesson button.

The Study picker has the same lifetime problem described in the brief: changing the topic does not invalidate the handed-over warm-up. Its input handler’s full implementation is **UNVERIFIED**, but no invalidation appears in the supplied changes.

This is not merely a learner choosing to ignore a proposal: the UI displays a material-specific proposal beneath a *different* activity. That recreates the confidently wrong linkage the evidence requirement was intended to prevent.

**Fix:** Invalidate all three first-move fields when the learner changes the hand-off’s material. Cover Study topic suggestions and target/course/lesson changes too—not just keyboard input. Prefer an explicit material-identity association or centralized invalidation rather than scattered field resets.

**Concrete check / REDs:**
- `test_body_double_editing_activity_invalidates_first_move`: receive activity A and lesson A, edit the actual input to B, start; neither picker nor live strip retains move A.
- `test_study_changing_target_invalidates_first_move`: repeat for typed topic, suggested topic, and another target kind.

The Body Double test needs behavioral DOM/component coverage; another substring assertion would not pin the transition.

### F2 — 🔴 A new Body Double hand-off can replace the running session’s move

**Location:** `components.js`, `bodyDoubleSession().init()`, `body-double-request` listener, approximately lines 3232–3250.

The listener unconditionally replaces `firstMove` and its lesson fields. The live strip reads those same fields, while its activity is represented separately by `liveActivity`.

Consequently, while session A is active, a request for B can install B’s move under A’s live activity. A request without a move instead erases A’s move before A ends. The listener contains no `sessionActive` or `starting` guard.

Whether every ordinary navigation path permits that request is **UNVERIFIED**; the component’s incorrect transition is directly testable without assuming navigation behavior.

**Fix:** Do not mutate active/starting-session material from an incoming picker request. Either reject/defer the request or keep pending-picker and live-session hand-offs separate. Promote the move to live state only with the corresponding successfully started session.

**Concrete check / REDs:**
- `test_body_double_request_does_not_replace_active_session_first_move`: set active session A with `liveActivity`, move and lesson A; dispatch request B; assert A’s live sentence and opener still refer to A.
- `test_body_double_request_during_start_does_not_mix_materials`: dispatch B while A’s start promise is pending, then resolve A.

Study’s existing listener guards and conflict-recovery implementations are **UNVERIFIED**. Apply the same check there rather than assuming its end/reset tests establish session ownership.

### F3 — 🟡 A one-character concept produces a false “searched miss”

**Location:** `decision.py::_resolve_lesson`, specifically:

```python
if len(q) < 2:
    continue
```

`_clean_concepts` retains nonempty one-character concepts. `_resolve_lesson(("C",))` nevertheless performs no search and returns `None`; `_first_move_sentence` then says:

> no indexed lesson mentions “C” yet.

That contradicts both “one query per concept” and the claim that `None` means a *searched* miss. Programming concepts such as C and R are not inherently invalid material.

**Fix:** Search valid single-character concepts if the explorer supports them. If it cannot, distinguish “query unsupported/not consulted” from “searched and absent,” and amend the spec’s fallback wording accordingly. Do not silently turn inability to search into a content-gap assertion.

**Concrete check / REDs:**
- `test_resolve_lesson_searches_single_character_concept`: stub the explorer search to return an evidenced C lesson; assert it was called with `"C"` and the lesson resolves.
- `test_unsearched_concept_does_not_claim_indexed_absence`: exercise any deliberately unsupported-query fallback.

### F4 — 🔵 The record still contains current-tense claims superseded by the implementation

**Location:** `design.md`, decisions 3–4; `index.html`, comment preceding `.today-first-move`.

Decision 3 still says lookup cost is paid “only on the body-double path.” Decision 4 says metadata is “present only on the body double.” The Today markup comment says the line is “hidden for every other action.” All are false after the warm-up change.

Decision 11 commendably preserves the renderer correction, but these remaining statements make the design internally contradictory.

**Fix:** Annotate the original decisions as amended by decisions 10–11; update the markup comment. Preserve historical claims as history, not as current invariants.

**Concrete check:** Search those three phrases in the final tree and reconcile each with `_warm_up`. A docs-contract pin could be named `test_first_move_record_describes_both_current_carriers`; an exact-wording test is not necessary.

### Requested checks with no additional established defect

- **Shared sentence and scope:** The repair branch passes `(concept,)`, even if the stripped string were empty, so it cannot reach the builder’s *empty sequence* “this milestone names no concept” branch. The generic branch likewise supplies a singleton. Actual nonempty-concept validation is **UNVERIFIED**. Milestone warm-ups can correctly reach that clause.

  The no-lesson warm-up is awkward but matches the binding spec: an indexed absence does not establish that the learner has no material elsewhere. I would prefer an explicitly optional reading route, but would not silently revise an owner-approved sentence in this patch.

- **Tails and energy:** Repair-first precedence is correct even when a repair matches the next milestone. Practice’s generic tail is acceptable, though less specific. Teachback after reading is scaffolded learning, not an unaided assessment; if teachback is used diagnostically elsewhere, inspect that contract separately. Excluding visual/audio and offering an optional ramp at high energy follow the recorded scope and are not defects.

- **Recall:** Keep the action-type exclusion. A long absence does not make priming harmless to a retrieval measurement. A deliberate study-then-retrieve activity would need its own semantics; changing this to `_review_type_for` is not justified by the supplied evidence.

- **Start behavior:** Filling the concept for *every* study action is explicitly covered by the spec and decision 11, not an undocumented scope addition. It is reasonable to fold in the missing hand-off. Browser assumptions about an initially blank picker remain **UNVERIFIED**; inspect `test_web_smoke_browser.py` and `tests/e2e/` for Today → Study flows before accepting head CI.

- **Resume and recovery:** A hand-off for different material should clear the old move. A reattached session with no stored move should show none rather than reconstruct one. But “reattached sessions have empty fields” is established only for a fresh component: existing picker state can survive unless recovery explicitly clears or replaces it. Inspect `endConflictSession` and `reattachConflictSession`; proposed probe: `test_reattach_does_not_inherit_pending_picker_first_move`. Their bodies were not supplied, so this is **UNVERIFIED**, not an additional established defect.

- **Rendering:** The supplied Today markup reads `plan?.primary` for both line and button; it does not add an alternate rendering. The new engine paths put the sentence only in metadata. Existing reason contents and the strength of the warm-up test’s negative assertion are **UNVERIFIED** without bodies. Pin both exact sentence absence and absence of a “first move” reason tail.

- **Layout:** The Body Double full-width flex item is compatible with a wrapping strip; the confirmation controls may consume an additional row, not inherently conflict. The Study row necessarily consumes height. Terminal `flex: 1`, minimum-height behavior, resize handling, and narrow-screen usability cannot be verified from these diffs. Check that a long sentence plus controls leaves a usable terminal and triggers its resize handling. No added generic terminal-mount selector is visible.

- **Tests:** Names do not establish exact-string assertions or attribute-order robustness. The reported comment-delimited `_live_strip` slicer is fragile; prefer parsing the relevant element. Node top-level tests are ordinarily sequential within a file and separate test files are process-isolated by default, so save/restore globals is not inherently unsafe. Explicit concurrency settings and whether every asynchronous operation is awaited remain **UNVERIFIED**.

- **Clock leak:** Acceptable as a separate test-isolation correction, not a blocker for this feature. Pin it with `test_due_progress_age_uses_injected_clock`: freeze the injected clock, plant progress exactly three days earlier, assert age three and the corresponding reason independently of the wall clock.

## 3. Refutations

1. **“A stale move never outlives its plan” / “the strip never shows a stale move beneath the next, unrelated activity” is not established.** Clearing on end and hand-off covers two transitions, not material edits or hand-offs received during an active session. F1–F2 provide concrete counterchecks.

2. **“`None` is a searched miss” is false for single-character concepts.** It also conflates rejected hits lacking evidence with no lexical hits. Whether evidence-incomplete rows occur in a real explorer index is **UNVERIFIED**; test that invariant before describing every such result as “no indexed lesson mentions.”

3. **“A deliberate lesson whenever the vault holds one” is broader than this resolver demonstrates.** It requests only one row per concept and examines `rows[0]`. If the best hit lacks title/course evidence, a valid second hit for that same concept is never considered. Recompute with an evidence-incomplete first hit and valid second hit; actual index guarantees preventing this are **UNVERIFIED**.

4. **The “only body double” record claims are superseded**, as identified in F4.

5. **Head CI, browser behavior, version 0.5.1, and detailed assertion quality remain UNVERIFIED here.** The supplied diffs contain no version change and no browser results. That does not prove an incorrect version or failing browser suite. The coordinator’s reported RED executions, GREEN amendments, and golden checks are accepted as supplied facts, not independently reproduced.

## 4. Gate

1. Invalidate a move when its picker material changes — REDs `test_body_double_editing_activity_invalidates_first_move` and `test_study_changing_target_invalidates_first_move`.
2. Isolate live/starting-session moves from subsequent hand-offs — REDs `test_body_double_request_does_not_replace_active_session_first_move` and `test_body_double_request_during_start_does_not_mix_materials`.
3. Stop reporting unsearched single-character concepts as indexed absences — REDs `test_resolve_lesson_searches_single_character_concept` and `test_unsearched_concept_does_not_claim_indexed_absence`.

Acceptance also remains conditional on the already-required head CI/browser and 0.5.1 release checks; their results are **UNVERIFIED** here.
