---
title: "feat: Autoresearch Persona Optimizer Loop"
type: feat
status: active
date: 2026-04-06
---

# Autoresearch Persona Optimizer Loop

## Overview

Implement the core autoresearch iteration loop for persona prompt optimization.
Following the Karpathy autoresearch pattern (`/Users/ataylor/code/tools/autoresearch/program.md`):
run eval → read scores + feedback → modify persona → re-eval → keep/discard → repeat.

The eval harness (`studyctl eval run`) already scores personas via Bedrock Sonnet 4.6.
What's missing is the **optimizer** that automatically modifies persona files based on
judge feedback, and the **loop** that iterates until success criteria are met or max
iterations exhausted.

## Current State (as of 2026-04-06)

**Working:**
- `studyctl eval run` — runs 7 scenarios via `claude -p` (print mode, no tmux)
- Bedrock Sonnet 4.6 as LLM judge (us-west-2)
- 7-dimension rubric scoring (clarity, socratic_quality, emotional_safety, etc.)
- Judge returns actionable feedback (2-3 suggestions per scenario)
- First passing scores: confused-student 75%, parking-lot 71.9%

**Not working yet:**
- No automatic persona modification based on feedback
- No keep/discard loop (manual re-runs only)
- No iteration tracking or convergence detection

## Proposed Solution

### New command: `studyctl eval optimize`

```bash
studyctl eval optimize --max-iterations 10 --agent claude
```

### The Loop (modelled on autoresearch/program.md)

```
LOOP (up to max_iterations):
  1. Run eval (all 7 scenarios via claude -p + Bedrock judge)
  2. If all scenarios pass (>= 70%) → DONE, commit persona
  3. Collect feedback from failed scenarios
  4. Call LLM optimizer: "Given these scores and feedback, modify the persona"
  5. Apply modifications to persona files
  6. Git commit the modified persona
  7. Re-run eval
  8. If avg score improved → KEEP (advance)
  9. If avg score worsened → DISCARD (git reset to previous commit)
  10. Log iteration to eval-results.tsv
```

### The Optimizer (LLM-driven persona modification)

The optimizer is itself an LLM call (Bedrock Sonnet/Opus) that:
- Receives the current persona text
- Receives the judge scores + feedback for each failed scenario
- Returns a modified persona with specific changes

```python
def optimize_persona(
    current_persona: str,
    eval_results: list[JudgeResult],
    scenarios: list[Scenario],
) -> str:
    """Use LLM to generate an improved persona based on judge feedback."""
    # Build prompt with current persona + all scores + all feedback
    # Ask LLM to return the FULL modified persona text
    # Return the modified persona
```

### Files to modify

| File | Change |
|------|--------|
| `packages/studyctl/src/studyctl/cli/_eval.py` | Add `optimize` command |
| `packages/studyctl/src/studyctl/eval/optimizer.py` | NEW — LLM-driven persona modifier |
| `packages/studyctl/src/studyctl/eval/prompts/optimizer.md` | NEW — optimizer prompt template |
| `packages/studyctl/src/studyctl/eval/orchestrator.py` | Add iteration loop with keep/discard |

### Success criteria

- [ ] `studyctl eval optimize --max-iterations 10` runs the full loop
- [ ] Each iteration: eval → feedback → modify persona → re-eval → keep/discard
- [ ] Git commit on keep, git reset on discard
- [ ] Iteration history logged to eval-results.tsv
- [ ] Loop stops when all 7 scenarios pass (>= 70%) or max iterations reached
- [ ] Final optimised persona committed with iteration count in commit message

### Key design decisions

- **Optimizer model**: Same Bedrock model as the judge (Sonnet 4.6). Could use Opus for higher quality.
- **Persona scope**: Modify `agents/shared/personas/study.md` (the main study persona). Other shared files (socratic-engine.md, break-science.md, etc.) are referenced but not modified by the optimizer — they're protocol docs, not persona instructions.
- **Git branch**: Run on a dedicated branch (`autoresearch/persona-YYYYMMDD`), merge to main when optimised.
- **Keep/discard threshold**: Keep if avg_score improves by any amount. Discard if equal or worse.
- **Feedback aggregation**: Aggregate feedback from ALL failed scenarios into one optimizer call, not per-scenario.

## References

- Karpathy autoresearch pattern: `/Users/ataylor/code/tools/autoresearch/program.md`
- Current eval harness: `packages/studyctl/src/studyctl/eval/`
- Current persona: `agents/shared/personas/study.md`
- Judge rubric: `packages/studyctl/src/studyctl/eval/prompts/judge-rubric.md`
