# Proposal: a context-derived plan bias (D-D)

**Status:** written proposal, no code (plan-integration follow-on item 6, T6.4). Becomes a
`ready-for-agent` issue at the push step (HANDOFF §3 item 7, step 4). Written 2026-09-18 against
`main` at `a5b9f903`; every code fact below was read from that tree.

## The owner's decision, verbatim

> **D-D** | **F2 → open a ticket, don't park:** a context-derived plan bias (prerequisite edges from the
> concept store via `get_concept_context`, milestone order; per-item energy demand from struggle state)
> — deterministic and rubric-testable. Not an LLM tie-break (unauditable; defeats D-16). Scenario 1's
> "the logical step before" was the first evidence.
>
> — `HANDOFF-2026-09-16.md` §2, owner, 2026-09-16

The evidence it names: rubric row 1 (`receipts/now-rubric-2026-09-16.md`), owner's verdict **yes** with
the line *"window function is the logical step before decorating it"* — a prerequisite-order argument the
engine did not make. The engine ranked the plan-matching due item first because it carried the plan
bias; the owner ranked it first because of what depends on it. Same answer, different reason, and the
reason is the one that generalises.

## What the engine does today (`studyloop/learning/decision.py`)

- **Rule 5, one constant.** `PLAN_RELATED_BIAS = 12`, added to a candidate's score when it carries a
  `plan_ref` or its concept/topic keys intersect a matchable plan's keys. The constant is sized to decide
  a near-tie *inside one urgency class* and to lose to a clearly more-urgent unrelated candidate
  (a struggling repair at +35, an overdue review whose base is `100 + min(days_ago, 30)`): a bias,
  never a filter. Review 3 F2 asked whether `now` should grow explicit urgency classes; the council kept
  the bias and pinned the constant to today's bands.
- **Rule 3, one floor per plan.** `ENERGY_CAPABILITY = {"low": 3, "medium": 6, "high": 10}` is compared
  with the plan's `energy_floor` (1–10); below the floor *new* milestone work is deferred while
  plan-related due recall and struggle repair stay eligible, "because repair is cheaper than encoding".
  Rubric row 3 (owner: **no**) is the counter-example — a live-struggle repair on a low-energy day —
  and is item 5's subject, not this proposal's.
- **Rule 6, milestone order by position.** A synthesised next-milestone candidate is the plan's first
  open milestone, base `MILESTONE_BASE_SCORE = 48` plus a target-urgency bonus. Milestone order is the
  document's order; nothing reads what a milestone's concepts require.
- **What the concept store already knows.** `learning/mastery.py::list_dependencies(topic)` returns
  edges with `source_concept`, `target_concept`, `relation_type`; `weak_links_for_topic` already
  consumes `relation_type == "prerequisite"` to name struggling concepts that block downstream ones.
  `get_concept_context` (MCP) returns `mastery_graph_json`'s `edges` for a topic, with the same fields,
  capped at 32 KiB and explicit that omitted edges cannot support a claim that no alternative exists.

So the ingredients exist and are already read for another purpose; what is missing is a rule that turns
them into a ranking signal for `now`.

## The proposal

Replace the single constant with a **derived bias** computed from three deterministic inputs, each a
rule with its own rubric row. The total stays bounded so the "bias, never a filter" invariant holds:
a clearly more-urgent unrelated candidate must still win.

| Rule | Input | Signal | Bound |
|---|---|---|---|
| 5a — plan relevance (today's rule 5) | plan refs / key intersection | the existing `+12` | as today |
| 5b — prerequisite order | `list_dependencies(topic)` edges with `relation_type == "prerequisite"` | a candidate whose concept is a **prerequisite of an open milestone's concept** in a matchable plan gains a small bonus; a candidate whose concept **depends on** a concept the learner is `struggling` with loses the same amount ("the logical step before" comes first) | ± a value below the urgency-class gap, pinned like `PLAN_RELATED_BIAS` |
| 5c — per-item energy demand | struggle state (`confidence`, `last_teachback_score`) and action type | a **demand** per candidate (repair of a live struggle is high demand; a recall of a `learning` concept is low) compared with `ENERGY_CAPABILITY[energy]`, so rule 3's floor stops being the plan's only energy fact | shared with item 5 (D-F); this proposal takes item 5's definition when it lands rather than inventing a second |

Design constraints, from the decision:

1. **Deterministic.** Every input is a stored fact (an edge, a confidence, a score); the bias for a
   fixed world is a pure function. No model call anywhere in ranking — an LLM tie-break is
   unauditable and defeats the D-16 rubric, which asks a human "would you do the primary?" and needs
   the answer to follow from stated rules.
2. **Rubric-testable.** Each rule gets a D-16 rubric row with a planted world and an expected primary,
   scored by the owner before it ships: row 1 re-run under 5b should still be **yes** and now for the
   engine's reason; a new row plants a struggling prerequisite and expects the dependent milestone
   *not* to be primary.
3. **Still a bias.** The golden `now_plan_no_active.json` stays byte-identical (no plan → no bias); the
   existing rule-5 pins (`test_matching_due_concept_outranks_unrelated_same_urgency`,
   `test_unrelated_more_urgent_due_outranks_new_milestone`, `test_weak_due_still_beats_overdue_synthesised_milestone`)
   stay green with the derived value in place of the constant.
4. **Partial knowledge is not knowledge.** `get_concept_context` is explicit that omitted edges cannot
   support "no alternative exists"; 5b must treat an absent edge as *no signal*, never as "not a
   prerequisite".
5. **Read once, through the seam.** Edges are read in `_PlanContext.build` beside the plan read, so the
   rule-1 pin (no per-consumer plan reads, no checkpoint-history reads) holds; the concept store is a
   second read, budgeted and measured on the live database before it ships (the item-4 preview read was
   measured at ~320 ms on an 877 MB `sessions.db` and recorded; this must be too).

## Out of scope

- Item 5 (D-F) owns the energy-demand *definition* and the body-doubling floor; this proposal consumes
  it and must not define a second one.
- No change to what a plan document stores. Prerequisite knowledge lives in the concept store; the
  plan keeps naming concepts per milestone.
- No filter, no reordering of urgency classes (review 3 F2 stands).

## Acceptance (for the issue)

- `PLAN_RELATED_BIAS` is replaced by a derived value with a pinned upper bound; the three rule-5 pins
  above and the golden byte-identity stay green unchanged.
- RED tests, one per rule: a prerequisite-of-open-milestone candidate outranks a same-class sibling;
  a candidate dependent on a struggling concept loses to that concept's repair; an absent edge changes
  no score.
- A measured read cost on a real `sessions.db`, recorded beside the constant.
- Rubric rows added and scored by the owner (D-16), row 1 re-run.
- Docs: `docs/study-plans.md` "Plan-aware now" describes the derived bias in the eligibility terms the
  contract test pins.

## References

`HANDOFF-2026-09-16.md` §2 D-D; `receipts/now-rubric-2026-09-16.md` rows 1–3; `council/review-3-arbitration-2026-09-16.md`
F2; `studyloop/learning/decision.py` (`PLAN_RELATED_BIAS`, `ENERGY_CAPABILITY`, `MILESTONE_BASE_SCORE`,
rule 5 application site); `studyloop/learning/mastery.py` (`list_dependencies`, `weak_links_for_topic`,
`agent_concept_context`).
