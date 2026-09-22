# Implementation Tasks — the body double's first move (#30)

TDD, as the programme's items were: the RED is committed before the production
edit; each task has a definition of done a reviewer can tick from output.

- [x] **T1 RED** `f43f7eb2` — eleven tests: engine (`test_body_double_carries_one_passive_first_move_on_the_deferred_milestone`,
      `..._names_the_lesson_when_the_content_index_resolves_it`, `..._survives_a_broken_content_index`),
      CLI (`test_cli_now_prints_the_first_move_beneath_the_sit_with_door`), Today card
      (`tests/js/today-panel-plan.test.js`: `firstMoveNote`, hand-off detail), Body Double view and card
      markup (`tests/test_web_body_double_first_move.py`, static pins — `components.js` has no node harness),
      docs (`test_docs_plan_integration_contract.py`, two tests). All red for the stated reason.
- [x] **T2 GREEN** — `_lesson_title_for`, `_first_move`, the reason tail and `metadata["first_move"]`;
      `cli/_now.py` `First move:` line; `today-panel.js` `firstMoveNote` + `firstMove` in the hand-off;
      `components.js` listener + `firstMove: ''`; `index.html` `#bd-first-move` and `.today-first-move`;
      both guides. DoD: the eleven RED tests green; `test_now_plan_guidance.py` + `test_learning_decision.py`
      green; golden `ec451ce8` unchanged; JS 21/21; ruff, pyright, mkdocs `--strict` clean.
- [x] **T3** Read cost of the lesson lookup measured on the live host with the FTS index present, recorded
      in `design.md` (861 ms cold / 45–58 ms warm per concept, body-double path only).
- [x] **T3b** Rubric 3c (b), owner: *a deliberate lesson should always be the case*. RED `2e1c7ea7`
      specified a fallback chain (concepts → milestone title → plan topics) with `_resolve_lesson` returning
      `(lesson_id, title)` and `metadata["first_move_lesson_id"]`. Built, then measured on the owner's real
      vault before it committed: the chain always names a lesson — the wrong one (`Frames` → a PySpark
      data-frames lab; `sql` → an SQL bootcamp intro). Superseded by T3c; only `first_move_lesson_id` and
      the `(lesson_id, title)` seam survive from it.
- [x] **T3c** Rubric 3c (c), owner 2026-09-21: *name the milestone and say why* — agreed. RED `fdfe1672`
      (seven tests: the real-vault replay through the real seam; a concept-less milestone is not looked up;
      every unmatched concept is named; an unreadable index raises out of the seam and the sentence makes no
      claim about it; the CLI prints the why-clause) → GREEN: `_resolve_lesson(concepts)` searches the
      deferred milestone's own concepts only; `_first_move` emits one of three honest no-lesson shapes
      (design decision 6); spec delta, design, `docs/study-plans.md` and the JS fixture say the same.
      DoD: `test_now_plan_guidance.py` 82/82, JS 150/150, ruff, pyright, mkdocs `--strict` clean, golden
      `ec451ce8` unchanged.
- [x] **T3d** Rubric 3c (d1), owner 2026-09-21: *keep the First move line, drop it from the reason*. RED
      `630cac72` (the reason ends at the co-study guarantee and carries neither the sentence nor the words
      "first move"; the CLI panel shows the sentence exactly once) → GREEN: the reason tail is removed;
      `metadata["first_move"]` is the move's only carriage (design decision 5); spec delta and the
      study-plans guide say the same. DoD: `test_now_plan_guidance.py` + `test_learning_decision.py`
      green, JS unchanged (the card reads the field, not the reason), golden `ec451ce8` unchanged, row 3c's
      screen re-emitted through both real collectors with the sentence once.
- [x] **T3e** Rubric 3c (d2), owner 2026-09-21: *build the button, gated behind the evidence sentence*. Owner's
      refinement of the (c) self-check — *"I would likely still open it in case there was some link that is
      being enforced"* — made the gate: a named lesson is followed, not merely doubted. Cycle 1, RED `2b85a80b`
      + `089d09ae` → GREEN `4459ea38`: `_resolve_lesson` returns `(lesson_id, title, course, concept)`, skips a
      hit lacking its course; the lesson sentence states its evidence (`Open “<lesson>” from <Course> — the
      match is the word “<concept>” — …`); `first_move_lesson_title` beside the id; design decision 7. Cycle 2,
      RED `e1576276` → GREEN: `explorer-open-lesson` + `openLessonById` on the Course Explorer; **Open the
      lesson** on the Today card (`today-open-first-move-lesson`) and the Body Double picker
      (`#bd-first-move-open`), each only when a lesson resolved; the hand-off carries id + title; both guides;
      design decision 8. DoD: engine + decision 88/88, static pins + docs contract green, JS 153/153, `node
      --check` on both edited scripts, mkdocs `--strict` clean, openspec valid, golden `ec451ce8` unchanged.
- [x] **T3f** Rubric 3c (d3), owner 2026-09-21: *carry the move and the button into the live session strip*.
      Checked in the markup: both lived only in the picker (`x-show="!sessionActive && !starting"`), so Start
      hid the sentence at the moment the blank page arrived. RED `74779bda` → GREEN: `#bd-live-first-move`
      wraps to its own row of the flex-wrap strip beneath the activity name, same sentence, with
      `#bd-live-first-move-open` beside it when a lesson resolved through the view's one opener; one CSS rule;
      `confirmEnd()` clears the three first-move fields beside the `activity` it already cleared (the move
      arrived with the activity and leaves with it); the guide's Start step; spec scenario *The move survives
      the start*; design decision 9. Rejected: auto-open at start. DoD: static pins + docs contract 39/39,
      engine + decision + web-now + golden 89/89, JS 153/153, `node --check` on the edited script, mkdocs
      `--strict` clean, openspec valid, golden `ec451ce8` unchanged.
- [x] **T3g** Rubric 3c (e), owner 2026-09-21: *no, offer the move at medium energy too* — built as (e1) the
      warm-up INTO the primary, on its own material (owner took the steer over the passive alternative).
      RED `fa5d76be` (five failing + one guard) → GREEN: `_first_move_sentence` shared by the sit-with move
      and the warm-up (material + tail differ); `_warm_up` on the primary only — plan-related, not the body
      double, `action_type` in hands-on/conversation/teachback — with three tails (repair → *then start the
      repair*; eligible milestone → its concepts, *then start the milestone*; else *then start on
      “<concept>”*); `_first_move_metadata` shared carriage; never recall (resolver not asked), never off a
      plan (golden byte-identical); both guides; new spec requirement + three scenarios; proposal corrected;
      design decision 10; read cost re-measured (161 ms cold / 45 ms warm). RED correction at GREEN: the
      medium payload has no `energy_deferred*` keys (omitted when empty), so its shape is the golden's plus
      `active_plans`. DoD: now-guidance + decision + web-now + golden + static pins 105/105, docs contract
      green, ruff/format/pyright clean, mkdocs `--strict` clean, openspec valid, golden `ec451ce8` unchanged,
      JS 153/153 (renderers unchanged — they key on `metadata.first_move`).
      CORRECTION (T3h): that last clause was true of the CLI only; the Today card gated on the body double.
- [x] **T3h** Rubric 3c (e2), owner 2026-09-21: *build it now, the (d2)+(d3) shape on the Study view*. RED
      `eb3be21a` (12 failing + one guard) → GREEN: Today `firstMoveNote`/`firstMoveLesson` read the field for any
      recommendation (the body-double gate hid the (e1) warm-up); `startAction` on a study action hands
      `{topic, energy, firstMove?, lesson?}` over `today-resume` (it used to hand NOTHING — the picker opened
      blank); `_firstMoveDetail` shared with the Body Double hand-off; `sessionTimer` holds the three fields,
      listener sets/clears them per hand-off, `openFirstMoveLesson()`, `confirmEndSession()` clears them with
      the topic, `startPlanning()` clears them; `#study-first-move`/`-open` beneath the topic,
      `#study-live-first-move`/`-open` beneath the status bar; CSS; guide (Study Session + Today); spec
      requirement text corrected + scenario; design decision 11 (and decision 10 corrected in place). DoD:
      new pins + Body Double pins + docs contract + now-guidance + web-now + golden 134/134, web unit suites
      reading the markup 144 passed, JS 160/160, `node --check` on both scripts, mkdocs `--strict` clean,
      openspec valid, golden `ec451ce8` unchanged.
- [x] ⚖ **T4** Council review (three seats) of the RED and the GREEN; arbitration; one commit per accepted
      finding. Review 8 ran 2026-09-21 on `c83ebd75` (astra ACCEPT-WITH-CORRECTIONS, grok
      ACCEPT-WITH-CORRECTIONS, qwen ACCEPT); GATE ACCEPT for `f8783a73` in
      `council/review-8-arbitration-2026-09-21.md`, seats in `council/review8/`. Landed one commit each:
      `a33249da`→`d029b0d6` (too-short concept; first well-formed hit), `c5065cf0` (the move never
      outlives its material — design decision 12), `357ee258` (F4 record), `79761a94`→`193b541d` (blank
      concept), `024373ba`→`f8783a73` (learning row's tail — my own finding). Open for the owner: the
      high-energy ramp (decision 10); separate change: the frozen-clock gap.
- [ ] **T5** Rubric row **3c** added to `docs/architecture/plan-integration/receipts/now-rubric-2026-09-16.md`:
      row 3's world emitted from the GREEN tree through both real collectors, the first move shown as
      emitted; verdict `PENDING` until the owner scores it. The change is archived only after the row is
      scored **yes**.
- [ ] **T6** CHANGELOG `[Unreleased]` entry; PR; CI green; fast-forward `main`; archive this change;
      ships in 0.5.1.
