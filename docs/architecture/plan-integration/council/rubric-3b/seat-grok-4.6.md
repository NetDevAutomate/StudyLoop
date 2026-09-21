# 1. Recommendations table

| Reading | Recommend to owner | One sentence |
|---|---|---|
| **(a)** | **YES** | Sit with the plan; do not open a live struggle as hands-on work at 3/10. |
| **(b)** | **YES** | A due recall is a familiar win with a real spacing cost; the sit-with belongs underneath it, not instead of it. |
| **(c)** | **YES** | Recovered teach-back is review, not repair; demand 0 matches a low-energy day. |
| **(d)** | **EITHER** | Do not restore the hands-on repair; whether you would actually tap the generic starter (vs a same-concept recall, vs closing the laptop) is the open call. |
| **(e)** | **YES** | An unrelated hands-on drill is the least-bad task the finding told us not to lead with; sit-with primary, drill alternate. |

# 2. Basis, per reading

## (a)

**(i)** Framework: *Emotional Regulation → Adaptive Responses* maps flat → body doubling and overwhelmed → review only; *Shutdown Protocol* and *Async Body Doubling* are presence with no teaching and no repair. *RSD / Naming Struggle Topics* forbids leading with a failure. *Demand Avoidance → Demand-Light Mode* treats a repair prompt as a demand. External: ADHD task-initiation cost is highest on aversive, uncertain work (Barkley; clinical consensus, moderate-strong); exposing a depleted learner to a live error is the RSD pattern the project's own framework treats as axiomatic (the empirical RSD literature is thin — treat this as a project constraint, not settled science). Body-doubling evidence itself is weak-to-moderate (community + OT parallel-work practice); it is used here because the framework and ADR-0001/0003 already committed to it, not because the RCTs are good.

**(ii)** Strongest opposite: unfinished-business / monotropic rumination. An ADHD brain often pays more for leaving the stuck thing stuck than for a short repair attempt; "sit with the plan, no repair" can read as being babied and *itself* trip RSD ("the system thinks I can't handle this"). The *Dopamine-Driven Learning Loop* section also says the struggle is the learning mechanism — some learners will want the fix.

**(iii)** Falsifier: over a few weeks of low-energy mornings you skip the sit-with and start the repair by hand, and you log that the card felt like a block rather than a relief. If that is the modal behaviour, (a) is wrong for you.

## (b)

**(i)** Spacing and retrieval (Roediger & Karpicke; Cepeda et al.) are the strongest evidence in this whole row: a due item has a real forgetting-curve cost and is a familiar win. Framework: *anxious → Start with a familiar win. Review mastered concept first.* Design rule is correct that due recall is never deferred. The proposal-not-a-filter rule keeps the sit-with visible without stealing the primary.

**(ii)** Strongest opposite: low-energy task-switch cost. The engine already subtracts 28 for a topic switch; jumping to unrelated Python while a live SQL struggle sits in `energy_deferred_repairs` can produce rumination, and *Naming Struggle Topics* says a non-sequitur next to a failure is the worst outcome. A learner already "in" SQL Windows may pay less to sit with that plan than to context-switch.

**(iii)** Falsifier: you consistently take the sit-with alternate and leave the due recall, or you notice the unused due item decaying and do not care. If the switch itself is what dumps the day, flip (b) and promote the proposal when the only real candidate is off-plan.

## (c)

**(i)** Same spacing/retrieval evidence as (b), plus the finding's own clause: a recovered item stays eligible as gentle review. Framework: *overwhelmed → review only*; *Win Surfacing* is RSD-protective. Demand `learning → low → 0` vs capability 3 is the one place the three-class demand model has a clean, observable effect.

**(ii)** Strongest opposite: teach-back is still a performance. Generating an explanation of a concept that was recently a struggle is closer to a test than to a familiar win, and *RSD in Socratic Context* warns that demonstration-of-competence prompts read as judgment. A silent recall would be the genuinely gentle move.

**(iii)** Falsifier: you skip or bounce off the teach-back on recovered concepts specifically at low energy, but you will do a plain recall of the same card. If that split shows up, the action *type* is wrong, not the eligibility.

## (d)

**(i)** The finding was about the day, not the plan: hands-on repair of a live struggle at 3/10 is the same RSD/initiation risk with or without `sql-windows`. That is why deferral is plan-independent (design §5 decision 1; I agree with the Q1 arbitration). What the evidence does *not* establish is that "one tiny recall loop" is a thing you will do. Framework *Pre-Study State Check* / *familiar win* wants a known concept; the starter is a nothing-burger. Q3 (same-concept gentle recall) is the option that actually follows from retrieval-practice evidence and from *anxious → familiar win*.

**(ii)** Strongest opposite, in two flavours. Restore the repair: a senior engineer with no plan and one stuck concept will not tap a generic starter — they will attempt the fix or close the laptop, and the starter reads as patronising. Or take Q3: keep the deferral, but offer a low-demand recall of `decorators` so the floor is still *their* work.

**(iii)** Falsifier for "keep the starter": you never choose it; the card is where sessions go to die. Falsifier for "restore the repair": you do the repair on those days and do not report a confidence dip. Falsifier for Q3: you accept a same-concept recall and come back the next day still willing. That last one is the observation that should decide the follow-on.

## (e)

**(i)** This is the finding's "instead of the least-bad task" clause, implemented. Framework *flat → body doubling*; *Low-Energy Sessions* asks whether the session should continue at all. A penalised unrelated hands-on (48 − 14 = 34) is exactly the class of work D-F objected to. I agree with the F2 arbitration: do not add a post-scoring floor that puts the drill back on top — that undoes the finding. The proposal is not a filter; the drill remains the alternate.

**(ii)** Strongest opposite: a bounded list-comprehension drill is a completable tiny win; "sit with SQL Windows, no new material, no repair" is structured nothing. ADHD often prefers a small finished artefact to open-ended presence, and the drill is off the struggle topic so it does not poke the live failure. Astra's post-scoring floor is this argument in code.

**(iii)** Falsifier: you consistently pick the drill alternate, or you start avoiding Today entirely when the primary is a sit-with and a real small task is sitting underneath. If the sit-with primary is what makes you close the app, flip (e).

# 3. Behavioural checks you would add

Verdict above is about the *action*. Surface is separate.

**(a)** Action is right. Two surface defects.

1. The reason names the struggle concept (`repair of "window function"`) with no adjacent strength. That is a direct hit on *Naming Struggle Topics* ("Never name a struggle without an adjacent strength"; "No structural connection, no mention" is about a different failure mode, but "lead with failure" is this sentence). Change the reason to name the deferred *milestone* and say a repair is waiting for more energy, without the concept label. Pin in `test_now_plan_guidance.py`: assert the (a) reason does not contain the struggle concept string. Done when `cli/_now.py`, `learning/recap.py`, and `today-panel.js` deferred-repair lines obey the same rule.
2. The door must actually be demand-light. Amendment 3 already says `web/routes/body_double.py` is the read-only focus reader and the door is `studyloop study "<title>" --mode co-study` / Body Double view with `origin=body-double`. This brief does **not** show that the session protocol then runs *Async Body Doubling* (presence, no questions, no repair) rather than the normal Socratic loop, which will see the live struggle and start teaching. If it does, (a) and (e) are false advertising. Add a protocol test: a session started from `source=body_double` does not inject deferred struggles as teaching targets and does not open on a question. Done criterion: first tutor turn matches the async script in the framework, not a repair prompt.

**(b)** Action is right. Check that the *primary* reason for `decorators` stays silent on the SQL struggle (*No structural connection, no mention*). If `decision.py` copies the deferred list into every candidate's reason, strip it for off-plan primaries. Existing alternate placement is already pinned by `test_preserves_one_plan_backed_action_when_energy_allows`.

**(c)** Action is right. `teachback` vs `recall` is a surface preference, not a verdict-flipper, and changing collector action types is out of item-5 scope. Do not add a test that forces `action_type=recall` unless (c)'s falsifier fires in real use.

**(d)** Action (not the repair) is right; the starter as the thing you are offered is the weak surface. If you want Q3, synthesise a same-concept `recall` (not `hands-on`) of `decorators`, `energy_demand=low`, score above the starter (28) and below any real due recall, reason naming the deferral without "no learning evidence found yet". Pin: `test_no_plan_deferred_repair_offers_same_concept_recall` in `test_now_plan_guidance.py`. If you keep the starter, decision 3's reason rewrite is already the right surface; do not touch the golden no-struggle world. I would not restore the repair and I would not gate deferral on a plan.

**(e)** Action is right. Same naming-of-struggle fix as (a). Ordering is already pinned by `test_body_double_ordering_after_adjustments_follows_the_energy_rule`; do not raise `BODY_DOUBLE_BASE_SCORE` and do not add Astra's post-scoring floor. The drill staying visible as an alternate is load-bearing — hiding it would turn the proposal into a filter.

# 4. Missing reading

**Same-concept due recall of a live struggle, low energy.** Fixture: row 3's world plus a due `study_progress` recall whose concept is `window function` (the live struggle). Design says due recall is never deferred, even on a struggling concept, so the primary becomes a retrieval of the thing they are currently failing. Question: do you want that recall as primary (spacing wins), or should a due recall of a live-struggle concept inherit the repair's demand and defer with it? (a)–(e) never cross the two sources on one concept; that is the rule collision that will actually fire in production.

# 5. Refutations

- **§2 rationale still says** `30 + 12 = 42 < any real candidate`. False on this tree. 42 > 34 (hands-on after the −14). Design §5 decision 4 corrected the claim; the rubric rationale did not. The behaviour is defensible; that sentence is not.
- **§0 still cites `web/routes/body_double.py` as the feature that implements the sit-with.** False. Amendment 3: that route is `GET /api/body-double/focus`. The door is `studyloop study "<title>" --mode co-study` and the Body Double view session start.
- **"A session with no new material and no repair" is not established by this brief.** It is a product assertion about what `--mode co-study` / `origin=body-double` does. No test in §3's GREEN list checks the session protocol. Until that test exists, (a) and (e) recommend a door whose payload we have not seen.
- **`medium` and `high` demand are not two behaviours.** `ENERGY_CAPABILITY` has 3, 6, 10; `ENERGY_DEMAND_CAPABILITY` has 6 and 4. Nothing sits between 3 and 6, so at every declared energy both classes take the same branch. Keeping the label as explanatory state is fine; calling them demand *classes* with distinct effects is not, today.
- **RSD is not a strong empirical construct.** Thin literature, not in DSM. It is a project axiom because *RSD / Imposter Syndrome Management* says so. Do not let "compounds the struggle (RSD)" do more scientific work than it can carry. The stronger grounded reasons for (a)/(d)/(e) are task-initiation cost, demand avoidance, and not spending the last spoons on the hardest card.

I do not disagree with the Q1 arbitration (do not gate deferral on a plan). I do think Q3 should have been taken, or at least presented as the default floor, rather than parked; that is why (d) is EITHER and not YES.

# 6. One paragraph for the owner

These five readings decide that a low-energy day is no longer "do the least-bad piece of real work." Live repair is treated like new work you do not have the budget for; recovered review and due recall stay allowed; and when the plan has nothing left that fits, the card offers presence with the plan instead of a penalised drill. That is the system refusing to put your face back in the thing that just hurt, not the system deciding you are incapable of it. If you asked why it will not let you fix the stuck thing today: because fixing it is the expensive card, and on a 3/10 day the expensive card is how a wobble becomes a story about yourself. The repair is still there. It is waiting for a day that can carry it. The open question only you can answer is the no-plan morning — whether a generic tiny loop is something you would actually do, or whether you want a quiet recall of the stuck concept, or whether you would rather the system get out of the way.
