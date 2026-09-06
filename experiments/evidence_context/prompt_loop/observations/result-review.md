# LiteLLM model council comparison

## Coverage

- Selected: claude-fable-5-1, grok-4.6, qwen3-coder
- Valid responses: grok-4.6, qwen3-coder
- Provider buckets: qwen, xai

## Failed or invalid responses

- **claude-fable-5-1:** ValueError: model did not return a JSON object

## Recommendations

### grok-4.6 (xai)

Do not promote or enlarge this loop. Freeze the scorer, split recommendation from evidence_basis, stop leaking gold rules to the proposer, and run one discriminating holdout: unseen fixtures, a non-Qwen answerer or judge, and human/cross-provider scoring of conflict_kind plus citation support.

Confidence: 0.82

No gain is demonstrated. Baseline remains winner only because a mis-specified category proxy could not credit a real queue fix. Both amendments changed unmeasured later advice from false 'correction'/'B' to 'unresolved'/'insufficient', which matches the written decision checks and the Fable/Grok unsupported labels. They still scored 2/4 because queue gold demands evidence_basis=insufficient while the schema treats existing unmeasured reports as reported_only. That encoding error, not equal quality, produced the tie. Audit never touched the candidates. Promotion is correctly withheld. Do not retune to the four seen fixtures.

### qwen3-coder (qwen)

Reject promotion of any candidate; conduct a new experiment with semantic quality scoring, cross-model validation, and independent holdout cases to meaningfully assess generalization.

Confidence: 0.85

The experiment demonstrates that prompt amendments can improve evidence-handling behavior in synthetic arbitration tasks, but the evaluation methodology has critical limitations. Candidate-1's amendment correctly classifies insufficient evidence cases as 'unresolved', improving integrity over the baseline's premature resolution of contradictory agent reports. However, the audit phase reveals that post-selection performance diverges significantly from development scores, indicating overfitting to known cases. The lack of semantic quality metrics, holdout sets, and cross-model validation undermines confidence in generalization claims.

## Repeated reasons

- None detected by deterministic comparison.

## Repeated risks

- None detected by deterministic comparison.

## Disagreement themes

- If the baseline's willingness to resolve insufficient evidence reflects a defect or pragmatic decision-making
  Models: qwen3-coder
- Qwen's prior needs_review on the four queue errors versus Fable/Grok unsupported. The written checks support unsupported.
  Models: grok-4.6
- Whether audit-phase divergence represents a methodological flaw or legitimate contextual adaptation
  Models: qwen3-coder
- Whether cache B is acceptable versus conditional. Proxy allows both; I would not call B proven.
  Models: grok-4.6
- Whether candidate-2's emphasis on measurable outcomes provides meaningful improvement over candidate-1's stricter evidence distinction
  Models: qwen3-coder
- Whether queue evidence_basis should be insufficient (current RULES) or reported_only (schema-consistent). I treat the RULES as the defect.
  Models: grok-4.6
- Whether retry 'correction' is required because the artifact says 'This corrects...' or whether unequal_evidence is safer. Proxy ignores conflict_kind.
  Models: grok-4.6

## Shared and unique assumptions

- Audit divergence indicates overfitting rather than contextual appropriateness
  Models: qwen3-coder
- Ledger and results.json are complete and unedited.
  Models: grok-4.6
- Prior 24-output review is independent of this 16-call live run.
  Models: grok-4.6
- Proxy scoring accurately reflects meaningful evidence-handling improvements
  Models: qwen3-coder
- Queue gold is meant to follow the prompt's own decision checks, not an unstated extra convention.
  Models: grok-4.6
- qwen3-coder as proposer and answerer is not external validation of Qwen judgments.
  Models: grok-4.6
- The development cases are representative of future arbitration scenarios
  Models: qwen3-coder

## Missing information

- Answers from a different model family on the same frozen prompt.
  Models: grok-4.6
- Any learner-usefulness or engine-comparison measure, which this design cannot provide.
  Models: grok-4.6
- Author intent for queue evidence_basis given the schema clash.
  Models: grok-4.6
- Candidate-1/2 answers on cache and storage.
  Models: grok-4.6
- Cost-benefit analysis of increased prompt complexity against marginal integrity gains
  Models: qwen3-coder
- Cross-model agreement rates on identical arbitration tasks to detect consensus-driven versus model-specific behaviors
  Models: qwen3-coder
- Human or non-Qwen scores of rationale entailment and citation support.
  Models: grok-4.6
- Human-rated semantic quality judgments for both development and holdout cases
  Models: qwen3-coder
- Independent holdout set performance to validate generalization beyond seen fixtures
  Models: qwen3-coder
- Unseen holdout fixtures never used in development or prior stages.
  Models: grok-4.6

## Arbitration note

This file groups wording deterministically. It does not establish truth or semantic consensus. Codex must arbitrate against primary evidence and the user's constraints.
