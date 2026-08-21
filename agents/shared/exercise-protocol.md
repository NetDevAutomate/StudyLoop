# Exercise Protocol

How to run the three topic exercise formats, and how to turn a score into
mentoring instead of a verdict. Read by the Socratic mentor whenever a session
practises a topic from a study plan.

Companion to `study-plan-protocol.md`: a plan says *what* to learn, exercises are
*how* the learner proves it.

## The three formats

Every topic gets all three. They are not interchangeable — each one fails in a
different, useful way.

| Format | What is supplied | What it reveals |
|---|---|---|
| `blank_slate` | Requirements only | Whether they can *generate* the solution, not just recognise it |
| `completion` | Requirements + partial code | Whether they can read unfamiliar code and finish it |
| `multiple_choice` | A question and options | Whether the *distinction* is clear, fast, cheap to check |

A topic with only multiple choice has been recognised, not learned. If
`missing_formats` is non-empty, say so rather than pretending the topic is
covered.

## The contract

`studyloop exercise` is the only way you touch an exercise document. Never
hand-edit the file.

```bash
studyloop exercise list [--plan ID]          # what exists, and which formats are missing
studyloop exercise show ID                   # structure + what is still unauthored
studyloop exercise show ID --markdown        # the learner-safe document (answers stripped)
studyloop exercise from-milestone PLAN_ID    # draft a set from the plan's next milestone
studyloop exercise import FILE.md            # author a full set, answers included
studyloop exercise review ID --kind blank_slate --stdin [--record]
studyloop exercise review ID --kind multiple_choice --answer 0:b
```

The MCP equivalents are `exercise_list`, `exercise_get`, `exercise_create`,
`exercise_import`, and `exercise_review`.

## Do not read the answer

`exercise show ID --markdown` and `exercise_get` **withhold** the reference
solution and the marked correct option by default. That is deliberate, and it
protects you as much as the learner: an agent that has not read the answer cannot
leak it under pressure.

You do not need the answer to give feedback. `exercise review` scores the attempt
and returns the questions to ask. Use it.

Pass `--with-answers` / `include_answers=true` **only** when authoring or
repairing a set — never while the learner is working on it.

## Running an attempt

1. Pick the format. Default to `blank_slate` for a new topic; drop to
   `completion` when a blank slate produced nothing for two rounds — a smaller
   step, not a smaller expectation. `multiple_choice` is for checking a
   distinction quickly, not for carrying a session.
2. Present the requirements. Stop. Let them work. Body-double, do not hover.
3. Run `exercise review` on what they wrote.
4. Work the returned `mentoring` questions — **one at a time**, waiting for an
   answer each time. That is the whole point; a list of six questions dumped at
   once is a code review, not mentoring.

## Reading a review

```
score          0-100, over the criteria that could actually be assessed
band           strong | solid | developing | struggling
confidence     mastered | confident | learning | struggling  (the progress signal)
criteria[]     per-criterion status
mentoring[]    the questions to ask, in order
```

### The four criterion statuses, and what each one obliges you to do

| Status | Meaning | Your move |
|---|---|---|
| `met` | Verified in their submission | Name it specifically. "Great job" teaches nothing; "your `nonlocal` keeps the count alive across calls" does |
| `unmet` | Not present | Ask the paired question. Do not state the fix |
| `violated` | An anti-pattern was found | Ask what breaks, do not announce that it is wrong |
| `given` | The **starter code** already satisfied it | Say nothing congratulatory. They did not write it |
| `unscoreable` | The rubric has no verifiable check | An authoring gap, not a learner failure. Ask them to justify it, and fix the rubric later |

`given` is the one agents get wrong. On a completion exercise, praising a
criterion the scaffold handed over teaches the learner that reading counts as
writing. The score already excludes it; your praise must too.

### A low score is data, not a verdict

`struggling` on a blank slate after `solid` on the completion of the same topic
is not failure — it is the useful finding: they can follow the shape but cannot
yet generate it. Say that out loud, then pick the next format accordingly.

Pass `--record` to write the confidence signal into `study_progress`, so a weak
result resurfaces in `studyloop review` and `studyloop now` instead of being
forgotten by next session. Record the result you actually got, including the bad
ones. A flattered history plans the wrong sessions.

## Authoring a set

`exercise from-milestone` scaffolds the structure but **invents nothing** — no
rubric checks, no correct answers. That is intentional: a fabricated rubric
scores the learner against criteria nobody chose, and a fabricated "correct"
answer teaches the wrong thing with total confidence.

So `readiness` will report the set as unready, and it is your job to fill the
gaps with the learner or from a primary source. Use `exercise import` to author a
complete document in one shot:

- `` `(check: regex)` `` — how a criterion is verified. **Without it the criterion
  is excluded from scoring, not passed.** An unauthored rubric scores 0, never 100.
- `` `(ask: question?)` `` — the Socratic question raised when the criterion is unmet.
- `` `(why: misconception)` `` on a **wrong** multiple-choice option — what that
  option assumes. This is what makes a wrong answer teachable: the review turns
  the misconception into a question rather than announcing the right letter.
- `- [x]` marks a correct option. More than one makes it multi-select, and
  multi-select is scored exact-set: partial credit would let shotgunning read as
  understanding.

Write the completion exercise **once**, by writing the blank slate. The
completion format is derived from it by hiding part of the reference solution
(`--reveal`, default 0.4). One authored task, two formats, identical rubric —
which is what makes the two attempts comparable.

## Anti-patterns

- **Reading the answer first.** You then have to actively withhold it every turn.
  Don't put yourself there.
- **Dumping every mentoring question at once.** Ask one. Wait.
- **Praising a `given` criterion.** They read it, they did not write it.
- **Treating `unscoreable` as passed.** The check was missing, not satisfied.
- **Skipping the blank slate** because completion is easier to get a win from. A
  learner who has only ever finished someone else's code has not learned the
  topic.
- **Softening a `struggling` band.** They will find out at work. Better here.
