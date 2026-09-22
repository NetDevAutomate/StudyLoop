# Council brief — review 8: the first move (issue #30), PR #32, tree `c83ebd75`

You are one of three reviewers (different model families, answering independently). You are reviewing an
IMPLEMENTATION on branch `feat/body-double-first-move` — 28 commits on top of `main` `fa1b2af3` (v0.5.0) — as
the tree to merge to `main` for 0.5.1. The coordinator verifies every 🔴/🟡 finding against the repository before
acting and lands accepted corrections one commit each. Say UNVERIFIED rather than assume. Do not restate the brief.

## 0. What you are reviewing against (binding)

### The issue
#30 — the owner's note beside rubric row 3b (a), 2026-09-20: *the sit-with session must not be a blank page* —
"open the Frames lesson and read it, nothing more". The `now` engine's body-double proposal (item 5's floor: when
nothing plan-related fits the day's energy, sit with the plan in a co-study session) must carry ONE tiny, passive
first move on the deferred material.

### Owner verdicts, rubric row 3c, scored one reading per turn on 2026-09-21 (receipt `now-rubric-2026-09-16.md`)
- **(a) the kind of move — yes.** Reading, passive, capped ("nothing more").
- **(b) the wording — yes, with a requirement:** *"A deliberate lesson should always be the case — great catch!
  This stops any decision fatigue and removes that friction."* Building it as a fallback chain (concepts → milestone
  title → plan topics) and MEASURING it on the owner's real vault showed the chain always names a lesson — the WRONG
  one (`Frames` → *405 Lab Execute PySpark Using Docker Locally*; `sql` → *ZTM Complete SQL Bootcamp — Introduction*).
- **(c) when no lesson matches — concepts only; otherwise name the milestone and say why — agreed.** Owner's
  self-check (would he notice the PySpark lab was wrong before opening it?): *"I suspect I would have doubts/concerns
  before opening which were confirmed after opening it"*, later refined: *"Before opening it — but honestly, I would
  likely still open it in case there was some link that is being enforced between PySpark and SQL"*. Reading taken
  by the coordinator: a named lesson carries implied authority and is FOLLOWED, not merely doubted — so a named
  lesson must state its evidence (course + matched concept) before anything opens it.
- **(d1) the sentence appeared twice (reason tail + dedicated line) — keep the `First move` line, drop it from the
  reason.** The reason explains the recommendation; the move is an action beside the door.
- **(d2) "Open X" actually opens X — build the button, gated behind the evidence sentence.** Open-the-lesson
  control on the Today card and the Body Double picker, opening the Course Explorer aside; shown only when a lesson
  resolved; in-session reader pane NOT built (issue #33's read-along needs the same pane, built once there).
- **(d3) the move survives the start — carry the move and the button into the live Body Double strip.** Rejected:
  auto-open at start.
- **(e) the medium-energy control — owner: NO, offer the move at medium energy too** (against the coordinator's
  steer that the move exists only when the engine has just refused everything else). Decomposed and built as
  **(e1) the warm-up INTO the primary, on the primary's own material** (owner: *"I think taking your steer would be
  a more appropriate way forward"*), ending `then start …` instead of `nothing more`; never on recall.
- **(e2) "build it now, the (d2)+(d3) shape on the Study view."** Found because the owner asked whether the move
  was carried into the live strip: Start → on a study action handed the Study picker NOTHING (not the warm-up, not
  the concept), and the Today card's `firstMoveNote`/`firstMoveLesson` gated on `source === 'body_double'`, so the
  card did not render the (e1) warm-up — the coordinator's (e1) claim "renderers needed no change" was FALSE for
  the card (true for the CLI). Corrected in code; the false claim is recorded, not erased (design decision 11).

### Standing rules that bind this tree
- The co-study persona's silence rule is untouched: the move is a proposal ON SCREEN, never something the companion
  or mentor says. PDA sensitivity (`agents/shared/audhd-framework.md`): a proposal, not a demand ("if you want one").
- No fabricated precision: a lesson is named with its evidence or not at all; a content gap is stated as such.
- TDD: every RED committed failing for its stated reason before its GREEN; corrections to a RED made at GREEN are
  recorded in the GREEN commit.
- The no-plan golden `packages/studyloop/tests/golden/now_plan_no_active.json` (sha256 prefix `ec451ce8`) is
  byte-identical throughout: the payload is additive (`metadata.first_move`, `first_move_lesson_id`,
  `first_move_lesson_title`) and adds no top-level key.
- Six supported harnesses (kiro-cli, Claude Code, Codex, OpenCode, pi, Grok Build): nothing here may work for one
  harness only. The engine, CLI and web UI are harness-independent; the MCP `get_next_action` returns
  `to_json_dict()` unchanged, so the new metadata reaches every harness that reads it.
- Versioning rule (owner, 2026-09-21): stay on the 0.5.x patch line; this ships as 0.5.1.

### Facts you may rely on (verified on `c83ebd75`, 2026-09-21)
- `ENERGY_CAPABILITY = {low: 3, medium: 6, high: 10}`; `ENERGY_DEMAND_CAPABILITY = {high: 6, medium: 4, low: 0}`.
  Row 3's world: plan `sql-windows` (floor 5), milestone 0 `Window basics` [window function] done, milestone 1
  `Frames` [window frame] open; `window function` recorded `struggling` 3 days before the frozen clock.
- Both collectors (due-progress AND struggle) run for real in the row-3 tests via
  `_plant_struggles_for_both_collectors`; the struggle's repair carries `energy_demand: high` (asks 6/10).
- Real-vault probes of the shipped seam `_resolve_lesson` (owner's explorer FTS index, 28 MB, content base
  `~/Obsidian/Personal/Study`): `("window frame",)` → `None`; `("window function",)` →
  `('ZTM/…/advanced-sql-4h', 'Advanced Sql 4H', 'Complete Sql Databases Bootcamp', 'window function')`
  161 ms cold / 45 ms warm; `("decorators",)` → `('CodeWithMosh/The_Ultimate_Typescript/…/decorators-29m',
  'Decorators 29M', 'The Ultimate Typescript', 'decorators')` 42–53 ms. A concept match is LEXICAL, not
  topic-scoped (a Python plan's "decorators" names a TypeScript lesson) — the evidence sentence is the remedy
  shipped; topic scoping is not.
- A known TEST-ISOLATION gap, not shipped code: `now_world` freezes `decision.datetime` only; the due collector's
  `days_ago` comes from `history/progress.py`, which reads the wall clock, so the medium screen's reason says
  "last seen 8 day(s) ago" for a row planted 3 days before the frozen 2026-09-16. Recorded for its own change.
- Renderer facts: CLI `_render_plan` prints `First move: <metadata.first_move>` beneath the door whenever the field is
  present (source-independent, unchanged since the base build). Today card and Body Double view: see the diffs.
- The Study view (`session-timer.js`) and the Today card (`today-panel.js`) have node harnesses
  (`tests/js/*.test.js`); `components.js` (Body Double view, Course Explorer) has none — its side is pinned
  statically (`test_web_body_double_first_move.py`), as is the markup for both session views.

## 1. Commits in the range (oldest first, fa1b2af3..c83ebd75)

```
f43f7eb2 test(now): RED — the body double proposes one tiny, passive first move (#30)
4d8d9fd5 feat(now): the body double proposes one tiny, passive first move (#30)
be3f30f8 docs(rubric): row 3c — the body double's first move, emitted from 4d8d9fd5, verdict PENDING (#30)
0df51360 docs(rubric): row 3c (a) yes — the kind of move; #33 filed for read-along
2e1c7ea7 test(now): RED — the first move always names a deliberate lesson when the index holds one (rubric 3c (b))
fdfe1672 test(now): RED — the first move names a lesson only from the milestone's own concepts, otherwise says why (rubric 3c (c))
62f3d6f8 feat(now): the first move names a lesson from the milestone's own concepts only, otherwise names the milestone and says why (rubric 3c (b)+(c))
b347fc67 docs(rubric): row 3c (b) yes-with-requirement and (c) agreed — concepts only, otherwise name the milestone and say why; screen re-emitted from 62f3d6f8
630cac72 test(now): RED — the first move appears once, beside the door, not also closing the reason (rubric 3c (d))
75bc9b7a feat(now): the first move appears once, beside the door — dropped from the reason (rubric 3c (d1))
22b64198 docs(rubric): row 3c (d1) — keep the First move line, drop it from the reason; screen re-emitted from 75bc9b7a
95e7e071 docs(rubric): row 3c — owner refines the (c) self-check: a named lesson is opened despite the doubt
2b85a80b test(now): RED — a named lesson states its evidence: the course it belongs to and the concept the match rests on (rubric 3c (d2))
089d09ae test(now): RED amendment — the seam also returns the concept that matched
4459ea38 feat(now): a named lesson states its evidence — the course it belongs to and the concept the match rests on (rubric 3c (d2))
e1576276 test(web): RED — 'Open X' actually opens X: the resolved lesson opens in the Course Explorer beside the view (rubric 3c (d2))
266afd4f feat(web): 'Open X' actually opens X — the resolved lesson opens in the Course Explorer beside the view (rubric 3c (d2))
084fad32 docs(rubric): row 3c (d2) — build the button, gated behind the evidence sentence; real-vault seam probe recorded
74779bda test(web): RED — the move survives the start: the live strip carries the first move and its control beneath the activity name (rubric 3c (d3))
5666f141 feat(web): the move survives the start — the live strip carries the first move and its control beneath the activity name (rubric 3c (d3))
ef3ad8f6 docs(rubric): row 3c (d3) — carry the move and the button into the live session strip; RED 74779bda → GREEN 5666f141
accb6725 docs(rubric): row 3c (e) — owner: no, offer the move at medium energy too; medium control re-emitted from 5666f141; (e1) shape pending
fa5d76be test(now): RED — a plan-related active primary carries a warm-up first move on its own material (rubric 3c (e1))
dacbea87 feat(now): a plan-related active primary carries a warm-up first move on its own material (rubric 3c (e1))
b64afd02 docs(rubric): row 3c (e1) — the warm-up into the primary, on its own material; RED fa5d76be → GREEN dacbea87; row 3c fully scored
eb3be21a test(web): RED — the warm-up follows Start into the Study view: picker and status bar carry it, the Today card renders it (rubric 3c (e2))
25886ff0 feat(web): the warm-up follows Start into the Study view — picker and status bar carry it, the Today card renders it (rubric 3c (e2))
c83ebd75 docs(rubric): row 3c (e2) — the warm-up follows Start into the Study view; (e1) renderer claim corrected in place; RED eb3be21a → GREEN 25886ff0
```

## 2. The design (verbatim, `openspec/changes/body-double-first-move/design.md`)

# Design — the body double's first move (#30)

Amends design §5 of the archived `plan-integration-followons` change (the
body-doubling floor). Decisions taken here, each verified against the tree at
`fa1b2af3`:

1. **Derived at synthesis, in `_body_double_candidate`.** The candidate already
   holds the named plans and `plans.deferred`; the first move is one more
   derived string beside the reason. No new read of plan documents (rule-1 pin:
   plans are read once, in `_PlanContext.build`).

2. **Milestone, always.** A body double implies a deferred next milestone for
   every matchable ready plan: `_PlanContext.build` synthesises an eligible next
   milestone as a candidate (rule 7), any plan-related candidate suppresses the
   body double (`any(plans.is_plan_related(c) for c in candidates)`), and a plan
   with no next milestone is a completion action, not a matchable plan. So the
   move draws on the first named plan's `DeferredMilestone`; the issue's
   "deferred repair only" branch is unreachable and not built.

3. **The lesson lookup is a seam, and a refinement — bounded to the milestone's
   own concepts.** `_resolve_lesson(concepts)` wraps the explorer's FTS
   (`_run_fts_search`, the `search_lessons` MCP path) with a lazy import so the
   learning layer does not import the web layer at load; one short query per
   concept, in order, stopping at the first `(lesson_id, title)`. Rubric 3c (b),
   owner 2026-09-21: *"A deliberate lesson should always be the case — this
   stops any decision fatigue and removes that friction."* — so a lesson is named
   whenever the vault holds one for the milestone's concepts. `None` is a
   *searched* miss; an index that cannot be consulted raises out of the seam, and
   the caller (not the seam) catches it, so the two are distinguishable (decision
   6). Cost: one FTS round-trip per concept until a hit, only on the body-double
   path (measured below).

4. **Additive carriage.** `metadata["first_move"]` and, when a lesson resolved,
   `metadata["first_move_lesson_id"]` — present only on the body double. The `Recommendation` dataclass is unchanged, so the no-plan golden
   (`ec451ce8`) is byte-identical without special-casing; the renderers read the
   field and re-derive nothing, so CLI and card agree by construction.

5. **A proposal, not a requirement — said once, beside the door.** The lead-in
   is "A first move, if you want one" (the Today card's label; the CLI's
   `First move:`); the Body Double view shows the text and says nothing — the
   co-study persona's silence rule is untouched. The move rides in
   `metadata["first_move"]` only. The first GREEN also closed the reason with
   it, so the same twenty-odd words appeared twice on a 3/10 screen — the
   `Why:` paragraph's tail and the dedicated line two lines below. Rubric 3c
   (d), owner 2026-09-21: keep the line, drop it from the reason — the reason
   explains the recommendation, the move is an action and belongs beside the
   door. Verified before deciding: no consumer reads the reason alone (CLI,
   Today card and MCP `get_next_action` all carry the payload's metadata), so
   nothing loses the move; the card's `Why:` shrinks by a line, which on a low
   day is the point.

6. **Concepts only; when nothing matches, name the milestone and say why —
   never widen the search (rubric 3c (c), owner 2026-09-21).** The first
   answer to (b) was a fallback chain — concepts, then the milestone's title,
   then the plan's topics — which does always name a lesson. Measured on the
   owner's real vault, it names the **wrong** one: `window frame` → nothing;
   `Frames` → *405 Lab Execute PySpark Using Docker Locally* ("frames" as data
   frames); `sql` → *ZTM Complete SQL Bootcamp — Introduction*; only the sibling
   milestone's `window function` → *Advanced Sql 4H*, and only because this
   plan's two milestones live in one lesson — a plan whose milestones span
   lessons would confidently name the finished one. A deliberate-but-wrong
   lesson spends a 3/10 day's one action on the wrong material and looks certain
   doing it (owner's self-check: *"I suspect I would have doubts/concerns before
   opening which were confirmed after opening it"*). So the title and topic
   steps are dropped, and the no-lesson sentence carries the information the fix
   needs — a lesson, or a concept name on the milestone, not a better search —
   in one of three honest shapes: searched-miss *"— no indexed lesson mentions
   “window frame” yet"* (every unmatched concept named); no concept on the
   milestone *"— this milestone names no concept to look up yet"* (the index is
   not asked — asking it with the title is the rejected chain); index unreadable
   — the plain sentence, no claim about an index that was never read. On the
   owner's vault today, `Frames` shows the first shape.

7. **A named lesson states its evidence — the course and the matched concept
   (rubric 3c (d2), owner 2026-09-21).** Re-checking the shipped seam on the
   owner's vault: a Python plan's `decorators` resolves to *Decorators 29M* in
   *The Ultimate TypeScript* — the concept match is lexical, not topic-scoped.
   Asked whether he would have noticed the (c) PySpark lab was wrong before
   opening it, the owner refined his answer: *"Before opening it — but honestly,
   I would likely still open it in case there was some link that is being
   enforced between PySpark and SQL."* A named lesson carries implied authority:
   the doubt does not stop the open, because the learner assumes the system had
   a reason for the link. So a wrong lesson is **followed**, not merely doubted,
   and the sentence must let the link be judged from the sentence, not by
   opening the lesson. Mechanism, from stored facts only: the FTS hit already
   carries `course_id`, which the seam had been discarding, and the seam knows
   which concept hit. The lesson form becomes *Open “Decorators 29M” from The
   Ultimate Typescript — the match is the word “decorators” — and read for ten
   minutes, nothing more.* — the course humanised by the explorer's own
   `_humanise`, exactly as its course list shows it, and "the match is the word"
   saying plainly that the link is a word match and nothing anyone built. A hit
   lacking its course or title is skipped: a lesson is named with its evidence
   or not at all. `first_move_lesson_title` rides beside `first_move_lesson_id`
   so a renderer opens the lesson by name without parsing the sentence. Topic
   scoping (hiding a TypeScript lesson from a Python plan) was NOT chosen: the
   courses carry no topic metadata to scope on, and it would also hide a lesson
   the learner legitimately wants; stating the evidence lets the learner decide.
   The control that opens the lesson (decision 8) waits behind this sentence.

8. **"Open X" actually opens X — in the Course Explorer aside, beside the view
   (rubric 3c (d2), owner 2026-09-21: build the button, gated behind the
   evidence sentence).** Before this, `first_move_lesson_id` was carried and
   consumed by nothing: the card said *Open “Decorators 29M”* beside a UI that
   could have opened it and left the finding to the learner. The Today card and
   the Body Double picker now offer **Open the lesson** — only when the engine
   resolved a lesson (row 3's Frames world shows no button, honestly). Both
   dispatch one window event, `explorer-open-lesson` `{lessonId, title}`, and
   the Course Explorer's new `openLessonById` opens its aside if closed and
   calls the existing `openLesson` with the same minimal lesson object
   `openSearchResult` builds — no second reader, no new fetch path. The aside
   is the third grid column beside whatever view is showing, so the learner
   stays on Today (or the picker, or the live session, since the aside
   persists across navigation) with the lesson next to it — the single pane the
   owner asked for, from parts that already existed. The hand-off to the Body
   Double view carries `firstMoveLessonId`/`firstMoveLessonTitle` beside
   `firstMove`, additive as before. NOT built: a reader pane inside the live
   Body Double session — #33's read-along needs that same pane, so it is built
   there, once. Sized as about a third of #30, as estimated.

9. **The move survives the start — on the live strip, beneath the activity
   name (rubric 3c (d3), owner 2026-09-21: carry the move and the button into
   the live session strip).** Checked in the markup, not recalled: the first
   move and its control lived only in the picker (`x-show="!sessionActive &&
   !starting"`). Pressing Start hid the picker and showed a strip with the
   activity name and End, then the console — the sentence was gone at exactly
   the moment the blank page arrived, and unless the lesson had been opened
   beforehand there was no second chance without ending the session. The
   view's state already survived the start (nothing cleared the three fields
   in `startSession()`), so the fix is markup reading state the view holds:
   `#bd-live-first-move` wraps to its own row of the flex-wrap strip beneath
   the activity name, same sentence, with `#bd-live-first-move-open` beside it
   when a lesson resolved, through the view's one opener. It stays a proposal
   on screen, never something the companion says — the co-study persona is
   untouched. REJECTED: an auto-open at start; the owner opens the lesson, or
   doesn't. One consequence built rather than left: `confirmEnd()` now clears
   the three first-move fields beside the `activity` it already cleared. The
   move arrived with the activity in one hand-off and leaves with it — now
   that the strip shows the move for the whole session, a stale one beneath
   the next, unrelated activity would be a confidently wrong proposal on the
   one surface that is always on screen, the class of defect (c) removed.
   Sized as about a tenth of #30, as estimated: one markup block, one CSS rule,
   one end-path line, one guide sentence, four pins.

10. **The move is a property of the recommendation, not of the sit-with — a
    warm-up on a plan-related active primary (rubric 3c (e), owner 2026-09-21:
    "no, offer the move at medium energy too", built as (e1) the warm-up INTO
    the primary, the owner taking that steer over the passive alternative
    beside it).** The coordinator's steer for (e) was that the move should
    exist only when the engine has just refused everything else; the owner
    overruled it — starting is hard at 6/10 too. The build honours the "no"
    without undoing 3b (d): the low day's move is the whole action and ends
    *nothing more*; printed beneath a task the day CAN carry, that sentence
    would tell the learner two contradictory things and the passive one is the
    easier to take. So the warm-up ends *then start …* and lowers the first
    step of the primary instead of competing with it, on the primary's OWN
    material (the medium screen's `window function` repair resolves on the
    owner's vault to *Advanced Sql 4H* in *Complete Sql Databases Bootcamp* —
    the lesson where window functions are taught, on topic). One definition,
    `_first_move_sentence`, builds both moves; only the material name and the
    tail differ, so (b)'s deliberate lesson, (c)'s honest no-lesson shapes and
    (d2)'s evidence sentence hold for both without a second implementation.
    Scope, each with its reason: the primary only (one move, never an
    alternate); never the body double (it has its own); never off a plan (the
    no-plan golden `ec451ce8` stays byte-identical, and the additive promise
    holds); never `recall` — reading the lesson before a retrieval test
    defeats the test, and row 3b (b) already said familiar recall leads as it
    is; never `visual`/`audio`, already passive. The tail names what the
    primary is, tested in this order: a repair (`energy_demand` in metadata —
    both collectors mark repairs and nothing else) → *then start the repair*;
    the plan's eligible next milestone → its own concepts, all of them, *then
    start the milestone*; any other plan-related active item → *then start on
    “<concept>”*. Applies at any energy, not medium alone — starting, not
    energy, is what it is for — and the CLI needed no change: it keys on
    `metadata.first_move`. The Today card did NOT follow without change — see
    decision 11, which corrects the claim made here at GREEN `dacbea87`.
    Beyond #30's title (the *body double's* first move), named
    honestly here and in the PR; the lead-in stays with the renderers (d1).
    Decided rather than asked: the energy scope and the three tails.

11. **The warm-up follows Start into the Study view — the (d2)+(d3) shape
    (owner 2026-09-21: "build it now, the (d2)+(d3) shape on the Study
    view").** Two defects, both found by reading the code the (e1) warm-up had
    to travel through — and one of them mine. (i) `startAction()` on the Today
    card handed the Body Double its activity, energy, move and lesson, but for
    a study action it only navigated: the Study picker opened blank — not the
    warm-up, not even the concept — and the learner retyped the topic from
    memory. Only the resume and parked paths (`today-resume`) ever carried a
    topic across. (ii) `firstMoveNote()`/`firstMoveLesson()` gated on `source
    === 'body_double'`, so the Today card did not render the (e1) warm-up at
    all. Decision 10 said "the renderers needed no change"; that was true of
    the CLI and false of the card, asserted from a grep of the field names
    without reading the two method bodies — recorded here and in the receipt
    rather than amended out of the pushed commit. The build: the gate comes
    off (the card reads the field wherever the engine put it, never
    second-guessing the source); Start on a study action hands `{topic:
    concept, energy, firstMove?, firstMoveLessonId?, firstMoveLessonTitle?}`
    over the EXISTING `today-resume` event (no new event; the resume and parked
    hand-offs keep their shape and, carrying no move, clear one left by an
    earlier Start); the Study view holds the three fields, shows the move
    beneath the topic in the picker and beneath the status bar for the whole
    session, opens the lesson through one `openFirstMoveLesson()` into the
    Course Explorer aside, clears the fields with the topic on end, and clears
    them on a planning launch (the architect interview is not a repair). The
    Body Double's own hand-off is unchanged and shares one `_firstMoveDetail`
    builder. Rejected, as at (d3): auto-opening the lesson at start.
    `session-timer.js` has a node harness, so this is behaviour-tested (the
    listener, the opener, the end path, the planning launch), with the markup
    pinned statically. Sized as about a third of #30, as estimated.

## Read cost

The lookup runs only when a body double is synthesised or (since (e1)) when the
primary is a plan-related active item. Measured 2026-09-21 on
the live host (content base `~/Obsidian/Personal/Study`, explorer FTS index
present) through the explorer search the seam calls: **861 ms cold** — the
explorer's own best-effort index refresh over the vault on the first query of a
process — then **45–58 ms warm per concept** (`("window function",)` →
"Advanced Sql 4H", `("decorators",)` → "Decorators 29M", `("window frame",)` →
`None`). Re-measured for the warm-up path the same day: `("window function",)`
**161 ms cold / 45 ms warm**, `("window frame",)` 53 ms, `("decorators",)`
53 ms. Paid once per `now` whose primary carries a move; a `now` with no
active plan pays nothing. For scale, item 4's completion review costs ~320 ms
per fully-checked plan on the same host.


## 3. The spec delta (verbatim, `openspec/changes/body-double-first-move/specs/active-learning-decisions/spec.md`)

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


## 4. Source diffs — `fa1b2af3..HEAD`, engine and the two harnessed components, in full

### `packages/studyloop/src/studyloop/learning/decision.py`

```diff
diff --git a/packages/studyloop/src/studyloop/learning/decision.py b/packages/studyloop/src/studyloop/learning/decision.py
index e036446a..aef11932 100644
--- a/packages/studyloop/src/studyloop/learning/decision.py
+++ b/packages/studyloop/src/studyloop/learning/decision.py
@@ -28,6 +28,7 @@ from typing import TYPE_CHECKING, Literal
 from studyloop.cli._shared import TOPIC_KEYWORDS

 if TYPE_CHECKING:
+    from collections.abc import Sequence
     from datetime import date

     from studyloop.planning.views import (
@@ -1280,6 +1281,211 @@ def _defer_repairs(
     return kept, tuple(deferred)


+def _resolve_lesson(concepts: Sequence[str]) -> tuple[str, str, str, str] | None:
+    """The indexed lesson the first move should name, or ``None``.
+
+    Returns ``(lesson_id, title, course, concept)`` — the concept being the one
+    the index matched, not the first one asked, so the sentence can say what the
+    match rests on.
+    Asks the explorer's own FTS — the path MCP ``search_lessons`` takes — one
+    short query per concept of the deferred milestone, in order, stopping at the
+    first hit. The concepts and nothing else: rubric 3c (c), measured on the
+    owner's real vault 2026-09-21, showed that falling back to the milestone's
+    title or the plan's topics always names a lesson — the wrong one ("Frames"
+    hit a PySpark data-frames lab; "sql" hit an SQL bootcamp introduction). A
+    deliberate-but-wrong lesson on a low-energy day is worse than an honest
+    "nothing matches yet", so the wider steps are not taken.
+
+    ``course`` is the hit's own ``course_id`` humanised exactly as the explorer's
+    course list shows it (``_humanise`` of the course directory) — the evidence
+    the sentence states beside the lesson (rubric 3c (d2)), so a lexical match
+    into the wrong course reads as one at a glance. A hit that lacks its course
+    or its title is skipped, never named: a lesson is named with its evidence or
+    not at all.
+
+    ``None`` is a *searched* miss. An index that cannot be consulted (no content
+    base, a locked db) raises instead of answering ``None``, so the caller can
+    tell the two apart and never claims "no indexed lesson mentions X" about an
+    index it did not read. Imported lazily: the engine does not import the web
+    layer at module load. Tests plant a lesson by replacing this seam, or the
+    explorer's search function beneath it.
+    """
+    from studyloop.settings import load_settings
+    from studyloop.web.routes import explorer
+
+    base = load_settings().content.base_path.expanduser()
+    with explorer._fts_lock:
+        for concept in concepts:
+            q = concept.strip()
+            if len(q) < 2:
+                continue
+            rows = explorer._run_fts_search(explorer._fts_db_path(), base, q, 1)
+            if rows:
+                lesson_id = str(rows[0].get("lesson_id") or "").strip()
+                title = str(rows[0].get("title") or "").strip()
+                course_id = str(rows[0].get("course_id") or "").strip()
+                course_dir = course_id.rsplit("/", 1)[-1] if course_id else ""
+                if lesson_id and title and course_dir:
+                    return lesson_id, title, explorer._humanise(course_dir), q
+    return None
+
+
+def _first_move(
+    plan: ActivePlanGuidance, plans: _PlanContext
+) -> tuple[str, str | None, str | None] | None:
+    """Issue #30: one tiny, passive first move on the deferred material.
+
+    The owner's note beside rubric row 3b (a): a sit-with session must not be a
+    blank page — "open the Frames lesson and read it, nothing more". Derived
+    from stored facts only: the plan's deferred next milestone (a body double
+    is synthesised only when every matchable ready plan's next milestone is
+    deferred — an eligible one would have been synthesised as a plan-related
+    candidate and suppressed it — so the milestone is always there to draw on)
+    and, when the content index resolves the milestone's own concepts, the lesson
+    the learner can actually open (rubric 3c (b): a deliberate lesson whenever the
+    vault holds one). Reading only, at the capability the day carries: never an
+    exercise, never a Socratic round. Returns ``(sentence, lesson_id, lesson_title)``.
+
+    A named lesson states its EVIDENCE (rubric 3c (d2), owner 2026-09-21 — "I
+    would likely still open it in case there was some link being enforced"): a
+    named lesson carries implied authority, so a wrong one is followed, not merely
+    doubted. The sentence therefore names the course the lesson belongs to and
+    the concept the match rests on — ``Open “<lesson>” from <Course> — the match
+    is the word “<concept>” — and read for ten minutes, nothing more.`` — so a
+    lexical match into the wrong course (a Python plan's "decorators" resolving
+    to a TypeScript lesson) is judgeable from the sentence, not by opening it.
+
+    When no lesson is named, the sentence names the milestone AND says why
+    (rubric 3c (c)), so it carries information instead of vagueness and points at
+    the fix — a lesson, or a concept name on the milestone, not a better search:
+
+    * searched, nothing matched — ``… — no indexed lesson mentions “<concept>” yet.``
+    * the milestone names no concept — ``… — this milestone names no concept to
+      look up yet.`` (the index is not asked; asking it with the title is the
+      rejected chain)
+    * the index could not be read — the plain sentence, with no claim about an
+      index that was never consulted; a failed refinement is not a warning.
+
+    ``None`` only when the plan has no deferred milestone, which the invariant
+    above rules out.
+    """
+    summary = plan.plan
+    deferred = next((d for d in plans.deferred if d.plan_id == summary.plan_id), None)
+    if deferred is None:
+        return None
+    concepts = _clean_concepts(plan.next_milestone.concepts if plan.next_milestone else ())
+    return _first_move_sentence(concepts, material=deferred.title, tail="nothing more")
+
+
+def _clean_concepts(concepts: Sequence[str]) -> tuple[str, ...]:
+    """Stripped, de-duplicated, in order — what the resolver is asked."""
+    cleaned: list[str] = []
+    for concept in concepts:
+        c = concept.strip()
+        if c and c not in cleaned:
+            cleaned.append(c)
+    return tuple(cleaned)
+
+
+def _first_move_sentence(
+    concepts: Sequence[str], *, material: str, tail: str
+) -> tuple[str, str | None, str | None]:
+    """One sentence, two moves: the sit-with's (``tail="nothing more"``) and the
+    warm-up's (``tail="then start …"``, rubric 3c (e1)). Same evidence rule for a
+    named lesson, same three honest shapes when none is named; only what the
+    move is FOR differs, and the tail says it. Returns ``(sentence, lesson_id,
+    lesson_title)``; the lead-in ("First move, if you want one:") belongs to the
+    renderers (rubric 3c (d1)), so the sentence carries none.
+    """
+    stem = f"Open your {material} material and read for ten minutes, {tail}"
+    if not concepts:
+        return f"{stem} — this milestone names no concept to look up yet.", None, None
+    try:
+        hit = _resolve_lesson(tuple(concepts))
+    except Exception:
+        logger.debug("first move: lesson index unavailable, naming the material", exc_info=True)
+        return f"{stem}.", None, None
+    if hit is not None:
+        lesson_id, title, course, matched = hit
+        kind = "phrase" if " " in matched.strip() else "word"
+        return (
+            f"Open “{title}” from {course} — the match is the {kind} “{matched}” — "
+            f"and read for ten minutes, {tail}.",
+            lesson_id,
+            title,
+        )
+    named = " or ".join(f"“{c}”" for c in concepts)
+    return f"{stem} — no indexed lesson mentions {named} yet.", None, None
+
+
+def _first_move_metadata(
+    sentence: str | None, lesson_id: str | None, lesson_title: str | None
+) -> dict[str, str | int | float | None]:
+    """The move's carriage: ``first_move`` and, when a lesson resolved, its id and
+    title beside it so a renderer opens it in StudyLoop's own frame without parsing
+    the sentence. Empty when there is no move, so a payload adds nothing."""
+    if not sentence:
+        return {}
+    carried: dict[str, str | int | float | None] = {"first_move": sentence}
+    if lesson_id:
+        carried["first_move_lesson_id"] = lesson_id
+        if lesson_title:
+            carried["first_move_lesson_title"] = lesson_title
+    return carried
+
+
+#: The actions a warm-up ramps into (rubric 3c (e1)). Never ``recall``: reading the
+#: lesson before a retrieval test defeats the test (row 3b (b): familiar recall
+#: leads as it is). Never ``visual``/``audio``: those are already passive.
+_WARM_UP_ACTIONS: frozenset[str] = frozenset({"hands-on", "conversation", "teachback"})
+
+
+def _warm_up(primary: _Candidate, plans: _PlanContext) -> tuple[str, str | None, str | None] | None:
+    """Rubric 3c (e1), owner 2026-09-21 ("no, offer the move at medium energy too",
+    taking the steer): a plan-related ACTIVE primary carries one first move on ITS
+    OWN material, worded as a ramp into the task.
+
+    The low-energy move is the sit-with's whole action and ends "nothing more";
+    printed beneath a task the day CAN carry, that sentence would tell the learner
+    two contradictory things and the passive one is the easier to take (the 3b (d)
+    mistake). The warm-up ends "then start …" and lowers the first step of the
+    primary instead of competing with it.
+
+    Scope: the primary only (one move); never the body double (it has its own);
+    never a candidate off every plan (so the no-plan golden is byte-identical);
+    never recall, visual or audio (:data:`_WARM_UP_ACTIONS`). Material, in order
+    of what the primary IS: a repair (``energy_demand`` in its metadata — both
+    collectors mark repairs and nothing else) asks the resolver its own concept
+    and ends "then start the repair"; a plan milestone (a ref naming the eligible
+    next milestone) asks that milestone's own concepts and ends "then start the
+    milestone"; any other plan-related active item asks its concept and ends
+    "then start on “<concept>”". Same evidence sentence, same honest no-lesson
+    shapes as the sit-with move (:func:`_first_move_sentence`).
+    """
+    if primary.source == BODY_DOUBLE_SOURCE or not primary.plan_refs:
+        return None
+    if primary.action_type not in _WARM_UP_ACTIONS:
+        return None
+    concept = primary.concept.strip()
+    if "energy_demand" in primary.metadata:
+        return _first_move_sentence(
+            (concept,), material=f"“{concept}”", tail="then start the repair"
+        )
+    ref = next((r for r in primary.plan_refs if r.milestone_index is not None), None)
+    if ref is not None:
+        plan = next((p for p in plans.matchable if p.plan.plan_id == ref.plan_id), None)
+        milestone = plan.next_milestone if plan is not None else None
+        if milestone is not None and milestone.index == ref.milestone_index:
+            return _first_move_sentence(
+                _clean_concepts(milestone.concepts),
+                material=milestone.title,
+                tail="then start the milestone",
+            )
+    return _first_move_sentence(
+        (concept,), material=f"“{concept}”", tail=f"then start on “{concept}”"
+    )
+
+
 def _body_double_candidate(
     plans: _PlanContext,
     candidates: list[_Candidate],
@@ -1302,10 +1508,14 @@ def _body_double_candidate(
     # An active-but-unready plan is matched but never synthesised (spec rule 8);
     # the body double is a synthesis, so only ready plans are sat with. The
     # warning beside it already says "pause or repair".
-    named = [plan.plan for plan in plans.matchable if plan.readiness.ready]
+    ready_plans = [plan for plan in plans.matchable if plan.readiness.ready]
+    named = [plan.plan for plan in ready_plans]
     if not named:
         return None
     first = named[0]
+    first_move, first_move_lesson_id, first_move_lesson_title = _first_move(
+        ready_plans[0], plans
+    ) or (None, None, None)
     titles = " and ".join(plan.title for plan in named)
     items = [
         f"milestone {d.milestone_index + 1} “{d.title}” of {d.plan_title}" for d in plans.deferred
@@ -1343,6 +1553,15 @@ def _body_double_candidate(
             "plan_id": first.plan_id,
             "deferred_milestones": len(plans.deferred),
             "deferred_repairs": len(deferred_repairs),
+            # Issue #30: additive — the no-plan golden never sees it. The move lives in
+            # metadata and nowhere else (rubric 3c (d)): the reason explains the
+            # recommendation, the move is an action beside the door, and every
+            # renderer (CLI, Today card, MCP get_next_action) reads this field — so
+            # the sentence appears once on a 3/10 screen instead of closing the
+            # reason and then repeating as its own line. Rubric 3c (b): the lesson
+            # the move names rides beside it as id + title, so nothing parses the
+            # sentence; absent when the index held nothing relevant.
+            **_first_move_metadata(first_move, first_move_lesson_id, first_move_lesson_title),
         },
         plan_refs=tuple(PlanRef(plan.plan_id, None) for plan in named),
     )
@@ -1434,6 +1653,17 @@ def build_now_plan(
         ranked = _guarantee_plan_backed(
             [plans.attach_refs(candidate) for candidate in ranked], time_minutes
         )
+    # Rubric 3c (e1): the primary — and only the primary — of a plan-related
+    # active kind carries one warm-up on its own material. After the guarantee,
+    # so it rides on the recommendation the learner actually sees.
+    warm_up = _warm_up(ranked[0], plans)
+    if warm_up is not None:
+        ranked = [
+            dataclasses.replace(
+                ranked[0], metadata={**ranked[0].metadata, **_first_move_metadata(*warm_up)}
+            ),
+            *ranked[1:],
+        ]
     primary = ranked[0].recommendation()
     alternates = [item.recommendation() for item in ranked[1:3]]
     return NowPlan(
```

### `packages/studyloop/src/studyloop/cli/_now.py`

```diff
diff --git a/packages/studyloop/src/studyloop/cli/_now.py b/packages/studyloop/src/studyloop/cli/_now.py
index d751a0ed..739190e1 100644
--- a/packages/studyloop/src/studyloop/cli/_now.py
+++ b/packages/studyloop/src/studyloop/cli/_now.py
@@ -58,6 +58,13 @@ def _render_plan(plan) -> None:
         f"Source: [dim]{escape(primary.source)}[/dim]\n"
         + (f"Plan: [magenta]{escape(plan_line)}[/magenta]\n" if plan_line else "")
         + f"\n[bold]{door}:[/bold]\n{escape(primary.evidence_command)}"
+        # Issue #30: the body double's one passive first move, beneath the door —
+        # where to sit, then what to open. Present only when the engine derived one.
+        + (
+            f"\n[bold]First move:[/bold] {escape(str(first_move))}"
+            if (first_move := primary.metadata.get("first_move"))
+            else ""
+        )
     )
     console.print(Panel(body, title="Study Now", border_style="cyan"))

```

### `packages/studyloop/src/studyloop/web/static/js/components/today-panel.js`

```diff
diff --git a/packages/studyloop/src/studyloop/web/static/js/components/today-panel.js b/packages/studyloop/src/studyloop/web/static/js/components/today-panel.js
index 706e7f24..a198cefe 100644
--- a/packages/studyloop/src/studyloop/web/static/js/components/today-panel.js
+++ b/packages/studyloop/src/studyloop/web/static/js/components/today-panel.js
@@ -120,13 +120,44 @@ export function todayPanel() {
            7, F7): the same event-not-storage handoff `today-resume` uses, so
            the picker opens on the plan the engine named instead of blank. The
            view starts nothing on its own; the learner still presses start. */
-        window.dispatchEvent(new CustomEvent('body-double-request', {
-          detail: { activity: this.bodyDoubleActivity(rec), energy: this.plan && this.plan.energy },
-        }));
+        const detail = { activity: this.bodyDoubleActivity(rec), energy: this.plan && this.plan.energy };
+        /* Issue #30: the engine's one passive first move rides along when there is
+           one, so the picker opens on something to open — additive; a payload
+           without it hands over exactly what it did before. Rubric 3c (d2): the
+           lesson the move names, when the engine resolved one, rides beside it. */
+        Object.assign(detail, this._firstMoveDetail(rec));
+        window.dispatchEvent(new CustomEvent('body-double-request', { detail }));
+      } else if (view === 'study-session') {
+        /* Rubric 3c (e2): Start used to navigate and hand the Study picker
+           NOTHING — not the (e1) warm-up, not even the concept — so the learner
+           retyped the topic from memory and the sentence the card had just
+           shown was thrown away. Same event the resume and parked paths use
+           (`today-resume`, event-not-storage), so the picker opens on the
+           action the engine named, with its move beside it when there is one.
+           The view starts nothing on its own; the learner still presses Start. */
+        const detail = { topic: rec.concept || '', energy: (this.plan && this.plan.energy) || null };
+        Object.assign(detail, this._firstMoveDetail(rec));
+        window.dispatchEvent(new CustomEvent('today-resume', { detail }));
       }
       Alpine.store('nav').go(view);
     },

+    /* The first move's share of a hand-off: the sentence and, when the engine
+       resolved a lesson, its id and title — additive, so a recommendation
+       without a move hands over exactly what it did before. One definition for
+       both session views. */
+    _firstMoveDetail(rec) {
+      const detail = {};
+      const firstMove = this.firstMoveNote(rec);
+      if (firstMove) detail.firstMove = firstMove;
+      const lesson = this.firstMoveLesson(rec);
+      if (lesson) {
+        detail.firstMoveLessonId = lesson.id;
+        detail.firstMoveLessonTitle = lesson.title;
+      }
+      return detail;
+    },
+
     /* What a body-double proposal asks the learner to sit with: the named
        plan's title, or the proposal's own concept when the payload lists no
        plan for it. */
@@ -136,6 +167,41 @@ export function todayPanel() {
       return (plan && plan.title) || (rec && rec.concept) || '';
     },

+    /* Issue #30: the engine's one tiny, passive first move, verbatim from
+       `metadata.first_move`; '' for a payload that carries none. Nothing here
+       re-derives it — the sentence is the engine's, so the CLI and the card
+       agree. Rubric 3c (e1)/(e2): the engine puts a move on the body-double
+       proposal AND, as a warm-up, on a plan-related active primary, so the card
+       reads the field wherever the engine put it and never second-guesses the
+       source (the body-double gate that used to sit here hid the warm-up). */
+    firstMoveNote(rec) {
+      const move = rec && rec.metadata && rec.metadata.first_move;
+      return move ? String(move) : '';
+    },
+
+    /* Rubric 3c (d2): the indexed lesson the first move names, when the engine
+       resolved one — `{ id, title }` from `metadata.first_move_lesson_id` and
+       `_title`; null for a milestone-form move or no payload. The sentence has
+       already stated the lesson's evidence (its course and the word the match
+       rests on), so what this opens is what the learner judged. */
+    firstMoveLesson(rec) {
+      if (!rec || !rec.metadata) return null;
+      const id = rec.metadata.first_move_lesson_id;
+      if (!id) return null;
+      return { id: String(id), title: String(rec.metadata.first_move_lesson_title || '') };
+    },
+
+    /* "Open X" actually opens X: asks the Course Explorer aside to open the
+       lesson beside this view. No navigation — the learner stays on Today with
+       the lesson open next to it. Nothing to open, nothing dispatched. */
+    openFirstMoveLesson() {
+      const lesson = this.firstMoveLesson(this.plan && this.plan.primary);
+      if (!lesson) return;
+      window.dispatchEvent(new CustomEvent('explorer-open-lesson', {
+        detail: { lessonId: lesson.id, title: lesson.title },
+      }));
+    },
+
     /* The view an action starts in. A body-double proposal (design §5) is a
        session in the Body Double view, whatever its action_type says; every
        other action keeps the action_type mapping above. */
```

### `packages/studyloop/src/studyloop/web/static/js/components/session-timer.js`

```diff
diff --git a/packages/studyloop/src/studyloop/web/static/js/components/session-timer.js b/packages/studyloop/src/studyloop/web/static/js/components/session-timer.js
index 9e6bfa45..24f87dd7 100644
--- a/packages/studyloop/src/studyloop/web/static/js/components/session-timer.js
+++ b/packages/studyloop/src/studyloop/web/static/js/components/session-timer.js
@@ -89,6 +89,13 @@ export function sessionTimer() {
       selectedCourse: '',
       selectedLesson: '',
       topicInput: '',
+      /* Rubric 3c (e2): the warm-up handed over with the topic by the Today
+         card's Start (today-resume), shown beneath the topic in the picker and
+         beneath the status bar for the whole session; '' when the hand-off
+         carried none. Cleared with the topic when the session ends. */
+      firstMove: '',
+      firstMoveLessonId: '',
+      firstMoveLessonTitle: '',
       selectedOption: null,
       /* sessionType removed (body-double-own-agent-picker §5.2): Body Double
          is its own view with its own factory, so the Study picker has exactly
@@ -154,6 +161,14 @@ export function sessionTimer() {
             const bands = { low: 3, medium: 5, high: 8 };
             this.energy = bands[e.detail.energy] || 5;
           }
+          /* Rubric 3c (e2): the move arrives beside the topic, or not at all.
+             Set from THIS hand-off every time, so a resume or a parked pick-up
+             (which carry no move) clears one left by an earlier Start. */
+          const detail = e.detail || {};
+          this.firstMove = detail.firstMove ? String(detail.firstMove) : '';
+          this.firstMoveLessonId = detail.firstMoveLessonId ? String(detail.firstMoveLessonId) : '';
+          this.firstMoveLessonTitle = detail.firstMoveLessonTitle
+            ? String(detail.firstMoveLessonTitle) : '';
         });

         // Plans-view hand-off (#14, design §5). The Plans view ASKS for a
@@ -280,6 +295,11 @@ export function sessionTimer() {
         this.selectedTopic = '';
         this.selectedOption = null;
         this.targetKind = 'topic';
+        /* Rubric 3c (e2): the architect interview is not a repair; a warm-up
+           left by an earlier Today hand-off must not sit beneath it. */
+        this.firstMove = '';
+        this.firstMoveLessonId = '';
+        this.firstMoveLessonTitle = '';
         /* The learner's brain dump, or '' — forwarded once, into this POST
            only; the server renders it into the brief and never stores it. */
         const brainDump = String(detail.brainDump || '').trim();
@@ -542,6 +562,23 @@ export function sessionTimer() {
         this.topic = 'Session ended';
         this.topicInput = '';
         this.selectedTopic = '';
+        /* Rubric 3c (e2): the move arrived beside the topic in one hand-off and
+           leaves with it — the status bar shows it for the whole session, so a
+           stale one beneath the next topic would be a confidently wrong ramp. */
+        this.firstMove = '';
+        this.firstMoveLessonId = '';
+        this.firstMoveLessonTitle = '';
+      },
+
+      /* "Open X" actually opens X (rubric 3c (d2), here for the Study view):
+         asks the Course Explorer aside to open the lesson the move names, beside
+         this view — no navigation, the learner stays put with the lesson next
+         to the picker or the console. Nothing to open, nothing dispatched. */
+      openFirstMoveLesson() {
+        if (!this.firstMoveLessonId) return;
+        window.dispatchEvent(new CustomEvent('explorer-open-lesson', {
+          detail: { lessonId: this.firstMoveLessonId, title: this.firstMoveLessonTitle },
+        }));
       },

       /* ---- recovery from a session this view does not own -------------- */
```

## 5. Markup, CSS and the unharnessed Body Double view — diffs in full

### `packages/studyloop/src/studyloop/web/static/index.html`

```diff
diff --git a/packages/studyloop/src/studyloop/web/static/index.html b/packages/studyloop/src/studyloop/web/static/index.html
index f84fc69d..81189fbb 100644
--- a/packages/studyloop/src/studyloop/web/static/index.html
+++ b/packages/studyloop/src/studyloop/web/static/index.html
@@ -1092,6 +1092,20 @@
               · <span x-text="plan?.primary?.action_type"></span>
             </p>
             <p class="today-reason">Why: <span x-text="plan?.primary?.reason"></span></p>
+            <!-- Issue #30: the body double's one passive first move, its own line
+                 beside the door; hidden for every other action. -->
+            <p class="today-first-move" x-show="firstMoveNote(plan?.primary)">
+              First move, if you want one: <span x-text="firstMoveNote(plan?.primary)"></span>
+            </p>
+            <!-- Rubric 3c (d2): "Open X" actually opens X — the lesson the move names
+                 opens in the Course Explorer beside this card; only when the engine
+                 resolved one (the sentence above has stated its evidence). -->
+            <p class="today-first-move-open" x-show="firstMoveLesson(plan?.primary)">
+              <button type="button" class="bulk-btn"
+                      data-testid="today-open-first-move-lesson"
+                      x-show="firstMoveLesson(plan?.primary)"
+                      @click="openFirstMoveLesson()">Open the lesson</button>
+            </p>
             <!-- Plan relevance (#10): which active plan this action advances.
                  Rendered from the engine's plan_refs; nothing here re-ranks. -->
             <p class="today-meta today-plan" x-show="planLabel(plan?.primary)">
@@ -1712,6 +1726,17 @@
             <label class="bd-field">What are you working on?
               <input id="bd-activity-input" type="text" x-model="activity"
                      placeholder="e.g. Window functions"></label>
+            <!-- Issue #30: the Today card's sit-with proposal hands over one passive
+                 first move with the plan title; a proposal the learner may ignore. -->
+            <p id="bd-first-move" class="picker-hint" x-show="firstMove" x-text="firstMove"></p>
+            <!-- Rubric 3c (d2): "Open X" actually opens X — the lesson the move names
+                 opens in the Course Explorer beside this picker, so the session can
+                 start with it already open; only when the engine resolved one. -->
+            <p class="picker-hint" x-show="firstMoveLessonId">
+              <button id="bd-first-move-open" type="button" class="bulk-btn"
+                      x-show="firstMoveLessonId"
+                      @click="openFirstMoveLesson()">Open the lesson</button>
+            </p>
             <label class="bd-field">Agent
               <select id="bd-agent-select" class="picker-select" x-model="agent">
                 <option value="">Choose an agent…</option>
@@ -1808,6 +1833,17 @@
                 <button id="bd-end-confirm-yes" type="button" class="bulk-btn" @click="confirmEnd()">Yes, end it</button>
                 <button id="bd-end-cancel" type="button" class="bulk-btn" @click="cancelEnd()">Keep going</button>
               </div>
+              <!-- Rubric 3c (d3): the move survives the start. The picker's copy
+                   hides with the picker; this one wraps to its own row beneath the
+                   activity name (the strip is flex-wrap) for the whole session — a
+                   proposal on screen, never something the companion says. Same
+                   sentence, same opener; nothing opens by itself. -->
+              <p id="bd-live-first-move" class="bd-live-first-move" x-show="firstMove">
+                <span x-text="firstMove"></span>
+                <button id="bd-live-first-move-open" type="button" class="bulk-btn"
+                        x-show="firstMoveLessonId"
+                        @click="openFirstMoveLesson()">Open the lesson</button>
+              </p>
             </div>
             <!-- x-if, NOT x-show: this console must not EXIST in the DOM unless a
                  Body Double session is running. It sits earlier in the document
@@ -2317,6 +2353,17 @@
               Suggestions are the first three topics from <code>config.yaml</code>.
               You can type any other course material or topic instead.
             </p>
+            <!-- Rubric 3c (e2): the warm-up the Today card's Start handed over
+                 with the topic (today-resume) — a proposal beneath the topic,
+                 hidden when the hand-off carried none. Same opener as the live
+                 line below; nothing opens by itself. -->
+            <p id="study-first-move" class="picker-hint study-first-move" x-show="firstMove">
+              <span class="study-first-move-label">First move, if you want one:</span>
+              <span x-text="firstMove"></span>
+              <button id="study-first-move-open" type="button" class="bulk-btn"
+                      x-show="firstMoveLessonId"
+                      @click="openFirstMoveLesson()">Open the lesson</button>
+            </p>
           </div>

           <div class="picker-field" x-show="targetKind === 'vendor' || targetKind === 'course' || targetKind === 'lesson'">
@@ -2698,6 +2745,18 @@
               <span x-show="message && !paused" x-text="message"></span>
             </div>
           </div>
+          <!-- Rubric 3c (e2): the move survives the start here too. The picker's
+               copy hides with the picker; this line sits beneath the status bar
+               that names the topic, for the whole session — a proposal on
+               screen, never something the mentor says. Cleared with the topic
+               when the session ends. -->
+          <div id="study-live-first-move" class="study-live-first-move" x-show="firstMove">
+            <span class="study-first-move-label">First move:</span>
+            <span x-text="firstMove"></span>
+            <button id="study-live-first-move-open" type="button" class="bulk-btn"
+                    x-show="firstMoveLessonId"
+                    @click="openFirstMoveLesson()">Open the lesson</button>
+          </div>
         </div>
       </div>

```

### `packages/studyloop/src/studyloop/web/static/style.css`

```diff
diff --git a/packages/studyloop/src/studyloop/web/static/style.css b/packages/studyloop/src/studyloop/web/static/style.css
index 3d4d1143..377f2eee 100644
--- a/packages/studyloop/src/studyloop/web/static/style.css
+++ b/packages/studyloop/src/studyloop/web/static/style.css
@@ -1961,6 +1961,30 @@ body[data-font="opendyslexic"] .card-content {
   text-overflow: ellipsis;
   max-width: 200px;
 }
+
+/* Rubric 3c (e2): the first move on the Study view. In the picker it is a
+   hint beneath the topic; in the live layout it is a row beneath the status
+   bar (same surface, same border) that stays for the whole session. */
+.study-first-move,
+.study-live-first-move {
+  display: flex;
+  flex-wrap: wrap;
+  align-items: center;
+  gap: 8px;
+  min-width: 0;
+  overflow-wrap: anywhere;
+  color: var(--text-muted);
+  font-size: 0.78rem;
+  line-height: 1.5;
+}
+.study-first-move { margin: 6px 0 0; }
+.study-live-first-move {
+  flex-shrink: 0;
+  padding: 6px 16px 8px;
+  background: var(--bg-card);
+  border-top: 1px solid var(--border);
+}
+.study-first-move-label { font-weight: 600; color: var(--text); }
 .status-energy {
   color: var(--text-muted);
   white-space: nowrap;
@@ -5109,6 +5133,23 @@ body[data-palette="everforest"] {
   font-weight: 650;
 }

+/* Rubric 3c (d3): the first move's row in the live strip. flex-basis 100% wraps
+   it beneath the activity name and End; the type mirrors the picker's hint so
+   the sentence reads as the same proposal it was before Start. */
+.bd-live-strip > .bd-live-first-move {
+  flex-basis: 100%;
+  display: flex;
+  flex-wrap: wrap;
+  align-items: center;
+  gap: 8px;
+  margin: 0;
+  min-width: 0;
+  overflow-wrap: anywhere;
+  color: var(--text-muted);
+  font-size: 0.78rem;
+  line-height: 1.5;
+}
+
 .bd-end-confirm {
   display: inline-flex;
   flex-wrap: wrap;
```

### `packages/studyloop/src/studyloop/web/static/components.js`

```diff
diff --git a/packages/studyloop/src/studyloop/web/static/components.js b/packages/studyloop/src/studyloop/web/static/components.js
index eb678693..15f4277c 100644
--- a/packages/studyloop/src/studyloop/web/static/components.js
+++ b/packages/studyloop/src/studyloop/web/static/components.js
@@ -1559,6 +1559,41 @@ function courseExplorer() {
         // Only reflect speaking state while the reader is the active surface.
         self.isReading = (e.detail && e.detail.state === 'speaking');
       });
+      /* Rubric 3c (d2), issue #30: another view asks for a lesson by id — the
+         Today card's or the Body Double picker's "Open the lesson" control for
+         the first move the engine resolved. The aside opens beside whatever
+         view is showing, so the learner does not leave it. */
+      window.addEventListener('explorer-open-lesson', (e) => {
+        const detail = (e && e.detail) || {};
+        self.openLessonById(detail.lessonId, detail.title);
+      });
+    },
+
+    // ------------------------------------------------------------------
+    // Open the aside (if closed) and a lesson by its full id, as a request
+    // from another view. Builds the same minimal lesson object
+    // openSearchResult() builds: id "provider/course/slug", course_id the
+    // first two segments, slug the rest, name the caller's title.
+    // ------------------------------------------------------------------
+    async openLessonById(lessonId, title) {
+      const id = String(lessonId || '').trim();
+      if (!id) return;
+      const store = Alpine.store('explorer');
+      if (!store.open) {
+        store.open = true;
+        const layout = document.querySelector('.app-layout');
+        if (layout) layout.classList.add('explorer-open');
+      }
+      if (!this._treeLoaded) await this._fetchTree();
+      const parts = id.split('/');
+      const courseId = parts.length > 2 ? parts.slice(0, 2).join('/') : '';
+      const slug = courseId ? parts.slice(2).join('/') : id;
+      this.openLesson({
+        id,
+        slug,
+        name: String(title || slug),
+        course_id: courseId,
+      });
     },

     // ------------------------------------------------------------------
@@ -3128,7 +3163,8 @@ function bodyDoubleSession() {
     slots: [], slotsUsed: 0, maxActive: 3, atCapacity: false, parkingLotCount: 0,
     focus: { topics: [], is_set: false, is_stale: false },
     focusCollapsed: false, captureCollapsed: false, captureTab: 'note',
-    activity: '', agent: '', transport: 'pty', energy: 5, agents: [],
+    activity: '', firstMove: '', firstMoveLessonId: '', firstMoveLessonTitle: '',
+    agent: '', transport: 'pty', energy: 5, agents: [],
     sessionActive: false, liveActivity: '', confirmingEnd: false,
     endError: '', // R-70: set when /api/session/end fails; keeps the dialog open
     starting: false, startError: '',
@@ -3196,6 +3232,16 @@ function bodyDoubleSession() {
       window.addEventListener('body-double-request', (event) => {
         const detail = (event && event.detail) || {};
         if (detail.activity) this.activity = String(detail.activity);
+        /* Issue #30: the proposal's one passive first move, shown beneath the
+           activity so the session does not open on a blank page. Cleared when
+           a hand-off carries none, so a stale move never outlives its plan. */
+        this.firstMove = detail.firstMove ? String(detail.firstMove) : '';
+        /* Rubric 3c (d2): the lesson the move names, when the engine resolved
+           one, so the picker can open it beside the view. Cleared with the
+           move, for the same reason. */
+        this.firstMoveLessonId = detail.firstMoveLessonId ? String(detail.firstMoveLessonId) : '';
+        this.firstMoveLessonTitle = detail.firstMoveLessonTitle
+          ? String(detail.firstMoveLessonTitle) : '';
         const bands = { low: 3, medium: 5, high: 8 };
         if (detail.energy && bands[detail.energy]) this.energy = bands[detail.energy];
       });
@@ -3228,6 +3274,17 @@ function bodyDoubleSession() {
       this._initDone = true;
     },

+    /* Rubric 3c (d2), issue #30: "Open X" actually opens X. Asks the Course
+       Explorer aside to open the lesson the first move names, beside this view —
+       the learner stays on the picker (or in the session) with the lesson next
+       to it. Nothing to open when the engine resolved no lesson. */
+    openFirstMoveLesson() {
+      if (!this.firstMoveLessonId) return;
+      window.dispatchEvent(new CustomEvent('explorer-open-lesson', {
+        detail: { lessonId: this.firstMoveLessonId, title: this.firstMoveLessonTitle },
+      }));
+    },
+
     async refreshFocus() {
       try {
         const res = await fetch('/api/body-double/focus');
@@ -3630,6 +3687,14 @@ function bodyDoubleSession() {
       this.conflictSession = null;
       this.startError = '';
       this.activity = '';
+      /* Rubric 3c (d3): the first move arrived beside the activity in the one
+         Today hand-off and leaves with it. Now that the live strip shows the
+         move for the whole session, a stale one beneath the NEXT, unrelated
+         activity would be a confidently wrong proposal on the one surface that
+         is always on screen. */
+      this.firstMove = '';
+      this.firstMoveLessonId = '';
+      this.firstMoveLessonTitle = '';
       this.confirmingEnd = false;
       /* Deliberately NOT clearing the note draft: losing a half-written note
          because the session ended is exactly the kind of loss this view exists
```

## 6. Tests — every test the range adds or changes, by name (bodies on request: say UNVERIFIED)

### `packages/studyloop/tests/js/session-timer.test.js`

```
test('today-resume carries the warm-up and its lesson beside the topic; a hand-off without one clears it'
test('openFirstMoveLesson asks the Course Explorer to open the resolved lesson; nothing to open, nothing dispatched'
test('ending the session clears the move with the topic it arrived beside'
test('a planning launch carries no warm-up'
```

### `packages/studyloop/tests/js/today-panel-plan.test.js`

```
test('firstMoveNote: the engine\u2019s first move verbatim, nothing when the payload carries none'
test('starting a body-double primary hands the first move to the Body Double view beside the plan'
test('firstMoveLesson: the resolved lesson (id + title) from the payload, null when none resolved'
test('openFirstMoveLesson: asks the Course Explorer to open the lesson beside the view, and does not navigate'
test('starting a body-double primary hands the resolved lesson to the Body Double view beside the move'
test('starting a study-session primary hands its topic, energy and warm-up to the Study view'
test('a study-session primary without a move hands its topic and energy only'
test('starting a flashcards primary still hands nothing and navigates'
```

### `packages/studyloop/tests/test_docs_plan_integration_contract.py`

```
def test_study_plans_doc_describes_the_first_move_in_the_engine_terms
def test_web_ui_guide_body_double_names_the_handed_over_first_move
def test_web_ui_guide_says_the_named_lesson_opens_beside_the_view
def test_web_ui_guide_says_the_move_survives_the_start
def test_docs_say_an_active_plan_related_action_carries_a_warm_up_first_move
def test_web_ui_guide_says_the_warm_up_follows_start_into_the_study_session
```

### `packages/studyloop/tests/test_now_plan_guidance.py`

```
def test_body_double_carries_one_passive_first_move_on_the_deferred_milestone(
def test_body_double_first_move_names_the_lesson_the_content_index_resolves(
def test_body_double_first_move_shows_the_course_so_a_lexical_match_is_judgeable(
def test_body_double_first_move_never_names_a_lesson_from_the_title_or_the_topic(
def test_body_double_first_move_says_when_the_milestone_names_no_concept(
def test_body_double_first_move_names_every_unmatched_concept
def test_resolve_lesson_asks_one_query_per_concept_in_order_and_returns_the_first_hit(
def test_body_double_first_move_survives_a_broken_content_index
def test_cli_now_prints_the_first_move_beneath_the_sit_with_door
def test_a_plan_related_repair_at_medium_energy_carries_a_warm_up_on_its_own_material(
def test_a_plan_milestone_primary_carries_a_warm_up_on_the_milestone_s_concepts(
def test_the_warm_up_names_the_material_and_says_why_when_nothing_is_indexed(
def test_no_warm_up_on_recall_or_without_a_plan_or_off_the_plan
def test_a_plan_related_active_item_that_is_neither_repair_nor_milestone_ramps_by_concept(
def test_cli_now_prints_the_warm_up_beneath_the_evidence_door_at_medium_energy(
```

### `packages/studyloop/tests/test_web_body_double_first_move.py`

```
def test_body_double_view_takes_the_first_move_from_the_today_hand_off
def test_body_double_picker_shows_the_first_move_beside_the_activity
def test_today_card_renders_the_first_move_as_its_own_line
def test_course_explorer_opens_a_lesson_by_id_on_request
def test_body_double_view_takes_the_resolved_lesson_from_the_hand_off
def test_body_double_picker_offers_to_open_the_resolved_lesson
def test_today_card_offers_to_open_the_resolved_lesson
def test_body_double_live_strip_carries_the_first_move_beneath_the_activity
def test_body_double_live_strip_offers_to_open_the_resolved_lesson
def test_the_move_leaves_with_the_activity_when_the_session_ends
```

### `packages/studyloop/tests/test_web_study_first_move.py`

```
def test_study_picker_shows_the_first_move_beneath_the_topic
def test_study_picker_offers_to_open_the_resolved_lesson
def test_study_live_layout_carries_the_first_move_beneath_the_status_bar
```


## 7. Verification on `c83ebd75` (measured by the coordinator, not asserted)

- Python: first-move pins (Body Double + Study) + docs contract + `test_now_plan_guidance` + `test_learning_decision`
  + `test_web_now` + golden: 134/134. Web unit suites that read the markup (`test_web_app`, `test_web_session`,
  `test_web_live_session_banner`, `test_web_retrieval_chip`, `test_lane_ownership`, `test_e2e_coverage_gate`,
  `test_web_dev_engines`): 144 passed, 1 skipped, 5 deselected. ruff, ruff format, pyright: clean.
- JS (`node --test packages/studyloop/tests/js/*.test.js`): 160/160; `node --check` on both edited component scripts.
- `mkdocs build --strict`: clean. `openspec validate body-double-first-move`: valid (two requirements, fifteen
  scenarios). Golden `ec451ce8` byte-identical at every commit.
- CI on the branch: 15/15 on head `ef3ad8f6` ((d3)); heads `b64afd02` ((e1)) and `c83ebd75` ((e2)) were still
  running when this brief was written — UNVERIFIED here; the coordinator reads them before merge.
- Every RED commit was run and seen failing for its stated reason before its GREEN. Three RED expectations were
  corrected at GREEN and recorded in the GREEN commit: the medium payload's key shape (`dacbea87`); the review-7 F7
  test's "an ordinary action dispatches nothing" and the async harness restoring stubs too early (`25886ff0`).
- Read cost of the lesson lookup on the live host: 861 ms cold on a process's first query (the explorer's own index
  refresh), 45–58 ms warm per concept; paid once per `now` whose primary carries a move; a `now` with no active
  plan pays nothing.

## 8. Deliverables — numbered H2 sections, in this order

1. **Verdict:** ACCEPT / ACCEPT-WITH-CORRECTIONS / REJECT for this tree as the merge to `main` for 0.5.1 — with the
   single sentence that decides it.
2. **Findings**, each with severity 🔴 defect (wrong behaviour or a bug), 🟡 must-fix-before-merge (design/contract
   violation, missing test, unsafe pattern), 🔵 should-fix, 💡 note. For each: file:line or function, what is wrong,
   why it matters, the concrete fix, and the RED test that would pin it (name it). Check specifically:
   - (a) **One sentence builder, two moves.** `_first_move_sentence(concepts, material, tail)` serves the sit-with
     move (`nothing more`) and the warm-up (`then start …`). Is the shared no-lesson clause `— this milestone names
     no concept to look up yet` ever reachable for a non-milestone warm-up (a repair always has a concept)? Is the
     `— no indexed lesson mentions “<concept>” yet` clause right beside `then start the repair` (the learner is
     told to open "material" the index does not hold, then start)? Would you word the no-lesson warm-up differently?
   - (b) **`_warm_up` scope and tails.** Primary only; never body double; requires `plan_refs`; `action_type` in
     {hands-on, conversation, teachback}; tails tested in this order: repair (`energy_demand` in metadata) →
     eligible-milestone ref → generic `then start on “<concept>”`. Cases to probe: a repair whose concept IS the
     eligible next milestone's concept (repair tail wins — right?); a `teachback` on a `learning` row (generic tail —
     is a warm-up before a teach-back sound?); a plan-related `hands-on` PRACTICE task (generic tail — does
     "then start on X" read right?); `visual`/`audio` excluded — right?; HIGH energy also carries the warm-up
     (decided, not asked) — does a 10/10 learner want a ramp beneath the repair, or is that patronising?
   - (c) **Recall exclusion.** Reading the lesson before a retrieval test defeats the test — is that always true
     (a `recall` on a plan concept the learner has not seen for weeks)? Should the exclusion be by action type or by
     the due-review kind (`_review_type_for`)?
   - (d) **The Start → hand-off changes behaviour for EVERY study action from the Today card**, not only ones with a
     move: the picker now opens with the concept filled in (it opened blank before — a pre-existing gap the
     coordinator folded in). Is that folding right, or should it have been its own change with its own owner
     decision? Any e2e in `packages/studyloop/tests/test_web_smoke_browser.py` or `tests/e2e/` that this could
     break (the coordinator ran none of the browser suites; CI does)? `today-resume`'s listener now OVERWRITES the
     three first-move fields on every hand-off (so resume / parked clear a stale move): any hand-off path that should
     NOT clear them? `startPlanning()` clears them; `endConflictSession` / `reattachConflictSession` do not — right?
   - (e) **Today card gate removal.** `firstMoveNote`/`firstMoveLesson` now read the field for ANY recommendation.
     The card renders `firstMoveNote(plan?.primary)` only, so alternates never show one — confirm from the markup
     in §4. Is there any consumer that showed the reason AND would now double-render? (d1) removed the sentence from
     the reason — is the "(d1): the move is not in the reason" assertion in the (e1) test strong enough?
   - (f) **State lifetimes.** Body Double: `confirmEnd()` clears the three fields with `activity`; the picker's
     `activity` input can be edited by the learner while the move stays — acceptable? Study: `confirmEndSession()`
     clears them with `topicInput`; the learner can retype the topic in the picker while the move stays beneath it —
     acceptable, or should an `@input` on `#topic-input` clear the move? A reattached foreign/own session shows no
     move (fields empty) — right?
   - (g) **Markup and layout.** `.bd-live-strip` is `flex-wrap`; `#bd-live-first-move` takes `flex-basis: 100%` —
     any interaction with `#bd-end-confirm` (also inside the strip)? Study: `#study-live-first-move` is a sibling
     AFTER `.session-status-bar` in a `flex-direction: column` layout that is `position: absolute; inset: 0` — does
     the new row steal height from the terminal area, and is the terminal's `flex: 1` (verify) enough? Any global
     selector (`.picker-hint`, `.bulk-btn`) that the new elements could shadow for an existing test (the repo has a
     recorded incident of a hidden mount matching a global `.xterm-mount` selector)?
   - (h) **Spec delta vs code.** Two requirements. Does every SHALL match the code as diffed — the three no-lesson
     shapes, the (d1) "reason SHALL NOT carry the sentence", the (e2) sentence about Start handing `concept` as
     topic, the "a planning launch SHALL clear it"? Any scenario the tests do not actually pin?
   - (i) **Tests.** Which assertions pin only via substring such that a wording change silently passes? Are the
     static markup pins over-fitted to attribute ORDER inside a tag? The `_live_strip` slicer ends at a comment
     string (`<!-- x-if, NOT x-show: this console`) — fragile? The JS harness for the Study view stubs `window`,
     `fetch`, `Alpine`, `CustomEvent` globally with save/restore — sound under `node --test`'s concurrency defaults?
   - (j) **The record.** The receipt (§0 summary) carries an explicit correction of a false coordinator claim
     ((e1) "renderers needed no change"). Is anything ELSE in this brief's claims unsupported by the diffs?
   - (k) **The frozen-clock leak** (§0 facts): should it block this merge, or is "recorded for its own change"
     acceptable? Name the RED that would pin the fix (`history/progress.py` reading an injectable clock).
3. **Refutations:** any claim in §0–§7 you believe is false or not established by the brief — say which and why.
4. **Gate:** the shortest list of corrections that would turn your verdict into ACCEPT, each with its RED test name;
   or "none".
