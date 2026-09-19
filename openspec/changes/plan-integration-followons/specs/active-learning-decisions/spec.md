## ADDED Requirements

### Requirement: The completion action is a closing review, never a verdict
Rule 9's completion action for a fully-checked active plan (item 4 / D-G)
SHALL be composed from the plan's **end assessment**, read through the preview
path — `PlanApplication().assess(AssessPlan(plan_id, phase="end",
record=False))` — exactly once per fully-checked plan per `build_now_plan`. The
read SHALL write nothing: the document's bytes and status, the plans directory
and the checkpoint log are unchanged, and the recording writers
(`evaluate_and_record`, `record_checkpoint`) are never called. The engine
proposes; the architect asks; the learner decides; `set_study_plan_status`
remains the only door to `complete`.

`CompletionAction` SHALL gain `due_reviews: int`, `struggles: int`,
`unverified_milestones: int`, `proposal: Literal["extend", "close"] | None`
and `evidence: tuple[str, ...]`, and SHALL keep `action`, the sentence every
renderer prints — now naming the proposal and the three counts and the one
door to acting on them, `studyloop plan close <id>`; it SHALL differ from the
pre-change either-way sentence. The counts and lines SHALL come from one
definition, `planning.views.CompletionReview.from_evaluation`, consumed by both
this action and the `plan close` brief so the two surfaces never disagree:
`proposal == "extend"` iff any count is above zero, else `"close"`; one
evidence line per counted item, capped at `COMPLETION_EVIDENCE_CAP` (8) with a
final `… and N more` line. **Due reviews SHALL count only rows that name a
concept** (owner decision, 2026-09-17): the scheduler's `New topic -- start
fresh` row (`concept: None`, `evidence: configured_topic`) is a cold-start hint
for "what should I review now", not a lapsed review, and SHALL NOT be counted;
`plan evaluate` keeps the row, the exclusion is the completion review's.
`CompletionAction` and `CompletionReview` SHALL carry `partial: bool`.

**A partial read SHALL NOT propose** (council review 6, F1). `evaluate_plan`
turns a reader that fails into a warning ending `unavailable — evaluation is
partial` (`evaluation.PARTIAL_READ_MARKER`, one definition) and an empty
default, so a count read while that reader was down is unread, not zero. When
the evaluation carries such a warning the review SHALL keep the counts it did
read, set `partial` true, set `proposal` `None` — neither `close` (a clean
slate is a fact about evidence, not its absence) nor `extend` — and name each
gap among its evidence lines (`Not read: <reader> unavailable — …`); the
sentence SHALL say the review is partial and could not propose, never "clean";
the `plan close` brief's proposal line SHALL read `unassessed — the review is
partial` and its status line SHALL NOT say the review proposes.

When the assessment fails, the recommendation SHALL NOT fail: the action
SHALL keep the plan-static sentence with `proposal` `None`, the counts `0` and
`evidence` empty, and `NowPlan.warnings` SHALL carry one entry naming the plan
and the failure, logged with its traceback first — so no renderer reads a
clean slate or outstanding work into a failure. The evaluation's own data-gap
warnings SHALL travel back into `warnings` prefixed with the plan id.

The new keys SHALL appear only inside `completion_actions` entries, which
exist only when a fully-checked active plan exists; the no-plan payload stays
byte-identical to `tests/golden/now_plan_no_active.json`. Renderers SHALL
show the sentence (CLI `now`, the Today card, the daily recap), the CLI SHALL
print each evidence line beneath it, and none SHALL re-rank.

#### Scenario: Due work on the plan's concepts proposes extend
- **WHEN** an active plan's every milestone is done and the end assessment
  finds one due review on one of its concepts
- **THEN** `completion_actions[0]` carries `(due_reviews, struggles,
  unverified_milestones) == (1, 0, 0)`, `proposal == "extend"`, an evidence
  line naming the concept, and a sentence naming the plan and `extend`; the
  JSON entry carries all five keys; no `study_plan:` candidate exists

#### Scenario: A clean assessment proposes close
- **WHEN** the end assessment finds no due reviews, no struggles and every
  done milestone backed by evidence
- **THEN** the counts are `(0, 0, 0)`, `proposal == "close"`, `evidence` is
  empty and the sentence names `close`

#### Scenario: New-topic rows are not due
- **WHEN** `spaced_repetition_due` returns only the `New topic -- start
  fresh` row (`concept: None`) for the plan's topic and the concepts have
  session mentions
- **THEN** `due_reviews == 0` and `proposal == "close"`

#### Scenario: The ranker never changes a status
- **WHEN** `build_now_plan` runs against a fully-checked active plan with the
  recording writers patched to raise
- **THEN** exactly one `AssessPlan(plan_id, "end", record=False)` intent is
  assessed, the document's bytes are unchanged, the status is still `active`
  and the checkpoint history is empty

#### Scenario: A failed assessment keeps the sentence and warns
- **WHEN** `assess` raises for the fully-checked plan
- **THEN** `completion_actions[0].action` equals the pre-change sentence,
  `proposal is None`, `warnings` names the plan and the failure, and the
  primary is still the collected due item

#### Scenario: A partial assessment never proposes a clean close
- **WHEN** one of the end assessment's history readers raises inside the
  evaluation and every other reader finds nothing outstanding
- **THEN** `completion_actions[0]` carries `proposal is None`,
  `partial is True`, the counts `(0, 0, 0)`, an evidence line beginning
  `Not read:`, a sentence that says the review is partial and never "clean" or
  "closing the plan", and `warnings` names the plan and the unavailable reader;
  `plan close <id>` still launches the architect, its brief's fourth line is
  `Proposal: unassessed — the review is partial`, the gap is among the first
  section's lines, and its status line does not say the review proposes

## MODIFIED Requirements

### Requirement: The now engine is plan-aware with tested ranking rules
`studyloop.learning.decision.build_now_plan` SHALL remain the only ranker of
study actions and SHALL consume active plans through exactly one call to
`PlanApplication().get_active_guidance(today=…)`, where `today` is the date
of the same instant `generated_at` records. It SHALL apply these rules, in
this order (the plan-application-seam design, §3; decision D-5 of its
council plan; item 5 / D-F of the follow-ons for rule 2's repair half and
the body-doubling floor):

1. Candidates are collected as before; a failure to read plans at all SHALL
   degrade to a `warnings` entry, never a failed recommendation, and SHALL be
   logged with its traceback on `studyloop.learning.decision` so a
   programming error cannot hide behind the learner-facing warning.
2. The energy capability is `low|medium|high → 3|6|10`. For an active plan
   whose `energy_floor` exceeds it, the next milestone SHALL be listed in
   `energy_deferred` and SHALL NOT become a candidate. Plan-related due recall
   stays eligible and plan-related whatever its recorded confidence. A
   struggle **repair** carries an energy demand of its own, derived once in
   the struggle collector from its own row classes and carried in the
   candidate's `metadata["energy_demand"]`: `struggling` seen within 14 days →
   `high` (asks for 6/10); `struggling` older than that, or a row whose only
   signal is a weak teach-back → `medium` (4/10); `learning` → `low` (0/10).
   A repair whose demand exceeds the capability SHALL be deferred exactly
   like new milestone work — listed in `energy_deferred_repairs` as a
   `DeferredRepair` (`plan_id`/`plan_title` when plan-related, else `None`,
   `concept`, `topic`, `confidence`, `energy_demand`, `required_capability`,
   `energy_capability`, `reason` naming the struggle) and never ranked; the
   deferral does not depend on a plan existing. A `low`-demand repair is
   always carried. `energy_deferred` stays milestone-shaped; a repair is never
   folded into it.
3. A candidate is plan-related when `normalise_match_key` of its concept,
   topic or course **equals** one of the plan's `match_keys`; no substring
   test. It names the plan's next milestone (`milestone_index`) only when the
   key equals one of that milestone's concepts **and** the plan is eligible —
   ready and within the energy capability; a topic or finished-milestone
   match, or any match on an energy-deferred or active-but-unready plan,
   carries `milestone_index = None` (plan-related repair), so a payload never
   names a milestone it also reports as deferred or that the seam would
   refuse to tick.
4. Scoring is today's scoring plus one bounded bias for plan-related
   candidates: within one urgency class plan-related beats unrelated, and a
   globally more-urgent unrelated candidate still wins — a bias, not a filter.
5. When no collected candidate represents an eligible (ready, energy-permitted)
   plan's next milestone, one `conversation` candidate SHALL be synthesised
   for it (source `study_plan:<plan_id>:<index>`, concept = the milestone's
   first concept or its title, topic = the plan's first topic), scored below
   every due and repair class. A learner with an active plan and no evidence
   is therefore sent to the plan, and `starter` is `false`. A deferred repair
   (rule 2) does not "represent" a milestone. When, after rules 2 and 5, **no
   candidate is plan-related** and at least one matchable active plan exists,
   one **body-double** candidate SHALL be synthesised instead of leaving the
   plan to the least-bad task: `source = "body_double"`, `action_type =
   "conversation"`, base score below the synthesised-milestone base so every
   real candidate outranks it (a proposal, never a filter), `plan_refs`
   `(plan_id, None)` for every matchable plan, a reason naming the deferred
   milestones and repairs it stands in for, and `evidence_command` the
   co-study session door — `studyloop study "<plan title>" --mode co-study` —
   set explicitly, never a progress write. No active plan (a draft is not
   one) → no body-double candidate; when every real candidate was deferred
   and no plan exists, the starter stands in and its reason says the energy
   deferred the repair work, not that no evidence exists.
6. After de-duplication every matching `PlanRef(plan_id, milestone_index)`
   SHALL be attached to each ranked action, ordered by target urgency
   (`overdue`, `soon`, `later`, `undated`) → most recent `updated` → `plan_id`,
   keeping the most specific milestone per plan.
7. When primary + alternates hold no plan-backed action and an eligible one
   whose estimate fits the requested time exists further down, it SHALL
   replace the last alternate only; the primary is never re-ranked by plans.
   Below a plan's floor that plan-backed action is the body-double proposal
   (it advertises no work the energy cannot carry), never the deferred
   milestone.
8. A fully-checked active plan SHALL appear in `completion_actions` and SHALL
   be neither matched nor synthesised. An active-but-unready plan SHALL be
   listed and matched (bias and a `milestone_index = None` reference) but
   never synthesised and never named as a milestone, with a warning naming
   its blockers.

`NowPlan` gains `active_plans` (ordered as rule 6), `energy_deferred`,
`energy_deferred_repairs`, `completion_actions` and `warnings`;
`LearningRecommendation` gains `plan_refs: tuple[PlanRef, ...] = ()`.
`to_json_dict()` SHALL omit each of these when empty, so a learner with no
active plan **and nothing deferred** receives the pre-#10 payload **byte for
byte** — pinned by `tests/golden/now_plan_no_active.json`, captured before any
of this shipped. The one plan-independent change is rule 2's repair half: a
learner with no plan whose live struggle is deferred at low energy receives
`energy_deferred_repairs` (and the starter, if nothing else was collected)
where they used to receive the hands-on repair itself.
Renderers (`studyloop now`, `GET /api/now`, the Today card, the daily recap in
its JSON, spoken and Rich-panel forms) SHALL show plan relevance, energy
deferral — one line per deferred milestone **and** one per deferred repair —
and the engine's warnings from these fields, SHALL label a body-double
primary's command as the session door it is ("Sit with the plan", and the
Today card starts it in the Body Double view) rather than as evidence to
record, SHALL escape learner-authored text before any markup (Rich or HTML),
and SHALL NOT re-rank. Ranking tests prove ranking compliance, not learner
benefit (D-16); a five-scenario human rubric receipt accompanies the change,
with row 3b re-run after this requirement's repair half.

#### Scenario: No active plan is byte-identical to the golden
- **WHEN** no active plan exists (an empty plans directory, or only a draft)
  and `build_now_plan()` runs with a frozen clock in an empty world
- **THEN** the serialised `to_json_dict()` equals
  `tests/golden/now_plan_no_active.json` byte for byte, and no
  `active_plans`, `energy_deferred`, `energy_deferred_repairs`,
  `completion_actions`, `warnings` or `plan_refs` key is present

#### Scenario: Matching due concept outranks unrelated of the same urgency
- **WHEN** an active plan's milestone names `window function` and two due
  items are two points apart, `decorators` (unrelated) ahead
- **THEN** `window function` is primary with `plan_refs == (PlanRef(plan, 0),)`
  and `decorators` is the first alternate with no refs

#### Scenario: A more-urgent unrelated item still wins
- **WHEN** the only collected candidate is an unrelated due item and the
  plan's next milestone is unrepresented
- **THEN** the due item is primary and the synthesised milestone
  (`study_plan:<id>:0`) is an alternate with a lower score

#### Scenario: Energy below the floor defers the milestone, keeps repair
- **WHEN** energy is `low` (3/10), the plan's `energy_floor` is 5, its next
  milestone is `Frames` and a `learning` row on a finished milestone's
  concept is collected by the struggle collector (gentle repair)
- **THEN** that repair is primary (`teachback`, `energy_demand == "low"`) with
  `PlanRef(plan, None)`, `energy_deferred` names `(plan, 1, 5, 3)`,
  `energy_deferred_repairs` is empty, and no `study_plan:` or `body_double`
  candidate exists; at `medium` energy nothing is deferred and the milestone
  is synthesised

#### Scenario: A live struggle's repair defers at low energy like new work
- **WHEN** energy is `low` and the struggle collector holds a `struggling` row
  seen 3 days ago on a plan concept, a `struggling` row seen 20 days ago on
  another, a `struggling` row seen 1 day ago unrelated to any plan, and a
  `confident` row kept only for a teach-back score of 9
- **THEN** none of the four is ranked; `energy_deferred_repairs` names all
  four — the live plan-related one `("high", 6, 3)` with the plan's id and
  title, the 20-day one `medium` (4), the weak-teach-back one `medium`, the
  unrelated one with `plan_id` and `plan_title` `None` — `energy_deferred`
  still names the milestone alone, and at `medium` energy the key is absent
  and the live repair is ranked again

#### Scenario: Due recall is never deferred
- **WHEN** energy is `low`, a due row on a plan concept is collected with
  `confidence == "struggling"` and a live struggle repair is also collected
- **THEN** the due row is primary with `PlanRef(plan, None)`, the repair is
  in `energy_deferred_repairs`, and no `body_double` candidate exists

#### Scenario: Nothing plan-related fits, so the engine proposes sitting with the plan
- **WHEN** energy is `low`, the plan's `energy_floor` is 5 (milestone
  deferred) and its only repair is a live struggle (deferred)
- **THEN** the primary is `source == "body_double"`, `action_type ==
  "conversation"`, `plan_refs == (PlanRef(plan, None),)`, `evidence_command ==
  'studyloop study "<plan title>" --mode co-study'`, its reason names the
  deferred milestone and the deferred repair, `starter` is `false`, and the
  JSON keys are the golden's then `active_plans`, `energy_deferred`,
  `energy_deferred_repairs`

#### Scenario: The body-double candidate is a proposal, not a filter
- **WHEN** the same world also collects an unrelated due item
- **THEN** the due item is primary with no refs and the body-double
  candidate is the only alternate, with a lower score

#### Scenario: No active plan, no body double
- **WHEN** no plan document exists (or only a draft) and a live unrelated
  struggle is collected at `low` energy
- **THEN** no `body_double` candidate exists, `energy_deferred_repairs` names
  the struggle with `plan_id None`, `starter` is `true` and the starter's
  reason says the energy deferred the repair work

#### Scenario: A deferred milestone is never named by a reference
- **WHEN** energy is `low`, the plan's `energy_floor` is 5 and the only
  collected candidate's concept equals the next milestone's concept
- **THEN** the candidate is primary with `PlanRef(plan, None)` while
  `energy_deferred` names that milestone; at `medium` energy the same
  candidate carries `PlanRef(plan, 0)` and nothing is deferred

#### Scenario: An unready active plan is matched but never named
- **WHEN** an active plan has no mission and no success criteria (unready)
  and a collected candidate equals its next milestone's concept
- **THEN** the candidate is primary with `PlanRef(plan, None)`, no
  `study_plan:` candidate exists, the plan's `active_plans` entry has
  `ready == False` and `eligible == False`, and one warning names the plan,
  its blockers and "pause or repair"

#### Scenario: No substring matching
- **WHEN** a milestone titled `Window functions deep dive` has no concepts
  and candidates `window functions deep dive tutorial`, `window` and
  `joins`/`SQL` are collected
- **THEN** only `joins` is plan-related (`PlanRef(plan, None)` via the topic
  `sql`, casefolded); the other two carry no refs

#### Scenario: Every matching plan is referenced, in order
- **WHEN** six active plans (overdue, soon, later, three undated with
  distinct and tied `updated`) all name the primary's concept
- **THEN** `plan_refs` lists all six ordered overdue → soon → later → undated
  by latest `updated` then `plan_id`, and `active_plans` is in the same order

#### Scenario: A plan-backed action is preserved when energy allows
- **WHEN** four unrelated due items outrank everything and the plan's
  `energy_floor` is 5
- **THEN** at `medium` energy the synthesised milestone replaces the second
  alternate (the primary and first alternate are unchanged); at `low` energy
  the primary and first alternate are the two best unrelated items, the
  second alternate is the body-double proposal with `PlanRef(plan, None)`,
  no `study_plan:` candidate exists and `energy_deferred` names the milestone

#### Scenario: Fully-checked plan emits a completion action
- **WHEN** an active plan's every milestone is done and an unrelated due item
  is collected
- **THEN** `completion_actions` names the plan, the due item is primary with
  no refs, no `study_plan:` candidate exists, and the plan's `active_plans`
  entry has `next_milestone_index == None`

#### Scenario: Renderers show, never re-rank
- **WHEN** `studyloop now --energy low`, `GET /api/now?energy=low` and the
  daily recap run against the energy-deferral fixture, and against the
  live-struggle fixture
- **THEN** each names the primary the engine chose, the plan it advances, the
  deferred milestone and — for the live-struggle fixture — one line per
  deferred repair with its demand and the day's capability; a body-double
  primary is labelled "Sit with the plan" with its `--mode co-study` door
  and never "Record evidence"; with no plan the CLI panel prints no plan
  lines, `GET /api/now` equals the golden, and the recap's `plan_context` is
  absent from its JSON, its spoken text and the `recap today` panel

#### Scenario: Learner-authored text is data to every renderer
- **WHEN** an active plan's title, topic or milestone text contains Rich
  markup, HTML or shell punctuation (`Plan [/bold]`, `<script>…`, `"; rm -rf ~`)
- **THEN** `build_now_plan` ranks and serialises it unchanged and writes
  nothing to the document; `studyloop now` exits 0 and shows the text
  literally; the Today card renders it through `x-text`
