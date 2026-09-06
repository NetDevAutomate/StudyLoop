# LiteLLM model council comparison

## Coverage

- Selected: claude-fable-5-1, grok-4.6, qwen3-coder
- Valid responses: claude-fable-5-1, qwen3-coder
- Provider buckets: anthropic, qwen

## Failed or invalid responses

- **grok-4.6:** ValueError: model did not return a JSON object

## Recommendations

### claude-fable-5-1 (anthropic)

Accept the pilot as conformance-only evidence for source_adapter; before any design commitment, run one bounded differential test of the parser boundary: ~20 hand-authored malformed sources (CRLF, trailing whitespace on markers, two or nested observed blocks, indented keys, key-case variants, identical winner lines inside and outside block, 'winner: C', a quote spanning lines) asserting that declarations() and declarations_with_spans() agree on block membership, no exception escapes release(), and every emitted span locator resolves; labels for these must be authored blind by a non-developer.

Confidence: 0.70

The 24/24 source_adapter result is a conformance check of a deterministic parser against 11 developer-authored fixture pairs (12 conditions, C01/C10 duplicated) with developer-authored labels; the model plays no role in gate output, so the 24 calls add nothing to adapter evidence. checked_only's 4 false blocks are 2 conditions x 2 repeats, both created by scripted proposal errors that source_adapter is immune to by construction, so the mode comparison is close to tautological. Real signal: advisory model choice was correct on all 17 valid fresh calls and failed only on provenance (C03) and ambiguity (C11), where quotes were locatable but insufficiency was invisible to it. No adapter decision bug is visible in five cases, but several latent parser-desync and semantic risks exist.

### qwen3-coder (qwen)

Approve the current implementation for bounded use within synthetic environments, contingent on resolving known ambiguities in source parsing and clarifying artifact authenticity protocols.

Confidence: 0.75

The synthetic policy-conformance pilot demonstrates strong internal consistency but limited real-world applicability due to its封闭 design and lack of production claims. While the mechanisms show promise in controlled scenarios, critical gaps remain in handling ambiguous sources, authenticating artifacts, and ensuring robustness beyond scripted conditions.

## Repeated reasons

- None detected by deterministic comparison.

## Repeated risks

- None detected by deterministic comparison.

## Disagreement themes

- 'All 23 valid draft quotes locatable' is presented as a positive; C03/C11 show locatability is orthogonal to sufficiency and should not be a headline metric.
  Models: claude-fable-5-1
- The brief frames 0/24 as a headline; I would report 11/11 fixture conformance and treat the 24 figure as a model-telemetry count only.
  Models: claude-fable-5-1
- The brief lists C05 as a checked_only 'false block'; given checked_only's stated contract (accept only verifier-matched candidate fields), abstaining on a proposal that cited an outside-block winner is correct-by-spec behavior, and labelling it false block conflates modes' contracts.
  Models: claude-fable-5-1
- The exclusion of human gold standard labels may underestimate error rates since developer-authored rules can share correlated bugs undetected by blinded review.
  Models: qwen3-coder
- Whether C05 dissent should be counted inside or outside block boundaries affects outcome labeling and highlights ambiguity in span extraction rules.
  Models: qwen3-coder

## Shared and unique assumptions

- declarations() in metadata_value.verify implements the same [observed]/[/observed] exact-line grammar as declarations_with_spans; the packet only summarizes it.
  Models: claude-fable-5-1
- Stage 8 derive() rejects provenance='report' and any None scope value; C03/C01 outputs are consistent with this but the policy code is not shown.
  Models: claude-fable-5-1
- Synthetic data accurately reflects potential real-world edge cases despite no production claims being made.
  Models: qwen3-coder
- The C06 repeat-2 'ValueError' originates from model output parsing, not from EvidenceSnapshot.freeze or the harness.
  Models: claude-fable-5-1

## Missing information

- Any real or non-developer-authored artifact samples to estimate over-blocking rate.
  Models: claude-fable-5-1
- Independent verification of source authenticity mechanisms could confirm whether reported limitations pose actual security risks.
  Models: qwen3-coder
- Meaning and downstream use of requirement_match in Stage 8 policy.
  Models: claude-fable-5-1
- Provenance of the C06 repeat-2 ValueError (model vs harness).
  Models: claude-fable-5-1
- Real-system deployment data showing how often these synthetic configurations occur in practice would validate generalizability.
  Models: qwen3-coder
- Source of declarations() and derive() to confirm grammar parity and provenance/None handling.
  Models: claude-fable-5-1
- Whether C10's adapter output was byte-identical to C01's (expected, and if not, indicates proposal leakage into the decision path).
  Models: claude-fable-5-1

## Arbitration note

This file groups wording deterministically. It does not establish truth or semantic consensus. Codex must arbitrate against primary evidence and the user's constraints.
