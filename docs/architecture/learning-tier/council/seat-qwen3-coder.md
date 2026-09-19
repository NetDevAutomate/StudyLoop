<!-- verified_model: qwen3-coder -->
<!-- finish_reason: stop · 12.6s · usage: {"completion_tokens": 998, "prompt_tokens": 5923, "total_tokens": 6921, "completion_tokens_details": {"reasoning_tokens": 0, "text_tokens": 998}, "prompt_tokens_details": {"cached_tokens": 0, "text_tokens": 5923, "cache_write_tokens": 0, "cache_creation_tokens": 0}, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0} -->

```
VERDICT: ACCEPT-WITH-CORRECTIONS
Plan correctly sequences feeding the learning tier ahead of measuring the judge. Key omissions include explicit checks for data integrity and coverage validation that must block merging. Corrections specified below ensure reliable execution.
```

| id | severity | claim | concrete check |
|----|----------|-------|----------------|
| F1 | BLOCKING | Harness grants missing for writers in codex, pi, grok – unknown mechanisms make verification impossible | Check `agents/codex/AGENTS.md`, `agents/pi/AGENTS.md`, existence of `agents/grok/` and `packages/studyloop/src/studyloop/adapters/grok.py` |
| F2 | MAJOR | No contract test validates MCP `record_teachback` writes correctly (vs CLI-only) | Add test asserting row in `teach_back_scores` with expected values after MCP call |
| F3 | MAJOR | Missing session guard allows partial eval runs instead of requiring all 13 golden sessions | In `eval_runner.py`, add assertion: count(transcript_sessions_in_union) == 13 or exit(1) |
| F4 | MAJOR | No coverage check blocks running J-a when <50% gold labels are supported by dynamic candidate set | Compute train coverage ratio using known concept list vs training label list; halt if <0.5 |
| F5 | MINOR | Teach-back protocol embedded in persona lacks automation guards (prompt-per-call friction unclear) | Confirm `kiro/study-mentor.json:allowedTools` omits `log_struggle` etc., allowing interactive approval |
| F6 | MINOR | Decision rule does not specify statistical testing to determine significance given small n=13 | Append to prereg: “Cluster bootstrap CIs required; adopt if CI lower bound > control” |

**ANSWERS**

**Q1. MCP `record_teachback`: right call or CLI-only?**
Adding the writer promotes parity across harness environments where shell interaction is unavailable. This reduces friction especially for non-Kiro agents. *Recommendation:* Implement MCP version mirroring CLI functionality exactly with backward compatibility maintained.

**Q2. Tool grants for codex/pi/grok unspecified grammars. Prompt-per-call on Kiro—defect or consent feature?**
Until clarified, harness parity remains unverified. The prompt-based flow might be intentional consent logic. However, consistency should be enforced programmatically. *Recommendation:* Determine exact mechanism per harness; treat absence from allowedTools as unintended friction unless documented otherwise.

**Q3. Prose triggers vs machine-readable ones—how prove consistency in CI?**
Projected protocols risk divergence without enforcement. Central source ensures coherence but needs a diff-detecting CI job. *Recommendation:* Introduce CI script comparing rendered sections among projected files; enforce match at diff-time.

**Q4. Is owner learner input essential to declare 'fed' tier?**
Scripted actor proves internal correctness under controlled conditions. But organic usage confirms ecological validity. Owner experience provides final integration guarantee. *Recommendation:* Include optional manual verification step on target harness before merge.

**Q5. Union read vs restoring archived sessions into active DB—which path?**
Importing sessions contradicts operational boundaries noted in F3-F4. Cold storage avoids contamination risks while preserving privacy. Full dataset guarantees fidelity. *Recommendation:* Maintain strict union-read approach with immutable archive.

**Q6. Which Jev arm—J-a/J-b/J-c—is validatable here without violating ownership constraints?**
J-b leverages system LLM which conflicts with measuring pure judgment capability. Pure Noul forms (J-c) isolate signal best. Bounded vocab arms limit realism. *Recommendation:* Select J-c; document it as component strength indicator due to lack of scorer pairing.

**Q7. Suitability of draft decision rule for n=13 sample size?**
Statistical insignificance undermines binary outcomes. Reporting directional findings maintains scientific rigor while discouraging premature adoption. Rule requires confidence anchoring. *Recommendation:* Revise to require directional improvement backed by cluster-bootstrap intervals; exclude hard thresholds.

**Q8. Staging interdependencies missed? Must items run sequentially or can parallelism help?**
Feeding must precede judging logically but technically separable. Parallel development risky without synchronized baselines. Staging captures dependencies appropriately. *Recommendation:* Retain serial staging but allow independent branch prototyping within shared sandbox.

**REVISED STAGING:** Unchanged — structure reflects logical dependency well.

**UNVERIFIED**:
- Existence and semantics of tool access grammar in `agents/{codex,pi,grok}/`
- Mechanism generating `agents/grok/`

**ONE THING:**
Mandate explicit coverage validation prior to candidate-driven evaluation arms to avoid misleading results on sparse label sets.
