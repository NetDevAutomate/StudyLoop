## ADDED Requirements

### Requirement: The body-double proposal carries one passive first move
When the `now` engine synthesises the body-double proposal (`source ==
"body_double"`, design §5's floor), `learning/decision.py::_first_move` SHALL
derive one first move for it from stored facts only: the first named plan's
deferred next milestone (`_PlanContext.deferred`) and, when
`_lesson_title_for(concepts)` resolves that milestone's concepts to a lesson in
the indexed content (the explorer's FTS, read once per body double), the
lesson's title. The move SHALL be the sentence `Open <material> and read for
ten minutes, nothing more.` where `<material>` is `“<lesson title>”` or `the
<milestone title> material`. It SHALL be passive — reading; never an exercise,
a practice task or a question — because it must be consumable at the
capability the day carries. It SHALL ride as `metadata["first_move"]` on the
body-double recommendation only and close its reason as `A first move, if you
want one: <move>`; it SHALL add no top-level key to the `now` payload, so the
no-plan golden is byte-identical. The content index is a refinement, never a
dependency: a lookup that fails or raises SHALL answer the milestone form with
no warning. A body double always has a deferred milestone to draw on — an
eligible next milestone would have been synthesised as a plan-related
candidate and suppressed the body double — so no other source of a first move
is defined.

#### Scenario: The move names the deferred milestone's material
- **WHEN** rubric row 3's world is ranked at `low` energy (plan floor 5,
  milestone 2 “Frames” deferred, a live struggle deferred) and the content
  index resolves nothing
- **THEN** the primary is the body double, `metadata["first_move"] == "Open
  the Frames material and read for ten minutes, nothing more."`, the reason
  ends with `A first move, if you want one: ` followed by that sentence, the
  `evidence_command` is unchanged, and the payload's top-level keys are the
  golden's then `active_plans`, `energy_deferred`, `energy_deferred_repairs`

#### Scenario: The move names the lesson when the index resolves it
- **WHEN** the same world is ranked and the lesson lookup resolves the
  milestone's concepts (`("window frame",)`) to “Window Frames and Ranges”
- **THEN** `metadata["first_move"] == "Open “Window Frames and Ranges” and
  read for ten minutes, nothing more."` and the lookup was called exactly
  once, with that milestone's concepts

#### Scenario: A broken content index degrades to the milestone, silently
- **WHEN** the lesson lookup raises
- **THEN** the primary is still the body double, the move names the Frames
  material, and `warnings` carries nothing about the index

#### Scenario: Every renderer shows the move beside the door, never instead of it
- **WHEN** the body double is primary
- **THEN** CLI `now` prints a `First move:` line beneath `Sit with the plan:`;
  the Today card renders `firstMoveNote(primary)` as its own line and hands
  `firstMove` to the Body Double view in the `body-double-request` detail
  beside `activity` and `energy`; the Body Double picker shows it beneath the
  activity (`#bd-first-move`); a payload without the field renders nothing
  and hands over exactly what it did before
