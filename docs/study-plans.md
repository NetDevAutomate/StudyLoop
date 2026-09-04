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

!!! important "The current form is manual"
    The free-text brain dump is saved as context, but the Web UI does not
    currently ask an agent to decompose it into the structured fields. An
    agent-led planning interview exists as repository work, but it is not an
    integrated Web UI path yet.

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

## What a plan does not do yet

- An active plan does not currently bias the recommendation from `studyloop now`
  or the Today card.
- The Web UI does not launch a planning agent or automatically structure the
  brain dump.
- There are no study-plan MCP tools; agents that manage plans use the CLI.

These gaps are stated here so that a plan never appears more connected than it
is. See the [roadmap](roadmap.md) for the intended continuity work.

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
