# Rubric row 3b — decision brief for the owner (2026-09-20)

**What this is.** Rubric row 3b asks you six times "would *I* do the primary?" — a question only you can
answer. This brief does not answer it. It gives you, per reading, a recommendation with its basis, the
strongest case for the opposite answer, and what you would observe in real use that should flip the verdict,
so your scoring is "agree or overrule" rather than reconstruction. Three council seats were asked for exactly
that (brief: `council/brief-rubric-3b-2026-09-20.md`; seats: `council/rubric-3b/`), independently, with the
project's own AuDHD framework and the emitted outputs in front of them. Every claim a seat made about the
tree was checked against source before it appears here; the ones that were wrong are listed at the end.

**How to record.** In `receipts/now-rubric-2026-09-16.md`, row 3b's verdict cell: replace `PENDING` with
`yes` / `no` per reading and one line each. Where you adopt a recommendation, say so ("yes — per brief");
where you overrule, one line of why is the finding. A `no` is not a blocker to the 0.5.0 line: the programme's
rule is "archived when *scored*", and a `no` becomes a `ready-for-agent` issue for 0.6.0, as D-D and D-E did.

## The readings, the seats, and the recommendation

| Reading | astra | grok | qwen | Arbiter's recommendation | Ten-second reason |
|---|---|---|---|---|---|
| **(a)** sit with the plan rather than repair the live struggle today | YES | YES | YES | **YES** | Repair of a live struggle at 3/10 is the expensive card; presence with the plan keeps the day non-zero without putting your face back in the thing that just hurt. |
| **(b)** the body-double proposal beneath the unrelated due recall | YES | YES | YES | **YES** | A short, familiar due recall is a real win with a real spacing cost; the sit-with belongs underneath it, not instead of it. |
| **(c)** the gentle teach-back on a `learning` concept at low energy | EITHER | YES | YES | **YES, with one caveat** | Explaining familiar material is review, not repair, and demand 0 matches the day — but `learning` is a database state, not proof of recovery, so the teach-back must stay brief and optional (see caveat below). |
| **(d)** no plan: the honest starter + the deferred line, not the hands-on repair | YES | EITHER | EITHER | **YES on the half that matters; the other half is genuinely yours** | Every seat keeps the repair deferred (the finding was about the day, not the plan). None can say whether *you* would tap "one tiny recall loop", want a same-concept gentle recall instead, or want the system out of the way. |
| **(e)** sit with the plan rather than an unrelated hands-on drill | EITHER | YES | YES | **YES** | The drill is the "least-bad task" the finding said not to lead with; it is still offered, one line below. |
| **(f)** the live struggle is *also* due for recall (new) | — | — | — | **Ask you; no recommendation** | The engine makes the recall primary (130) while the same concept's repair sits deferred at 6/10. Spacing research favours the retrieval; the finding's logic (do not put the failing thing in front of a 3/10 day) argues the other way. The seats predicted this collision; they did not score it. |

## Basis, opposing case, falsifier — per reading

### (a) — recommend YES

- **Basis.** The framework's *Demand-Light Mode* and *Shutdown Protocol* (a low-energy day is a state check, not
  a to-do list); task-initiation cost in ADHD is highest for the hardest, most emotionally loaded item;
  *Body Doubling for Study Sessions* is the project's own low-demand default. Grok's framing is the honest one:
  the grounded reasons are initiation cost and demand avoidance, not RSD as a measured construct.
- **Strongest opposite.** A senior engineer with one concrete stuck thing may prefer to attempt it with support
  rather than sit beside it; deferral can read as being told what you cannot do.
- **Falsifier.** You repeatedly open the deferred repair anyway on low-energy days and finish it without a
  confidence dip the next day. If that happens, the demand class for a live struggle is set too high for you.

### (b) — recommend YES

- **Basis.** Retrieval practice on a *familiar* item is the cheapest real learning available and has a genuine
  spacing cost if skipped; *Pre-Study State Check → familiar win*. The body double is a proposal (42) and is
  still one line below.
- **Strongest opposite.** "Due" can turn into an obligation to finish; a due recall on a bad day should be
  stoppable without becoming a remedial lesson (astra). That is a surface rule for the session, not a ranking
  question.
- **Falsifier.** You skip the due recall for the sit-with more often than not. Then the recall is not the
  familiar win the score assumes.

### (c) — recommend YES, with a caveat you should know

- **Basis.** A teach-back on a concept you are actively learning is consolidation, not repair (design §5 demand
  `low`); *Dopamine-Driven Learning Loop* — a short successful explanation is a win.
- **The caveat (astra, checked against source and true).** `learning` in `study_progress` is whatever status was
  last recorded; the engine treats it as "recovered" but has no evidence of recovery. A teach-back requires
  retrieval, organisation and expression — not zero effort. The recommendation holds *because the co-study and
  study personas make everything optional at energy ≤ 6*, not because the item is free.
- **Strongest opposite.** Explaining is harder than recognising; on a 3/10 day you might manage a worked
  example and not an explanation.
- **Falsifier.** You repeatedly ask to see an example first, or abandon the teach-back despite recognising the
  concept. Then `learning` should not map to demand 0 for you.

### (d) — recommend YES on the deferral; the floor is your call

- **What all three seats agree on.** Do **not** gate the deferral on a plan (review 7 Q1, rejected again ×3):
  the finding was about the day's energy and a live struggle, and a no-plan learner has the same day. Do
  **not** silently restore the hands-on repair.
- **What no seat can settle.** Whether "one tiny recall loop" is something *you* would tap. Grok: "the card is
  where sessions go to die" is the falsifier for keeping it; astra: a vague starter may itself be a decision
  burden; the alternative that follows from retrieval evidence is a same-concept gentle recall (review 7 Q3,
  parked as a follow-on, design §5 decision 8).
- **Recommendation.** Score (d) on the *deferral* — yes if you agree the repair should not be the primary on a
  3/10 day with no plan. If the generic starter is not something you would do, say so in the line: that makes
  Q3 (a same-concept gentle recall as the no-plan floor) the 0.6.0 item, with a countable finish.
- **Falsifier for the starter.** You never choose it. **Falsifier for Q3.** You accept a same-concept gentle
  recall and come back the next day still willing — grok's "the observation that should decide the follow-on".

### (e) — recommend YES

- **Basis.** The finding's own words: "instead of the least-bad task". The low-energy rule already penalises
  hands-on work (−14, pre-existing); the body double outranks *only* such a penalised task and removes nothing
  (the drill is the alternate at 34). Review 7's F2 corrected the *claim* that every real candidate outranks
  it; the behaviour was kept and is now stated correctly in the rubric too.
- **Strongest opposite (astra, fair).** A *familiar* unrelated drill is not the class of work the finding
  objected to — it is concrete, predictable and may be easier to start than an open-ended presence session.
  The score arithmetic (42 vs 34) does not measure that difference.
- **Falsifier.** You repeatedly pick the drill over the sit-with and complete it. Then the ordering should
  flip for you — as a preference, not a safety finding.

### (f) — no recommendation; the question is yours

- **What the engine does** (emitted from `c519bc2a`): with the plan, primary `window function` **recall** at
  130 (100 + 30 overdue), `plan_refs` to the plan, no alternates, and `energy_deferred_repairs` naming the
  *same* concept at 6/10. Without a plan: `decorators` recall 118, the same concept deferred beside it.
- **Why it is a real question.** "Due recall is never deferred" is a policy, not a conclusion from retrieval
  research (astra's refutation 3): the spacing benefit of retrieval does not establish that a retrieval attempt
  on a live failure is suitable at 3/10. The two rules meet on one concept and the recall wins by construction.
- **What you are asked.** One bounded retrieval attempt on the failing concept — spacing wins — or should a due
  recall on a live-struggle concept inherit the repair's demand and defer with it? And what should happen
  immediately after an unsuccessful attempt? If your answer is "defer", that is a `no` on (f) and a 0.6.0 item
  with a RED test already nameable: `test_due_recall_on_a_live_struggle_inherits_the_repair_demand`.

## What the council changed in the tree, and what it did not

**Applied** (RED `a0946376`, GREEN `c519bc2a`; design §5 decision 9), because the finding held against source:

1. The body-double reason named the deferred struggle with nothing beside it. The framework's own rule
   (*Naming Struggle Topics*: "never name a struggle without an adjacent strength") is now followed with data
   the plan already records: the reason opens with `1 of 2 milestones of SQL Windows done.` and says nothing
   when nothing is done — a strength is never invented.
2. "A body-double session, no new material, no repair" promised a door the engine does not control (grok). The
   co-study persona guarantees "the student drives" and "stay quiet by default", so the reason now says that,
   and a test holds the persona to those words.
3. The rubric's own rationale still said `42 < any real candidate` — review 7's F2 fixed the code, design and
   spec but never the receipt you score against. Corrected.
4. Reading (f) added and emitted (astra §4 and grok §4 named the same missing reading independently).

**Not applied, and why:**

- Gating deferral on an active plan (qwen, review 7 Q1) — rejected by every seat this round too.
- Suppressing the deferred-item names from the body-double reason (astra 🟡: "do not turn an unrelated session
  into a recital of unfinished difficulties") — D-F asks for them by name, so this is yours: if you want the
  deferred list *only* in the CLI's "Deferred for energy" block and the Today card's notes, not in the sit-with
  sentence, say so on row 3b and it is a one-line change with a test.
- A same-concept gentle recall as the no-plan floor (Q3) — stays the recorded follow-on; your (d) line decides
  whether it is built.

**Seat claims checked and found wrong or out of scope** (so they are not acted on): grok's "§0 cites
`web/routes/body_double.py` as the feature" — that is the HANDOFF's verbatim text and was amended in design
§5 (T5.1 amendment 3); grok's "medium and high are not two behaviours" — true and already recorded (design §5
decision 7); qwen's refutation that the collector "runs across multiple sessions" misreads "over three
readings" (three fixtures, one call each); astra's refutation 6 (the async body-double copy asks questions
despite "no questions") is about `agents/shared/audhd-framework.md`'s prose, not this change — noted for a
docs pass, not fixed here.

## One paragraph, plain language

These readings decide that a low-energy day is no longer "do the least-bad piece of real work". Fixing the
thing you are stuck on is treated as work the day cannot carry; reviewing something you already know and
recalling something that is due stay allowed; and when the plan has nothing left that fits, StudyLoop offers to
sit with you rather than hand you a penalised drill. If you asked why it will not let you fix the stuck thing
today: because on a 3/10 day the expensive card is how a wobble becomes a story about yourself — the repair is
still there, named, waiting for a day that can carry it. The two things only you can settle are the no-plan
morning (would you actually tap a generic starter?) and the collision in (f) (when the stuck thing is also due,
do you want to be asked to recall it?).
