## ADDED Requirements

### Requirement: The completion action is a closing review, never a verdict
Rule 8's completion action for a fully-checked active plan (item 4 / D-G)
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
