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

## Read cost

The lookup runs only when a body double is synthesised. Measured 2026-09-21 on
the live host (content base `~/Obsidian/Personal/Study`, explorer FTS index
present) through the explorer search the seam calls: **861 ms cold** — the
explorer's own best-effort index refresh over the vault on the first query of a
process — then **45–58 ms warm per concept** (`("window function",)` →
"Advanced Sql 4H", `("decorators",)` → "Decorators 29M", `("window frame",)` →
`None`). Paid once per `now` that synthesises a body double; a plain `now` pays
nothing. For scale, item 4's completion review costs ~320 ms per fully-checked
plan on the same host.
