# Proposal — the body double proposes one tiny, concrete first move (#30)

## Why

Item 5 (D-F, on `main` at `96806feb`) gave a low-energy day a floor: when
nothing plan-related fits the day's energy and an active plan exists, the
engine proposes sitting with the plan — a body-double session, the learner
drives, the companion stays quiet. Scoring rubric row 3b (a) the owner said
**yes** to that floor and recorded one note beside it: *"the sit-with session
must not be a blank page — the body double should propose one tiny, concrete
first move on the deferred material (e.g. 'open the Frames lesson and read it,
nothing more'). A goal-less session is the hardest ADHD start; sharpening the
replacement beats restoring the rejected repair."* Today
`_body_double_candidate` names what was deferred and proposes nothing; the
co-study persona pins "stay quiet by default"; the learner sits down to a
title. Issue #30.

## What

One derived field and one sentence, from facts the engine already holds:

- `_first_move(plan, plans)` reads the first named plan's deferred next
  milestone and, when `_lesson_title_for(concepts)` resolves its concepts to an
  indexed lesson, the lesson's title, and returns `Open <material> and read for
  ten minutes, nothing more.` — passive by construction.
- The body-double recommendation carries it as `metadata["first_move"]`
  (additive, body-double only; the no-plan golden is untouched) and its reason
  ends `A first move, if you want one: <move>`.
- CLI `now` prints a `First move:` line beneath the door; the Today card
  renders its own line and hands `firstMove` to the Body Double view with the
  plan title; the picker shows it beneath the activity. The door is unchanged.
- `docs/study-plans.md` ("Plan-aware now") and `docs/web-ui-guide.md` ("Body
  Double") describe it in the engine's terms, pinned by the docs contract.

## What is deliberately not built

- **A first move for a deferred repair.** A body double is synthesised only
  when no plan-related candidate exists; an eligible next milestone would have
  been synthesised as one (rule 7). So every matchable ready plan behind a body
  double has its next milestone in `energy_deferred`, and the issue's "deferred
  repair only" row cannot occur. Recorded here rather than shipped as dead code.
- **Speaking the move.** The Body Double view shows it on screen; the persona's
  silence rule is untouched, and the move is never turned into questioning
  (PDA sensitivity, `agents/shared/audhd-framework.md`).
- **A second content read per consumer.** The lookup runs once, inside the
  engine, only on the body-double path.

## Rubric

A D-16 row (3c) plants row 3's world and expects the first move to name Frames;
the owner scores it before the change ships in 0.5.1.
