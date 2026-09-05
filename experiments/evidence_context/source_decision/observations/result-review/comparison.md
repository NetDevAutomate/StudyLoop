# LiteLLM model council comparison

## Coverage

- Selected: claude-fable-5-1, grok-4.6, qwen3-coder
- Valid responses: qwen3-coder
- Provider buckets: qwen

## Failed or invalid responses

- **claude-fable-5-1:** ValueError: model did not return a JSON object
- **grok-4.6:** TimeoutError: timed out

## Recommendations

### qwen3-coder (qwen)

Approve with mandatory investigation into draft-policy divergence causes, particularly regarding extractor omissions and model endorsement of unsupported recommendations.

Confidence: 0.85

Implementation exhibits correct boundary behavior and policy conformance but shows evidence of model drafting defects and measurement validity concerns. Four false blocks indicate advisory draft divergence from checked-only policy, while source-adapter alignment confirms syntactic parsing integrity. Explanation quality and citation validity remain unmeasured.

## Repeated reasons

- None detected by deterministic comparison.

## Repeated risks

- None detected by deterministic comparison.

## Disagreement themes

- Extent to which unsupported endorsements (C03, C11) represent drafting flaws versus unavoidable artifacts of synthetic fixtures.
  Models: qwen3-coder
- If coordinator retention of C01/C10 counterfactual pair undermines validity due to non-independence rather than intentional design.
  Models: qwen3-coder
- Whether draft telemetry should influence approval given its separation from policy-rendered content.
  Models: qwen3-coder

## Shared and unique assumptions

- Deterministic policies accurately reflect intended decision logic and are free of implementation defects.
  Models: qwen3-coder

## Missing information

- Human evaluation of next-check phrasing to ensure it discourages unsafe extrapolations or historical revision.
  Models: qwen3-coder
- Independent verification of explanation entailment and citation accuracy beyond locatability checks.
  Models: qwen3-coder
- Real-world corpus performance to assess generalization beyond synthetic cases.
  Models: qwen3-coder

## Arbitration note

This file groups wording deterministically. It does not establish truth or semantic consensus. Codex must arbitrate against primary evidence and the user's constraints.
