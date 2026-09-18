# Proposal: an age-aware nudge and a retire/snooze door for an overdue item (D-E)

**Status:** written proposal, no code (plan-integration follow-on item 6, T6.4). Becomes a
`ready-for-agent` issue at the push step (HANDOFF §3 item 7, step 4). Written 2026-09-18 against
`main` at `a5b9f903`; every code fact below was read from that tree.

## The owner's decision, verbatim

> **D-E** | Scenario 2 note: an overdue item **unrelated** to the plan must not sit as an alternate
> indefinitely. Fact: due score already grows `+1/day` (cap +30), so it overtakes the +12 bias in
> ~2 weeks; missing are an **age-aware nudge line** and a **retire/snooze** action for a due card (only
> backlog topics can be `resolved` today).
>
> — `HANDOFF-2026-09-16.md` §2, owner, 2026-09-16

The evidence it names: rubric row 2 (`receipts/now-rubric-2026-09-16.md`), owner's verdict **yes** —
clear the overdue review first — with the note: *"an overdue item unrelated to the plan must not sit as
an alternate indefinitely — propose it explicitly (age-aware nudge) or let the learner retire it."*

## What the engine and the store do today

- **A due item is a `study_progress` row whose `last_seen` is old enough.** `history/progress.py`
  computes `days_ago` from `last_seen` and marks the row due when it reaches an interval in
  `REVIEW_INTERVALS` — 1, 3, 7, 14, 30 days, each with a review type ("5-min recall quiz" …
  "Teach-back session"); a `struggling` row is always due as "Guided repair + tiny practice". There is
  **no `next_review` column** and no state that says "not due": a `mastered` row keeps coming back on
  the same intervals, and the only thing that moves `last_seen` is studying it again
  (`record_progress`). A row therefore stays due — and stays a `now` candidate — until it is studied
  or deleted.
- **The score arithmetic the decision cites is right.** `learning/decision.py` scores a due candidate
  `100 + min(days_ago, 30)` (+35 if `struggling`, +15 if `learning`). A plan-related candidate adds
  `PLAN_RELATED_BIAS = 12` (rule 5). So an unrelated due item at *d* days beats a plan-related one at
  *d′* days once `d > d′ + 12`: roughly two weeks of sitting as an alternate, then it wins the primary
  on age alone — silently. The learner sees it move up; nothing tells them why, and nothing offers a
  way to say "I have moved on from this".
- **`resolved` exists only for parked topics.** `record_topic_progress(confidence="resolved")` (MCP)
  calls `parking.resolve_parked_topic(topic_id)` — a *backlog* row, not a `study_progress` row. The
  Today card and CLI `now` have no control on a due item at all.

## The proposal

Two additions, both small, both on the existing candidate — no new ranking rule.

### 1. An age-aware nudge line

When an eligible due candidate is **unrelated to every matchable plan** and has been due long enough
to have overtaken the plan bias — i.e. `days_ago ≥ threshold`, with the threshold **derived from the
constants**, not a second number: the smallest `days_ago` at which `min(days_ago, 30) ≥ PLAN_RELATED_BIAS`
plus the plan-related candidate's own age — the candidate carries a `nudge` line that says so in plain
words: *"Overdue 16 days and unrelated to your plan — do it, or retire it: `studyloop review retire
<topic> <concept>`."* Rendered where the completion review's evidence lines are rendered today (CLI
`now` beneath the action, Today card beside it, MCP payload as an additive key). The line is a fact
about age, not a proposal to rank differently.

### 2. A retire/snooze door for a due item

A `study_progress` row gains one of two learner-issued states, through the seam every surface uses:

| Door | Meaning | Mechanism | Undo |
|---|---|---|---|
| **retire** | "I am done with this concept for now" | a `retired_at` timestamp on the row (or a `confidence` value the due predicate excludes — decided at RED with the migration); the row is no longer due, keeps its history, and disappears from every consumer of `spaced_repetition_due` — `now` (CLI, Today, MCP `get_next_action`), recap, `studyloop review`, and the plan evaluation's due count | studying it again (`record_progress`) clears the state |
| **snooze** | "not this week" | a `snoozed_until` date; the row is not due before it and returns to the normal intervals after | expiry, or an explicit un-snooze |

Exposed the same way the plan lifecycle is: a CLI verb (`studyloop review retire|snooze`), a Today-card
control on the due item, and one MCP tool beside `record_study_progress` — the mirror of
`record_topic_progress(confidence="resolved")` for cards that the decision asks for. The store writes
one row; retire is never inferred from age (the decision says *let the learner* retire it).

Design constraints:

1. **Learner-issued only.** Nothing retires or snoozes on the learner's behalf — the RSD-safe framing
   the project keeps: the nudge proposes, the learner decides (same shape as item 4's consensual
   close).
2. **History kept.** A retired row is excluded from the due set, not deleted; `get_study_history` and
   the plan evaluation's `unverified_milestones` still see it.
3. **Plan-aware, not plan-bound.** The nudge fires only for items unrelated to every matchable plan;
   a plan-related overdue item is the plan's business (item 4's closing review already counts it).
4. **Golden unchanged.** The no-plan golden holds a `source=starter` primary with no due items, so it
   is byte-identical by construction; the nudge is an additive key on a due candidate.
5. **The threshold is derived, not a new constant** — so when D-D replaces `PLAN_RELATED_BIAS` with a
   derived bias, the nudge moves with it.

## Out of scope

- Any change to `REVIEW_INTERVALS` or to how `days_ago` is computed.
- Reranking. The overtaking-on-age behaviour is correct (row 2: clear the overdue review first); what
  is missing is the *explanation* and the *exit*, not a different order.
- Flashcard/quiz `card_reviews` — a different store with its own scheduler (a simplified SM-2 in
  `review_db.py`, read by `get_due_cards` through `review_service.due_cards`); a retire door for those
  is a separate ticket if wanted.

## Acceptance (for the issue)

- RED: a due unrelated item past the derived threshold carries the nudge line on CLI, Today and MCP;
  a plan-related one does not; one below the threshold does not.
- RED: `retire` removes the row from the due set and from `now` candidates, keeps its history row,
  and `record_progress` on the same concept clears it; `snooze` excludes it until the date and not
  after.
- The migration is in `agent_session_tools.migrations` and the clean-rebuild closure classifies the
  new column/state (the 2026-09-12 rebuild caught two tables the migrations did not create; do not
  repeat that).
- Golden `now_plan_no_active.json` byte-identical; `test_docs_plan_integration_contract.py` green
  with the doc sentence added to `docs/study-plans.md` "Plan-aware now" and `docs/cli-reference.md`.
- A D-16 rubric row: row 2's world advanced 16 days, the owner asked whether the nudge line is one
  they would act on.

## References

`HANDOFF-2026-09-16.md` §2 D-E; `receipts/now-rubric-2026-09-16.md` row 2; `studyloop/history/progress.py`
(`REVIEW_INTERVALS`, `_review_type_for`, `_progress_review_due`, `spaced_repetition_due`,
`record_progress`); `studyloop/learning/decision.py` (due scoring `100 + min(days_ago, 30)`,
`PLAN_RELATED_BIAS`); `studyloop/mcp/tools.py` (`record_topic_progress`, `resolve_parked_topic`);
`agent_session_tools/migrations.py` (`study_progress` columns: `id, topic, concept, confidence,
first_seen, last_seen, session_count, notes, created_at, updated_at`).
