# Council brief — rubric row 3b: a decision brief for the owner (2026-09-20)

You are one seat of a three-seat council. You do **not** see the other seats. You are **not** the owner, and
this brief does **not** ask you to score the rubric: the rubric's question is "would *I*, the learner, do the
primary?" and only the owner can answer it. What you are asked for is a **recommendation per reading**, grounded
in evidence-based practice for AuDHD adult learners and in the project's own framework documents quoted below,
so the owner's scoring becomes "agree or overrule" rather than reconstruction. Where practice is genuinely
undetermined, say so — a confident recommendation with no basis is worth less than "either is defensible
because X".

The owner is a neurodivergent (ADHD + ASD) senior engineer retraining from networking into data engineering,
self-taught, learning Python/SQL/data engineering with StudyLoop. The engine under review recommends the next
study action from live evidence (due spaced-repetition reviews, recorded struggles, an active study plan) and
the learner's stated energy for the day.

## 0. The owner decision that item 5 implements (HANDOFF §2, verbatim row)

| D-F | Scenario 3 (**no**): a struggle-repair task has no energy demand; hands-on repair of a live struggle on a low-energy day compounds the struggle (RSD). Derive per-item energy demand from struggle recency / teach-back; when nothing plan-related fits the day's capability, synthesise a **body-doubling / open-session** candidate (feature exists: ADR-0001/0003, `web/routes/body_double.py`) naming the deferred items. |

## 1. Rubric row 3 — the original finding (verbatim from the rubric receipt)

| 3 | Energy-deferred | Plan `sql-windows` with `energy_floor: 5`; milestone 0 `Window basics` **done** (concepts `[window function]`), milestone 1 `Frames` (concepts `[window frame]`). One struggle-repair item `window function`/sql, `hands-on`, base 82. **Energy `low`** (capability 3/10). | **`window function`** (hands-on, score 80, `plan_refs=[(sql-windows, None)]`); no alternates; `energy_deferred=[(sql-windows, milestone 1, floor 5, capability 3)]`; JSON gains `energy_deferred`. | Rule 3: capability 3 < floor 5, so the *new* milestone (Frames) is deferred and named, not synthesised; the plan-related repair on a finished milestone's concept stays eligible and keeps its ref (`None`: plan-related repair, not the next milestone). Score = 82 + 12 bias − 14 (hands-on at low energy). | **no** — owner, 2026-09-16: a struggle-repair task has no energy demand of its own; recommending hands-on repair of a *live* struggle on a low-energy day risks compounding the struggle and damaging confidence (RSD). Finding for council: (1) derive a per-item energy demand for repair from struggle recency/teach-back — at low energy a live struggle defers like new work, a recovered one stays eligible as gentle review; (2) when nothing plan-related fits the day's capability, synthesise a body-doubling / open-session candidate (feature exists: ADR-0001/0003, `web/routes/body_double.py`) naming the deferred items, instead of the least-bad task. |

## 2. Rubric row 3b — the five emitted readings the owner must score (verbatim)

| 3b | Energy-deferred — **re-run after D-F (item 5, 2026-09-19)** | Row 3's fixture (`sql-windows`, `energy_floor: 5`, milestone 0 `Window basics` done `[window function]`, milestone 1 `Frames` `[window frame]`; **energy `low`**, capability 3/10), with the struggle collector running for real over three readings: **(a)** `window function` recorded `struggling` 3 days ago (a live struggle); **(b)** the same plus an unrelated due recall `decorators`/python base 100; **(c)** `window function` recorded `learning` (recovered); added after council review 7: **(d)** **no plan at all**, one live struggle `decorators`/python, low energy; **(e)** row 3's world plus one **unrelated hands-on** practice task `list comprehension drill`/python base 48, low energy. | **(a)** primary **`Sit with SQL Windows`** (conversation, `source=body_double`, score 42, `plan_refs=[(sql-windows, None)]`, command `studyloop study "SQL Windows" --mode co-study`), reason *"Nothing plan-related fits low energy today — deferred: milestone 2 “Frames” of SQL Windows; repair of “window function”. Sit with SQL Windows instead: a body-double session, no new material, no repair."*; no alternates; `energy_deferred=[(sql-windows, 1, 5, 3)]`; **`energy_deferred_repairs=[(sql-windows, window function, struggling, high, 6, 3)]`** with reason *"low energy carries 3/10; repairing 'window function' (a live struggle) asks for at least 6/10 — deferred like new work; due recall and gentle review stay available"*. **(b)** primary **`decorators`** (118, no refs); the body-double proposal is the only alternate (42). **(c)** primary **`window function`** (teachback, 100, `plan_refs=[(sql-windows, None)]`, `energy_demand=low`); nothing deferred but the milestone. **(d)** primary **`one tiny recall loop`** (the starter, 28, reason *"Today's energy deferred the repair work it cannot carry; start with one small retrieval signal instead"*); no alternates; `energy_deferred_repairs=[(None, decorators, high, 6)]` — where before item 5 the primary was the hands-on repair of `decorators`. **(e)** primary **`Sit with SQL Windows`** (42); the hands-on drill is the alternate at 34 (48 − 14 low-energy penalty). | Rule 3 extended (design §5): repair carries a demand derived in the struggle collector — live `struggling` → high (6/10), older `struggling` or a weak teach-back → medium (4/10), `learning` → low (0/10) — and below the capability is deferred like new work into its own key, never ranked; due recall is never deferred. When nothing plan-related fits and an active plan exists, one body-double candidate is synthesised (base 30 + 12 bias = 42 < any real candidate — a proposal, not a filter) carrying the co-study session door. | **PENDING** — owner: (a) would you sit with the plan rather than repair the live struggle today? (b) is the body-double proposal right to sit beneath the unrelated due recall? (c) is the gentle teach-back on a recovered concept one you would do at low energy? (d) with **no plan**, is the starter plus the deferred line the floor you want on a low-energy day, rather than the hands-on repair you used to get (review 7: two seats keep it, one would restore the repair)? (e) at low energy, would you sit with the plan rather than do an unrelated hands-on drill (review 7 F2: the proposal outranks a task the low-energy rule penalises, and nothing else)? |

The row's columns are: scenario/fixture · primary emitted (with score, source, plan refs, the offered command,
the reason sentence) · engine rationale · the owner's question per reading. The five readings are **(a)–(e)**.
## 3. Design §5 — the item-5 design and its recorded decisions (verbatim)

#### 5. Item 5 — per-item energy demand and the body-doubling floor (D-F) — designed here, reviewed separately

*(One page, written before item 5's RED; see tasks T5.\*.)*

- **Energy demand per candidate.** `_struggle_candidates` derives `energy_demand ∈ {low, medium, high}` from
  struggle state: `confidence == "struggling"` (a live struggle, ≤ 14 days) → `high`; `struggling` older than
  14 days or a weak teach-back → `medium`; recovered / gentle review → `low`. Demand maps to a required
  capability (`high` → 6, `medium` → 4, `low` → 0) compared with `ENERGY_CAPABILITY[energy]`.
- **Rule 3 extended.** Below capability, *repair* above demand is deferred exactly like new milestone work and
  listed in `energy_deferred` with a reason naming the struggle; recovered repair stays eligible as gentle
  review. Due recall (`source=study_progress` due rows) is unaffected.
- **Body-doubling floor.** When the eligible plan-related set is empty **and** at least one active plan exists,
  synthesise one candidate: `source="body_double"`, `action_type="conversation"`, low base score (below any
  real candidate), reason naming the deferred items, `plan_refs` for each named plan with `milestone_index
  None`, and an `evidence_command` that opens the existing body-double session route (`studyloop study
  --mode co-study` / `web/routes/body_double.py`). A proposal, not a filter: real candidates still rank above
  it.
- **No-plan output byte-identical to the golden**; `INTERLEAVE_RATIOS["low"]` unchanged (the design does not
  call for it).
- **Rubric row 3b** (owner scores): scenario 3's fixture at low energy now yields the deferred repair named in
  `energy_deferred` and a body-double primary (or the due recall if one exists).

**T5.1 review against the code (2026-09-18, tree `7208eb67`) — three amendments, each from reading
`learning/decision.py`, not the text above:**

1. **Demand classes are the struggle collector's classes.** `_struggle_candidates` emits a row only when
   `confidence in ("struggling", "learning")` or `last_teachback_score < 14`; "recovered / gentle review" is not a
   row it produces. So: `struggling` with `last_seen` ≤ 14 days → `high`; `struggling` older than 14 days, or any
   row whose only signal is a weak teach-back → `medium`; `learning` → `low`. Demand is derived once, in the
   collector, and carried in the candidate's `metadata` beside `confidence` so the scorer and the renderers read
   one value. Required capability `high → 6`, `medium → 4`, `low → 0` stands (the `low` class is what "repair is
   cheaper than encoding" was always about).
2. **`energy_deferred` is milestone-shaped and cannot carry a repair as it is.** `DeferredMilestone` has a
   mandatory `milestone_index`, and all three renderers (`cli/_now.py`, `learning/recap.py`,
   `today-panel.js::deferredNotes`) print `milestone {index + 1} "{title}" needs energy {floor}/10`. A deferred
   repair gets its own frozen `DeferredRepair` (`plan_id`/`plan_title` when plan-related, else `None`, `concept`,
   `topic`, `confidence`, `energy_demand`, `required_capability`, `energy_capability`, `reason` naming the
   struggle), carried in a **new additive key `energy_deferred_repairs`** — not folded into `energy_deferred`,
   whose consumers would print "milestone None". Same "readable off the top" rule as the closing review's
   evidence lines: each renderer gains one line per deferred repair.
3. **The body-double door is a session start, not `web/routes/body_double.py`.** That route is the read-only focus
   reader (`GET /api/body-double/focus`). The session door is `studyloop study "<topic>" --mode co-study` on the
   CLI and a session start from the Body Double view (origin `body-double`) on the Web. `_evidence_command` has
   no branch for a `conversation` candidate and would fall through to `studyloop progress … -c learning`, which is
   a write, not a door — so the body-double candidate carries `evidence_command = 'studyloop study "<plan title>"
   --mode co-study'` set explicitly, and `_evidence_command` is not asked to guess. `source="body_double"`,
   `action_type="conversation"`, base score below `MILESTONE_BASE_SCORE` (48) so any real candidate outranks it.

Rule 3's *deferral* of repair is the change; rule 3's *eligibility* of plan-related due recall is untouched. The
no-plan golden stays byte-identical because a body-double candidate requires an active plan and the golden world
has none; `INTERLEAVE_RATIOS["low"]` unchanged.

**Decisions taken at GREEN (2026-09-19), each a test in `test_now_plan_guidance.py`:**

1. **The deferral is plan-independent.** A live struggle is a live struggle whether or not a plan names it
   (amendment 2's `plan_id … else None` already said so); the finding was about the learner's day, not the
   plan. The body double, by contrast, *requires* a matchable active plan — it is "sit with the plan".
   Consequence, stated rather than hidden (sharpened by review 7 F3): D-5's "a learner with no active plan
   receives the pre-#10 payload byte for byte" holds for a no-plan learner **with no struggle candidate and
   nothing deferred** — the golden world. Two changes are plan-independent: every struggle-collector candidate
   carries `metadata.energy_demand` at every energy, and repair above the day's capability (a live or older
   struggle, a weak teach-back, at low energy) is deferred — with the starter if nothing else was collected —
   where the learner used to get the repair itself. Review 7 put the scope question to three seats: two (astra,
   grok) keep it plan-independent ("gating it on a plan would leave the original no unfixed for every no-plan
   learner"), one (qwen) would gate it; arbitrated as **keep**, the contract re-worded to the truth above in the
   spec delta and both docs, and the no-plan floor put to the owner as row 3b reading (d).
2. **Rule 8's guaranteed slot below the floor is the body-double proposal.** It carries `plan_refs`, so where
   four unrelated due items outrank everything at low energy the second alternate is now the proposal, not a
   third unrelated item. It advertises no work the energy cannot carry — the property rule 8's docstring
   protects — and the primary is untouched. `test_preserves_one_plan_backed_action_when_energy_allows` says so.
3. **The starter tells the truth after a deferral.** With no plan and every real candidate deferred, the starter
   stands in; its reason now says the energy deferred the repair work rather than "no learning evidence found
   yet", which would be false. The golden world defers nothing, so its sentence is unchanged.
4. **Body-double shape.** Base `BODY_DOUBLE_BASE_SCORE = 30` — below every real candidate's *base*; after the
   day's adjustments it sits above a hands-on task the low-energy rule penalises (48 − 14 = 34 < 30 + 12 = 42)
   and below every due and conversation candidate. Review 7 F2 (two seats 🔴, one 💡) was arbitrated as the
   energy rule doing what the finding asked, not a filter: the *claim* "any real candidate outranks it" was the
   defect, corrected in the constant's comment, the spec and here, and pinned by
   `test_body_double_ordering_after_adjustments_follows_the_energy_rule`; the judgement is row 3b reading (e).
   Concept `Sit with <title>` (one plan) / `Sit with your plans`; `plan_refs` for every **ready** matchable plan
   (rule 7 may add a topic-matched husk reference; the proposal names ready plans only); reason naming each
   deferred milestone and repair; command `studyloop study <title> --mode co-study`, the title quoted as one
   shell argument (review 7 F1). The Today card starts it in the Body Double view and hands the plan title over
   (`body-double-request`, review 7 F7); the CLI labels the command "Sit with the plan".
5. **A deferred repair does not "represent" a milestone** (rule 6 runs after the deferral), so an eligible
   milestone whose only collected representative was a deferred live struggle is synthesised as a conversation —
   the learner can still talk about it (`test_deferred_repair_allows_only_eligible_milestone_conversation`).
6. **The body double names ready plans only.** An active-but-unready plan is matched but never synthesised
   (spec rule 8), and the body double is a synthesis; with only a husk active and nothing plan-related fitting,
   nothing is proposed to sit with — the warning beside it already says "pause or repair"
   (`test_body_double_is_never_synthesised_for_an_unready_plan`).
7. **`medium` and `high` demand are behaviourally identical today** (nothing in `ENERGY_CAPABILITY` sits between
   3 and 6): both need at least medium self-reported energy. The class is kept as explanatory state so the
   payload says *why* (review 7: astra and grok keep it, qwen would collapse it); the spec says so.
8. **Not taken, recorded as follow-ons:** a same-concept gentle `recall` synthesised for a no-plan learner whose
   only candidates were deferred (grok 🔵 / qwen 🟡; astra: do not invent an unvalidated lower-demand action) —
   the owner's row 3b reading (d) decides whether the starter is the floor they want.

Known edge, not solved here: a `struggling` row whose `last_seen` cannot be parsed is read as live (`high`) —
the cautious side; `_days_since` returns `None` and the demand falls to `high`.

## 4. Engine facts you may rely on (verified on the reviewed tree `849c78aa`)

```python
ENERGY_CAPABILITY: dict[EnergyLevel, int] = {"low": 3, "medium": 6, "high": 10}
ENERGY_DEMAND_CAPABILITY: dict[EnergyDemand, int] = {"high": 6, "medium": 4, "low": 0}
```

- Scores (from `decision.py` on the reviewed tree): a due spaced-repetition recall is `100 + days overdue`
  (capped at +30); a struggle repair is a **`hands-on`** candidate at 82 when the concept is `struggling`, a
  **`teachback`** at 70 otherwise, plus up to +42 when the last teach-back was weak; a hands-on practice task is
  48; a synthesised milestone conversation is `MILESTONE_BASE_SCORE = 48`; the body-double proposal is
  `BODY_DOUBLE_BASE_SCORE = 30` + `PLAN_RELATED_BIAS = 12` = **42**. The pre-existing low-energy rule subtracts
  **14 from every `hands-on` or `visual` candidate** (and 28 from a topic switch). The body double is a
  *proposal, not a filter* — nothing is removed from the ranking by it.
- Deferral (rule 3, extended by item 5): a repair whose demand exceeds the day's capability is moved into
  `energy_deferred_repairs` with a reason sentence and is **never ranked**; due recall is **never deferred**,
  even on a `struggling` concept. Demand: live `struggling` (≤ 14 days) → high 6/10; older `struggling` or a
  weak teach-back → medium 4/10; `learning` (recovered) → low 0/10. At `low` energy the capability is 3/10, so
  medium and high are behaviourally identical (both deferred); at `medium` (6/10) both are carried.
- The body double is synthesised only when an active **ready** plan exists and nothing plan-related fits the
  day; it names the deferred items in its reason and opens the existing body-double session
  (`studyloop study "<plan title>" --mode co-study`), a session with no new material and no repair.
- With **no plan** and everything deferred, the primary is the pre-existing "honest starter" (`one tiny recall
  loop`, score 28) whose reason now says *why* ("Today's energy deferred the repair work it cannot carry…").
- The rubric is scored on frozen fixtures; the outputs in §2 were emitted from the tree, not written by hand.

## 5. Review 7's record — where three seats already split (verbatim rows)

| F2 | "Base below `MILESTONE_BASE_SCORE` so every real candidate outranks it" is false after adjustments: at low energy the proposal (42) outranks a hands-on task that energy penalises (34) (astra 🔴, qwen 🔴; grok 💡 "acceptable, do not lower the base"). | **Claim corrected, behaviour kept.** Reproduced exactly as computed. Every due and conversation candidate still outranks it at every modality; only a hands-on task the low-energy rule already penalises sits beneath — the energy rule doing what the finding asked ("instead of the least-bad task"), not a filter: nothing is removed from the ranking. Astra's proposed post-scoring floor would put a penalised hands-on task above the proposal at low energy, i.e. re-recommend the class of work the finding objected to. The *claim* was the defect: corrected in the constant's comment, the docstring, the spec delta's rule-5 clause and design §5 decision 4; the judgement is the owner's — row 3b reading (e). | `02e282e6`; `test_body_double_ordering_after_adjustments_follows_the_energy_rule` (recall and conversation modality) |
| Q1 | Gate the deferral on an active plan (qwen 🔴). | **Rejected** — see below. | design §5 decision 1; row 3b reading (d) |
| Q3 | Synthesise a same-concept gentle recall as the no-plan floor (qwen 🟡; grok 🔵 "follow-on"). | **Not taken; recorded as a follow-on** and put to the owner. | design §5 decision 8; row 3b reading (d) |

Q1 (gate the deferral on an active plan) and Q3 (a same-concept gentle recall as the no-plan floor) are the two
alternatives to reading **(d)**; F2 is reading **(e)**. The arbiter's ruling is recorded; you may disagree with
it — say why.

## 6. The project's AuDHD framework — the sections that bear on these readings (verbatim)

#### Emotional Regulation

##### Pre-Study State Check
Always assess emotional state before teaching begins. See `session-protocol.md` for the full state check flow.

##### Adaptive Responses

| State | Adaptation |
|-------|------------|
| anxious | Start with a familiar win. Review mastered concept first |
| frustrated | Switch modality — diagram exercise or code kata instead of Q&A |
| flat | Body doubling mode — low demand, periodic check-ins |
| overwhelmed | Shorter chunks (5 min max), more scaffolding, review only |
| shutdown | Gentle exit. No teaching. No questions. No productivity |

##### Shutdown Protocol
When a learner is in shutdown:
- "Not a study day. That's OK. Want to just sit here quietly?"
- Do NOT try to teach, motivate, or redirect
- Offer to set a reminder for tomorrow
- If they want to stay, switch to async body doubling (see below) — presence without demands

##### Mid-Session Emotional Shifts
Watch for signs of emotional state change during a session:
- Sudden short answers → possible frustration or overwhelm
- "I should know this" → RSD activation
- Going silent → possible shutdown or deep processing (ask which)
- Rapid topic-switching → anxiety or hyperfocus seeking

Response: Name what you observe. "You seem [frustrated/quieter]. Want to adjust, take a break, or keep going?"

#### Demand Avoidance (PDA) Awareness

Questions are demands. For PDA-profile learners, "What do you think happens if...?" can trigger the same avoidance response as "Do your homework." The Socratic method must adapt.

##### Detection Signals
- Refusing to engage after previously being willing
- Doing the opposite of what's suggested
- Hostility toward the session structure itself ("stop asking me questions")
- "I don't want to" that isn't frustration — it's autonomic refusal

##### Demand-Light Mode
When PDA signals are detected, switch to:
- **Observations instead of questions:** "I notice this pattern..." not "What pattern do you see?"
- **Invitations instead of instructions:** "You could try..." not "Try this"
- **Autonomy framing:** "Entirely up to you" after every suggestion
- **Sharing instead of testing:** "Here's something interesting I noticed about this code..."
- **No sequential intake questions** — infer from context, observe, adapt

##### Express Start
The session protocol itself (state check, energy check, sensory check) is three demands in a row. For PDA-profile users, offer: "Ready to dive in? I'll figure out the rest as we go."

#### RSD / Imposter Syndrome Management

##### Reframe Mistakes
- "This approach shows good functional thinking — now let's add the Context to complete the pattern"
- "Missing the Context is a common oversight when transitioning from scripting to architecture"
- "Your network automation background gives you strong procedural thinking — patterns add structural abstraction"

##### Validate Senior Experience
- "You already understand separation of concerns from network segmentation..."
- "Just as VLANs isolate broadcast domains, the Strategy Pattern isolates algorithm variations"
- "This is adding Pythonic patterns to your existing architectural toolkit"

##### Imposter Syndrome Triggers
Watch for: "I should already know this", "This is taking me too long", "Maybe I'm not cut out for this"

**Response:** "You have 30 years of designing complex distributed systems. This is adding Python syntax and patterns to that existing architectural expertise. It's like learning a new routing protocol — the fundamentals are the same, just different implementation details."

##### RSD in Socratic Context
Socratic questions can be interpreted as judgment:
- "Why did you do it that way?" sounds like criticism
- Softened variant: "Your instinct here is sound — there's one piece that might bite us later"

**Anticipatory avoidance** (not starting sessions because of imagined failure):
- Surface evidence first: "Last session you nailed X"
- Lower stakes framing: "Let's just look at some code together, no quiz"

##### Naming Struggle Topics (Re-Surfacing Deferred Work)
When a session plan targets a struggle topic or returns to a deferred concept, the naming decides whether the learner engages or the RSD alarm fires.

**Rules:**
- **Lead with present competence.** Frame the topic as an APPLICATION of what the learner already demonstrably holds — never as a return to a failure.
- **Never name a struggle without an adjacent strength** in the same breath.
- **No structural connection, no mention.** If the deferred topic is not genuinely related to the current work, stay silent. A non-sequitur that also recalls a failure is the worst outcome.

**Model phrasing:**
> "Remember when we started working on X — as we're doing Y, this is a great opportunity to show how X makes this design better."

**Never say:**
- "Remember when you struggled with..." — anchors the topic to failure before any work begins
- "You failed to grasp..." — direct judgment; RSD reads it as identity, not feedback
- "We had trouble with..." — the plural doesn't soften it; the learner hears "you"
- "This was hard for you" — labels the learner, not the material

##### Win Surfacing
Proactively counter RSD with evidence:
- Run `studyloop wins` and surface recent mastered concepts
- "Last week you couldn't explain decorators. Today you used one correctly without prompting. That's real growth."
- Keep celebrations factual and specific — empty praise triggers AuDHD suspicion

#### Sensory/Cognitive Overload Prevention

##### Information Chunking
- Maximum 3-4 concepts per explanation
- Tables for comparisons (easier to parse than prose)
- TL;DR summaries at the top
- Break long code into digestible sections

##### Overload Warning Signs
- Requesting repetition of previously covered concepts
- Asking for simplification mid-explanation
- Multiple questions about same topic
- Expressing frustration or overwhelm

##### Response to Overload
1. Pause: "Let's take a breath and summarise what we've covered"
2. Simplify: Remove non-essential details
3. Reframe: Connect to known concept (networking)
4. Visual: Switch to diagram or table

#### Dopamine-Driven Learning Loop

Research note: the effort of actively reasoning your way to an answer triggers a dopamine release that keeps the ADHD brain engaged.

**The loop:**
1. Present a puzzle/challenge (not an explanation)
2. Guide with questions (productive struggle)
3. Student discovers the answer (dopamine hit)
4. Metacognitive checkpoint (consolidate)
5. Apply to new context (transfer)

**Never short-circuit this loop** by giving the answer too early. The struggle IS the learning mechanism for the AuDHD brain.

#### Body Doubling for Study Sessions

##### Active Body Doubling
When acting as active study partner:
- **Start:** "What are you working on? How long do you want to go?"
- **Midpoint:** "How's it going? Need to adjust?"
- **End:** "What did you accomplish? What's the next micro-step for tomorrow?"
- Keep check-ins brief — don't break flow state

##### Async Body Doubling
For low-energy or shutdown states where the learner wants presence without interaction:
- "I'm here. Work at your own pace. I'll check in every 15 minutes unless you say otherwise."
- Check-ins are minimal: "Still going?" or "Need anything?"
- No teaching, no questions, no suggestions unless asked
- The value is presence and accountability, not instruction
- If the learner starts asking questions, transition to active mode naturally

#### Energy-Adaptive Intervals

Break frequency adjusts based on the energy level declared at session start.

| Energy Level | Micro-Break | Short Break | Long Break |
|---|---|---|---|
| High (7-10) | Every 25 min | Every 50 min | Every 90 min |
| Medium (4-6) | Every 20 min | Every 40 min | Every 75 min |
| Low (1-3) | Every 15 min | Every 30 min | Every 60 min |

If no energy level is declared, default to **Medium** intervals.

##### Low-Energy Sessions

When energy is 1-3:
- Micro-breaks are especially important (executive function depletes faster)
- Short breaks should include standing even if the student doesn't want to walk
- Consider whether the session should continue at all after the long break threshold
- *"Your energy was low when we started. After this break, let's check in — worth continuing or better to come back tomorrow?"*

## 7. Deliverables — numbered H2 sections, in this order

1. **Recommendations table.** One row per reading **(a)–(e)**: `Recommend to owner: YES / NO / EITHER`, then one
   sentence the owner can read in ten seconds.
2. **Basis, per reading.** For each of (a)–(e): (i) the practice or principle it rests on — name the framework
   section above where one applies, or the external body of evidence (e.g. executive-function load and task
   initiation in ADHD, RSD and error exposure, autistic burnout and demand, spacing/retrieval effects) and be
   honest about how strong that evidence is; (ii) the **strongest argument for the opposite answer**; (iii)
   what the owner would *observe in real use* that should flip the verdict (a falsifier, not a feeling).
3. **Behavioural checks you would add.** For each reading, is the emitted output the *action a learner should be
   offered*, or is it right in principle but wrong in its surface (the reason sentence, the door offered, the
   score, the alternate)? If the surface is wrong, name the concrete change and the test that would pin it —
   but distinguish this clearly from the rubric verdict, which is about the action.
4. **Missing reading.** Is there a sixth situation the owner should be asked about that (a)–(e) omit? Name the
   fixture and the question, or say "none".
5. **Refutations.** Any claim in §0–§6 you believe is false or not established by this brief.
6. **One paragraph for the owner**, plain language, no code: what these five readings decide about how StudyLoop
   treats a low-energy day, and what you would tell a learner who asked "why won't it let me fix the thing I'm
   stuck on today?"

Do not restate the brief. Do not score the rubric on the owner's behalf; recommend. Where you would say
"the learner should", say instead what the evidence supports and what would falsify it.
