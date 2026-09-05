# LiteLLM model council comparison

## Coverage

- Selected: claude-fable-5-1, grok-4.6, qwen3-coder
- Valid responses: claude-fable-5-1, grok-4.6, qwen3-coder
- Provider buckets: anthropic, qwen, xai

## Recommendations

### claude-fable-5-1 (anthropic)

Run it as a pilot with claims pre-registered as 'injected-fault robustness on synthetic logs' only; before running, add ≥5 repeated samples per cell (or documented deterministic decoding), add an always-'none' and always-follow-metadata baseline scorer, add at least two harder cases (a consistent fabricated quote whose value matches the target while the source disagrees, and a longer noisy source where metadata could plausibly help), log validator rejection reasons, and confirm case ids are not sent to the model.

Confidence: 0.72

Stage10 is a well-scoped fault-tolerance smoke test, not a utility study. The sources are 5-6 lines and the answer prompt already states the full decision rule, so the raw arm has everything it needs; metadata can only add noise or a nudge, never information. With 18 single-shot calls on one model, no repeats, a 4-of-6 'none' base rate, and faults that are mostly self-inconsistent (quote contradicts value), the design can show whether wrong metadata harms and whether the checker neutralizes those specific faults, but it cannot support any claim that metadata improves decision usefulness. The checker's rules are internally coherent for this syntax, but the fixtures were built by the same hands as the validator, so passing proves little beyond self-consistency.

### grok-4.6 (xai)

Do not run as a usefulness study. Either add non-trivial help-cases, kind/token controls, and a pre-registered no-generalization rule, or relabel this a 6-fixture fault-injection probe and drop the metadata-utility question.

Confidence: 0.84

Stage10 cannot answer its stated goal. Six near-identical line logs plus a policy-complete answer prompt test instruction-following under planted faults, not whether metadata improves usefulness. The checker only rejects syntax it was built to reject; the metric cannot support even a scoped utility claim.

### qwen3-coder (qwen)

Proceed with caution and request additional heterogeneous test cases before drawing utility conclusions.

Confidence: 0.75

The design isolates metadata effects but lacks sufficient variation and real-world fidelity to support strong conclusions about decision usefulness or source-checking efficacy.

## Repeated reasons

- None detected by deterministic comparison.

## Repeated risks

- None detected by deterministic comparison.

## Disagreement themes

- A defender can say the brief already disclaims authentication, entailment, holdout, and production, so a narrow probe is in-scope.
  Models: grok-4.6
- Checked-unknown leaving original text is the right non-repair policy even if models misuse it.
  Models: grok-4.6
- Fixing four faults where the injected candidate value always equals the target is a design choice I would change: include a fault whose value matches the target with a fabricated but plausible quote (source says r1, metadata quotes 'revision: r2'). That is the realistic failure and the one where the candidate arm is most likely to fail.
  Models: claude-fable-5-1
- Same prompt across arms is a real control; adding help-cases would confound format with metadata.
  Models: grok-4.6
- Six fixtures may be enough as a pre-live gate that the harness wires three arms and the checker rejects the four seeds.
  Models: grok-4.6
- The brief frames the goal as 'does metadata improve usefulness'; I disagree this design can address that question at all. It can address 'does wrong metadata degrade, and does checking recover' only.
  Models: claude-fable-5-1
- Treating citation checks as 'traceability only' undersells them: a citation that appears in metadata but not in source is a direct, automatable measure of metadata contamination and should be scored.
  Models: claude-fable-5-1
- Whether six line-based synthetic notes adequately represent production decision contexts
  Models: qwen3-coder

## Shared and unique assumptions

- Answer prompt already encodes the full A/B/none rule, so metadata is a shortcut or distractor, not new evidence.
  Models: grok-4.6
- Case ids like 'wrong_winner' and 'injected_fault' objects are stripped from model inputs.
  Models: claude-fable-5-1
- Checker is exact-line, unique-declaration, parse-equals-value inside the sole [observed] block.
  Models: grok-4.6
- Citation substring checks are run against source text only, not against metadata quotes.
  Models: claude-fable-5-1
- Decoding is non-deterministic at default settings, so single calls per cell carry material variance.
  Models: claude-fable-5-1
- Model behavior is consistent across conditions given identical prompts except for metadata visibility
  Models: qwen3-coder
- One sample per cell on one model; extractor output is overwritten on 4/6 cases.
  Models: grok-4.6
- Source kind and the answer prompt are shown identically in all three arms; only the metadata block differs.
  Models: claude-fable-5-1
- Source kind may be structured in metadata arms but only implicit in raw text.
  Models: grok-4.6
- The checked arm renders rejected fields as 'unknown' without revealing the candidate value; otherwise the arms are not cleanly separated.
  Models: claude-fable-5-1

## Missing information

- A pre-registered analysis that forbids usefulness language unless help-cases exist.
  Models: grok-4.6
- A scoring rubric for explanation quality and a definition of 'usefulness' beyond A/B/none correctness.
  Models: claude-fable-5-1
- Any prior Stage9 results on the same fixtures that would indicate ceiling effects for the raw arm.
  Models: claude-fable-5-1
- At least one noisy source with correct metadata (help) and one syntactically valid but target-wrong field that passes the checker (checker blind spot).
  Models: grok-4.6
- Confirmation that fixture ids and injected_fault objects are excluded from all model inputs.
  Models: claude-fable-5-1
- Decoding parameters and whether repeated runs are planned; without variance estimates no conclusion is defensible.
  Models: claude-fable-5-1
- Decoding settings, whether 18 calls are single-shot, and any seed.
  Models: grok-4.6
- Empirical evidence showing human or system performance differences under each metadata condition
  Models: qwen3-coder
- Exact payload per arm: is kind, field set, and rejection reason serialized, and is raw given the same kind field?
  Models: grok-4.6
- Extractor schema, parse rule after colon, uniqueness/whitespace/case policy, behavior with 0 or 2 [observed] blocks.
  Models: grok-4.6
- How unsupported endorsement vs missed justified choice will be scored when explanation and recommendation conflict.
  Models: grok-4.6
- The exact rendering of candidate and checked metadata blocks as seen by the model, including whether rejection reasons or candidate values leak into the checked arm.
  Models: claude-fable-5-1
- The preserved original extractions for all six cases and whether they pass the validator unmodified.
  Models: claude-fable-5-1
- Validator specification details: normalization rules, uniqueness scope, handling of malformed block markers, and how zero-block sources are treated.
  Models: claude-fable-5-1

## Arbitration note

This file groups wording deterministically. It does not establish truth or semantic consensus. Codex must arbitrate against primary evidence and the user's constraints.
