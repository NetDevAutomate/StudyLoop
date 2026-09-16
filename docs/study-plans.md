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
above, then evaluates the plan against real study evidence at the start,
middle, and end of every session run against it. It ships to every harness —
see [Connect your AI coding tool](agent-install.md) for the native start
command on your harness. The launcher-driven form works everywhere:

```bash
studyloop plan architect
# or, choosing a harness explicitly:
studyloop study --mode plan-architect --agent claude
```

In the Web UI, **Plan with architect** on the **Study Plans** view (beside
**New plan**, with an optional subject) starts the same interview as a
*planning* session in the Study Session console, using the agent and transport
the start picker has selected. The console is labelled as a planning session,
and the label survives a page reload. The click creates nothing: the plan
appears in the list when the interview creates it. If a session is already
running, the console offers to reattach to it or end it first, exactly as a
normal start does.

Whichever door starts it, the architect works from a planning brief — the
interview questions, an evidence seed from your study history, and the plans
that already exist — and creates, revises, activates, and evaluates plans
through the same plan tools an MCP-connected agent uses (see
[Study-plan tools over MCP](agent-install.md#study-plan-tools-over-mcp)),
falling back to `studyloop plan …` at a shell when its harness has no
`studyloop` server. Activation is readiness-gated on every one of those
paths, and deleting a plan needs your explicit confirmation. The
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

## Plan-aware now

An active plan changes what StudyLoop recommends. `studyloop now`, the Web
**Today** card, the daily `recap`, and the MCP `get_next_action` tool all read
one recommendation result, and that result considers every active plan: the
action that advances a plan's next milestone is named with the plan and the
milestone it serves, a plan with no other evidence still gets its next
milestone suggested, and a plan whose energy floor is above your current
energy has that milestone deferred with a reason rather than dropped. This is
plan-aware guidance with tested ranking rules — a bias, not a filter: an
overdue review or a fresh struggle on an unrelated topic can still outrank new
milestone work, and with no active plan the recommendation is exactly what it
was before plans existed. The ranking rules are tested; whether the primary is
the action *you* would take is a separate judgement, recorded per scenario in
the project's rubric receipt rather than claimed here.

## Deliberately not automatic

A plan biases guidance and gives agents a full set of lifecycle tools. It does
**not** run the session. By design, StudyLoop does not:

- **bind a live study session to a plan** — starting a study session never
  selects a plan and never stores a plan id on the session; the planning
  session the architect runs in is labelled `planning`, and that label is all
  it persists.
- **run checkpoints from session events** — start, mid, and end evaluations
  happen when you (or the architect) ask for them; a preview writes nothing,
  and only an explicit record is kept.
- **complete milestones from study evidence** — a milestone is checked off by
  you or by the architect, never inferred from a session.
- **enforce one active plan** — every active plan is considered,
  deterministically; none is a hidden singleton.
- **turn a plan into a filter** — off-plan study is never blocked, and urgent
  reviews or struggles can outrank plan work.
- **structure the manual form's brain dump** — the free text is saved as
  context; the architect interview is the door for an agent-led decomposition.

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
