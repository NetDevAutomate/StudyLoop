# Stage 7 — Can a prompt optimiser improve the thing we actually care about?

The most useful result of this stage is an evaluator defect. Both generated prompt
amendments stopped choosing an unbenchmarked queue in the observed answers, yet the
frozen score rejected those answers. They called their evidence `reported_only`:
accurate as a description of the source, although the scorer demanded `insufficient`.
Those labels mix **source type** with **whether a decision is justified**.

## Run the lesson independently

From this experimental worktree root:

```sh
uv run python -m experiments.evidence_context.prompt_loop --output /tmp/evidence-stage-7
uv run --group dev pytest experiments/evidence_context/tests/test_prompt_loop.py -q
```

Use a new output directory each time. The default is a **scripted offline demo**:
it makes no provider calls and intentionally demonstrates selecting an amendment.
Its scripted improvement is not an observed model result. The actual live run below
selected the baseline. Compare both to understand mechanics versus evidence.

The output contains `manifest.json`, frozen synthetic inputs, every attempted call
in `ledger.json`, `candidates.json`, a locked `selection.json`, and `results.json`.
An existing output directory is never overwritten. An interrupted run retains its
attempt ledger but is not resumable; use a fresh directory and count prior costs.

An explicitly live run uses the existing loopback LiteLLM gateway:

```sh
# LITELLM_API_KEY must already be provided securely in your environment.
# Optional LITELLM_BASE_URL defaults to http://127.0.0.1:4000.
uv run python -m experiments.evidence_context.prompt_loop --live --output /tmp/evidence-stage-7-live
```

Live mode allows at most 18 calls, two amendments, and two repeats per development
case. It uses Qwen3-Coder at temperature zero through the existing Stage 6 client.
Calls have a 90-second socket timeout and no application retries. This is a call
cap, not a dollar cap; input length and gateway pricing affect cost. Failed calls
count toward the cap. Costs absent from responses are reported as missing, not free.

## What the loop can change

Only an appended prompt amendment, up to 1,000 characters. It cannot execute code,
modify the scorer, replace source evidence, change the answer schema in code, or
inspect the audit scenarios through its supplied inputs. The instruction against
case-specific shortcuts is a prompt request, not an enforced semantic guarantee.
Output schema and citation checks reject some consequences of a bad amendment.

The proposer sees the development questions, sources, fixed label rules and prior
answers/scores. Exposing development labels is intentional training feedback.
The answering model receives only the prompt and source context, not scoring labels.

1. Run the unchanged Stage 6 v2 prompt on queue and retry, twice each.
2. Ask for one amendment, then run those same four checks.
3. Repeat once, with accumulated development feedback.
4. Keep a candidate only if all integrity checks pass and its score strictly improves.
   A tie keeps the incumbent; this is not an actual complexity measurement.
5. Write the selected candidate before auditing cache and storage once each.
6. Report the audit; never feed it back into this run or automatically promote a prompt.

All four cases were previously seen by us. The audit is hidden from this run's
proposer inputs but **is not an independent held-out dataset**. Repeating two cases
twice does not create four independent scenarios. Temperature zero is not a promise
of identical responses; gateway cache behavior was not independently established.

## Why a small loop before DSPy?

Your local autoresearch projects separate editable `train.py` from fixed evaluation
in `prepare.py`, establish a baseline, then retain useful experiments. We borrowed
that structure: the editable object is prompt text; the fixed object is the
scorer and fixture set. We retain rejected attempts instead of erasing their history.
No files in either autoresearch repository were changed.

DSPy's GEPA can use metric feedback to generate and select prompt variations.
It still needs a meaningful metric and evaluation data; its documentation describes
training/validation setup and reflection feedback. See the
[official GEPA guide](https://dspy.ai/getting-started/gepa-optimization/).
We have not installed DSPy or compared optimisers. Keeping this loop small makes the
selection error easy to inspect before adding another layer of machinery.

| Choice | Benefit here | Cost or limitation |
|---|---|---|
| Small explicit loop | Every input, score and selection is inspectable | Few candidates; no sophisticated search |
| DSPy later | Reusable optimisation framework and richer feedback | Still optimises the metric we supply; integration work |
| More hand tuning | Fast individual hypothesis checks | Easy to move rules after observing failures |
| Frozen rules + separate diagnosis | Preserves what the experiment actually measured | Requires a new version/run to fix a bad metric |

## Three different meanings of a passing answer

**Integrity:** the JSON has the required fields; cited IDs exist; claiming artifact
support includes a cited artifact; at least one citation exists. This does not prove
the citation text entails the claim or that a synthetic artifact is real verification.

**Development proxy:** integrity passes, and recommendation/evidence-basis labels
match the allowed case categories. We deliberately do not score `conflict_kind`:
reviewers found correction versus unequal evidence taxonomy ambiguous.

**Source-grounded explanation:** the conclusion and its explanation follow the
supplied evidence, stay inside its scope and explain uncertainty. This requires
separate review. Learner usefulness additionally requires feedback from a learner.

A test deliberately attaches an invented million-machine validation claim to an
otherwise passing answer. The proxy still passes it. This is a documented blind
spot, not a supported claim. A score is only as broad as what its checks inspect.

## Walk through the observed surprise

Open `observations/live-answers.json` and compare baseline queue answers with both
candidates. The baseline selects B because later advice supposedly corrects A.
Both candidates instead say `recommendation: insufficient`, explain that no
benchmark exists, and ask for one. Their evidence label is `reported_only`.

Now open `runner.py`, find `RULES["queue"]`, and trace `score()`. The scorer requires
both recommendation and evidence basis to equal `insufficient`. The second label
fails, so the improvement in decision behavior disappears from the aggregate score.

Like a network monitoring rule that confuses a link being present with a route being
usable, this mixes two different questions: **what evidence arrived?** and **can it
support this decision?** They deserve separate fields and separate checks.

The frozen run is preserved. We do not retroactively change its winner or announce
a gain in general answer quality. A new evaluator version needs its own reviewed
schema, counterexamples and pre-result criteria. See [RESULTS.md](RESULTS.md) and [COUNCIL-DECISION.md](COUNCIL-DECISION.md).

## Optional small learner contribution

`exercise.py` has a separate 5–10 line exercise: decide when a development candidate
is eligible for independent review, balancing improvement against citation failures.
It is deliberately disconnected from the frozen runner. Implementing it lets you
choose a meaningful policy without changing the historical experiment.

## What this tells us about database design

Nothing here selects SQLite, a graph engine or vector storage. It tests what happens
*after* context is retrieved. It suggests that a future context contract should
separate source provenance, claim scope and decision sufficiency. Those can be
represented in SQLite as well as a graph. Choose an engine only after measuring
retrieval and lifecycle requirements with representative evidence.
