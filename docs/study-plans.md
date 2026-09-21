# Study Plans

A study plan gives a larger learning goal enough shape to guide a session without
turning planning into another project. It records why the goal matters, what
success would look like, and a small set of milestones you can actually check.

Plans are optional. Study Session, review, and Today all work without one.

## Create a plan in the Web UI

1. Run `studyloop web` and open **Study Plans** in the sidebar.
2. Select **New plan**.
3. Start with the large prompt: describe where you are now, where you want to get
   to, what you have tried, and what tends to block you.
4. Fill in or edit **Title**, **Why**, **Success looks like**, **Topics**, and
   **Milestones**.
5. Create the plan, read it back, and change anything that does not sound like
   your own goal.

!!! important "The form is manual; the interview is the other door"
    The free-text brain dump is saved as context, but the Web UI does not
    ask an agent to decompose it into the structured fields. For an agent-led
    interview instead, choose **Plan with architect** beside **New plan** —
    see [Build a plan with the study-plan-architect](#build-a-plan-with-the-study-plan-architect).

## Keep the plan small enough to use

A useful plan can answer three questions:

- **Why:** what becomes possible if I learn this?
- **Success:** what could I do or explain that would demonstrate it?
- **Next milestone:** what is the next observable piece of progress?

Three to five milestones are usually easier to return to than a complete
curriculum. Add a constraint or an out-of-scope item when it protects the plan
from expanding.

Example:

```text
Title: Understand Python decorators
Why: Read and change the decorators used in our data pipelines
Success looks like:
- Explain the wrapper relationship without notes
- Write and test one timing decorator
Topics:
- python
Milestones:
- Trace a decorated function call (concepts: wrapper, closure)
- Write @timed with functools.wraps (concepts: decorator, wraps)
- Test metadata and return values (concepts: testing, function metadata)
```

The `(concepts: ...)` suffix is optional, but useful: it connects a milestone to
the confidence evidence StudyLoop records for those concepts.

## Use checkpoints instead of guilt

Open a plan and use the **Checkpoint** controls at three natural moments:

- **Start:** is this still the right work, and what is the smallest next step?
- **Mid:** has the session drifted, or has the plan itself proved wrong?
- **End:** what moved, what evidence exists, and what should be left ready?

A checkpoint can describe a plan as `on-track`, `at-risk`, `stalled`, or
`complete`. These labels describe the plan and its evidence, not the learner.
Previewing a checkpoint does not save it; choose **Record checkpoint** when the
result is worth preserving.

Milestone checkboxes update the Markdown plan itself. Activation is refused when
the plan has no mission, success criteria, or milestones, because an empty active
plan would create noise rather than direction.

## Activation

Creating, importing, replacing, or revising a plan through supported Web
operations checks the resulting document before saving it as active. CLI
activation commands also refuse plans missing a mission *why*, success
criteria, or milestones. Refused activation writes nothing. More than one plan
may be active.

## Build a plan with the study-plan-architect

Instead of filling in the form yourself, be interviewed. The
`study-plan-architect` persona runs the mission-first interview described
above, and it is instructed to check the plan against real study evidence at
explicit start, mid, and end checkpoints during a session you ask it to work
on. Those checkpoints run when you or the architect ask for them: StudyLoop
never fires them from session events and never binds the conversation to a
plan (see [Deliberately not automatic](#deliberately-not-automatic)). The
persona definitions ship to every harness — see
[Connect your AI coding tool](agent-install.md) for the native start command
on yours; which harness definitions also attach the `studyloop` MCP server is
a per-harness fact, stated there. The launcher-driven form works everywhere:

```bash
studyloop plan architect
# or, choosing a harness explicitly:
studyloop study --mode plan-architect --agent claude
```

In the Web UI, **Plan with architect** on the **Study Plans** view (beside
**New plan**, with an optional subject and an optional brain dump) starts the
same interview as a *planning* session in the Study Session console, using the
agent and transport the start picker has selected. The console is labelled as
a planning session, and the label survives a page reload. The click creates
nothing: the plan appears in the list when the interview creates it. If a
session is already running, the console offers to reattach to it or end it
first, exactly as a normal start does; ending the session before you have
answered anything leaves no plan and frees the slot.

The planning brief — the interview questions, an evidence seed from your
study history, the plans that already exist and, when you typed one, your
brain dump as its own quoted section — is built into the persona on the Web
door (`purpose=planning`). The brain dump reaches the architect exactly as
written (up to 4000 characters), as evidence to open the interview from; it
is never the session's topic, is not decomposed by StudyLoop, and is not
stored on the session — it travels once, inside the persona. The architect's
one-question-at-a-time protocol is persona text: the browser tests prove the
brief is delivered, not how a live model behaves with it. An architect started from a shell or
from a harness gathers the same material itself: over MCP with
`get_planning_interview`, or with `studyloop plan interview`, which prints the
questions and the seed and starts no agent. From there the architect creates,
activates, and evaluates plans through the same plan tools an MCP-connected
agent uses (see
[Study-plan tools over MCP](agent-install.md#study-plan-tools-over-mcp)),
falling back to `studyloop plan …` at a shell when its harness has no
`studyloop` server. Two operations have no CLI command — revising an existing
plan's fields and deleting a plan — so an architect without the server says
so instead of improvising: both need an MCP-connected session
(`update_study_plan`, `delete_study_plan`) or the Web API; the Web UI itself
offers neither control. A plan's mission — why, success criteria, constraints,
out of scope — is revisable on those same two doors (`update_study_plan`, and
`PATCH /api/plans/{id}` with the matching keys), or by editing its Markdown.
Activation is readiness-gated on every one of those paths. The
`record_plan_learning` tool the second-brain wind-down calls before any
projection (see [second-brain.md](second-brain.md)) is part of the same set.

## Use plans from the terminal

```bash
# See what exists
studyloop plan list
studyloop plan show PLAN_ID

# Create a small plan
studyloop plan new \
  --title "Understand Python decorators" \
  --why "Read and change our pipeline decorators" \
  --success "Explain the wrapper relationship" \
  --topic python \
  --milestone "Trace a decorated call (concepts: wrapper, closure)"

# Check and update it
studyloop plan evaluate PLAN_ID --phase start
studyloop plan milestone PLAN_ID 0 --done
studyloop plan status PLAN_ID active
```

Run `studyloop plan interview` to print the questions an agent-led planning
conversation should work through. It does not itself start an agent.

## Recording, retries, and deletion

A few behaviours are the same on every door and worth knowing before you
script against plans or ask an agent to:

- **A recorded checkpoint reports each write.** Recording writes to two
  places: the checkpoint log in the session database and the plan document.
  When one of those writes fails the evaluation is still returned — it
  succeeded — and the result says which write did not land. Over MCP that is
  `db_write`, `document_write` and `recording_complete: false` with the reason
  in `warnings`; at the terminal `studyloop plan evaluate … --record` prints
  `Checkpoint recorded.` only when both writes saved, otherwise `Checkpoint
  partially recorded — database: …, document: …` (or `Checkpoint not
  recorded` when neither landed), still exiting 0; the Web UI shows the same
  three outcomes after **Record checkpoint**. A preview is "not recorded";
  "partially recorded" is a different thing and is never rounded up.
- **Milestone flags are retry-safe; omitting them toggles.** `studyloop plan
  milestone PLAN_ID 0 --done` (or `--undone`) sets the state you asked for,
  so running it twice is safe. Without a flag the command reads the current
  state and sets its opposite — a toggle, which a blind retry undoes. The MCP
  `set_study_plan_milestone(plan_id, index, done)` is always a set. The Web
  checkbox uses a toggle request, fine for a click and not safe to replay; a
  caller that needs replay safety states the desired state (`PATCH` with
  `milestones`, or the CLI flags).
- **An active plan that is no longer complete is paused or repaired before
  it is written to.** Reads and previews still work; a milestone, a revision
  or a recorded checkpoint that appends to the document is refused with the
  blockers named until you pause the plan (`studyloop plan status PLAN_ID
  paused`) or repair the missing parts. You do not have to trip over the
  refusal to find such a plan: `studyloop doctor` names each one with its
  blockers, `studyloop plan list` marks it `!` after its status (`--husks`
  lists only those; every `--json` row carries `ready`), the Web sidebar
  shows the same mark, and `GET /api/plans` rows carry `ready`. Repair is a
  conversation: `studyloop plan repair PLAN_ID` launches the architect with
  the blockers as the first section of its brief and the plan as it stands,
  and writes nothing itself; the architect then repairs every blocker class
  the gate names — mission, success criteria, milestones — with
  `update_study_plan` (or you can, with `PATCH /api/plans/{id}`). One honest
  limit: while the plan is active, a write that leaves any blocker standing
  is still refused, so either everything is repaired in one write or the plan
  is paused first and re-activated once ready. The brief says how the plan
  got that way only when the seam knows (a document that predates the gate);
  otherwise it says it cannot tell.
- **Deletion is explicit on every door, and history is kept.** The Web UI has
  no delete control; its API's `DELETE /api/plans/{id}` treats the request
  itself as the confirmation. Over MCP `delete_study_plan` is refused unless
  `confirmed=true`, and the architect persona asks you first. The CLI has no
  delete command. Deleting a plan removes the document and keeps its
  checkpoint history in the session database.

## Plan-aware now

An active plan changes what StudyLoop recommends. `studyloop now`, the Web
**Today** card, the daily `recap`, and the MCP `get_next_action` tool all read
one recommendation result, and that result considers every active plan: the
action that advances a plan's next milestone is named with the plan and the
milestone it serves; a **ready** plan whose next milestone is within your
current energy gets that milestone suggested even when no other evidence
points at it; and a plan whose energy floor is above your current energy has
that milestone deferred with a reason rather than dropped. Repair has an
energy demand of its own: on a low-energy day a **live** struggle (recorded
as struggling within the last two weeks) is deferred like new work — listed,
not recommended — an older struggle or a weak teach-back needs medium energy,
and a concept you are still learning is the gentle review that stays
available at any energy; due reviews are never deferred. When nothing
plan-related fits the day's energy, the recommendation is to **sit with the
plan** — a body-double session: you drive, the companion stays quiet unless
you ask — with the recorded progress named first and the deferred items after
it, then one **first move**, if you want one: open the deferred milestone's
material (the indexed lesson when one matches its concepts, otherwise the
milestone by name) and read for ten minutes, nothing more. It is a proposal
you may ignore — never an exercise, never a question — and the Body Double
picker shows it beneath the plan title when you arrive from the Today card. A
real, unrelated action still outranks the sit-with proposal
when one exists. An active plan that
is **not ready** — a hand edit removed its mission or its milestones — is
listed with a warning naming what to repair; it still biases related work,
but no milestone is suggested for it until it is paused or repaired. A plan
whose milestones are all checked appears as a completion action instead of
new work, and that action is a **closing review**, not a verdict: the engine
reads the plan's end assessment as a preview — due reviews and struggles on
the plan's own concepts, and milestones marked done with no evidence behind
them — and proposes *extend* while any count is above zero, *close* when all
three are zero, with one evidence line per counted item. The scheduler's
"new topic — start fresh" rows are not counted as due here: a topic you never
logged progress on is not a lapsed review, and a plan you have just finished
should not tell you to start fresh. Nothing about a plan's status changes
because of the review; `studyloop plan close PLAN_ID` launches the architect
with the same review as the first section of its brief, and the plan becomes
`complete` only when you agree in that conversation (the architect calls
`set_study_plan_status`). A plan you had paused or abandoned, or never
activated, can be closed the same way once every milestone is checked — the
architect asks whether you want it closed (kept as `complete`) or deleted, and
deletes only when you say so. If the assessment cannot be read, the completion
action keeps its plain sentence and a warning says why — a failure is never
shown as a clean slate. This is plan-aware guidance with tested ranking rules — a bias, not
a filter: an overdue review or a fresh struggle on an unrelated topic can
still outrank new milestone work. With no active plan the recommendation is
unchanged — except that repair above the day's energy (a live or older
struggle, a weak teach-back) is deferred whether or not a plan names it; a
plan that cannot be read adds a warning and nothing else. The
ranking rules are tested; whether the primary is the action *you* would take
is a separate judgement. Five frozen scenarios and the engine's primaries are
in the project's rubric receipt
(`docs/architecture/plan-integration/receipts/now-rubric-2026-09-16.md`),
scored by the maintainer on 2026-09-16: the matching-due, urgent-unrelated
and no-plan scenarios and the fully-checked plan's primary were accepted; the
energy-deferred scenario (hands-on repair of a live struggle on a low-energy
day) and the completion action's wording were not. The energy-deferred
scenario is still follow-on work rather than an edit to the ranking; the
completion action was reworked into the closing review described above, and
its re-run row was scored by the maintainer on 2026-09-18 — accepted on both
readings, the evidence-backed *extend* and the clean *close*.

## Deliberately not automatic

A plan biases guidance and gives agents a full set of lifecycle tools. It does
**not** run the session. By design, StudyLoop does not:

- **bind a live study session to a plan** — starting a study session never
  selects a plan and never stores a plan id on the session; the planning
  session the architect runs in is labelled `planning`, and that label is all
  it persists. A planning session takes the same single session slot as any
  other session: one live session at a time, and no second session authority.
- **run checkpoints from session events** — start, mid, and end evaluations
  happen when you (or the architect) ask for them; a preview writes nothing,
  and only an explicit record is kept.
- **complete milestones from study evidence** — a milestone is checked off by
  you or by the architect, never inferred from a session.
- **enforce one active plan** — every active plan is considered,
  deterministically; none is a hidden singleton.
- **turn a plan into a filter** — off-plan study is never blocked, and urgent
  reviews or struggles can outrank plan work.
- **schedule recurring planning sessions** — a planning session starts only
  when you ask for one, from the Web control or the launcher; nothing
  re-opens the interview on a timer or books the next one.

One related limit is a fact about a door rather than an automation StudyLoop
refuses: the manual form's free-text brain dump is saved as context and never
decomposed into the structured fields. The architect interview is the door for
an agent-led decomposition, and the Web **Plan with architect** control carries
its own optional brain dump to the architect as evidence — StudyLoop itself
still decomposes nothing. The same holds at the other end of a plan: checking
off the last milestone never completes it. The plan gets a closing review and
a proposal, `studyloop plan close` opens the conversation, and the status
moves to `complete` only when you agree in it.

These boundaries are stated here so that a plan never appears more connected
than it is. See the [roadmap](roadmap.md) for the intended continuity work.

## Where plans live

Plans are Markdown files stored in StudyLoop's local state directory. Find the
exact folder with:

```bash
studyloop plan path
```

The plan document is the **single source of truth**. If you publish a plan into a
second brain (see [Second Brain](second-brain.md)), what appears there is a
projection: regenerated from this document and never read back into it.

Because the document is the source of truth, it remains readable and editable
without the Web UI. Checkpoint history is also indexed in the session database.

## When planning becomes avoidance

Stop editing the plan and choose a five-minute action if you notice yourself:

- refining milestone wording without trying one;
- adding resources faster than you use them;
- inventing target dates without a real deadline;
- treating a missing plan field as a reason not to study.

The plan exists to make the next session easier to start. A rough plan that gets
used is doing its job.
