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

## Planned stages — not implemented

4. Capture health: distinguish configured hooks from successful imports, partial
   capture and stale history. Explain why empty retrieval may not mean no history.
5. Installation ownership: temporary-environment setup/reinstall/upgrade/uninstall
   contracts for a standalone consumer plus StudyLoop, preserving shared state.
6. Evidence lifecycle integration: connect correction/deletion to the retrieval
   store and its citations, and address identity, reclassification and restore gaps.
7. Held-out decision evaluation: keyword versus relationships with shuffled-link
   control; add semantic arms only when implemented. Fixed model/context budget,
   lineage-separated cases, citation correctness, usefulness and operating costs.
8. Engine comparison only if the earlier measurements identify a reason to run it.

Before promoting the lifecycle design, seek a further diverse implementation
review. The existing three-provider council covered initial design, not stage 3.
