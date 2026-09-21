## ADDED Requirements

### Requirement: The body-double proposal carries one passive first move
When the `now` engine synthesises the body-double proposal (`source ==
"body_double"`, design §5's floor), `learning/decision.py::_first_move` SHALL
derive one first move for it from stored facts only: the first named plan's
deferred next milestone (`_PlanContext.deferred`) and the indexed lesson
`_resolve_lesson(concepts)` returns for **that milestone's own concepts** — one
FTS query per concept through the explorer's own search, in order, the first
**well-formed** hit wins, the hit being `(lesson_id, title, course, concept)` —
the course the hit's own `course_id` humanised exactly as the explorer's course
list shows it, the concept the one that matched. A hit lacking its course or
its title SHALL be skipped as a ROW — the seam fetches a handful of rows per
concept (`_FTS_ROWS_PER_CONCEPT`, 3) so a malformed top row does not hide a
well-formed lesson beneath it (council review 8) — and never named. A concept
shorter than the explorer's minimum query (`_MIN_QUERY_CHARS`, 2) is
UNSEARCHABLE: it SHALL NOT be sent to the resolver and SHALL NOT be reported as
a searched miss (council review 8, astra F3). The milestone's title and the plan's topics SHALL NOT be searched
(rubric 3c (c), measured on the owner's vault 2026-09-21: both steps always
named a lesson, and the wrong one). When a concept resolved the move SHALL be
`Open “<lesson title>” from <Course> — the match is the word “<concept>” — and
read for ten minutes, nothing more.` (`phrase` for a multi-word concept):
rubric 3c (b), a deliberate lesson whenever the vault holds one, and rubric 3c
(d2), owner 2026-09-21 — a named lesson carries implied authority and would be
opened despite a doubt, so the sentence states the evidence the naming rests
on and a lexical match into the wrong course is judgeable from the sentence.
Otherwise the move SHALL be `Open your <milestone title> material and read for
ten minutes, nothing more<why>.`, where `<why>` SHALL say why no lesson is
named so the sentence carries
information instead of vagueness and points at the fix — a lesson, or a concept
name on the milestone, not a better search:

- searched, nothing matched: ` — no indexed lesson mentions “<concept>” yet`,
  every unmatched SEARCHED concept named, joined by ` or ` (a too-short concept
  is not named here — it was not searched);
- every concept too short to search: ` — “<concept>” is too short for the
  index to look up` (`are` for several), and the index SHALL NOT be asked;
- the milestone names no concept: ` — this milestone names no concept to look
  up yet`, and the index SHALL NOT be asked;
- the index could not be read: empty — no claim about an index that was never
  consulted.

When a lesson resolved, `metadata["first_move_lesson_id"]` and
`metadata["first_move_lesson_title"]` SHALL carry its id and title so a
renderer can open it in StudyLoop's own frame without parsing the sentence;
both SHALL be absent otherwise. The move SHALL be passive — reading; never an exercise,
a practice task or a question — because it must be consumable at the
capability the day carries. It SHALL ride as `metadata["first_move"]` on the
body-double recommendation, and ONLY in `metadata`: the reason SHALL NOT carry
the sentence (the reason explains the recommendation; the move is an action,
rendered by each consumer once, beside the session door — rubric 3c (d)); it
SHALL add no top-level key to the `now` payload, so the
no-plan golden is byte-identical. The content index is a refinement, never a
dependency: a lookup that raises SHALL answer the plain milestone form with
no warning. A body double always has a deferred milestone to draw on — an
eligible next milestone would have been synthesised as a plan-related
candidate and suppressed the body double. The one other carrier of a first
move is the warm-up on a plan-related active primary (the requirement below,
rubric 3c (e1)); the sentence, its evidence rule and its no-lesson shapes are
one definition, `_first_move_sentence`, differing only in the material named
and the tail.

#### Scenario: The move names the deferred milestone and says which concept the index lacks
- **WHEN** rubric row 3's world is ranked at `low` energy (plan floor 5,
  milestone 2 “Frames” `[window frame]` deferred, a live struggle deferred) and
  the content index was searched and resolves nothing
- **THEN** the primary is the body double, `metadata["first_move"] == "Open
  your Frames material and read for ten minutes, nothing more — no indexed
  lesson mentions “window frame” yet."`, the reason ends with `the companion
  stays quiet unless you ask.` and contains neither that sentence nor the words
  `first move`, `metadata` has no
  `first_move_lesson_id`, the `evidence_command` is unchanged, and the payload's
  top-level keys are the golden's then `active_plans`, `energy_deferred`,
  `energy_deferred_repairs`

#### Scenario: The move names the lesson the milestone's concepts resolve, with its evidence, and carries its id and title
- **WHEN** the same world is ranked and the resolver returns
  `("ztm/advanced-sql/window-frames", "Window Frames and Ranges", "Advanced Sql", "window frame")`
- **THEN** `metadata["first_move"] == "Open “Window Frames and Ranges” from
  Advanced Sql — the match is the phrase “window frame” — and read for ten
  minutes, nothing more."`, `metadata["first_move_lesson_id"] ==
  "ztm/advanced-sql/window-frames"`, `metadata["first_move_lesson_title"] ==
  "Window Frames and Ranges"`, and the resolver was asked exactly once, with
  `("window frame",)` — the milestone's own concepts and nothing else

#### Scenario: A lexical match into another course is judgeable from the sentence
- **WHEN** a Python plan's deferred milestone `Decorators` `[decorators]` is
  ranked at `low` energy against an index shaped like the owner's vault, where
  `decorators` resolves to `Decorators 29M` in course
  `udemy/the-ultimate-typescript`
- **THEN** the move is `Open “Decorators 29M” from The Ultimate Typescript —
  the match is the word “decorators” — and read for ten minutes, nothing
  more.` — the course named as the explorer's course list shows it and the
  match named as a word match — with `first_move_lesson_id` and
  `first_move_lesson_title` carried

#### Scenario: The milestone's title and the plan's topics never name a lesson
- **WHEN** the same world is ranked against a content index shaped like the
  owner's vault — `Frames` matches a PySpark data-frames lab, `sql` matches an
  SQL bootcamp introduction, `window frame` matches nothing
- **THEN** the explorer's search was asked `["window frame"]` only, the move is
  the milestone sentence with ` — no indexed lesson mentions “window frame”
  yet.`, no `first_move_lesson_id` is carried, and neither wrong lesson
  appears anywhere in the serialised recommendation

#### Scenario: A milestone with no concept is not looked up
- **WHEN** the deferred milestone has no `concepts`
- **THEN** the resolver is not called and the move is `Open your Frames
  material and read for ten minutes, nothing more — this milestone names no
  concept to look up yet.`; with two unmatched concepts the clause reads `— no
  indexed lesson mentions “window frame” or “frame clause” yet.`

#### Scenario: The resolver asks one query per concept and lets an unreadable index raise
- **WHEN** the explorer's search answers nothing for `window frame` and one
  row for `frame clause`
- **THEN** `_resolve_lesson(("window frame", "frame clause", "range"))` returns
  that row's `(lesson_id, title, course, "frame clause")` — the concept that
  matched, the course humanised from the row's `course_id` — after exactly two
  queries in that order; a set of concepts with no hits returns `None`; a hit
  whose row lacks a `course_id` is skipped as a row — the well-formed row
  beneath it is named, and a concept whose only rows are malformed returns
  `None`; and a search
  that raises propagates out of the seam rather than being reported as a miss

#### Scenario: A broken content index degrades to the milestone, silently and without a claim
- **WHEN** the lesson lookup raises
- **THEN** the primary is still the body double, the move is `Open your Frames
  material and read for ten minutes, nothing more.` with no why-clause and no
  `first_move_lesson_id`, and `warnings` carries nothing about the index

#### Scenario: Every renderer shows the move beside the door, once, never instead of it
- **WHEN** the body double is primary
- **THEN** CLI `now` prints a `First move:` line beneath `Sit with the plan:`
  and the sentence appears nowhere else on the panel — the `Why:` paragraph
  does not repeat it;
  the Today card renders `firstMoveNote(primary)` as its own line and hands
  `firstMove` to the Body Double view in the `body-double-request` detail
  beside `activity` and `energy`; the Body Double picker shows it beneath the
  activity (`#bd-first-move`); a payload without the field renders nothing
  and hands over exactly what it did before

#### Scenario: The move survives the start
- **WHEN** a Body Double session starts from a hand-off that carried a first
  move
- **THEN** the live session strip shows the same sentence beneath the activity
  name (`#bd-live-first-move`, `x-show="firstMove"`) for the whole session —
  the picker's copy hides with the picker, so the sentence appears once at a
  time; when a lesson resolved, `#bd-live-first-move-open` sits beside it and
  reuses the view's one opener (`openFirstMoveLesson()`); nothing opens by
  itself at start — the learner presses the control, or doesn't; the
  companion says nothing about the move (the co-study persona is untouched);
  a session started without a hand-off shows no line;
  and `confirmEnd()` clears `firstMove`, `firstMoveLessonId` and
  `firstMoveLessonTitle` beside the `activity` it already clears — the move
  arrived with the activity in one hand-off and leaves with it, so the strip
  never shows a stale move beneath the next, unrelated activity

#### Scenario: "Open X" actually opens X, beside the view
- **WHEN** the body double is primary and the move names a lesson
  (`first_move_lesson_id` and `first_move_lesson_title` carried)
- **THEN** the Today card shows an **Open the lesson** control
  (`data-testid="today-open-first-move-lesson"`) beside the first-move line
  and the Body Double picker shows `#bd-first-move-open` beside the move
  (and the live strip `#bd-live-first-move-open` once the session runs) —
  each only when a lesson resolved; pressing any dispatches
  `explorer-open-lesson` `{lessonId, title}` and navigates nowhere; the Course
  Explorer's `openLessonById` opens its aside if closed and opens that lesson
  with the existing reader; the `body-double-request` detail carries
  `firstMoveLessonId` and `firstMoveLessonTitle` beside `firstMove`; a move
  that names only the milestone shows no control and hands over no lesson

### Requirement: A plan-related active primary carries one warm-up first move on its own material
When `build_now_plan` has ranked and applied the plan-backed guarantee, and
the primary (and only the primary) is plan-related (carries a `PlanRef`), is
not the body double, and is of an active kind — `action_type` in `hands-on`,
`conversation`, `teachback` — `learning/decision.py::_warm_up` SHALL derive
one first move on the primary's own material and carry it as
`metadata["first_move"]` (with `first_move_lesson_id`/`first_move_lesson_title`
when a lesson resolved, exactly as on the body double). Rubric 3c (e), owner
2026-09-21: *no, offer the move at medium energy too*, built as the warm-up
INTO the primary rather than a passive alternative beside it — the low day's
move is the whole action and ends `nothing more`; printed beneath a task the
day can carry, that sentence would contradict the primary and the passive
option is the easier to take (row 3b (d)). The warm-up therefore SHALL end
`then start …`, naming what the primary is, in this order of tests:

- a repair (`energy_demand` in the candidate's metadata — both collectors mark
  repairs and nothing else): the resolver is asked `(concept,)`, the material
  is `“<concept>”`, the tail `then start the repair`;
- the plan's next milestone (a `PlanRef` naming an eligible milestone): the
  resolver is asked that milestone's own concepts, all of them in order, the
  material is the milestone's title, the tail `then start the milestone`;
- any other plan-related active item: `(concept,)`, `“<concept>”`, `then start
  on “<concept>”`.

Recall SHALL never carry a warm-up and the resolver SHALL NOT be asked for
one — reading the lesson before a retrieval test defeats the test (row 3b (b):
familiar recall leads as it is); `visual` and `audio` are already passive and
carry none. A primary off every plan SHALL carry none, so the no-plan golden
is byte-identical; alternates SHALL carry none (one move). CLI `now` keys on
`metadata.first_move` and prints `First move:` beneath `Record evidence:`
without change. The Today card SHALL read `metadata.first_move` and the lesson
fields for ANY recommendation that carries them — its `firstMoveNote` and
`firstMoveLesson` gated on `source == "body_double"` and hid the warm-up
(rubric 3c (e2), correcting (e1)'s record) — and SHALL render the line and the
**Open the lesson** control for the warm-up as for the sit-with move. Pressing
**Start** on a study action SHALL hand the Study view the action's `concept` as
topic, the day's energy, and the move with its lesson when one rides on it,
over the existing `today-resume` event; the Study picker SHALL show the move
beneath the topic (`#study-first-move`, `#study-first-move-open`) and the live
layout SHALL carry it beneath the status bar for the whole session
(`#study-live-first-move`, `#study-live-first-move-open`), cleared with the
topic when the session ends; a planning launch SHALL clear it. A hand-off
without a move (resume, a parked pick-up, a primary the engine gave none)
SHALL clear any earlier one.

#### Scenario: The row-3 repair at medium energy carries a warm-up into itself
- **WHEN** rubric row 3's world is ranked at `medium` energy (capability 6)
  with both collectors live, and `_resolve_lesson(("window function",))`
  returns `("ztm/complete-sql-bootcamp/advanced-sql-4h", "Advanced Sql 4H",
  "Complete Sql Databases Bootcamp", "window function")`
- **THEN** the primary is the `window function` repair (hands-on) and its
  `metadata["first_move"]` is `Open “Advanced Sql 4H” from Complete Sql
  Databases Bootcamp — the match is the phrase “window function” — and read
  for ten minutes, then start the repair.`, with the lesson id and title beside
  it; the resolver was asked exactly once, with `("window function",)`; the
  reason is the collector's own and carries no move; no body double appears;
  the payload's top-level keys are the golden's plus `active_plans`
- **WHEN** the resolver returns `None`
- **THEN** the move is `Open your “window function” material and read for ten
  minutes, then start the repair — no indexed lesson mentions “window
  function” yet.` with no lesson id; an unreadable index gives the plain ramp
  and no warning; CLI `now --energy medium` prints `First move:` beneath
  `Record evidence:`, once

#### Scenario: A milestone primary ramps on the milestone's own concepts
- **WHEN** the plan's eligible next milestone `Frames` `[window frame, frame
  clause]` is the primary at `medium` (nothing collected represents it)
- **THEN** the resolver is asked `("window frame", "frame clause")` and the
  move ends `then start the milestone.`

#### Scenario: No warm-up on recall, off the plan, or without a plan
- **WHEN** the primary is a plan-related `recall`, or an active item matching
  no plan, or there is no active plan at all
- **THEN** `metadata` carries no `first_move`, the resolver is not asked, and
  the no-plan payload is byte-identical to the golden

#### Scenario: The warm-up follows Start into the Study view
- **WHEN** the Today card's primary is a plan-related repair carrying
  `first_move`, `first_move_lesson_id` and `first_move_lesson_title`, and the
  learner presses **Start**
- **THEN** the card dispatches `today-resume` `{topic: <concept>, energy,
  firstMove, firstMoveLessonId, firstMoveLessonTitle}` and navigates to
  `study-session`; the Study picker fills the topic and shows the move beneath
  it with **Open the lesson**; once the session runs the same move sits
  beneath the status bar with the control; pressing either dispatches
  `explorer-open-lesson` `{lessonId, title}`; `confirmEndSession()` clears the
  move with the topic; a primary without a move hands over `{topic, energy}`
  only; a flashcards primary hands over nothing and navigates as before
