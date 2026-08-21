# Study Plan Protocol

How to build a study plan *with* the learner, and how to keep it honest once it
exists. Shared by the `study-plan-architect` agent on every harness, and read by
the Socratic mentor whenever a session runs against a plan.

Adapted from Matt Pocock's `teach` skill
(<https://github.com/mattpocock/skills/tree/main/skills/productivity/teach>):
mission-first, learning records as ADRs for learning, primary sources over
recalled knowledge. StudyLoop collapses that multi-file workspace into one
Markdown document per plan so it renders as a single page in the web UI and
stays diffable in git.

## The contract

A plan is a Markdown document. `studyloop plan` is the only way you touch it —
never hand-edit the file, and never write to `.storage` or the sessions DB
directly.

```bash
studyloop plan list                 # what plans exist
studyloop plan interview --json     # the questions to ask + evidence to ground them
studyloop plan show ID              # structure + what is still missing
studyloop plan show ID --markdown   # the document itself
studyloop plan new --title ...      # create (see Creating below)
studyloop plan evaluate ID --phase start|mid|end [--record]
studyloop plan milestone ID INDEX --done
studyloop plan status ID active     # refused while the plan is unevaluable
```

## Two jobs

1. **Creating** a plan — an interview, not a form fill.
2. **Evaluating** a plan — three checkpoints in every session that runs against
   it: `start`, `mid`, `end`.

---

## Job 1 — Creating a plan

### Never write the plan before you understand the mission

`studyloop plan interview --json` returns the question set *and* a `seed` block
built from the learner's own history: topics they are struggling with, concepts
due for review, and questions they keep re-asking. Open with that evidence:

> "You've asked about Glue job bookmarks in four sessions this month. Is that
> what this plan is really about?"

Grounding the first question in evidence beats "what would you like to learn?",
which invites a vague answer you will then be stuck building on.

### Work the questions in order, one at a time

The interview is ordered deliberately. Each answer bounds the next question.
Ask **one** question, stop, and wait — the same rule as any Socratic turn.

| Question | What a usable answer looks like | Push back when |
|---|---|---|
| Why | A change in their work or life | It is "to understand X" — that is a topic, not a reason |
| Success looks like | 2-4 things they will be able to *do* | It restates the why, or cannot be observed |
| Topics | Existing StudyLoop topics | Invented topics that match nothing in the DB |
| Constraints | Hours per week, days, energy levels | "As much as it takes" — that plans for a good day only |
| Out of scope | Named adjacent rabbit holes | Empty — then the parking lot has no rule to apply |
| Milestones | 3-6 steps, each one session's work | Fewer than 3 (untrackable) or more than 8 (two plans) |
| Target date | A real date, or nothing | A date invented to fill the field |
| Resources | Sources they already trust | — |

**A bad mission is worse than no mission.** A plan whose `why` is vague produces
milestones no evaluation can judge, and the learner ends up managing the plan
instead of learning. If they cannot articulate why after two attempts, say so
plainly and offer to park the plan until they can.

### Name concepts on every milestone

```
Understand Glue job anatomy (concepts: glue job, job bookmark)
```

The `(concepts: ...)` suffix is the join key against `study_progress`. Without
it, an evaluation cannot tell a milestone that was genuinely learned from one
that was merely ticked — the `claimed-done-without-evidence` signal goes dark
and the plan quietly starts lying.

### Then create it

```bash
studyloop plan new --title "Ship a Glue ETL Job" \
  --why "Own the nightly customer-events pipeline without pairing." \
  --success "Deploy a Glue job unaided" \
  --success "Explain the job bookmark to a colleague" \
  --topic data-engineering --topic python \
  --milestone "Understand Glue job anatomy (concepts: glue job, job bookmark)" \
  --milestone "Write the transform (concepts: dynamicframe)" \
  --milestone "Schedule and monitor it (concepts: cloudwatch)" \
  --out-of-scope "EMR tuning" \
  --resource "https://docs.aws.amazon.com/glue/latest/dg/"
```

The command prints `readiness`: **blockers** stop activation, **nudges** are
worth fixing but not fatal. Read them back to the learner rather than silently
accepting a weak plan, then activate:

```bash
studyloop plan status ship-a-glue-etl-job active
```

Activation is refused while the plan has no mission, no success criteria, or no
milestones. That refusal is the feature — an unevaluable plan must not be able
to masquerade as an active one.

### Revising a plan

Missions change. When the learner discovers they care about something different,
confirm it explicitly, then update the plan and record a learning record saying
what changed and why. Do not let a stale mission steer future sessions, and do
not rewrite a mission without asking.

---

## Job 2 — Evaluating a plan

Run all three checkpoints. A plan that is only checked at the start becomes a
wish list; one that is only checked at the end cannot correct a drifting
session.

```bash
studyloop plan evaluate PLAN_ID --phase start --record --study-id "$STUDY_ID"
```

Print the returned Markdown block into the conversation. It is written to be
read by the learner, not parsed by you.

### `start` — is this still the right thing, and what is next?

Run it **before** the first teaching turn, along`studyloop resume` and
`studyloop review`. Then:

- Open with any due review the plan names — retrieval practice first, new
  material second.
- Work the `next_milestone`, not whatever is most interesting.
- If the verdict is `stalled`, do not re-litigate the plan. Pick the smallest
  possible win and rebuild momentum.
- If `unverified_milestones` is non-empty, quiz one of them. A milestone ticked
  without evidence is the most likely place the plan has drifted from reality.

### `mid` — is this session drifting?

Run it at the first natural break (see `break-science.md` for the
energy-adaptive schedule). `drift_topics` lists what recent sessions are
actually about that the plan does not claim. Drift is information, not
misbehaviour:

- **Tangent** → `studyloop park "..."` and return to the milestone.
- **The plan was wrong** → say so, and offer to re-scope it.

Never silently follow the drift. The learner chose this plan; a change of
direction is their call.

### `end` — what moved, and what does the plan owe next time?

Run it during wind-down, before `studyloop session end`:

1. Tick what was genuinely completed:
   `studyloop plan milestone PLAN_ID 0 --done`
2. Record per-concept confidence: `studyloop progress "<concept>" -t <topic> -c <confidence>`
   — this is what the *next* `start` checkpoint reads.
3. Write a learning record if a misconception was corrected, prior knowledge was
   disclosed, or understanding genuinely deepened. Not for coverage: being shown
   something is not learning it.
4. Record the checkpoint with `--record` so the verdict is durable.
5. State the next session's target out loud.

**Only tick a milestone the learner demonstrated.** Ticking it for them
manufactures the exact false progress the evaluation exists to catch.

## Verdicts

| Verdict | Means | Do |
|---|---|---|
| `on-track` | Progressing, no contradicting signal | Continue with `next_milestone` |
| `at-risk` | Struggle signal, unverified milestones, or the target date is slipping | Address the named cause before new material |
| `stalled` | No plan activity for 14+ days | Smallest possible win; consider re-scoping |
| `complete` | Every milestone ticked | Close the plan, or extend with a follow-on mission |

`warnings` means the evaluation is **partial** — a table was unavailable (normal
on a fresh install). Say so rather than presenting a partial verdict as
complete.

## Anti-patterns

- **The form fill** — firing all eight questions at once. It is an interview.
- **Planning instead of learning** — a 40-minute planning session is a failure
  mode, not thoroughness. Aim to finish a plan in under 10 minutes and improve
  it from evidence later.
- **The invented deadline** — leave `target_date` blank rather than making one
  up. A fake date produces a fake `at-risk` verdict.
- **Milestones without concepts** — silently disables evidence checking.
- **Ticking for the learner** — the plan then lies to every future session.
- **Ignoring `out_of_scope`** — it is the rule the parking lot applies.
- **Hand-editing the document** — bypasses validation and the derived index.
