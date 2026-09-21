## Purpose

Choose one concrete study action for right now from due reviews, weak
concepts, practice tasks, session continuity, and transfer gaps — weighted
by energy, time budget, modality preference, and interleave mode.  Expose
the decision via `studyloop now`, and provide supporting surfaces:
`studyloop chat-note` (Socratic context packs), `studyloop practice verify`
(attempt recording), `studyloop recap today` (daily synthesis with optional
voice), and `studyloop mastery graph|weak-links` (dependency inspection).

## Requirements

### Requirement: The decision engine produces a ranked plan from multiple candidate sources
`build_now_plan()` (`learning/decision.py`) SHALL gather candidates from
five sources — due spaced-repetition cards (`_due_card_candidates`), due
progress items (`_due_progress_candidates`), struggling/low-score concepts
(`_struggle_candidates`), last-session continuity (`_continuity_candidates`),
and practice-task files (`_practice_candidates`) — then optionally add
transfer/weak-link candidates when `interleave="adaptive"` and energy is
not `"low"`.  It SHALL return a `NowPlan` containing one `primary`
recommendation plus up to two `alternates`, deduped by
`(topic, concept, action_type)`.

#### Scenario: Fresh database with no learning evidence
- **WHEN** all candidate sources return empty lists
- **THEN** `build_now_plan()` returns a `NowPlan` with `starter=True` and
  a single fallback recommendation sourced from the first configured topic

#### Scenario: Multiple candidate sources produce overlapping entries
- **WHEN** the same `(topic, concept, action_type)` tuple appears from both
  `_due_progress_candidates` and `_struggle_candidates`
- **THEN** `_dedupe()` retains only the highest-scored instance

### Requirement: Energy and modality reshape candidate scoring
`_score_candidates()` SHALL apply additive/subtractive adjustments to each
candidate's base score: modality match adds 18 points; low energy penalises
`hands-on`/`visual` by −14 and cross-topic candidates by −28; high energy
boosts `hands-on`/`visual`/`teachback` by +10.  Adaptive interleave mode
further penalises or boosts `visual` candidates depending on energy band.

#### Scenario: Low-energy session requests audio modality
- **WHEN** `energy="low"` and `modality="audio"`
- **THEN** candidates whose `action_type` is `hands-on` or `visual` lose
  14 points, and candidates from a different topic than the last session
  lose an additional 28 points, making continuity-based recall/conversation
  candidates dominate

### Requirement: The CLI exposes the plan with energy, time, modality, interleave, speak, and json flags
`studyloop now` (`cli/_now.py`) SHALL accept `--energy` (low/medium/high,
default medium), `--time` (int minutes, default 25), `--modality`
(recall/conversation/hands-on/visual/audio, default recall),
`--interleave` (off/adaptive, default off), `--json` (output as JSON), and
`--speak` (speak the primary recommendation via `speak_text()`).  The time
input is clamped to `[5, 180]` inside `build_now_plan()`.

#### Scenario: User asks for a quick low-energy recommendation
- **WHEN** `studyloop now --energy low --time 15` is invoked
- **THEN** the returned plan has `energy="low"`, `time_minutes=15`, and
  the primary recommendation's `estimated_minutes` respects the per-action
  floor (5 min for recall/audio, 10 min for other types)

### Requirement: chat-note builds a Socratic context pack scoped to allowed study roots
`build_note_companion_pack()` (`learning/note_companion.py`) SHALL resolve
the note path against `allowed_note_roots()` (obsidian vault, study paths,
content base path) and reject paths outside those roots with a `ValueError`.
It SHALL chunk the note by headings and code fences (limit 8 chunks), build
a mode-specific instruction prompt (recall/diagram/trace/teachback/repair),
and return a `NoteCompanionPack` including the full prompt and a
`suggested_command` for recording evidence.

#### Scenario: Note outside configured roots
- **WHEN** `studyloop chat-note /etc/passwd --mode recall` is invoked
- **THEN** the command raises a `ClickException` wrapping the ValueError
  "Note is outside the configured StudyLoop study/vault roots."

#### Scenario: Teachback mode
- **WHEN** `--mode teachback` is passed
- **THEN** the `suggested_command` in the pack is a `studyloop teachback`
  invocation and the prompt instructs the agent to run a teach-back

### Requirement: practice verify records attempts and updates study progress
`verify_practice_task()` (`learning/practice.py`) SHALL load a
`PracticeDeck` from the JSON path, validate the 1-based task index,
determine verification kind (`command` or `checklist`), check expected
artifacts, and record the result to `practice_attempts` via
`_record_attempt()`.  It SHALL also call `record_progress()` with
confidence `"confident"` on pass or `"struggling"` on fail.  Command
verification requires the `--run-command` flag; without it, a
`PermissionError` is raised.

#### Scenario: Checklist verification with missing artifacts
- **WHEN** a task has `verification.kind = "checklist"`, the user provides
  `--notes "done"`, but one expected artifact file is absent from workdir
- **THEN** `passed` is `False` (notes present but missing artifacts),
  progress is recorded as `"struggling"`, and the attempt row is inserted

#### Scenario: Command verification without --run-command
- **WHEN** `studyloop practice verify deck.json --task 1` is invoked
  without `--run-command` and the task's verification kind is `"command"`
- **THEN** a `PermissionError` is raised with message "Command
  verification requires --run-command."

### Requirement: recap today synthesises a four-field daily summary with optional voice and audio export
`build_daily_recap()` (`learning/recap.py`) SHALL assemble a `DailyRecap`
with fields `win`, `repair_target`, `due_item`, and `next_action` sourced
from `get_wins(days=1)`, `get_struggling_topics(days=7)`,
`spaced_repetition_due()`, and `build_now_plan()` respectively.  The CLI
(`cli/_recap.py`) SHALL accept `--speak` (live TTS via `speak_text()`),
`--audio-file PATH` (export via `synthesize_text_to_file()`), and `--json`.
When all data sources are empty, `has_data` is `False` and the recap
provides safe fallback strings.

#### Scenario: No learning data available
- **WHEN** `studyloop recap today` runs on a fresh install with an empty DB
- **THEN** the recap panel shows a fallback win ("You kept the loop alive
  by checking in"), `has_data` is `False`, and `next_action` is
  `build_now_plan().primary.evidence_command`

#### Scenario: Audio file export
- **WHEN** `studyloop recap today --audio-file recap.wav` is invoked
- **THEN** `synthesize_text_to_file()` (`learning/voice.py`) is called
  with `recap.speakable_text()` and the resolved path; success prints a
  green confirmation, failure prints a yellow warning

### Requirement: mastery graph renders concept dependencies as Mermaid or JSON
`mastery_graph_mermaid()` and `mastery_graph_json()` (`learning/mastery.py`)
SHALL query `concept_dependencies` for the given topic, seed edges from
local markdown (heading paths, wikilinks, tags) and existing
`concept_relations`/`knowledge_bridges` tables if the topic has no edges
yet, then return a Mermaid `flowchart LR` string or a JSON dict with
`nodes`, `edges`, `edge_count_total`, and `limited` flag.

#### Scenario: Topic with no pre-existing edges
- **WHEN** `studyloop mastery graph --topic python` runs and
  `concept_dependencies` has no rows for "python"
- **THEN** `seed_inferred_dependencies("python")` scans configured
  markdown roots for heading adjacency, wikilinks, and tags, inserts
  edges with confidence 0.35–0.50, and the graph renders those seeded
  edges

### Requirement: weak-links surfaces struggling prerequisites that block downstream concepts
`weak_links_for_topic()` (`learning/mastery.py`) SHALL join
`concept_dependencies` edges with `study_progress` rows for the topic,
filter to source concepts whose confidence is `"struggling"` or
`"learning"` or whose `last_teachback_score < 14`, and return them sorted
by severity (struggling first, then by ascending teachback score).

#### Scenario: A concept recorded as struggling feeds two downstream edges
- **WHEN** `study_progress` has concept "list comprehensions" with
  confidence "struggling" and `concept_dependencies` has two edges with
  `source_concept = "list comprehensions"`
- **THEN** `weak_links_for_topic()` returns an entry with
  `concept="list comprehensions"` and `reason` containing "is struggling
  and feeds {target_concept}"

### Requirement: Voice output is optional and never blocks the learning workflow
`speak_text()` (`learning/voice.py`) SHALL locate `study-speak` on PATH
(or `~/.local/bin/study-speak`), invoke it with the text, and return a
boolean.  On failure (binary not found, timeout, non-zero exit) it returns
`False` without raising.  Every CLI caller (`_now.py`, `_chat_note.py`,
`_recap.py`) SHALL print a yellow warning and continue when `speak_text()`
returns `False`.

#### Scenario: study-speak binary not installed
- **WHEN** `studyloop now --speak` runs and `study-speak` is not on PATH
  and not at `~/.local/bin/study-speak`
- **THEN** `speak_text()` returns `False`, the CLI prints "[yellow]Voice
  output was unavailable; continuing without speech.[/yellow]", and the
  recommendation is still displayed normally

### Requirement: Activation is readiness-gated on every entry path
The study-plan domain SHALL expose one application seam,
`studyloop.planning.PlanApplication`, and it SHALL be the only writer any
adapter (Web routes, CLI commands, MCP tools) uses for study plans. `apply`
SHALL evaluate readiness whenever the *resulting* document would be `active` —
create with `status="active"` (`CreatePlan`), import of a document whose
frontmatter says `active` (`ImportDocument`), replacement of an existing
document with one whose frontmatter says `active` (`ReplaceDocument`), and a
lifecycle transition to `active` (`TransitionLifecycle`) — and SHALL raise
`PlanNotReady` carrying a `ReadinessView` **before any canonical write** when
the plan has no mission `why`, no success criteria, or no milestones. Readiness
SHALL be computed by exactly one function (`authoring.readiness`), reached only
through the seam; no adapter SHALL carry a readiness check of its own.

The seam's read side (`browse`, `inspect`, `prepare_planning`) SHALL return
frozen, tuple-only views whose `to_json_dict()` returns a fresh container on
every call and serialises `PlanSummary` and `ReadinessView` to exactly the
`StudyPlan.summary()` and `authoring.readiness()` key sets. Domain failures
SHALL be exceptions with no CLI, HTTP or MCP vocabulary: `PlanNotFound`,
`InvalidPlanId`, `PlanConflict`, `InvalidField`, `PlanNotReady`,
`InvalidMilestone`.

#### Scenario: Create with status active on an unready plan
- **WHEN** `apply(CreatePlan(title="Vague", answers={}, status="active"))` is
  called
- **THEN** `PlanNotReady` is raised, its `readiness.ready` is `false` with a
  non-empty `blockers` tuple, and no document exists afterwards

#### Scenario: Whole-document replacement whose frontmatter says active
- **WHEN** `apply(ReplaceDocument(plan_id, markdown))` is called with a
  document whose frontmatter says `active` and which has no milestones
- **THEN** `PlanNotReady` is raised and the stored document is byte-identical
  to what it was before the call

#### Scenario: Status transition to active on an unready plan
- **WHEN** `apply(TransitionLifecycle(plan_id, "active"))` is called for a
  draft whose readiness reports blockers
- **THEN** `PlanNotReady` is raised and `inspect(plan_id).summary.status` is
  still `draft`

#### Scenario: Every door raises the same refusal
- **WHEN** the same unready document is refused via `CreatePlan`,
  `TransitionLifecycle`, `ReplaceDocument` and `ImportDocument`
- **THEN** the four `ReadinessView` payloads are equal apart from `plan_id`,
  and `str(exc)` is `plan is not ready to activate` for each

#### Scenario: Replacement keeps identity
- **WHEN** `apply(ReplaceDocument(plan_id, markdown))` is called with a
  document whose frontmatter names a different `id` and `created`
- **THEN** the persisted plan keeps the original `plan_id` and `created`, the
  content edits are applied, and no second document appears

#### Scenario: Several ready plans may be active
- **WHEN** two ready plans are created with `status="active"` and a third
  ready plan is transitioned to `active`
- **THEN** all three succeed and `browse(status="active")` returns all three

#### Scenario: Duplicate id without overwrite
- **WHEN** `apply(CreatePlan(..., plan_id="demo"))` is called and `demo`
  already exists with `overwrite=False`
- **THEN** `PlanConflict` is raised and the existing plan is unchanged; with
  `overwrite=True` the plan is replaced

#### Scenario: Browse order is the store's and is deterministic
- **WHEN** `browse()` is called over active and draft plans
- **THEN** active plans come first, then ascending `updated`, ties broken by
  plan id, and repeated calls return equal tuples

### Requirement: Partial checkpoint recording is reported, never silent
`evaluate_and_record` SHALL treat a `False` return from
`index.record_checkpoint` exactly as it treats a raised failure: by appending
`checkpoint not saved to the database` to the evaluation's `warnings`. The
index's swallow-and-return-`False` remains its best-effort policy; the caller
SHALL honour the answer. A successful database write SHALL add no warning.

#### Scenario: Database write reports failure by returning False
- **WHEN** `record_checkpoint` returns `False` during `evaluate_and_record`
- **THEN** the returned evaluation's `warnings` contains an entry mentioning
  `database`, and the evaluation is still returned with a valid verdict

#### Scenario: Database write succeeds
- **WHEN** `record_checkpoint` returns `True`
- **THEN** no warning mentioning `database` is present

### Requirement: Milestone set is idempotent and refuses indices the plan lacks
`apply(SetMilestone(plan_id, index, done))` SHALL set — not toggle — one
milestone's `done` state on a loaded candidate, judge the resulting document
with the same readiness gate every write uses when the plan is active, and
save once when the state changed. Applying the same intent twice SHALL leave
the same document *byte for byte*: a retry that asks for the state the
milestone already has writes nothing and leaves `updated` untouched (the
gate still runs first).
`index` is a 0-based position: an index past the end **or negative** SHALL
raise `InvalidMilestone` before any write. A plan that does not exist SHALL
raise `PlanNotFound` before the index is judged.

#### Scenario: Set is idempotent
- **WHEN** `SetMilestone(plan_id, 0, done=True)` is applied twice
- **THEN** the first application saves exactly once and the second saves
  nothing (document bytes and `updated` unchanged), the milestone is done
  after both, and `SetMilestone(plan_id, 0, done=False)` undoes it

#### Scenario: Negative index
- **WHEN** `SetMilestone(plan_id, -1, done=True)` is applied
- **THEN** `InvalidMilestone` is raised and the document is byte-identical

#### Scenario: Ticking a milestone on an unready active document
- **WHEN** `SetMilestone` is applied to a hand-edited active plan that has no
  mission
- **THEN** `PlanNotReady` is raised — the resulting document would be
  active-but-unready — and nothing is written

### Requirement: Deletion is confirmed and retains the checkpoint log
`apply(DeletePlan(plan_id, confirmed))` SHALL raise `InvalidField` unless
`confirmed` is `True` (after `PlanNotFound` for an unknown id), remove the
canonical document and its derived index row, retain every row of the durable
checkpoint log for that id, and return a frozen `DeleteResult(plan_id)` whose
`to_json_dict()` is `{"deleted": true, "plan_id": "<id>"}` — `apply` returns a
`DeleteResult` for this intent and a `PlanDetail` for every other, because a
detail cannot describe a plan that no longer exists.

#### Scenario: Unconfirmed delete
- **WHEN** `DeletePlan(plan_id)` is applied with `confirmed` left `False`
- **THEN** `InvalidField` is raised and the document is unchanged

#### Scenario: Confirmed delete keeps history
- **WHEN** a plan with one recorded checkpoint is deleted with `confirmed=True`
- **THEN** a `DeleteResult` is returned, `inspect(plan_id)` raises
  `PlanNotFound`, the derived index no longer lists the plan, and
  `checkpoint_history(plan_id)` still returns the row

### Requirement: Assessment reports each recording sink independently
`assess(AssessPlan(plan_id, phase, study_id, record, append_to_plan))` SHALL
return a frozen `AssessmentResult` carrying a `PlanEvaluationView` (whose
`to_json_dict()` equals `PlanEvaluation.to_dict()` key for key and whose
`markdown` is the rendered checkpoint block), `db_write` and `document_write`
each in `not_requested | saved | failed`, and the evaluation's `warnings`.
`record=False` SHALL call `evaluate_plan` and write to neither sink;
`record=True` SHALL call the existing `evaluate_and_record` (the Bug-B fix's
single checkpoint writer) — the seam adds no
second checkpoint writer — and read its two recording warnings back into the
sink fields. A failed sink SHALL be a reported outcome on the result, never an
exception (no `PartialRecording`), because the evaluation succeeded.
`recording_complete` is `True` when no requested sink failed — vacuously true
for a preview. The plan SHALL be found before the phase is judged (`PlanNotFound`
before `InvalidField`). Because appending the checkpoint re-saves the plan
document, `record=True, append_to_plan=True` on an *active* plan SHALL run the
same readiness gate every other write runs — before either sink is touched —
and raise `PlanNotReady` (with `already_active=True`) for an active-but-unready
document; a preview or a database-only recording persists no document and is
not gated.

#### Scenario: Preview writes neither sink
- **WHEN** `assess(AssessPlan(id, "mid", record=False))` is called
- **THEN** both sink fields are `not_requested`, no checkpoint row exists in
  the log or the document, and `recording_complete` is `True`

#### Scenario: Both sinks saved
- **WHEN** `assess(AssessPlan(id, "end", study_id="s1"))` is called and both
  writes succeed
- **THEN** both sink fields are `saved`, `recording_complete` is `True`, and
  the row is present in the log (with `study_id == "s1"`) and in the document

#### Scenario: Database failure reported, document still written
- **WHEN** the log write returns `False` or raises
- **THEN** `db_write == "failed"`, `document_write == "saved"`,
  `recording_complete` is `False`, `warnings` contains `checkpoint not saved
  to the database`, and the evaluation carries a valid verdict

#### Scenario: Recording onto an unready active document is refused first
- **WHEN** `assess(AssessPlan(id, "start"))` is called for a hand-edited active
  plan with no mission
- **THEN** `PlanNotReady` is raised before the checkpoint log is written, the
  document is byte-identical, and the same call with `record=False` or
  `append_to_plan=False` succeeds

#### Scenario: Document failure reported independently
- **WHEN** the document save raises
- **THEN** `document_write == "failed"`, `db_write == "saved"`, the log holds
  the row, and the document is unchanged

### Requirement: Active-plan guidance is a deterministic read
`get_active_guidance(*, today=None)` SHALL return a frozen `ActiveGuidance`
holding one `ActivePlanGuidance` per plan whose status is `active`, ordered by
`plan_id`, with: the `PlanSummary`; the plan's `ReadinessView` (`readiness`) —
the same view every write is judged by, so an active-but-unready document (a
hand edit or pre-gate import with no mission) is still listed but its entry
says that every `SetMilestone`, `RevisePlan` or document-appending recorded
assessment on it will be `PlanNotReady` until it is paused or repaired (a
preview, or a recording with `append_to_plan=False`, touches no document and
is not gated — see "Assessment reports each recording sink independently"),
with no second `inspect` per
plan; `next_milestone` (the first unchecked
milestone, or `None`); `match_keys`, a sorted, de-duplicated `tuple` of
`normalise_match_key`
over the topics and every milestone's concepts (casefold, punctuation replaced
by spaces, whitespace collapsed — matching is equality on the key, never a
substring test; a tuple, not a `frozenset`, because D-3 binds every view to
tuples and a consumer that wants a set builds one); `target_urgency` in `overdue` (days until target `< 0`),
`soon` (`0..7`), `later` (`> 7`) or `undated`; `energy_floor`; a
`completion_action` string only when the plan has milestones and every one is
done; and per-plan `warnings` for defects worked around (no milestones, a
target date that is not a date). Every document SHALL be enumerated by its
storage id and loaded through the identity-pinning seam path, so an entry's
id is the file's, never an untrusted frontmatter `id`; documents that cannot
be read or parsed SHALL be named in the collection's `warnings`, in id order.
Non-active plans are skipped. `today`
pins the urgency computation and the nested summary's `days_until_target` —
one effective date for the whole payload — for frozen-clock callers and
defaults to the UTC
date.

This view is the one plan-static read the `now` decision engine consumes
(see "The now engine is plan-aware with tested ranking rules").

#### Scenario: One entry per active plan, ordered, others skipped
- **WHEN** plans `zeta` (active), `alpha` (active), `mid` (active) and one
  plan in each of `draft`, `paused`, `complete`, `abandoned` exist
- **THEN** `get_active_guidance().plans` has three entries in the order
  `alpha`, `mid`, `zeta`, and repeated calls return equal views

#### Scenario: Match keys and next milestone
- **WHEN** an active plan has topics `["SQL", "Data-Engineering"]` and
  milestones with concepts `["Window-Function"]` (done) and `["RANK vs
  DENSE_RANK", "dense rank"]`, `["window frame"]`
- **THEN** `match_keys == ("data engineering", "dense rank", "rank vs dense
  rank", "sql", "window frame", "window function")` — sorted, de-duplicated —
  and `next_milestone` is index `1`

#### Scenario: Urgency buckets
- **WHEN** the target date is 30 or 1 day(s) ago, today, 1, 7, 8 or 90 days
  ahead, or unset
- **THEN** `target_urgency` is `overdue`, `overdue`, `soon`, `soon`, `soon`,
  `later`, `later`, `undated` respectively

#### Scenario: Every milestone done
- **WHEN** an active plan's milestones are all `done`
- **THEN** `next_milestone` is `None` and `completion_action` is a non-empty
  string naming the plan

#### Scenario: Malformed documents become warnings
- **WHEN** an active plan has no milestones and `target_date: someday`, and an
  unreadable file sits beside it
- **THEN** the guidance is returned; the plan's entry has `next_milestone ==
  None`, `completion_action == None`, `target_urgency == "undated"` and
  warnings naming the milestones and the date; the collection's `warnings`
  name the unreadable file

#### Scenario: Identity is the file, not the frontmatter
- **WHEN** `alpha.md` carries frontmatter `id: beta` beside a real `beta.md`,
  and two unreadable files sit beside a healthy plan
- **THEN** the entries are `alpha`, `beta` (and `healthy`) with unique ids and
  their own titles — never two `beta` entries; `readiness.plan_id` matches
  the entry id; the collection's `warnings` name exactly the unreadable files
  in id order and never the readable mismatched one; `inspect(<entry id>)`
  resolves to the same document

#### Scenario: An unready active plan is listed with its blockers
- **WHEN** an active document has topics and milestones but no mission `why`
  and no success criteria, beside a ready active plan
- **THEN** both appear in `.plans`; the husk's `readiness.ready` is `false`
  and its `readiness.blockers` name the missing why and success criteria; the
  ready plan's `readiness.ready` is `true`; `load_plan` ran once per document;
  and `to_json_dict()` carries the `readiness` block per entry

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
   "conversation"`, base score below every real candidate's base and then
   scored like any other candidate — so every due and conversation candidate
   outranks it at every energy while a hands-on task the low-energy rule
   penalises may not; a proposal, never a filter: nothing is removed from the
   ranking — `plan_refs` `(plan_id, None)` for every **ready** matchable plan
   (rule 7 may add a reference to an unready plan whose topic the proposal
   shares; the proposal itself names ready plans only), a reason that opens with
   the progress the plan records (`N of M milestones of <plan> done.`, omitted when
   none is done — never invented) before naming the deferred milestones and
   repairs it stands in for, and describes the door by what the co-study persona
   guarantees (the learner drives; the companion stays quiet unless asked), and
   `evidence_command` the
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
active plan, no struggle candidate and nothing deferred receives the pre-#10
payload **byte for byte** — the golden world, pinned by
`tests/golden/now_plan_no_active.json`, captured before any of this shipped.
Exactly two changes are plan-independent (rule 2's repair half): every
struggle-collector candidate's `metadata` carries `energy_demand` at every
energy, and repair above the day's capability — a live struggle, an older
struggle or a weak teach-back at low energy — is deferred into
`energy_deferred_repairs` (with the starter, if nothing else was collected)
where the learner used to receive the repair itself. `medium` and `high`
demand both need at least medium self-reported energy today; the class is
carried so the payload says why.
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
- **WHEN** energy is `low`, a due `recall` item on a plan concept is collected
  (whatever its metadata says about confidence) and a live struggle repair is
  also collected
- **THEN** the due item is primary with `PlanRef(plan, None)`, the repair is
  in `energy_deferred_repairs`, and no `body_double` candidate exists

#### Scenario: A struggling row's due item is the repair, collected twice
- **WHEN** energy is `low` and one `struggling` row seen 3 days ago on a
  finished milestone's concept is read by both the due-progress collector
  (which labels every `struggling` row due — "Guided repair + tiny practice",
  `hands-on`) and the struggle collector
- **THEN** both copies are deferred, `energy_deferred_repairs` names the
  concept once (`high`), the concept is ranked nowhere, and the primary is the
  `body_double` proposal (the starter when no plan exists); at `medium` energy
  the due copy is primary as before and the key is absent

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
  and never "Record evidence"; with no plan and no struggle candidate the CLI
  panel prints no plan lines, `GET /api/now` equals the golden, and the
  recap's `plan_context` is absent from its JSON, its spoken text and the
  `recap today` panel

#### Scenario: Learner-authored text is data to every renderer
- **WHEN** an active plan's title, topic or milestone text contains Rich
  markup, HTML or shell punctuation (`Plan [/bold]`, `<script>…`, `"; rm -rf ~`)
- **THEN** `build_now_plan` ranks and serialises it unchanged and writes
  nothing to the document; `studyloop now` exits 0 and shows the text
  literally; the Today card renders it through `x-text`

### Requirement: Adapters reach study plans only through the seam
No module under `studyloop/cli`, `studyloop/web/routes` or `studyloop/mcp`
SHALL import `studyloop.planning.store`, `.index`, `.authoring` or
`.evaluation` (directly, relatively, as a whole-package handle, by wildcard
`from studyloop.planning import *`, by a literal string naming a forbidden
module or the whole package, by name through `from studyloop.planning import …`
for the names those modules contribute, or transitively through one of the
four allowed seam modules — `from studyloop.planning.application import
store`). `tests/test_architecture_plan_seam.py` SHALL enforce this by
parsing every adapter module, SHALL reject each planted bypass in a temp copy
of an adapter, and SHALL check its explicit name list against what
`studyloop.planning` actually re-exports from the four modules.

#### Scenario: Planted bypass is rejected
- **WHEN** `from studyloop.planning.store import save_plan`, `from
  studyloop.planning import *`, `importlib.import_module("studyloop.planning")`
  or `from studyloop.planning.application import store` is appended to a copy
  of `web/routes/plans.py` and the checker runs on the copy
- **THEN** the checker reports a violation for each; on the real tree it
  reports none

### Requirement: The learning-record rule has one copy
Learning-record validation (non-empty title; no H1–H3 lines in the body) and
idempotent numbering SHALL live in one function,
`studyloop.planning.store.append_learning_record(plan, title, body=, status=)`,
applied to an in-memory plan. The store's `record_learning` SHALL wrap it
(load → append → save only when created, so a duplicate leaves the file's
bytes untouched) and the seam's `RevisePlan(learning_record=…)` SHALL call it
on the revision candidate, translating its `ValueError` to `InvalidField`.
A revision whose only content is a learning record that already exists SHALL
write nothing (no save, bytes and `updated` untouched — the guarantee the
store's `record_learning` always gave); a duplicate record beside another
field change SHALL still be one save, and an empty revision remains a
"touch" (one save, `updated` bumped, nothing else changed).

#### Scenario: The seam follows the store's rule
- **WHEN** `store.append_learning_record` is replaced by a function that
  raises `ValueError("the store said no")` and `RevisePlan(learning_record=…)`
  is applied
- **THEN** `InvalidField` carrying that message is raised and no record is
  added

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
