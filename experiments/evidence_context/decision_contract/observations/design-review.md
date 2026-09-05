# LiteLLM model council comparison

## Coverage

- Selected: claude-fable-5-1, grok-4.6, qwen3-coder
- Valid responses: claude-fable-5-1, grok-4.6, qwen3-coder
- Provider buckets: anthropic, qwen, xai

## Recommendations

### claude-fable-5-1 (anthropic)

Approve the contract for the Stage 8 probe with three edits before answer-model runs: (1) state explicitly that any applicable artifact supersedes requirement_fit mode; (2) fix basis_ids rule for insufficient decisions to 'all supplied source IDs'; (3) add a sufficiency detail field or an explicit 'conflicting' explanation requirement; and add at least four adversarial cases plus automated consistency checks listed below.

Confidence: 0.78

The contract separates provenance (report|artifact), per-source applicability, and decision sufficiency more cleanly than the prior stage, and the eight cases exercise each axis at least once. However, it still uses a single 'insufficient' label for two different states (no applicable evidence vs contradictory applicable evidence), leaves basis_ids citation rules partly ambiguous for inapplicable/unknown artifacts, does not explicitly state that applicable artifacts override requirement_fit mode, and lacks adversarial cases (conclusion/text mismatch, injected instructions, scope casing, both-options requirement_match). It is fit for a narrow probe only if paired with schema and consistency validators; it is not evidence about real verification.

### grok-4.6 (xai)

Lock the eight expected labels below, add negative fixtures for dual/zero requirement_match and mode/artifact precedence, and run answer models only as a schema/contract probe.

Confidence: 0.80

The contract structurally separates provenance, applicability, and sufficiency, and it correctly treats measured abstention as a first-class outcome. It does not by itself prevent false assurance: 'supported' plus a letter recommendation can still be over-read as validation of synthetic metadata. Accept only as a locked pre-run fixture spec, not as evidence quality.

### qwen3-coder (qwen)

Approve with mandatory clarification on handling requirement_fit precedence over measured results and add explicit gate for scope alignment verification.

Confidence: 0.85

The contract distinguishes provenance, applicability, and sufficiency clearly but introduces ambiguity in requirement_fit mode where measured outcomes override explicit requirement claims. Several cases lack necessary artifact alignment or contain conflicting data, leading to insufficient or conditional decisions.

## Repeated reasons

- None detected by deterministic comparison.

## Repeated risks

- None detected by deterministic comparison.

## Disagreement themes

- A narrower contract could forbid recommendation letters unless sufficiency is supported, to reduce false assurance.
  Models: grok-4.6
- basis_ids for measured gaps are underspecified (all sources vs only the explanatory subset).
  Models: grok-4.6
- In validated_fit I would accept basis_ids of S3 or S2+S3, and the contract should say so; forcing S3-only penalizes a reasonable and more transparent citation.
  Models: claude-fable-5-1
- Requiring exact metadata match for applicability is appropriate for this probe but should be labeled as a probe-specific rule; otherwise later stages may inherit an overly brittle notion of applicability that rejects legitimately transferable artifacts.
  Models: claude-fable-5-1
- The brief frames the contract as distinguishing three concepts, but sufficiency still collapses 'no applicable evidence' and 'contradicted evidence' into one value; I would add a sub-field or a fourth value rather than rely on explanation prose.
  Models: claude-fable-5-1
- There's tension between excluding reports from validation while allowing them to drive conditional decisions based on requirement_match.
  Models: qwen3-coder
- validated_fit could be read as still conditional because decision_mode is requirement_fit; the written rule makes that path only 'with no applicable artifacts.'
  Models: grok-4.6
- Whether validated_fit should prioritize empirical outcome over initial requirement assertion is debatable under current framing.
  Models: qwen3-coder

## Shared and unique assumptions

- All sources are synthetically generated and treated as logically consistent within their own context.
  Models: qwen3-coder
- Exact four-field artifact match is the sole empirical bar; reports are never empirical.
  Models: grok-4.6
- Expected labels are graded on sufficiency, recommendation, applicability and basis_ids, with reasons checked for presence and rough content rather than exact strings.
  Models: claude-fable-5-1
- requirement_fit may be conditional only when no applicable artifact exists and exactly one option has requirement_match true.
  Models: grok-4.6
- Scope matching is intended as exact string equality on the four keys; extra keys in artifact scope are not disqualifying.
  Models: claude-fable-5-1
- The eight cases are a smoke probe of contract comprehension, not a measure of evidence-extraction quality.
  Models: claude-fable-5-1
- The three concepts are provenance (source kind), applicability (use for this target), and sufficiency (what may be decided).
  Models: grok-4.6
- These cases are authored synthetic fixtures, not holdout or verification evidence.
  Models: grok-4.6

## Missing information

- A recency-ban test on S2-style wording.
  Models: grok-4.6
- Additional cases needed to change confidence: injected instruction in a source text, artifact conclusion contradicting its text, two requirement_match=true reports, requirement_match=true in measured mode, inapplicable artifact alongside requirement_fit reports (should yield conditional, not supported), and an artifact whose scope has an extra unrelated key.
  Models: claude-fable-5-1
- Exact-match, known-mismatch, and missing-field classifier tests, including string-normalization policy.
  Models: grok-4.6
- Explicit rule defining precedence between requirement_fit claims and subsequent contradictory empirical findings.
  Models: qwen3-coder
- Gate ensuring all artifact scopes include full target dimensions before declaring applicability.
  Models: qwen3-coder
- Golden source_assessments and decision objects for all eight cases.
  Models: grok-4.6
- Grader checks that limitations disclaim authenticity/reproduction/stats/entailment and that conditional text says proposal suitability, not measured success.
  Models: grok-4.6
- Implementation tests I would expect: schema key exactness; basis_ids subset of supplied IDs and nonempty; sufficiency/recommendation pairing invariants (supported⇒A|B, insufficient⇒none, conditional only in requirement_fit); applicability of every report is not_validation; every source has a reason; no applicable artifact cited when scope mismatches; scope-normalization behavior.
  Models: claude-fable-5-1
- Mechanism for resolving discrepancies between multiple applicable artifacts measuring same target.
  Models: qwen3-coder
- Negative fixtures: two requirement_match true, zero true, measured reports with requirement_match true, requirement_fit plus conflicting artifacts, empty source list.
  Models: grok-4.6
- The grading rubric: which fields are scored, whether basis_ids is set-equality or superset, and how reasons are judged.
  Models: claude-fable-5-1
- Whether the answer-model prompt includes the contract verbatim or a paraphrase, and whether source text is delimited to support 'treat as data'.
  Models: claude-fable-5-1

## Arbitration note

This file groups wording deterministically. It does not establish truth or semantic consensus. Codex must arbitrate against primary evidence and the user's constraints.
