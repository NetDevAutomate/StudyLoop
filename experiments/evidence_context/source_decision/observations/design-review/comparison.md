# LiteLLM model council comparison

## Coverage

- Selected: claude-fable-5-1, grok-4.6, qwen3-coder
- Valid responses: claude-fable-5-1, grok-4.6, qwen3-coder
- Provider buckets: anthropic, qwen, xai

## Recommendations

### claude-fable-5-1 (anthropic)

Freeze a written block-scoped grammar (tags on their own lines, exact byte equality for values, no normalization, unknown keys inside the block disallowed or explicitly ignored) before execution, replace the duplicate C10 with a formatting-edge case, and pre-register that C05 is the discriminating case between the conservative and source-adapter paths.

Confidence: 0.82

Applying the stated policy mechanically yields four supported choices (C01 B, C04 A, C05 A, C10 B) and eight 'none' outcomes. The policy is mostly unambiguous for this set, but C05 exposes a real specification gap: the policy says out-of-block lines are not observed declarations, yet a source-adapter reparse that scans the whole text rather than the block interior would count them as duplicates and flip C05 to none, so the two release paths can legitimately disagree on the same source. The case set is also thin: C01 and C10 are byte-identical, only four positives exist, and no case probes whitespace, case-folding, key ordering, unknown keys inside the block, unclosed tags, or tag-with-trailing-text edge conditions, so the experiment cannot distinguish a correct parser from a lucky one.

### grok-4.6 (xai)

Do not execute the 24-call experiment; lock a formal observed-block grammar, drop or replace the C01/C10 duplicate, add malformed-fence and in-block extra-key cases, and score both deterministic paths against a written oracle rather than this council.

Confidence: 0.86

Policy application is mostly mechanical and yields 4 supported choices (C01 B, C04 A, C05 A, C10 B) and 8 none. The proposed 24-call run should not proceed as designed: the case set is duplicated and under-powered, the declaration grammar is informal, and these model reviews are explicitly not independent gold.

### qwen3-coder (qwen)

Reject the current labeling policy and experimental setup; revise to allow for robust handling of ambiguous or malformed source data and ensure true independence of evaluation.

Confidence: 0.85

The labeling policy is overly rigid and fails to account for realistic data quality issues, while the experimental design lacks independence and introduces circular reasoning through its reliance on pre-existing (and potentially flawed) automated extractions.

## Repeated reasons

- C03|none|source.kind is report, not artifact, regardless of block content
  Models: claude-fable-5-1, grok-4.6, qwen3-coder
- C09|none|duplicate winner declarations A and B inside the block
  Models: claude-fable-5-1, grok-4.6, qwen3-coder
- C01|B|artifact, single well-formed block, all four fields byte-equal to target, exactly one winner B
  Models: claude-fable-5-1, grok-4.6
- C02|none|environment fixture-west mismatches target fixture-east
  Models: claude-fable-5-1, grok-4.6
- C06|none|no winner declaration inside the block
  Models: claude-fable-5-1, grok-4.6
- C07|none|two [observed] blocks present, policy requires exactly one
  Models: claude-fable-5-1, grok-4.6
- C08|none|workload two writers mismatches target six writers
  Models: claude-fable-5-1, grok-4.6
- C11|none|duplicate revision declarations r1 and r2
  Models: grok-4.6, qwen3-coder
- C12|none|revision declaration missing from block while target requires r2
  Models: claude-fable-5-1, grok-4.6

## Repeated risks

- None detected by deterministic comparison.

## Disagreement themes

- A stricter reading could mark C05 none on the theory that any trailing key: value is malformed, not merely unobserved.
  Models: grok-4.6
- Conservative-vs-adapter field selection is not specified tightly enough for two implementers to match without further rules.
  Models: grok-4.6
- Counting C10 as a distinct case inflates apparent coverage; it should be replaced, not retained.
  Models: claude-fable-5-1
- Duplicate same-value keys are untested; C11 only shows conflicting duplicates.
  Models: grok-4.6
- If enforcing exact equality across all four dimensions is more important than semantic alignment when minor variations occur.
  Models: qwen3-coder
- The brief frames C05 as unambiguous under 'lines outside the block are not observed declarations'; I would argue it is the single most valuable case and should be pre-registered as a deliberate path-divergence probe rather than folded into the positive set.
  Models: claude-fable-5-1
- The brief treats the source-adapter path as 'never a silent repair', but if it re-derives the full answer from source without reference to the candidate, it is not a release path for the model output at all; it is an independent oracle, and the experiment then measures whether the model is redundant rather than whether it is correct.
  Models: claude-fable-5-1
- Unknown in-block keys are unspecified; some will treat them as fatal, others as ignorable.
  Models: grok-4.6
- Whether 'artifact' vs 'report' distinction meaningfully contributes to labeling fidelity when both can contain equivalent structured data.
  Models: qwen3-coder
- Whether excluding cases based on duplicate or missing declarations improves or degrades overall experimental validity.
  Models: qwen3-coder

## Shared and unique assumptions

- A declaration is a single in-block `key: value` line; only revision, workload, environment, metric, and winner are relevant.
  Models: grok-4.6
- Any duplicate required key is fatal even if one value equals the target.
  Models: grok-4.6
- Block tags [observed] and [/observed] must appear on their own lines and the block interior is the only parsed region.
  Models: claude-fable-5-1
- Lines after [/observed] are ignored rather than making the block malformed.
  Models: grok-4.6
- Only revision/workload/environment/metric/winner are required; presence of other keys inside the block is not addressed by the policy and is assumed absent in these fixtures.
  Models: claude-fable-5-1
- source.id is not a policy input and differences in it would not affect labels.
  Models: claude-fable-5-1
- Target fields are always complete, so equality is a four-field exact string match with no normalization specified.
  Models: grok-4.6
- The purpose of the experiment is to evaluate decision-making reliability under realistic conditions, not merely to validate a brittle parsing rule.
  Models: qwen3-coder
- Value comparison is exact string equality with no case-folding or whitespace trimming beyond the newline delimiter.
  Models: claude-fable-5-1
- Winner must be exactly the token A or B; kind must be exactly artifact.
  Models: grok-4.6

## Missing information

- A non-duplicate positive matrix that separately varies winner A/B and outside-noise vs true omission.
  Models: grok-4.6
- BNF or equivalent for observed blocks: spacing, case, unknown keys, duplicate same values, unclosed fences.
  Models: grok-4.6
- Data comparing outcomes from conservative vs source-adapter paths using truly independent ground truth rather than recycled script-based proposals.
  Models: qwen3-coder
- Empirical evidence showing how often real-world sources deviate from perfect formatting versus how often such deviations correlate with incorrect decisions.
  Models: qwen3-coder
- Exact conservative-path rule when a candidate has extra or conflicting winner/revision fields.
  Models: grok-4.6
- The definition of the pre-registered false-blocking metric and the sample size deemed sufficient to detect a meaningful rate with only four positives.
  Models: claude-fable-5-1
- The exact reference grammar used by the source-adapter path, in particular whether it is block-scoped and how it handles duplicate keys, ordering, casing, and whitespace.
  Models: claude-fable-5-1
- What the 'frozen prior answer prompt' contains and whether it embeds any of the target field values, which would let the model reconstruct answers without reading the source.
  Models: claude-fable-5-1
- Whether a reference parser has already been run on these 12 fixtures and what it outputs for C05.
  Models: claude-fable-5-1
- Whether the 'strict JSON' and 'complete-fence-only' measurements share a single model call or are separate calls, which affects whether the 24-call budget is actually 48.
  Models: claude-fable-5-1
- Whether these council strings will be used as gold despite the brief stating they are not independent human labels.
  Models: grok-4.6
- Whether trailing text is defined as ignore or malformed.
  Models: grok-4.6

## Arbitration note

This file groups wording deterministically. It does not establish truth or semantic consensus. Codex must arbitrate against primary evidence and the user's constraints.
