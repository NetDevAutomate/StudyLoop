# Independently runnable learning stages

Run commands from the experimental worktree root. Each stage has an immutable Git
checkpoint so later changes cannot silently change the version you are studying.
These are local commits: preserving the repository preserves the checkpoints;
no remote publication or backup is implied.

| Stage | Question | Checkpoint | Entry point and guide |
|---|---|---|---|
| 1 — Evidence retrieval | Can reviewed relationships add relevant evidence while preserving citations and bounds? | `c262c08` | `python -m experiments.evidence_context`; README.md and ARBITRATION.md |
| 2 — Shared context requirements | What must StudyLoop and a standalone consumer both guarantee? | `46442cb` | `tests/test_shared_context_requirements.py`; REQUIREMENTS.md. This is an executable contract stage, not a separate visual demo. |
| 3 — Correction and forgetting | Can offline replicas converge without resurrecting forgotten content? | `b44145a` | `python -m experiments.evidence_context.lifecycle_demo`; STUDY-GUIDE.md |
| 4 — Capture health | Does configured capture actually yield recent history? | `ae2b250` | `python -m experiments.evidence_context.capture_health`; capture_health/GUIDE.md and COUNCIL-DECISION.md |
| 5 — Retrieval measurement | Does returned context contain the required evidence? | `1b9a658` | `python -m experiments.evidence_context.retrieval_eval`; retrieval_eval/GUIDE.md, EXPLANATION-RUBRIC.md and COUNCIL-DECISION.md |
| 6 — Conflict arbitration | Does the answer resolve conflicting evidence responsibly? | `66902e2` | `python -m experiments.evidence_context.arbitration_lab`; arbitration_lab/GUIDE.md, RESULTS.md and versioned prompts |
| 7 — Bounded prompt loop | Does our score recognise a better evidence-based decision? | `f3a8457` | `python -m experiments.evidence_context.prompt_loop`; prompt_loop/GUIDE.md, RESULTS.md and COUNCIL-DECISION.md |
| 8 — Decision contract | Which sources apply, and what decision do they justify? | `f7f6796` | `python -m experiments.evidence_context.decision_contract`; decision_contract/GUIDE.md, RESULTS.md and expandable HTML walkthrough |
| 9 — Code-owned release | Can model drafts override missing metadata or enter released prose? | `d7a9c8f` | `python -m experiments.evidence_context.acceptance_gate`; acceptance_gate/GUIDE.md, RESULTS.md and replay walkthrough |
| 10 — Metadata value | Does source-backed metadata improve decisions? | `620090a` | `python -m experiments.evidence_context.metadata_value`; metadata_value/GUIDE.md, RESULTS.md and actual-answer replay |
| 11 — Source to decision | Can code enforce evidence requirements without blocking justified choices? | `e1428be` | `python -m experiments.evidence_context.source_decision`; source_decision/GUIDE.md, RESULTS.md and saved learning walkthrough |
| 12 — Real retrieval pilot | Which selected history reaches and helps the answer? | `27e6900` | `retrieval_matrix/trial.py` and `report.py`; GUIDE.md, RESULTS.md, private real-answer replay |
| 13 — Equivalent storage | Which engine serves the same nodes, edges and rows? | `6fff879` | `storage_matrix/benchmark.py` and `query_diagnostic.py`; GUIDE.md and RESULTS.md |
| 14 — Evidence replacement | Do reviewed results improve answers, and what still fails? | `ec8bbc1` | `evidence_selection/runner.py` and `viewer.py`; GUIDE.md, RESULTS.md and reviewer audit |

Stage 3 uses its own lifecycle adapter and database schema. It does not modify the
stage 1 evidence store, and does not require stage 1 demo output. Stage 2 uses
stage 1 fixtures/code; its pinned checkpoint contains everything needed to run it.
Stages 1–11 use temporary/synthetic demo data. Stage 12 also provides an explicitly
private real-transcript replay. Use a new output path for every demo run; existing directories are deliberately not overwritten.

## Run from the current worktree

```sh
# Stage 1: keyword and reviewed-relationship retrieval
uv run python -m experiments.evidence_context --output /tmp/evidence-stage-1
uv run --group dev pytest experiments/evidence_context/tests/test_evidence_contract.py experiments/evidence_context/tests/test_snapshot_and_cli.py -q

# Stage 2: whole-pack scope boundaries and grounded explanations
uv run --group dev pytest experiments/evidence_context/tests/test_shared_context_requirements.py -q

# Stage 3: correction, offline deletion and stale replay
uv run python -m experiments.evidence_context.lifecycle_demo --output /tmp/evidence-stage-3
uv run --group dev pytest experiments/evidence_context/tests/test_lifecycle.py -q
```

Current-tree commands run the current implementation. For the exact historical
behaviour, use a checkpoint worktree instead.

## Freeze a stage without switching your working branch

From a checkout of this Git repository, choose one new directory:

```sh
git worktree add --detach /tmp/studyloop-evidence-stage-1 c262c08
cd /tmp/studyloop-evidence-stage-1
uv sync --all-packages --group dev
uv run python -m experiments.evidence_context --output /tmp/evidence-stage-1-frozen
```

Substitute `46442cb` or `b44145a` and a different directory for stages 2 or 3,
then run that stage's command above. A detached worktree is suitable for inspection;
create a branch there before making changes you want to keep. Dependency fetching
may need network access; the tests and demos do not call model providers.

## Convention for every following stage

- Keep prior entry points and demos working. Use a separate module/directory and
  disposable schema where a new design has different semantics.
- Record a completion commit here, plus exact setup, demo and test commands.
- Include a guide explaining the problem, alternatives, why we chose one, costs,
  observed results and what remains unproven. Include expected demo observations.
- Distinguish a contract-test stage from a user-facing demonstration. Never imply
  that a synthetic adapter validates an installed integration.
- Preserve synthetic fixtures; keep real transcripts and provider outputs private.
- Keep council advice, coordinator decisions and test evidence distinguishable.

## Stage 4 commands

```sh
uv run python -m experiments.evidence_context.capture_health --output /tmp/evidence-stage-4
uv run --group dev pytest experiments/evidence_context/tests/test_capture_health.py -q
```

Checkpoint `ae2b250` can be opened in a detached worktree using the same procedure.
The council reconsidered the order using all four stages' evidence. See
[capture_health/COUNCIL-DECISION.md](capture_health/COUNCIL-DECISION.md).

## Stage 5 commands

```sh
uv run python -m experiments.evidence_context.retrieval_eval --output /tmp/evidence-stage-5
uv run --group dev pytest experiments/evidence_context/tests/test_retrieval_eval.py -q
```

Checkpoint `1b9a658` preserves the runnable synthetic evaluator. It accepts a
separate dataset, but independent real held-out labels and efficacy are not yet
established. See retrieval_eval/HOLDOUT-PROTOCOL.md for that next evidence gate.

## Stage 6 commands

```sh
uv run python -m experiments.evidence_context.arbitration_lab --output /tmp/evidence-stage-6-v1
uv run python -m experiments.evidence_context.arbitration_lab --prompt-version v2 --output /tmp/evidence-stage-6-v2
uv run --group dev pytest experiments/evidence_context/tests/test_arbitration_lab.py -q
```

Default execution prepares offline. The guide explains explicit paid live runs and
includes readable preserved observations from both pilot rounds. Checkpoint
`66902e2` pins this development stage. The user requested this arbitration probe;
it does not replace or satisfy the independently labelled real-holdout gate.

## Stage 7 commands

```sh
uv run python -m experiments.evidence_context.prompt_loop --output /tmp/evidence-stage-7
uv run --group dev pytest experiments/evidence_context/tests/test_prompt_loop.py -q
```

Checkpoint `f3a8457` preserves this stage. Default execution is a scripted offline
loop; explicit `--live` uses the gateway with at most 18 calls. The guide separates
scripted demonstration from the preserved 16-call live run. Two full pre-loop
councils reviewed sources and blinded answers; result review had two valid providers
because Fable failed structured output twice. Both amendments improved the observed
queue recommendation, but a defective category proxy hid that change. The original
selector and results remain frozen for study.

## Stage 8 commands

```sh
uv run python -m experiments.evidence_context.decision_contract --output /tmp/evidence-stage-8
open /tmp/evidence-stage-8/walkthrough.html
uv run --group dev pytest experiments/evidence_context/tests/test_decision_contract.py -q
```

Checkpoint `f7f6796` preserves the contract, eight fixtures, reference walkthrough,
pre-run expectations and sixteen actual model answers. Default execution is offline;
`--live` makes sixteen bounded gateway calls. The reference handles unknown scope
correctly, but the model invented a missing revision in one case. Choice matches were
7/8 new versus 5/8 legacy; these are not general quality scores. Three providers
reviewed the design; two returned valid result reviews after Grok failed twice.
The optional revision-classification exercise is saved for a later dedicated session.

## Stage 9 commands

```sh
uv run python -m experiments.evidence_context.acceptance_gate --output /tmp/evidence-stage-9
open /tmp/evidence-stage-9/walkthrough.html
uv run --group dev pytest experiments/evidence_context/tests/test_acceptance_gate.py -q
```

Checkpoint `d7a9c8f` preserves the snapshot-bound draft comparison and code-owned
release. Offline mode replays eight actual drafts and eighteen controls/challenges;
`--live` makes twelve calls. Four live drafts diverged on missing scope, including
both injected-source drafts; none supplied the released decision/prose. Draft agreement
was 3/6 prompt-only and 5/6 in a precomputed-answer copy control. The release is always
policy-rendered, so this is conformance measurement, not model-answer certification.
Both council rounds returned all three providers. Upstream metadata forgery remains
an explicit blind spot. All 153 evidence-context tests passed at this checkpoint.

## Stage 10 commands

```sh
uv run python -m experiments.evidence_context.metadata_value --output /tmp/evidence-stage-10
open /tmp/evidence-stage-10/walkthrough.html
uv run python -m experiments.evidence_context.metadata_value.normalization_audit --input experiments/evidence_context/metadata_value/observations --output /tmp/evidence-stage-10-answers.json
open /tmp/evidence-stage-10-answers.html
uv run --group dev pytest experiments/evidence_context/tests/test_metadata_value.py experiments/evidence_context/tests/test_metadata_normalization.py -q
```

Checkpoint `620090a` preserves the source verifier and 64-call pilot. The
first walkthrough is offline/reference; the second replays actual answers without
provider calls. Original strict JSON parsing accepted only 9/56 answer drafts. A separate
post-hoc fence-only diagnostic found choice matches of raw 12/16, original extraction
14/16 and checked 12/16. The gain was one missing-revision case repeated twice; checked
introduced a report-only regression. All conditions failed duplicate revision. These
are development category scores, not validated answer quality. All 173 experiment
tests passed. See the council decision for review coverage and limitations.

## Stage 11 commands

```sh
uv run python -m experiments.evidence_context.source_decision --output /tmp/evidence-stage-11
uv run python -m experiments.evidence_context.source_decision.viewer --input experiments/evidence_context/source_decision/observations --output /tmp/evidence-stage-11-learning.html
open /tmp/evidence-stage-11-learning.html
uv run python -m experiments.evidence_context.source_decision --replay experiments/evidence_context/source_decision/observations --output /tmp/evidence-stage-11-replay
uv run --group dev pytest experiments/evidence_context/tests/test_source_decision.py -q
```

Checkpoint `e1428be` preserves twelve condition checks across eleven source/target
pairs, with pre-run model-reviewed labels and one recorded dissent. The 24 draft calls
produced 23 valid advisory decisions, including four unsupported choices on old cases.
The matched-candidate gate withheld four justified outputs; explicit source rederivation
matched all twelve condition labels, independently of model prose. Repeat policy outputs
are not additional independent checks. The fresh cases had 17 valid correct advisory
responses and one parsing failure. This is conformance, not efficacy or authenticity.

All 201 evidence-context tests passed. All three providers labelled before execution;
result review had one full-packet responder and two responders to a focused compact
retry, insufficient for three-provider result consensus. The guide explains all
limitations and the intentionally identical-source omission control.

## Stage 12 commands

```sh
uv run --group dev pytest experiments/evidence_context/tests/test_retrieval_matrix.py -q
uv run python -m experiments.evidence_context.retrieval_matrix.report \
  --directory experiments/evidence_context/.private/stage-12/run \
  --output /tmp/stage-12-replay.html
open /tmp/stage-12-replay.html
```

Checkpoint `27e6900` preserves a four-question real development pilot, 32 gateway
answers and the unchanged prompt. Under pre-retrieval coordinator labels all four
arms covered Q1 2/3, Q2 3/3, Q3 0/4 facts. Reviewer-label sensitivity is retained.
All eight Q4 answers abstained. Schema compliance did not stop prose from promoting
plans into results. No held-out efficacy or retriever superiority is established.
Three providers labelled before retrieval; full result review returned only Qwen;
a bounded focused retry also returned only Qwen. See the detailed council arbitration.

The replay requires the owner's ignored private snapshot, which is deliberately not
in a public Git clone. Synthetic tests run without that snapshot or provider calls.
The private archive is alongside the learning checkout; Git does not back it up.

## Stage 13 commands

```sh
uv run --with ladybug==0.20.2 python -m experiments.evidence_context.storage_matrix.benchmark \
  --corpus experiments/evidence_context/storage_matrix/demo-corpus.json \
  --output /tmp/stage-13-demo
uv run python -m experiments.evidence_context.storage_matrix.query_diagnostic \
  --directory /tmp/stage-13-demo
uv run --with ladybug==0.20.2 --group dev pytest experiments/evidence_context/tests/test_storage_matrix.py -q
```

Checkpoint `6fff879` preserves the full SQLite/Ladybug/mixed benchmark and
separate post-hoc SQL diagnostic. The committed fixture is tiny and synthetic; the
actual measurement used 1,019 real nodes and ten disjoint copies. All 240 sampled
query conditions returned identical rows across engines; 3,600 warm query timings
were collected. A SQLite plan change reduced replicated two-hop median from 0.494ms
to 0.019ms in a separate paired diagnostic. It is not substituted into the frozen
engine race. No migration is justified. Grok and Qwen returned full storage reviews;
Fable failed. No three-provider result consensus is claimed.

All 206 evidence-context tests passed, including prior stages and new boundary/equality
checks. The private replay passed browser checks for 32 entries, Q3 filtering and
expansion. Both new stages passed the commit hooks. Source DB and production config
were not modified by these experiments; graph stores are disposable snapshots.

## Stage 14 commands

```sh
uv run python -m experiments.evidence_context.evidence_selection.viewer \
  --directory experiments/evidence_context/.private/stage-14/run \
  --output /tmp/stage-14-walkthrough.html
open /tmp/stage-14-walkthrough.html
uv run --group dev pytest experiments/evidence_context/tests/test_evidence_selection.py -q
```

Checkpoint `ec8bbc1` preserves 24 fresh answer calls: four development questions,
original/reviewed/reviewed-plus-nearby conditions, two repeats each. The answering
prompt/model remained fixed. Q3's reviewed conditions supplied all four required
reported-result facts and recovered them in the answers; interpretation still failed.
Clean packs overstated validation, while filled packs promoted a correction in progress
to completion. These are oracle controls, not a deployed automatic retriever. Actual
context lengths differ under one shared ceiling; order/density remain confounds.

Three providers returned design reviews. The initial twelve-answer review had two
responders whose blanket criticisms included demonstrable misreadings. A focused
three-answer audit returned all four providers; Fable and Grok correctly distinguished
qualified decisions, validation overclaims and completion overclaims. Other disagreements
and response-contract defects are retained. This is not general reviewer calibration
or full-trial consensus. No answer was regenerated or automatically accepted.

All 212 evidence-context tests passed. Browser checks confirmed 24 replay entries,
six filtered Q3 drafts, expansion and no page errors. Commit checks passed. Private
transcripts/outputs remain in the ignored .private archive alongside the learning tree;
a Git clone deliberately does not contain them. The Stage8 exercise remains unchanged.

## Next evidence gate

The complete-evidence control has now run. Next, represent reported event state,
evidence basis and target identity separately, then test whether a verifier can allow
a reported cleanup outcome while withholding an unsupported completed-fix claim.
Review findings must identify exact answer/source clauses and be tested against honest
qualified answers as well as overclaims. Preserve false blocks and reviewer disagreement.

Use new independently labelled cases before claiming general efficacy or building an
automatic extraction/retrieval integration. Stage14 reused development questions and
known labels; it does not satisfy the held-out requirement. A later distraction study
should counterbalance positions and actual lengths rather than change several factors.

Keep SQLite canonical and indexes replaceable while investigating information value.
A new engine race needs a named workload and a fair optimized-query baseline. Work/
personal scope, correction/forgetting through derived indexes, capture health and
installation ownership remain requirements for integration. No DSPy integration,
production prompt promotion or migration occurred.
