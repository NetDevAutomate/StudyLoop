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
