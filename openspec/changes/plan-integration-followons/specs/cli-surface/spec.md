## ADDED Requirements

### Requirement: The plan CLI discovers husks and repairs them through the one launch chain
An active plan that is not ready — a "husk" (item 3 / D-C; deviation 12 kept)
— refuses every write until it is repaired or paused, and the CLI SHALL let
the learner find one before they trip over the refusal. `studyloop plan list`
SHALL mark a husk with `!` after its status in the Rich table and nothing
after any other status; `--husks` SHALL list only husks (`PlanApplication.husks()`,
read-only, storage-pinned identity, `browse` order); every `--json` row SHALL
carry `ready` as its eighteenth key. `PlanSummary.ready` and
`StudyPlan.summary()["ready"]` SHALL agree, so the D-3 legacy-dict pin holds
with the contract grown by one key on both sides.

`studyloop plan repair <id>` SHALL be the architect launch and never a second
path: it SHALL `_inspect(id)` (unknown id → the seam's not-found through
`_fail_for`, exit `1`), SHALL exit `0` with `Nothing to repair on '<id>'` and
no launch for a ready plan, SHALL exit `0` with no launch and a pointer to
`studyloop plan architect` for a plan that is not active (a draft or a paused
plan is unready by nature, not a husk), and for a husk SHALL `ctx.invoke(study,
…, mode="plan-architect", topic=<the plan's title>, brief=…, brief_intro=…)`.
`brief` and `brief_intro` SHALL be plain keywords on `study()` — not click
options — threaded `study → _handle_start → start_session →
build_canonical_persona`. The brief's first section SHALL be
`### Repair: what this plan is missing` listing exactly `readiness.blockers`
as `- ` lines and nothing else, followed by the plan as it stands (title, id,
status, topics, milestones done/total, created) and one provenance sentence:
`creation stamp predates the readiness gate` (and `cannot tell when it became
incomplete`) only when `created` parses as a date before
`READINESS_GATE_DATE`; otherwise `cannot tell how it got that way`; never
`never judged` (council review 6 F4). The
sentence SHALL never claim a hand edit. The `brief_intro` SHALL say `PLAN
REPAIR` and `ask the learner only for what is missing`; the default intro
(`None`) SHALL keep the planning sentence byte-for-byte so the Web door's
`persona_hash` does not move. The command itself SHALL write nothing: the
document, the plans directory and the checkpoint log are unchanged after it
returns.

The refusal a husk write meets (`_refuse_activation(already_active=True)`)
SHALL name both exits: `studyloop plan repair <id>` and `studyloop plan status
<id> paused`.

#### Scenario: plan list marks the husk, filters to it, and every JSON row carries ready
- **WHEN** one ready active plan, one draft and one active document with no
  mission exist and `plan list`, `plan list --json`, `plan list --husks` and
  `plan list --husks --json` are run
- **THEN** the table's Status cell reads `active !` for the husk and `active` /
  `draft` for the others; every JSON row has 18 keys with `ready` `true` /
  `false` / `false`; `--husks` lists only the husk in both forms

#### Scenario: plan repair on a husk launches once with the blockers first and creates nothing
- **WHEN** `plan repair husk` is run on an active document with no mission,
  created before the gate date
- **THEN** exactly one `start_session` call is made with `mode="plan-architect"`
  and `topic` equal to the plan's title; the brief's first section lists
  exactly the two mission blockers; the brief names the title, status,
  topics and `0/1` milestones and says `predates the readiness gate`; the
  intro says `PLAN REPAIR` and not `build a study plan`; the plans directory
  and the checkpoint history are unchanged

#### Scenario: plan repair is honest when provenance is unknown
- **WHEN** `plan repair husk` is run on a husk whose `created` is after the
  gate date
- **THEN** the brief says `cannot tell how it got that way`, does not say
  `predates the readiness gate`, and does not say `hand edit`

#### Scenario: Nothing to repair, unknown id, refusal names both exits
- **WHEN** `plan repair glue-etl` is run on a ready active plan; `plan repair
  nope` on no such plan; and `plan evaluate husk --record` on a husk
- **THEN** the first exits `0` with `Nothing to repair on 'glue-etl'` and no
  launch; the second exits `1` naming `nope` with no traceback; the third
  exits `1` and names both `studyloop plan status husk paused` and `studyloop
  plan repair husk`

### Requirement: The plan CLI closes a fully-checked plan through the one launch chain, consensually
`studyloop plan close <id>` (item 4 / D-G) SHALL be the architect launch and
never a second path — the sibling of `plan repair`, through the same
`ctx.invoke(study, …, mode="plan-architect", topic=<the plan's title>,
brief=…, brief_intro=…)`. It SHALL `_inspect(id)` (unknown id → the seam's
not-found through `_fail_for`, exit `1`); SHALL exit `1` with `'<id>' still
has N open milestone(s)` and no launch while any milestone is open; SHALL
exit `1` with a pointer to `studyloop plan architect` for a plan with no
milestones; SHALL exit `0` with no launch for a plan that is already
`complete`; and for a fully-checked plan SHALL run the end assessment as a
**preview** (`AssessPlan(phase="end", record=False)`) and launch once. The
command itself SHALL write nothing: the document, the plans directory, the
plan's status and the checkpoint log are unchanged after it returns; the
status moves to `complete` only when the learner agrees in the launched
session and the architect calls `set_study_plan_status`.

The brief's first section SHALL be `### Closing review`, whose first four
`- ` lines are `Due reviews on plan concepts: N`, `Struggles on plan
concepts: N`, `Unverified milestones: N` and `Proposal: extend|close`,
followed by one `- ` evidence line per counted item — the same
`CompletionReview` the `now` engine puts on its completion action, so the two
never disagree on a count (new-topic rows excluded) — then the plan as it
stands (title, id, status, topics, milestones done/total, created), and a
`### Data gaps` section only when the evaluation reported a reader
unavailable. The `brief_intro` SHALL say `CLOSING REVIEW` and `only when the
learner agrees`, and SHALL NOT say `build a study plan`.

#### Scenario: plan close on a fully-checked plan launches once with the review first and writes nothing
- **WHEN** `plan close glue-etl` is run on an active plan whose two milestones
  are both done, with the due reader returning one real due row on a plan
  concept and one `New topic -- start fresh` row (`concept: None`)
- **THEN** exactly one `start_session` call is made with `mode="plan-architect"`
  and `topic` equal to the plan's title; the `### Closing review` section's
  first four lines are `Due reviews on plan concepts: 1`, `Struggles on plan
  concepts: 0`, `Unverified milestones: 0`, `Proposal: extend`, followed by an
  evidence line naming the due concept; the brief says `2/2`; the intro says
  `CLOSING REVIEW` and `only when the learner agrees` and not `build a study
  plan`; the plans directory, the plan's `active` status and the checkpoint
  history are unchanged

#### Scenario: plan close on an unfinished plan refuses without launching
- **WHEN** `plan close glue-etl` is run on an active plan with two open
  milestones
- **THEN** it exits `1` with `'glue-etl' still has 2 open milestone(s)`, no
  traceback, no launch, and the plans directory unchanged
