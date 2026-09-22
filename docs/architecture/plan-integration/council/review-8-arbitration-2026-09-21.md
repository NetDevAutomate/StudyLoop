# Arbitration — council review 8 (issue #30: the first move, rubric row 3c (a)–(e2))

**Date:** 2026-09-21 (run) / 2026-09-22 (arbitration written) · **Arbiter:** coordinating agent (owner
present for the run; the owner rotated the gateway's provider credential that had blocked the run all
evening, then asked for it) · **Reviewed tree:** `feat/body-double-first-move` @ `c83ebd75` (28 commits on
`main` `fa1b2af3` = v0.5.0; range `fa1b2af3..c83ebd75`). Seats ran against `brief-review8-2026-09-21.md`
(`review8/manifest.json`, run 19:31:19Z; astra and qwen `finish_reason=stop`, **grok `length`** — its
24,000-token cap cut its answer inside its last 💡, after its verdict, findings and refutations were
complete). **Corrections landed at:** `a33249da` → `d029b0d6` (F3 + refutation 3), `c5065cf0` (F1/F2 —
the class), `357ee258` (F4), `79761a94` → `193b541d` (blank concept), `024373ba` → `f8783a73` (my own).

**Why this record was written a day late, and where the evidence lived meanwhile.** The coordinating
session was interrupted mid-GREEN on the night of the run and its two continuations timed out before
producing output. The seat transcripts were never copied into the repo that night; they survived only in a
gitignored run directory on the main checkout (`reviews/2026-09-21-first-move/council/`), from which the
three `seat-*.md` files and the brief actually sent (93.9 KB, 1,505 lines — not the 44 KB draft written
earlier that day before readings (b)–(e2) existed, which is deleted) were copied on 2026-09-22; the
pre-commit whitespace hooks normalised trailing whitespace and final newlines on the copies, `git diff -w`
against the originals is empty, and the originals' sha256 are in `manifest.json`. `manifest.json` is
otherwise built from the run's own `spend.json` and `run.log`. Had the run directory
been cleaned, the arbitration would have had to be reconstructed from the RED commit body alone.

**Brief size, recorded:** 93.9 KB (~24k prompt tokens per seat): the twenty-eight commits, every diff in
the range, the spec delta, design decisions 1–11, rubric row 3c as scored through (e2), the real-vault
probes, and eight numbered check questions including "be adversarial about state that outlives the
hand-off it came with".

## Seats and verdicts

| Seat | Verdict | 🔴 | 🟡 | 🔵/💡 |
| --- | --- | --- | --- | --- |
| `openai.gpt-6-astra` | ACCEPT-WITH-CORRECTIONS | F1 material edit keeps the move; F2 a hand-off replaces the running session's move | F3 one-character concept reported as a searched miss | F4 record still says "body double only"; requested checks (blank concept UNVERIFIED, reattach, layout, clock leak) |
| `grok-4.6` | ACCEPT-WITH-CORRECTIONS | — | plans-view/reattach hand-off leaves a stale move; Body Double asymmetric hand-off; 0.5.1 version pin | `deferred.title` vs `next_milestone.concepts`; blank-concept ramp; single-letter miss; `limit=1` hides the next row; (a)–(f) answers; aria-label; nested `x-show` |
| `qwen3-coder` | ACCEPT | "no concept" clause reachable for repairs | recall exclusion should use `_review_type_for`; topic edit keeps the move; planning launch keeps the move | high-energy wording; `.picker-hint`/`.bulk-btn` reuse; clock leak |

### Method

Every 🔴/🟡 was checked against the tree before acceptance, and each accepted finding landed RED → GREEN,
one commit each, with the RED run red against the pre-fix source. Two things to say plainly about the
process this time. The RED for the lifetime class (four JS behaviour tests, four static pins) was written
the night of the run but never committed before the interruption; it is in `c5065cf0` beside its GREEN,
with the eight failures re-confirmed against the pre-fix tree at the start of the resumed session. And that
RED contained a test that armed the real one-second tick without `destroy()`, so `node --test` never
exited the file — the earlier continuation turns "hung" to a 120-second timeout on a suite that was
actually 4 failed / 19 passed; fixed in the same commit (JS now 164/164 in 15 s).

### Findings and dispositions

| # | Finding (seat) | Disposition | Commit / test |
| --- | --- | --- | --- |
| F1 | Editing the material in the picker (`#topic-input`, `#bd-activity-input`), or choosing another target from a picker select, keeps the previous material's move and **Open the lesson**; both ride into the session (astra 🔴; qwen 🟡; grok 💡 (f), who argued a typo-fix in the plan title would lose a correct move). | **Accepted — the class.** One writer per view, `clearFirstMove()`; `onTopicEdited()`/`onActivityEdited()` on the inputs, `selectOption()` for every picker select, `@change` on `#target-kind-select`, end paths routed through the helper. Grok's counter weighed and recorded (design decision 12): the move is one Start away; a confidently wrong proposal on the surface that is always on screen is the defect (c) removed. | `c5065cf0`; JS `editing the topic clears the move…`, `choosing another target from any picker select clears the move`; pins `test_editing_the_activity_clears_the_first_move`, `test_editing_the_topic_or_changing_the_target_kind_clears_the_move` |
| F2 | Both listeners write the three move fields unconditionally, and the same fields feed the LIVE strip — a request for B while A runs installs B's move (or nothing) beneath A (astra 🔴; grok 🟡 "asymmetric hand-off"). | **Accepted.** Both listeners return before the move fields when `sessionActive \|\| starting`; the picker's topic/activity and energy are still pre-filled for the next session, as before. Grok's pairing asymmetry (a move without an activity) is not a shape the one dispatcher produces — `today-panel.js` always sends `activity` (`bodyDoubleActivity(rec)`) with the move — so only the live guard was built. | `c5065cf0`; JS `a hand-off during a live or starting session does not touch the live move`; pin `test_a_hand_off_during_a_live_or_starting_session_leaves_its_move_alone` (guard before the first write) |
| F2b | `reattachConflictSession()` adopts a session that is not the hand-off's while a picker move is pending (grok 🟡; astra "requested checks", UNVERIFIED there). | **Accepted, both views.** The adopted session clears the move; nothing is reconstructed. Grok's sibling claim that a **plans-view** hand-off leaves a stale move is **refuted**: `plan-architect-request` calls `startPlanning()`, which cleared the three fields since (e2) `25886ff0` — in the reviewed tree. | `c5065cf0`; JS `reattaching to a session that is not the hand-off's carries no move`; pin `test_reattaching_a_session_that_is_not_the_hand_offs_carries_no_move` |
| F3 | `_resolve_lesson` skips queries under two characters, then the sentence says *no indexed lesson mentions “C” yet* about a search that never ran (astra 🟡; grok 🔵). | **Accepted, reproduced** (the RED printed that sentence). `_first_move_sentence` separates searchable from too-short concepts (one constant, `_MIN_QUERY_CHARS`): too-short ones are named as *too short for the index to look up* and never sent; a miss names only searched concepts. | `a33249da` → `d029b0d6`; `test_a_concept_too_short_to_search_is_not_reported_as_a_searched_miss` |
| R3 | The seam fetched one row per concept and, when it lacked title or course, gave up on the concept — a malformed top row hid a well-formed lesson beneath it (astra refutation 3; grok 🔵 "`limit=1`"). | **Accepted.** The seam fetches `_FTS_ROWS_PER_CONCEPT` (3) and names the first well-formed row; a concept whose only rows are malformed still answers `None`. Residual, recorded not fixed: that `None` is then reported as *no indexed lesson mentions X yet* although a row did mention X and was unusable — an edge of a dirty index, and the honest wording ("no usable indexed lesson") would leak an implementation detail into a learner sentence; left as is. | `a33249da` → `d029b0d6`; `test_resolve_lesson_skips_a_malformed_top_row_and_names_the_well_formed_hit_beneath_it` |
| F4 | Design decisions 3–4 and the Today markup comment still say the move/lookup is body-double only (astra 🔵; grok 💡 "stale comment"). | **Accepted.** Each annotated as history amended by decisions 10–11; the markup comment says what the gate removal made true. | `357ee258` |
| G1 | A blank-concept active item can be the plan-related primary (a candidate matches a plan on concept, topic OR course; the struggle collector does not guard `row["concept"]`), and the repair/generic tails mint *Open your “” material …* (grok 🔵; astra "requested checks", UNVERIFIED there; qwen 🔴 named the neighbouring clause). | **Accepted, reproduced** — the RED printed *Open your “” material and read for ten minutes, then start on “” — “” is too short for the index to look up.* Tails needing a concept now require one; the milestone tail keeps its own concepts; blank otherwise → no warm-up, resolver not asked. | `79761a94` → `193b541d`; `test_no_warm_up_when_the_primary_names_no_concept` |
| G2 | `_first_move` names `deferred.title` but resolves `plan.next_milestone.concepts` — could be two milestones (grok 🔵). | **Refuted.** `DeferredMilestone` is built from `plan.next_milestone` itself (`milestone_index=next_milestone.index, title=next_milestone.title`) and carries no concepts of its own; the two are one object's fields by construction. | `decision.py` `_PlanContext` build |
| G3 | The tree carries no 0.5.1 version bump (grok 🟡). | **Rejected as a finding on this change.** The version is bumped by the release change, as v0.5.0 was in PR #29, not on a feature branch; task T6 records the release intent. Both `pyproject.toml` files read 0.5.0, correctly, until the 0.5.1 release change. | — |
| Q1 | The *this milestone names no concept* clause is reachable for repairs (qwen 🔴). | **Refuted.** The repair tail passes a 1-tuple, which never reaches `if not concepts`; grok's own analysis says the same. With G1 a blank never reaches the builder either. | — |
| Q2 | Exclude the warm-up by `_review_type_for`, not `action_type == "recall"`, in case a retrieval test is emitted as an active type (qwen 🟡; grok 💡 (c) "UNVERIFIED against the collectors"). | **Refuted with the collectors.** Due review cards are `action_type="recall"`; struggle rows are `hands-on` (struggling) or `teachback` (learning), both repairs/reviews not retrieval tests; practice files are `hands-on` practice; milestones `conversation`. No retrieval test is emitted active. | `decision.py` collectors |
| Q3 | `startPlanning()` does not clear the move (qwen 🟡). | **Refuted — already in the reviewed tree** since (e2) `25886ff0`; `test('a planning launch carries no warm-up')` pins it. | `25886ff0` |
| Q4 | High-energy warm-up may read as patronising (qwen 🔵; grok 💡 (b)). | **Owner's call, recorded not changed** — design decision 10 names "at high energy too" as a decision taken rather than asked, one line to reverse. | design decision 10 |
| Q5 | `.picker-hint`/`.bulk-btn` reuse risks selector collisions (qwen 🔵). | **Rejected.** The tests that query `.picker-hint` generically (`test_web_session_lifecycle`, `test_web_layout_regression`) passed in CI on `c83ebd75` (15/15); ids are unique and the reuse is deliberate for consistent styling. | CI run 35641759712 |
| Q6 | Clock leak: the due collector's `days_ago` reads the wall clock while the test world freezes `decision` only (qwen 💡; astra "acceptable, separate correction"). | **Recorded, open, separate change** — as in the receipt since (e). | — |
| C1 | *(coordinator, found verifying Q2)* Every struggle row carries `energy_demand`, so a `learning` row's teach-back took the repair tail — *then start the repair* beneath a reason saying *a gentle review keeps it fresh*; row 3b (c) removed that contradiction from the reason. | **Accepted, reproduced.** The demand-marked tail names the row's kind: *then start the review* for `learning`, *the repair* otherwise. Design decision 10's "both collectors mark repairs and nothing else" corrected in place. | `024373ba` → `f8783a73`; `test_a_learning_row_s_warm_up_ends_at_the_review_not_a_repair` |

### Rejected or not taken, with reasons

- **grok 💡 aria-label on the two buttons.** The visible text *Open the lesson* is the accessible name; an
  `aria-label` repeating it adds nothing and diverging from it breaks label-in-name. Not taken.
- **grok 💡 nested `x-show`** on `#bd-first-move-open` inside a `<p>` with the same condition. True and
  redundant; kept, because the static pin binds the control's own visibility so a future markup move keeps
  it gated. Cost nil.
- **grok 💡 (d) "the Start behaviour change should have been named in the PR body".** It is — the (e2)
  paragraph of the PR body states that Start used to hand the Study picker nothing and now hands
  `{topic, energy, firstMove?, lesson?}` for a study action; design decision 11 says "every study action".
  Grok's UNVERIFIED e2e worry is answered by CI: 15/15 on `c83ebd75`, e2e journeys included.
- **grok 💡 (e) the (d1) pin only checks the words "first move".** Refuted:
  `test_now_plan_guidance.py:1701–1702` asserts the reason ends at *the companion stays quiet unless you
  ask.* AND that the sentence itself is absent AND that the words are absent.
- **astra's F1 remedy "explicit material-identity association".** Not taken; a per-view single writer and
  guards at every material-changing transition give the same guarantee without a new identity field on the
  hand-off, and the harness proves each transition.
- **grok's deadlock hypothesis** on `_fts_lock` — refuted by grok itself from the brief's real-vault probes.

### Refutations, weighed

1. astra 1 — "a stale move never outlives its plan is not established": **correct**; F1/F2/F2b are the
   counter-examples, all landed.
2. astra 2 — "`None` is a searched miss is false for single-character concepts": **correct** (F3); the
   evidence-incomplete-row half is R3, with its residual recorded above.
3. astra 3 — "a deliberate lesson whenever the vault holds one is broader than the resolver demonstrates":
   **correct** (R3).
4. astra 4 — record claims superseded: **correct** (F4).
5. astra 5 — head CI, browser behaviour and 0.5.1 UNVERIFIED there: CI 15/15 on `c83ebd75` and on
   `b64afd02`; 0.5.1 is the release change's (G3).
6. qwen — "none": qwen accepted the brief's facts wholesale; two of its four gate items were already in
   the reviewed tree (Q3) or refuted by the collectors (Q2).

### Verification after fixes (tree `f8783a73`)

JS 164/164 (15 s); first-move pins (Body Double + Study) + plan-integration docs contract + now-guidance
+ learning-decision + web-now 148 passed; web unit suites reading the markup 30 passed; `node --check`
both scripts; ruff / format clean; pyright 0; openspec valid (the lifetime scenario and two sentences
added); mkdocs `--strict` clean; golden `ec451ce8` byte-identical throughout — no council correction
touched the no-plan payload.

### Process findings

- **Copy seat outputs into the repo in the turn they arrive.** The run directory that saved this
  arbitration is gitignored and was one cleanup away from gone; the lesson already existed for subagent
  result files and applies to any run directory.
- **A hanging JS suite reads as a timeout, not a failure.** Two whole continuation turns were lost to a
  test that armed `setInterval` without `destroy()`. Any test that calls a method arming the tick must tear
  it down; the file header's SKIPPED list already says why.
- **Verify a seat's UNVERIFIED before dismissing it.** G1 (blank concept) and C1 (learning-row tail) were
  both found by checking claims the seats had marked UNVERIFIED or made on adjacent ground, not by
  accepting them as written.

## Gate decision

**GATE: ACCEPT** — for the tree at `f8783a73`, not the reviewed tree. Every 🔴 and 🟡 is either landed with
a discriminating test (F1, F2, F2b, F3, R3, F4, G1, C1) or refuted here with the evidence (G2, G3, Q1, Q2,
Q3, Q5). Two items stay open and are the owner's or a separate change: Q4 (the high-energy ramp, one line
to reverse) and Q6 (the frozen-clock gap in `history/progress.py`). Row 3c is fully scored (a)–(e2); the
change archives after CI is green on the branch and `main` is fast-forwarded.
