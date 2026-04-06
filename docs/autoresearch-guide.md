# Autoresearch Persona Optimizer — Runbook

> Developer tooling for autonomous persona prompt optimization.
> Not a user-facing feature — this is for contributors tuning the study mentor.

## Overview

The autoresearch framework automatically improves the study mentor's persona
prompt by running an eval loop: score the persona against fixed scenarios,
use an LLM to make one targeted improvement, keep or discard based on results.

Based on [Karpathy's autoresearch](https://github.com/karpathy/autoresearch)
pattern with [AutoAgent](https://github.com/thirdlayer-inc/autoagent) improvements
(trajectory reading + one-change-at-a-time diagnostics).

All tooling lives in the gitignored `dev/` directory.

## Prerequisites

- AWS credentials configured (Bedrock Sonnet 4.6 as judge + optimizer)
- `claude` binary on PATH (used in headless `claude -p` mode)
- `boto3` installed: `uv pip install boto3`
- Eval judge config in `~/.config/studyctl/config.yaml`:

```yaml
eval:
  judge:
    provider: bedrock
    model: us.anthropic.claude-sonnet-4-6
    region: us-west-2
```

## Quick Reference

```bash
# Run persona optimizer (5 iterations, ~45 min)
uv run python dev/run.py --no-git-check --max-iterations 5

# Monitor live progress
tail -f /tmp/optimizer.log

# Run baseline only (no optimization, just score current persona)
uv run python dev/run.py --no-git-check

# Run judge rubric calibration (3 iterations, ~10 min)
uv run python dev/run_judge.py --max-iterations 3

# Monitor judge optimizer
tail -f /tmp/judge-optimizer.log
```

## How It Works

```
              Baseline eval (score unmodified persona)
                              |
                              v
    .---> Read trajectories + iteration history
    |                         |
    |     Diagnose ONE root cause from response text
    |                         |
    |     Generate minimum persona edit
    |                         |
    |     Write edit + git commit
    |                         |
    |     Run eval (7 scenarios)
    |                         |
    |     Score improved? ----+---- Yes: KEEP (commit stays)
    |          |                          |
    |          No                    Update best score
    |          |                          |
    |     DISCARD (soft reset)            |
    |          |                          |
    |     3 consecutive? ---> STOP        |
    |          |                          |
    '----------+--------------------------'
```

### The loop step by step

1. **Baseline**: Score the unmodified persona against 7 scenarios
2. **Optimize**: LLM reads actual agent responses + judge feedback, identifies ONE weakness, produces minimum edit
3. **Commit**: `git add` + `git commit` the modified persona (the hypothesis)
4. **Eval**: Run all 7 scenarios with the modified persona
5. **Keep/Discard**: If avg score improved, keep (commit stays). Otherwise, soft reset to restore the previous persona
6. **Converge**: Stop after 3 consecutive discards (local maximum reached)
7. **Memory**: Results.tsv history is passed to the optimizer each iteration to prevent retrying failed approaches

## File Structure

```
dev/                              # gitignored — not shipped to users
  run.py                          # persona optimizer entry point
  run_judge.py                    # judge rubric calibration
  eval-results.tsv                # iteration results (untracked)
  AUTORESEARCH.md                 # comprehensive learning doc
  eval/
    optimizer.py                  # LLM-driven one-change strategy
    orchestrator.py               # runs scenarios, captures trajectories
    models.py                     # Scenario, JudgeResult, EvalSummary
    llm_client.py                 # Bedrock/Ollama/OpenAI client
    git_ops.py                    # git helpers (short_hash, is_clean)
    reporter.py                   # TSV + markdown report generation
    scenarios.py                  # YAML scenario loader
    judge/
      llm.py                      # 7-dimension rubric scoring
      base.py                     # Judge protocol
    targets/
      persona.py                  # claude -p eval target
      base.py                     # EvalTarget protocol
    prompts/
      judge-rubric.md             # scoring rubric template
      optimizer.md                # optimizer prompt (one-change strategy)
    scenarios/
      study.yaml                  # 7 test scenarios
      judge-calibration.yaml      # human-scored reference responses
```

## What Gets Modified

| Runner | Artifact | Location |
|--------|----------|----------|
| `run.py` | Study persona | `agents/shared/personas/study.md` (tracked) |
| `run_judge.py` | Judge rubric | `dev/eval/prompts/judge-rubric.md` (gitignored) |

The persona file is tracked in git. The optimizer commits changes on keep and soft-resets on discard. Only the persona file is touched — no `--hard` resets.

## The 7 Scenarios

| ID | Tests | Key Dimension |
|----|-------|---------------|
| confused-student | Emotional safety with "I feel stupid" | emotional_safety (2x weight) |
| parking-lot | Redirecting tangents back to topic | topic_focus (2x weight) |
| hyperfocus | Intervention at low energy + 45 min | emotional_safety + energy_adaptation |
| win-recognition | Naming specific student achievements | win_recognition (2x weight) |
| wrong-answer | Gentle misconception correction | emotional_safety (1.5x weight) |
| low-energy | Adapting to energy 2/10 | energy_adaptation (2x weight) |
| deep-dive | High energy deep technical question | all equal |

## Interpreting Results

The log file (`/tmp/optimizer.log`) shows for each scenario:
- The student question
- The agent's full response
- Judge score (0-100%) with per-dimension breakdown
- Judge feedback (2-3 actionable suggestions)

The TSV file (`dev/eval-results.tsv`) tracks iteration history:

```
iteration  timestamp             avg_score  passed  total  commit   status    description
0          2026-04-06T08:30:00   56.1       1       7      8dbbc0b  baseline  unmodified persona
1          2026-04-06T08:38:00   64.4       2       7      a1b2c3d  keep      improved from 56.1%
2          2026-04-06T08:46:00   70.4       3       7      b2c3d4e  keep      improved from 64.4%
```

### Score thresholds

- **Pass**: >= 70% weighted score per scenario
- **Keep**: avg score improved over previous best
- **Converge**: 3 consecutive discards = local maximum

## Judge Calibration

The judge rubric can itself be calibrated against human reference scores:

```bash
uv run python dev/run_judge.py --max-iterations 3
tail -f /tmp/judge-optimizer.log
```

The metric is MAE (Mean Absolute Error) — how far the judge's scores are from human ratings. The calibration dataset at `dev/eval/scenarios/judge-calibration.yaml` contains 7 real agent responses with human-assigned reference scores.

Run this when:
- Setting up a new eval harness (calibrate before optimizing)
- The optimizer makes changes that don't match expectations (judge signal issue)
- The persona has evolved significantly

## Extending to Other Prompts

The framework is reusable. To optimize a different prompt:

1. **Define scenarios** — write a YAML file with test cases for the target behaviour
2. **Set the artifact path** — change `PERSONA_PATH` in `run.py` to point to the target file
3. **Adjust the rubric** — modify `judge-rubric.md` dimensions for the target (co-study might weight different things than study)
4. **Run** — same command, different target

Candidates:
- `agents/shared/personas/co-study.md` — passive support mode
- `agents/shared/socratic-engine.md` — questioning strategy protocol
- MCP tool descriptions — how well the agent uses studyctl tools

## Troubleshooting

**"No AI agent found"** — `claude` binary not on PATH. Install Claude Code.

**"Bedrock API error"** — AWS credentials not configured. Check `~/.aws/credentials` or env vars.

**"Optimizer returned unchanged persona"** — the optimizer couldn't find anything to improve. May be at a genuine maximum, or the prompt needs refinement.

**Scores stuck at 0%** — check the agent response in the log. If it's about tool permissions ("studyctl commands need your approval"), the persona is over-emphasizing tool execution. The mentor should recommend commands, not try to run them.

**git state corrupted** — if git gets into a bad state from the optimizer, check `git reflog` to find the commit you want and `git reset <hash>`.

## Lessons Learned

See `dev/AUTORESEARCH.md` for the comprehensive learning document, and `docs/local_repo_docs/solutions/prompt-engineering/autoresearch-persona-optimization-loop.md` for the full solution writeup.

Key takeaways:
1. One change at a time beats full rewrites
2. The optimizer must see actual agent responses, not just scores
3. Never gate the judge with keyword heuristics
4. Soft git reset — never `--hard` in an optimization loop
5. Convergence detection prevents wasting iterations
6. Iteration memory prevents repeating failed approaches
