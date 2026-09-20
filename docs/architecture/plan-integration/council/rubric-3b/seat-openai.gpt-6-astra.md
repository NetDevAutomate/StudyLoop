## 1. Recommendations table

These are recommendations about the **action**, not scores on the owner’s behalf.

| Reading | Recommend to owner | Ten-second reason |
|---|---|---|
| **(a)** | **YES** | Offer sitting with the plan rather than reopening a live struggle; keep the session genuinely free of teaching and performance demands. |
| **(b)** | **YES** | A short, familiar due recall reasonably precedes optional body doubling, provided “due” does not become an obligation to finish. |
| **(c)** | **EITHER** | A brief explanation of familiar material can consolidate learning, but `learning` does not establish recovery or make teach-back low-demand. |
| **(d)** | **YES** | Keep repair deferral independent of plan ownership and offer the tiny starter, without requiring retrieval or inventing an easier version of the deferred repair. |
| **(e)** | **EITHER** | Sitting with the plan and doing a familiar unrelated drill are both defensible; the score arithmetic cannot establish which costs this learner less. |

## 2. Basis, per reading

### (a) Sit with SQL Windows

- **Basis:** *Emotional Regulation*, *Demand-Light Mode*, and *Async Body Doubling* support reducing demands when the learner is flat or overwhelmed. ADHD task-initiation and executive-function research supports scaffolding and reducing unnecessary switching. Direct evidence that body doubling—especially AI presence—outperforms brief repair for AuDHD adults is limited. The strongest justification here is the owner’s recorded preference, not a clinical finding that repair necessarily causes harm.
- **Strongest opposite argument:** Unresolved confusion can itself consume attention. One tightly bounded, well-scaffolded correction might provide relief, whereas sitting beside an unfinished plan could prolong avoidance or feel pointless.
- **Falsifier:** Across several comparable low-energy opportunities, the owner repeatedly abandons the open session but voluntarily completes a bounded repair, retains the correction at the next review, and shows no recurring frustration or early exit. That would support offering that repair format, rather than a blanket preference for presence.

### (b) Due decorators recall above body doubling

- **Basis:** Spacing and retrieval practice have strong general learning evidence, including Dunlosky et al. (2013) and Rowland’s retrieval-practice meta-analysis (2014). That supports retaining access to recall; it does **not** directly validate this ranking for low-energy AuDHD adults. *Emotional Regulation* supports a familiar win, but a due item is not necessarily mastered or easy.
- **Strongest opposite argument:** An unrelated Python recall introduces a topic switch, and retrieval can feel evaluative. The owner may have arrived specifically to maintain contact with SQL, not clear a review queue.
- **Falsifier:** Due recall repeatedly produces errors followed by escalation into instruction, abandonment, or avoidance of the next session, while voluntarily chosen presence sessions remain usable. Prefer body doubling under those conditions.

### (c) Recovered-concept teach-back

- **Basis:** Retrieval and self-explanation can strengthen learning. However, *Demand Avoidance* and *RSD in Socratic Context* identify questions and explanations as possible performance demands. `learning` is a database state, not evidence of mastery; a teach-back requires retrieval, organisation, and expression. Evidence supports offering a bounded version, not assigning it zero actual effort.
- **Strongest opposite argument:** For **YES**, successful recent explanations would make this an excellent familiar win. For **NO**, explanation may be substantially harder than recognising an example or quietly reviewing it, even when the underlying concept is familiar.
- **Falsifier:** Repeated successful, brief explanations with little prompting and successful later recall support **YES**. Repeated requests to see an example first, inability to initiate an explanation, or abandonment despite accurate recognition support **NO** for teach-back as the default.

### (d) No-plan starter rather than live repair

- **Basis:** The reason to avoid automatically assigning demanding repair concerns the learner’s state, not whether a plan exists. Plan-gating would restore the original problem for no-plan users. *Demand-Light Mode* supports a small invitation; *Shutdown Protocol* requires an exit rather than any learning task when shutdown is present. Retrieval evidence supports the starter only if it actually retrieves something sufficiently familiar.
- **Strongest opposite argument:** “One tiny recall loop” may be too vague to start and may create a new decision burden. A learner with one concrete problem could reasonably prefer a specific, supported repair over an unrelated generic exercise.
- **Falsifier:** The owner repeatedly cannot choose material for the starter, exits without starting, or manually returns to the deferred repair. If that repair succeeds without recurrent escalation, replace the generic floor with a personalised option. This would not justify making deferral plan-dependent.

### (e) Body doubling above the unrelated drill

- **Basis:** *Emotional Regulation* supports body doubling when flat, but also recognises modality switching and code katas as potentially useful when frustrated. A familiar drill can be concrete, predictable, and easier to initiate than an open-ended conversation. There is no established evidence that “hands-on” alone measures energy demand, or that 42 versus 34 captures the relevant difference.
- **Strongest opposite argument:** For **YES**, the owner explicitly wanted presence instead of the least-bad work when nothing plan-related fits. For **NO**, that preference arose from **live struggle repair**, not evidence that all unrelated practice is unsuitable.
- **Falsifier:** Repeated selection and successful completion of the drill, without escalating effort or abandoning the session, supports promoting it. Repeated drill abandonment followed by usable presence sessions supports the current ordering. Until then, either ordering is defensible with the other visible.

These observations would personalise the policy; they would not establish a general AuDHD treatment effect.

## 3. Behavioural checks you would add

The tests below are **proposed additions**, not claims about tests already present. Use `test_now_plan_guidance.py` for decision behaviour and dedicated renderer/session tests for the user-facing contract.

### (a): Right action; reason and session contract need checking

The emitted reason names a struggle without adjacent evidence of competence. That conflicts with *Naming Struggle Topics*. The fixture does provide one usable fact: “Window basics” is marked done—not proof of mastery, but evidence of completed work.

- **Concrete change:** In the body-double reason produced through `learning/decision.py`, use factual framing such as:
  **“Window basics is marked complete. Frames and a follow-up on window functions can wait. Sit with SQL Windows if useful—no new material or repair.”**
- Keep structured deferral data intact. Avoid making “asks for at least 6/10” sound like a measured human limit in `cli/_now.py`, `learning/recap.py`, and `today-panel.js::deferredNotes`.
- **Tests:** `test_body_double_reason_pairs_deferred_concept_with_recorded_progress`; `test_body_double_door_preserves_presence_only_intent`.
- **Done:** The command opens co-study on the intended plan; the Web door preserves the same intent; neither automatically launches a quiz, repair, teaching sequence, or intake questionnaire. `web/routes/body_double.py` remains a focus reader, not the session-start mechanism.

### (b): Right default ordering; isolate unrelated deferred work

- **Concrete change:** Keep the recall primary and body double alternate. Do not attach SQL struggle reminders to the decorators recall’s opening explanation. Group them under the separate SQL option or deferred-work area.
- In `cli/_now.py`, `learning/recap.py`, and `today-panel.js::deferredNotes`, distinguish transparent deferral reporting from unsolicited resurfacing during unrelated work.
- **Tests:** `test_due_recall_precedes_body_double_without_sql_repair_in_primary_reason`; renderer equivalents for grouped deferred details.
- **Done:** Recall remains primary; the body-double door remains available; launching decorators does not introduce SQL repair. The recall can be stopped or skipped without automatically becoming a remedial lesson.

### (c): Action uncertain; “low demand” must not imply guaranteed ease

- **Concrete change:** Present teach-back as a brief optional explanation, not a mastery test. Do not display `learning` as “recovered” unless independent evidence supports that description. Retain `energy_demand=low` as a policy classification, not a claim of zero effort.
- In `learning/decision.py::_struggle_candidates`, explicitly test what happens when `confidence="learning"` coexists with a weak recent teach-back; the supplied prose leaves the priority insufficiently clear.
- **Tests:** `test_learning_candidate_is_not_rendered_as_mastered`; `test_learning_with_weak_teachback_has_explicit_demand_precedence`; `test_low_energy_teachback_can_end_without_repair_escalation`.
- **Done:** Classification priority is documented and pinned; the owner can attempt one short explanation and stop without mandatory corrective work. A weak-performance signal is not silently lost behind a reassuring label.

### (d): Keep plan-independent deferral; verify that the starter is usable

- **Concrete change:** Keep the truthful deferral reason. Make the invitation concrete without synthesising recall on the deferred struggle: “One tiny recall loop on something familiar, if useful; stopping is also fine.”
- Do not claim that no evidence exists, and do not quietly restore hands-on repair.
- **Tests:** `test_no_plan_live_repair_defers_to_truthful_optional_starter`; `test_starter_does_not_target_deferred_struggle_implicitly`; retain the no-struggle/no-plan golden.
- **Done:** No live repair appears in the ranked results; the deferred row has `plan_id=None`; the starter does not initiate decorators repair; the unchanged golden remains byte-identical.

### (e): Valid proposal; priority remains a preference, not a safety finding

- **Concrete change:** Preserve both choices while the owner decides. Describe the alternate as familiar practice if evidence supports that description; do not describe it as harmful merely because it is hands-on.
- Keep `test_body_double_ordering_after_adjustments_follows_the_energy_rule`, but add an explicit fixture asserting that the drill remains available. Document that the ordering expresses an energy-and-plan preference.
- **Test:** `test_low_energy_unrelated_drill_remains_selectable_below_body_double`.
- **Done:** Primary 42, alternate 34, neither hidden; selecting the drill launches the drill without inserting deferred SQL repair. Do not change `BODY_DOUBLE_BASE_SCORE` solely to satisfy an unsupported “all real candidates first” rule.

## 4. Missing reading

**(f) The deferred live struggle is also due for recall.**

- **Fixture:** No active plan; low energy; `decorators` recorded `struggling` three days ago; a due `study_progress` recall on the **same concept**. Repair is deferred, but recall remains eligible.
- **Owner question:** “Would you want one bounded retrieval attempt on this same live struggle, or presence/an exit instead—and what should happen immediately after an unsuccessful attempt?”

This tests the boundary hidden by reading (b)’s unrelated recall. A source label must not allow the same demanding repair to return through a “due recall” door.

## 5. Refutations

1. **“Hands-on repair on a low-energy day compounds the struggle” is not a universal finding.** It is a credible risk and an owner-specific reason for this default. RSD is not established here as the inevitable mechanism, and not every AuDHD learner shares that response.

2. **The demand thresholds are engineering heuristics.** Fourteen days, capability 3/6/10, and demand 0/4/6 are not validated cognitive measurements. An older struggle is not necessarily cheaper; `learning` is not necessarily recovery.

3. **“Due recall is never deferred” is a policy, not a conclusion from retrieval research.** Retrieval benefits do not establish suitability during shutdown or severe overload. Keeping recall eligible need not mean insisting on it after the state check.

4. **The F2 arbitration overgeneralises the original concern.** Promoting a familiar unrelated drill would not necessarily “re-recommend the class of work the finding objected to”: live struggle repair and routine practice have different demands. Keeping 42 above 34 is defensible, but not compelled by D-F.

5. **“The struggle IS the learning mechanism for the AuDHD brain” and “never short-circuit” are unsupported absolutes.** Productive retrieval and reasoning can help; unproductive struggle can impair learning and participation. Worked examples, explicit explanation, and scaffolding are legitimate approaches. The dopamine note does not establish a universal instructional sequence.

6. **Async body doubling’s wording contradicts itself.** “Still going?” and “Need anything?” are questions, despite “no questions.” For presence-only mode, questions and check-ins need explicit opt-in; otherwise they undermine the promised reduction in demands.

7. **Naming every deferred struggle can conflict with the project’s own naming rules.** Preserve the audit data, but do not turn an unrelated recall session into a recital of unfinished difficulties. Never fabricate a strength to repair that conflict.

## 6. One paragraph for the owner

These readings decide whether low energy changes the kind of invitation StudyLoop makes, rather than merely subtracting points from difficult work. I recommend keeping live repair out of the default recommendation even without a plan, offering genuinely quiet presence when a plan exists, and leaving familiar recall available. Teach-back and unrelated drills need your experience to settle their priority. If you asked, “Why won’t it let me fix the thing I’m stuck on?”, I would say: “It is using a cautious default because you said reopening a live struggle on a low-energy day can make things worse. That is a recommendation, not a judgement about your ability. It should not prevent a deliberate choice to try a small, supported repair—and stopping or doing nothing remains a valid choice.”
