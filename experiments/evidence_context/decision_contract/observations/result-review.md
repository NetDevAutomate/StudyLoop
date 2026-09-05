# LiteLLM model council comparison

## Coverage

- Selected: claude-fable-5-1, grok-4.6, qwen3-coder
- Valid responses: claude-fable-5-1, qwen3-coder
- Provider buckets: anthropic, qwen

## Failed or invalid responses

- **grok-4.6:** ValueError: model did not return a JSON object

## Recommendations

### claude-fable-5-1 (anthropic)

Do not declare the contract ready. Next step: rerun the missing-scope (J01/J16-type) and revision-mismatch (J12-type) scenarios with at least 5 samples per arm plus new variants (missing environment, missing workload, two missing fields, near-match revision strings), scored against pre-registered expected answers by a non-Qwen judge; require 0 inference-of-missing-scope failures before adoption.

Confidence: 0.78

12 of 16 answers match the supplied decision rules; 3 are unsupported (J01, J12, J16) and 1 needs review (J10). Both schema arms fail the missing-revision scenario (J01 infers 'implicit r2'; J16 silently treats the artifact as applicable), and the old schema also accepts an r1 artifact for an r2 target (J12). The exact-match, conflicting-artifact, metric-mismatch, reports-only and requirement-fit-with-artifact scenarios are handled correctly in both arms. With one sample per cell, a single Qwen answer model, no gold labels and partial blinding via schema, this is a smoke test, not validation. The contract is not ready: the 'unknown scope' rule is the discriminating weakness.

### qwen3-coder (qwen)

Revise the evaluation protocol to enforce stricter adherence to artifact applicability rules and clarify how to handle contradictory empirical results.

Confidence: 0.85

Review of 16 items reveals inconsistent application of decision rules, particularly regarding artifact applicability and precedence. Several responses misapply requirement-fit logic in measured mode, conflate unsupported reports with evidence, or fail to properly assess artifact scope. Notably, some responses ignore direct contradictions between artifacts, while others incorrectly treat non-matching revisions or metrics as sufficient.

## Repeated reasons

- None detected by deterministic comparison.

## Repeated risks

- None detected by deterministic comparison.

## Disagreement themes

- Counting J10 as a failure of the old schema would be unfair; counting it as a full pass would hide that the two arms disagree on the conditional rule, which is itself informative about prompt clarity.
  Models: claude-fable-5-1
- How to weigh recency of reports when all evidence is synthetic and non-chronological.
  Models: qwen3-coder
- If unknown scope should default to exclusion or remain open for interpretation.
  Models: qwen3-coder
- The brief frames J06-style 'next_check: none needed' as acceptable because the field is nonempty; I would treat it as a soft failure of the limitation-awareness intent since the evidence is synthetic and unreproduced.
  Models: claude-fable-5-1
- The contract allows a conditional B recommendation from requirement-fit reports while the question asks 'which option is justified for reopen correctness'; J10's refusal is arguably the more honest answer to the question as posed, and the rule may be encouraging an over-confident label.
  Models: claude-fable-5-1
- Whether partial schema visibility constitutes adequate blinding or introduces bias.
  Models: qwen3-coder

## Shared and unique assumptions

- All sources are synthetic and lack external validity; thus, generalization beyond scope is unwarranted.
  Models: qwen3-coder
- Decision rules accurately reflect intended evaluation criteria and should be strictly enforced.
  Models: qwen3-coder
- Old-schema answers are judged on recommendation and rationale only; absence of applicability/reason_code fields is not penalised.
  Models: claude-fable-5-1
- Paired items (J01/J16, J05/J14, J07/J12, J13/J04, J03/J10, J11/J06, J15/J08, J02/J09) are the two prompt conditions of the same scenario, as implied by identical evidence sets.
  Models: claude-fable-5-1
- The expected answer per scenario is derivable mechanically from the RULES text (unknown scope means no applicable artifact; any known mismatch means inapplicable; requirement_fit with exactly one requirement_match=true means conditional B).
  Models: claude-fable-5-1

## Missing information

- An independent non-Qwen judge's scoring of the same 16 items to check that this review's expected answers are not idiosyncratic.
  Models: claude-fable-5-1
- Arm labels after scoring, to confirm the paired-scenario inference used here and to attribute the J01 vs J16 failure modes to prompt condition rather than chance.
  Models: claude-fable-5-1
- Explicit confirmation of artifact authenticity and source independence.
  Models: qwen3-coder
- Independent reproduction of key test artifacts to verify consistency.
  Models: qwen3-coder
- Multiple samples per scenario per arm (n≥5) to distinguish systematic rule misapplication from sampling noise.
  Models: claude-fable-5-1
- Scenarios where artifact metadata matches but the artifact text does not entail the stated conclusion, to test the 'metadata does not prove entailment' clause.
  Models: claude-fable-5-1
- Statistical power and error bounds for synthetic test outcomes.
  Models: qwen3-coder
- Variants with different missing fields (environment, workload) and with near-miss revision strings (r2.1, r2-hotfix) to characterise the unknown-scope failure.
  Models: claude-fable-5-1

## Arbitration note

This file groups wording deterministically. It does not establish truth or semantic consensus. Codex must arbitrate against primary evidence and the user's constraints.
