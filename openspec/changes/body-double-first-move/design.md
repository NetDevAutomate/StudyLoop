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

3. **The lesson lookup is a seam, and a refinement.** `_lesson_title_for` wraps
   the explorer's FTS (`_run_fts_search`, the `search_lessons` MCP path) with a
   lazy import so the learning layer does not import the web layer at load;
   one short query per concept, first title wins; every failure answers `None`.
   The caller guards it again so a replaced seam that raises degrades the same
   way. Cost: one FTS round-trip per concept, only on the body-double path
   (measured below).

4. **Additive carriage.** `metadata["first_move"]`, present only on the body
   double. The `Recommendation` dataclass is unchanged, so the no-plan golden
   (`ec451ce8`) is byte-identical without special-casing; the renderers read the
   field and re-derive nothing, so CLI and card agree by construction.

5. **A proposal, not a requirement.** The reason's lead-in is "A first move, if
   you want one"; the Today card's label repeats it; the Body Double view shows
   the text and says nothing — the co-study persona's silence rule is untouched.

## Read cost

The lookup runs only when a body double is synthesised. Measured 2026-09-21 on
the live host (content base `~/Obsidian/Personal/Study`, explorer FTS index
present) with `decision._lesson_title_for` as shipped: **861 ms cold** — the
explorer's own best-effort index refresh over the vault on the first query of a
process — then **45–58 ms warm per concept** (`("window function",)` →
"Advanced Sql 4H", `("decorators",)` → "Decorators 29M", `("window frame",)` →
`None`). Paid once per `now` that synthesises a body double; a plain `now` pays
nothing. For scale, item 4's completion review costs ~320 ms per fully-checked
plan on the same host.
