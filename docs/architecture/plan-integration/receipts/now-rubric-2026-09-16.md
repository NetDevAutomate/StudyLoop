# Plan-aware `now` — five-scenario human rubric (D-16) · 2026-09-16

**Status: owner verdicts RECORDED 2026-09-16 (interactive walkthrough with the coordinator).** Scenarios 1, 2 and the primary of 4: yes. Scenario 3: **no** (finding). Scenario 4 completion action: **no as phrased** (finding). Scenario 5: verified. **Row 4b added 2026-09-18** (item 4 / D-G, tree `feat/plan-close`): scenario 4 re-run with the end assessment planted, both proposals recorded as emitted; verdict `PENDING` for the owner — row 4 is kept as the record of the original finding. This receipt was produced unattended
overnight. Every scenario below was *run* on frozen fixtures and the primary
and its rationale are recorded exactly as the engine emitted them; the
"would I do the primary?" column is a human judgement that only the owner can
give, so it is left `PENDING` rather than faked. Ranking compliance is proven
by `packages/studyloop/tests/test_now_plan_guidance.py`; this receipt is the
separate, cheaper pre-ship check D-16 asks for, and it proves nothing about
learning (D-16: "plan-aware guidance with tested ranking rules", never "better
learning").

- Tree: `feat/p3-now` at `df33690b` (engine `0f1b3d08`, renderers `df33690b`).
- Golden: `packages/studyloop/tests/golden/now_plan_no_active.json`,
  sha256 `ec451ce8857c8a72e398e3054e3c060cd3b5b13ecb29e29cba3822dc192503c0`,
  captured on the pre-#10 tree (`848f413b`).
- Clock frozen at `2026-09-16T09:30:00+00:00`; empty sessions DB, empty plans
  directory, empty content roots, no topics, no focus (the module's
  `isolate_now_world`). Defaults unless stated: energy `medium` (capability
  6/10), 25 minutes, modality `recall`, interleave `off`.
- Candidates are injected through the collector monkeypatches
  `test_learning_decision.py` uses (`_patch_collectors`), so scores are the
  fixtures' base scores plus today's scoring (+18 modality match on `recall`)
  plus the plan bias (+12) where a candidate is plan-related.

## Scenarios

| # | Scenario (D-16 list) | Frozen fixture | Primary emitted | Engine rationale (rule) | Owner verdict: "would I do the primary?" |
|---|---|---|---|---|---|
| 1 | Matching due | Active plan `sql-windows` ("SQL Windows", topics `[sql]`, next milestone 0 concepts `[window function]`). Due items: `decorators`/python base 102, `window function`/sql base 100. | **`window function`** (sql, recall, score 130, `plan_refs=[(sql-windows, 0)]`); alternate `decorators` (120, no refs). | Rule 5: both are due items two points apart — one urgency class — so the plan-related one takes the +12 bias and wins; the unrelated due item is *kept* as an alternate (bias, not filter). Rule 7 names the milestone the action advances. | **yes** — owner, 2026-09-16: "window function is the logical step before decorating it" (a prerequisite-order argument; see F2 follow-on). |
| 2 | Urgent-unrelated wins | Same plan. One due item: `decorators`/python, base 100 (an overdue spaced-repetition review). Nothing represents milestone 0. | **`decorators`** (118, no refs); alternate `window function` (60, `source=study_plan:sql-windows:0`, `plan_refs=[(sql-windows, 0)]`, reason "Next milestone 1/1 of plan 'SQL Windows': Window basics"). | Rule 5: the unrelated candidate is in a more urgent class (due review) and wins outright — the bias cannot lift new-milestone work over it. Rule 6: the plan's next milestone was unrepresented, so it was synthesised at base 48 + bias 12 = 60 and appears as the plan-backed alternate (rule 8 satisfied without any swap). | **yes** — owner, 2026-09-16: clear the overdue review first. Note for follow-on: an overdue item *unrelated* to the plan must not sit as an alternate indefinitely — propose it explicitly (age-aware nudge) or let the learner retire it. |
| 3 | Energy-deferred | Plan `sql-windows` with `energy_floor: 5`; milestone 0 `Window basics` **done** (concepts `[window function]`), milestone 1 `Frames` (concepts `[window frame]`). One struggle-repair item `window function`/sql, `hands-on`, base 82. **Energy `low`** (capability 3/10). | **`window function`** (hands-on, score 80, `plan_refs=[(sql-windows, None)]`); no alternates; `energy_deferred=[(sql-windows, milestone 1, floor 5, capability 3)]`; JSON gains `energy_deferred`. | Rule 3: capability 3 < floor 5, so the *new* milestone (Frames) is deferred and named, not synthesised; the plan-related repair on a finished milestone's concept stays eligible and keeps its ref (`None`: plan-related repair, not the next milestone). Score = 82 + 12 bias − 14 (hands-on at low energy). | **no** — owner, 2026-09-16: a struggle-repair task has no energy demand of its own; recommending hands-on repair of a *live* struggle on a low-energy day risks compounding the struggle and damaging confidence (RSD). Finding for council: (1) derive a per-item energy demand for repair from struggle recency/teach-back — at low energy a live struggle defers like new work, a recovered one stays eligible as gentle review; (2) when nothing plan-related fits the day's capability, synthesise a body-doubling / open-session candidate (feature exists: ADR-0001/0003, `web/routes/body_double.py`) naming the deferred items, instead of the least-bad task. |
| 4 | Fully-checked | Plan `done-plan` ("Done Plan"), milestones A and B both done. One due item `decorators`/python base 100. | **`decorators`** (118, no refs); `completion_actions=[(done-plan, "Every milestone of 'Done Plan' is checked off — close the plan or extend it with a follow-on mission.")]`; no `study_plan:` candidate anywhere; JSON gains `active_plans` + `completion_actions`. | Rule 9: a fully-checked plan is reported as a completion action and is neither matched (no bias, no refs) nor synthesised. | **primary yes / completion action no as phrased** — owner, 2026-09-16: the completion action must be contextual and consensual. Run the end assessment (`assess(phase="end")`: due reviews, struggles, unverified milestones on the plan's concepts). If outstanding work touches the plan's concepts (or their prerequisites — F2 concept edges), propose *extend* and name the evidence; if clean, propose *close* and ask the learner to agree ("anything you are not comfortable with?"). Status never changes automatically (#7). Natural vehicle: architect with `purpose=planning` and the assessment in the brief (`plan close <id>`, sibling of `plan repair <id>`). Finding for council. |
| 4b | Fully-checked — **re-run after D-G (item 4, 2026-09-18)** | Row 4's fixture (`done-plan`, milestones A `[alpha]` and B `[beta]` both done; one due item `decorators`/python base 100), plus the end assessment's readers planted: **(a)** one due review on plan concept `alpha` (`overdue`) with session mentions backing both concepts; **(b)** no due rows, same mentions. | Primary unchanged in both: **`decorators`** (118, no refs); no `study_plan:` candidate. **(a)** `completion_actions=[(done-plan, due 1 / struggles 0 / unverified 0, proposal **extend**, evidence `["Due review: alpha — overdue"]`)]`, sentence: "Every milestone of 'Done Plan' is checked off, and the closing review proposes extending the plan — 1 due review, 0 struggles and 0 unverified milestones on its concepts. Walk the evidence with the architect: studyloop plan close done-plan." **(b)** counts 0/0/0, proposal **close**, evidence `[]`, sentence: "Every milestone of 'Done Plan' is checked off and the closing review is clean — it proposes closing the plan. Close it with the architect when you agree: studyloop plan close done-plan." No warnings; JSON gains the five keys only inside the entry. | Rule 9 as before for the ranking. The completion action is now the end assessment read as a preview (`assess(phase="end", record=False)`, one call, no write, no status change): `extend` iff any of the three counts on the plan's own concepts is above zero, else `close`; due counts only rows naming a concept (the scheduler's "new topic" row is excluded — owner decision 2026-09-17). `plan close done-plan` launches the architect with the same review as the brief's first section; status moves only when the learner agrees. | **PENDING** — owner: does (a) read as a proposal you would walk, and (b) as a close you would agree to? |
| 5 | No-plan identical | No plan documents at all; no collector candidates. | **`one tiny recall loop`** (python, recall, 28, `source=starter`) — the starter. | D-5: `serialise(plan) == golden` → **byte-identical** (`True` in the run); the JSON key list is exactly the golden's — no additive key is present. | **verified** — owner walkthrough 2026-09-16: nothing to judge; the byte-identical golden is the acceptance. |

## How to re-run

```bash
uv run --group dev pytest packages/studyloop/tests/test_now_plan_guidance.py -q -p no:cacheprovider
```

The five rows correspond to
`test_matching_due_concept_outranks_unrelated_same_urgency`,
`test_unrelated_more_urgent_due_outranks_new_milestone`,
`test_energy_below_floor_defers_new_milestone_keeps_repair`,
`test_fully_checked_active_plan_emits_completion_not_candidate` and
`test_no_active_plans_json_byte_identical_to_golden`; the primaries above are
what those tests assert, printed from a throwaway driver over the same
fixtures. Row 4b corresponds to
`test_completion_action_carries_the_end_assessment_and_proposes_extend_when_concepts_are_due`
(reading a) and `test_completion_action_proposes_close_when_the_assessment_is_clean`
(reading b), printed the same way on 2026-09-18 with the end assessment's
history readers planted through `_plant_evidence`.

## What the owner should do

Read each primary as if it were this morning's `studyloop now` and replace
`PENDING` with `yes` / `no` + one line. A `no` on rows 1–4 is a finding for
council review 3, not a reason to edit the ranking without one. Post-ship
accept/skip logging tagged `plan_backed|not` remains the follow-on ticket
D-16 names; it is not part of #10's DoD.
