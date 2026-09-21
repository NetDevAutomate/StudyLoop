## ADDED Requirements

### Requirement: The body-double proposal carries one passive first move
When the `now` engine synthesises the body-double proposal (`source ==
"body_double"`, design §5's floor), `learning/decision.py::_first_move` SHALL
derive one first move for it from stored facts only: the first named plan's
deferred next milestone (`_PlanContext.deferred`) and the indexed lesson
`_resolve_lesson(concepts)` returns for **that milestone's own concepts** — one
FTS query per concept through the explorer's own search, in order, first hit
wins, the hit being `(lesson_id, title, course, concept)` — the course the
hit's own `course_id` humanised exactly as the explorer's course list shows
it, the concept the one that matched. A hit lacking its course or its title
SHALL be skipped, never named. The milestone's title and the plan's topics SHALL NOT be searched
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
  every unmatched concept named, joined by ` or `;
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
body-double recommendation only, and ONLY there: the reason SHALL NOT carry
the sentence (the reason explains the recommendation; the move is an action,
rendered by each consumer once, beside the session door — rubric 3c (d)); it
SHALL add no top-level key to the `now` payload, so the
no-plan golden is byte-identical. The content index is a refinement, never a
dependency: a lookup that raises SHALL answer the plain milestone form with
no warning. A body double always has a deferred milestone to draw on — an
eligible next milestone would have been synthesised as a plan-related
candidate and suppressed the body double — so no other source of a first move
is defined.

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
  whose row lacks a `course_id` is skipped and returns `None`; and a search
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
