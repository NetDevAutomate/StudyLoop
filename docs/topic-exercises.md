# Topic Exercises (Developer Preview)

> [!WARNING]
> This capability is not part of StudyLoop's supported learner surface. Its
> value alongside the mentor's existing Socratic workflow is still unproven.
> It is retained for evaluation and may be reconsidered if learners ask for it.
> Access requires an explicit development gate: `studyloop --dev exercise …`,
> `studyloop web --dev` for the HTTP API, or `studyloop-mcp --dev` in an MCP
> server config. Normal CLI help, MCP `tools/list`, and the production web API
> do not expose exercises.

For a generic MCP config, the development flag is explicit in the server's
`args` array:

```json
{
  "mcpServers": {
    "studyloop-mcp": {
      "command": "studyloop-mcp",
      "args": ["--dev"]
    }
  }
}
```

Removing `--dev` removes every `exercise_*` tool from discovery; the tools do
not remain registered behind runtime errors.

Every topic in a study plan gets exercises in **three shapes**. The learner
attempts one, StudyLoop scores it, and the gaps come back as *questions* rather
than as the answer.

The `study-mentor` / `socratic-mentor` agents run these during sessions. Both go
through `studyloop --dev exercise`. See
[`agents/shared/exercise-protocol.md`](https://github.com/NetDevAutomate/StudyLoop/blob/main/agents/shared/exercise-protocol.md)
for the agent-facing rules.

## The three formats

| Format | What is supplied | What it reveals |
|---|---|---|
| `blank_slate` | Requirements only | Whether the learner can **generate** the solution |
| `completion` | Requirements + partial code | Whether they can read unfamiliar code and finish it |
| `multiple_choice` | A question and options, authored in Markdown | Whether a **distinction** is clear — fast and cheap to check |

A topic covered only by multiple choice has been recognised, not learned.
`missing_formats` on every listing reports which shapes are absent, so a partial
set is never mistaken for a complete one.

## One pipeline, not two features

The two code formats are the *same* feature. They differ by exactly one field —
`starter_code` — and run through one function, `review_code()`. "How much
starting code is supplied" is a parameter (`--reveal`, default `0.4`), not a code
path.

```
                      ┌───────────────────────────┐
  blank_slate  ──────►│                           │
  (starter = "")      │   review_code()           │──►  score
                      │   • criteria statuses     │     band / confidence
  completion   ──────►│   • Socratic questions    │     mentoring[] (questions)
  (starter = partial) │   • leak scrubbing        │
                      └───────────────────────────┘
```

That single pipeline is what makes the two attempts comparable: same
requirements, same rubric, same scoring. The only thing that changes is how much
of the shape the learner was handed.

### Supplied code earns nothing

The design decision that keeps completion scores honest: a criterion the **starter
code already satisfies** is recorded `given` and excluded from the score
entirely — from the numerator *and* the denominator.

Without this, a learner who submits the scaffold unchanged would inherit its
criteria as passes and score highly for code they never wrote. With it, that
submission scores **0**, with a warning saying why.

| Status | Meaning | Counts toward score? |
|---|---|---|
| `met` | Verified in the submission | Yes |
| `unmet` | Not present | Yes (as a miss) |
| `violated` | An anti-pattern was found | Yes (as a miss) |
| `given` | Supplied by the starter code | **No** — not the learner's work |
| `unscoreable` | The rubric has no verifiable check | **No** — an authoring gap, not a learner failure |

`unscoreable` exists because the alternative is worse. A criterion with no
`check` pattern cannot be verified; treating it as met would award full marks to
`def f(): pass`. So an unauthored rubric scores **0 with an explanation**, never
100.

## Improvements are asked, never told

Three layers enforce this, because a single one would eventually be bypassed:

1. **Every mentoring entry is question-shaped.** A criterion's `ask` annotation is
   the question raised when it is unmet; anything missing a `?` gets one.
2. **Leak scrubbing.** `scrub_leaks()` removes any substantive reference-solution
   line (≥ 14 characters) from the mentoring text before it is returned.
3. **The answer never reaches the client.** `GET /api/exercises/{id}` withholds
   the reference solution, the rubric `check` patterns, and which choice is
   correct. The document it serves is redacted *by construction* — a new object
   is built carrying only learner-visible fields and then rendered, so a field
   added later cannot leak by omission the way a blacklist regex would.

The E2E journey asserts layer 3 at the **network boundary**: every
`/api/exercises` response body observed by the browser is scanned for the hidden
solution. Asserting on the DOM alone would only prove the answer was not
*displayed*; this proves it was never *sent*.

Authors and grading agents opt in explicitly with `?include_reference=true`.

### Wrong multiple-choice answers are mentored, not corrected

A distractor carries a `why:` annotation naming the misconception it encodes. A
wrong answer turns that into a question about the learner's own reasoning:

> You picked the option that assumes globals are shared, so two counters would
> collide — what would have to be true about the code for that to hold?

The correct option is never named.

## File-first

The Markdown document is the source of truth:

```
<state_dir>/study-plans/exercises/<set-id>.md
```

Override with `STUDYLOOP_EXERCISES_DIR`; find the active directory with
`studyloop --dev exercise path`. Losing the database never loses an exercise.

### Document shape

Multiple choice is authored in plain Markdown — GFM task lists where `- [x]`
marks the correct option — so a quiz can be written in any text editor with no
tooling.

````markdown
---
id: python--closures
plan_id: python
topic: closures
concepts:
  - closures
---

# Closures

## Blank Slate

### Requirements

- `make_counter()` returns a callable that counts its own calls

### Rubric

- [3] Keeps state in the enclosing scope `(check: nonlocal\s+\w+)`
  `(ask: Where must the count live to survive between calls?)`

### Reference Solution

```python
def make_counter():
    count = 0

    def increment():
        nonlocal count
        count += 1
        return count

    return increment
```

## Completion

### Requirements
### Starter Code
### Rubric
### Reference Solution

## Multiple Choice

### Q1 — What keeps a closure's variable alive?

- [ ] The global namespace `(why: globals are shared between counters)`
- [x] A cell object held by the function

`(ask: What would happen if two counters shared one global?)`
````

Annotations are order-independent and strippable, matching the `(concepts: …)`
convention plan milestones already use:

| Annotation | Where | Purpose |
|---|---|---|
| `(check: regex)` | Rubric criterion | How the criterion is verified. **Absent ⇒ excluded, not passed** |
| `(forbid: regex)` | Rubric criterion | An anti-pattern that fails the criterion |
| `(ask: question?)` | Criterion or question | The Socratic prompt |
| `(why: misconception)` | A **wrong** choice | What that option assumes — makes the wrong answer teachable |

`[3]` is the criterion's weight. `- [x]` marks a correct option; more than one
makes the question multi-select, scored **exact-set** (partial credit would let
shotgunning every box read as understanding).

Round-trip fidelity holds: `parse_exercise_set(render_exercise_set(s)) == s` for
every field the parser knows, and unrecognised sections are preserved in `notes`
rather than dropped.

## CLI

```bash
studyloop --dev exercise list [--plan ID] [--topic T]   # what exists, which formats are missing
studyloop --dev exercise show ID                        # structure + what is unauthored
studyloop --dev exercise show ID --markdown             # the learner-safe document
studyloop --dev exercise show ID --with-answers         # authoring view

studyloop --dev exercise from-milestone PLAN_ID         # draft from the plan's next milestone
studyloop --dev exercise new --topic T --requirement R --reference sol.py [--reveal 0.4]
studyloop --dev exercise import FILE.md                 # author a full set, answers included

studyloop --dev exercise review ID --kind blank_slate --stdin [--record]
studyloop --dev exercise review ID --kind completion --file attempt.py
studyloop --dev exercise review ID --kind multiple_choice --answer 0:b --answer 1:a,c

studyloop --dev exercise path                           # where documents live
```

`--record` writes the derived confidence into `study_progress`, so a weak result
resurfaces in `studyloop review` and `studyloop now` instead of being forgotten.
Score bands map onto the existing confidence vocabulary:

| Score | Band | Confidence recorded |
|---|---|---|
| ≥ 90 | `strong` | `mastered` |
| ≥ 70 | `solid` | `confident` |
| ≥ 40 | `developing` | `learning` |
| < 40 | `struggling` | `struggling` |

## REST API

One review endpoint serves all three formats, because the domain has one
pipeline:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/exercises?plan_id=&topic=` | List sets with `missing_formats` |
| `GET` | `/api/exercises/{id}` | All three formats, **answers withheld** |
| `GET` | `/api/exercises/{id}?include_reference=true` | Authoring view |
| `GET` | `/api/exercises/{id}/markdown` | Redacted document (add `?include_reference=true` for the full one) |
| `POST` | `/api/exercises/{id}/review` | `{kind, submission \| answers, record}` → score + mentoring |
| `POST` | `/api/exercises` | Create from a task, a milestone, or raw Markdown |
| `PATCH` | `/api/exercises/{id}` | Update fields or replace the document |
| `DELETE` | `/api/exercises/{id}` | Delete the document |

Two write guards worth knowing about:

- A `markdown` body that carries none of the expected section headings is
  rejected, rather than persisted as a set with all three formats missing.
- A `PATCH` that would strip every reference solution and unmark every correct
  answer is refused with **409**. That is precisely what fetching the *redacted*
  `/markdown` and writing it back would do — silent, unrecoverable loss disguised
  as a successful save. Fetch with `?include_reference=true` to edit the authored
  document, or pass `"allow_answer_loss": true` when the removal is intended.

## MCP tools (`studyloop-mcp --dev` only)

When the MCP server command includes `--dev`, it registers `exercise_list`,
`exercise_get`, `exercise_create`, `exercise_import`, and `exercise_review`.
Without that flag none of those names appears in `tools/list`.

`exercise_get` withholds answers by default. That protects the agent as much as
the learner: an agent that has not read the solution cannot leak it under
pressure — and it does not need to, because `exercise_review` scores the attempt
and returns the questions to ask.

## Web UI — not built; API is dev-only

!!! warning "There is no Exercises panel in the browser"
    The backend REST surface in `web/routes/exercises.py` is registered only by
    `studyloop web --dev`; the normal app has no `/api/exercises` routes. No
    browser UI consumes it: there is no Exercises section in Study Plans, no
    tabs, and no attempt editor. For development evaluation use the gated
    [CLI](#cli), MCP server, or API. None is a supported learner workflow yet.

### The planned design

Kept here because it is a real design decision record, not a feature list. When the panel is built, this is the shape it should take:

- Three tabs over **one** attempt surface. Switching to Completion re-seeds the same editor with the supplied scaffold — visibly the same flow, because it is.
- The scaffold label states the parameter: "no starting code — you write all of it" versus "43% of the solution supplied".
- Criteria marked `✓ met`, `• unmet`, `✕ violated`, `– given`, `? unscoreable`, with `given` rows explicitly labelled as excluded from the score.
- Mentoring as an ordered list under **"Ask, do not tell"**.
- A copy-for-mentor action yielding the Markdown block for pasting into a session.
- The answer key must never reach the browser: `GET /api/exercises/{id}` already withholds it, and the panel must not add an authoring view that leaks it.

A Playwright journey for this panel exists at `packages/studyloop/tests/e2e/test_journey_exercises.py`, written **before** the UI as its specification. It does not pass — it cannot, because the surface it drives does not exist. Treat it as the spec for the work, **not** as evidence the feature works. (e2e is also excluded from CI by default; see [CI Workflows](ci.md).)

## Authoring: nothing is invented

`exercise from-milestone` scaffolds structure but fabricates **no** rubric checks
and **no** correct answers, and `readiness()` reports the set as unready with the
specific gaps.

That is deliberate. A fabricated rubric scores the learner against criteria
nobody chose, and a fabricated "correct" answer teaches the wrong thing with
total confidence. An honest "this is not scoreable yet" is worth more than a
plausible fiction — so the failure mode is a set that refuses to flatter, not one
that quietly passes everyone.

Fill the gaps with the learner, or from a primary source, using
`studyloop --dev exercise import`.
