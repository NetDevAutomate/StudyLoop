# LiteLLM model council comparison

## Coverage

- Selected: claude-fable-5-1, grok-4.6, qwen3-coder
- Valid responses: grok-4.6, qwen3-coder
- Provider buckets: qwen, xai

## Failed or invalid responses

- **claude-fable-5-1:** ValueError: model did not return a JSON object

## Recommendations

### grok-4.6 (xai)

Do not promote extracted or checked metadata from these scores. Independently re-label the 56 frozen answers for quote origin and checker-as-authority, then run one 8-call source-hidden probe on duplicate_revision and report_only only; no prompt edits, no other cases, no engine choice.

Confidence: 0.76

This synthetic pilot does not establish metadata utility. The extracted-vs-raw choice delta is only missing_revision twice. Checked nets zero by fixing that case and breaking report_only. Every arm endorses on duplicate_revision. Fence-stripping is a legitimate format diagnostic, not a replacement score. Labels, fixtures, and the decision rule share one author, so these are not independent outcomes.

### qwen3-coder (qwen)

Run a follow-up experiment comparing raw vs. extracted performance with clearer fault isolation and independent labeling.

Confidence: 0.75

Metadata checking adds minimal value and introduces regressions; raw source evaluation performs adequately on clean cases but fails systematically on edge cases involving missing or ambiguous fields.

## Repeated reasons

- None detected by deterministic comparison.

## Repeated risks

- None detected by deterministic comparison.

## Disagreement themes

- Calling checked a 'repair' of missing_revision overstates it: extracted already repaired that case without status codes, and checked simultaneously created a new endorsement class.
  Models: grok-4.6
- Choice_matches is the wrong headline once citation origin and kind-handling fail on otherwise 'correct' rows.
  Models: grok-4.6
- False authority from checked wording is a hypothesis suggested by report_only echoing 'unique exact declaration'; it is not identified without an ablation, so it should not be written as a wording cause.
  Models: grok-4.6
- I would not treat recovered fences as evidence the model 'really' produced 56 valid answers; the frozen contract was strict JSON and most arms failed it.
  Models: grok-4.6
- If normalization should be considered part of the core process or a post-hoc correction that undermines experimental validity
  Models: qwen3-coder
- The extent to which markdown fence failures reflect model limitations versus interface brittleness
  Models: qwen3-coder
- The protocol claim that raw versus extracted estimates a clean-metadata context effect is not supported by the headline delta; that delta is a seeded-absence case, not clean context.
  Models: grok-4.6
- Whether the checked wrapper provides net benefit or falsely implies authority through apparent validation
  Models: qwen3-coder

## Shared and unique assumptions

- Cache independence is unknown, so near-duplicate answers may not be independent draws.
  Models: grok-4.6
- Coordinator expected_choice values implement the written A/B/none rule.
  Models: grok-4.6
- Model behavior is stable across repeats and conditions
  Models: qwen3-coder
- Post-hoc removal of one complete fence left recommendation text unchanged.
  Models: grok-4.6
- Source and target text were fully visible in every answer arm.
  Models: grok-4.6
- Two temperature-0 repeats are paired observations, not a reliability estimate.
  Models: grok-4.6

## Missing information

- A second model or seed condition; one coder model cannot separate fixture regularity from method.
  Models: grok-4.6
- Ablation study removing individual metadata fields to isolate their contributions
  Models: qwen3-coder
- An ablation that holds fields fixed and varies only checker status text, or hides source while holding metadata fixed.
  Models: grok-4.6
- Any natural extractor miss on this grammar; ceiling extraction means fault recovery was never tested on live mistakes.
  Models: grok-4.6
- Cache independence confirmation to rule out cross-condition contamination
  Models: qwen3-coder
- Independent human labels for all answer outputs to validate automated checks
  Models: qwen3-coder
- Independent pre-result labels for choice, quote origin (observed-block vs target vs metadata vs outside-block), and whether explanations treat matched status as authenticity.
  Models: grok-4.6
- Per-call token counts, request IDs, and cache-hit flags.
  Models: grok-4.6

## Arbitration note

This file groups wording deterministically. It does not establish truth or semantic consensus. Codex must arbitrate against primary evidence and the user's constraints.
