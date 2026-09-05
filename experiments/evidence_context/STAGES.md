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

Stage 3 uses its own lifecycle adapter and database schema. It does not modify the
stage 1 evidence store, and does not require stage 1 demo output. Stage 2 uses
stage 1 fixtures/code; its pinned checkpoint contains everything needed to run it.
All examples below create temporary/synthetic data only. Use a new output path
for every demo run; existing directories are deliberately not overwritten.

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

## Next evidence gate, then further stages

Freeze prompt tuning after v2's observed failure. Independently review the existing
case semantics and blind-grade outputs, then test a task-level applicable-validation
policy against those outputs without hardcoding expected answers. See
arbitration_lab/COUNCIL-DECISION.md for accepted advice and corrected reviewer errors.

Keep the real 3–5 disjoint-question pilot with independent pre-result labels as the
precondition for efficacy claims. Learner understanding requires actual feedback.
Lifecycle-to-evidence and installed-package ownership tests remain required before
production. Capture health still needs real detection and watermarks; no engine
selection follows from synthetic examples or successful response parsing.
