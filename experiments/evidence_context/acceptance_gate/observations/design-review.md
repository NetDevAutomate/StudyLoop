# LiteLLM model council comparison

## Coverage

- Selected: claude-fable-5-1, grok-4.6, qwen3-coder
- Valid responses: claude-fable-5-1, grok-4.6, qwen3-coder
- Provider buckets: anthropic, qwen, xai

## Recommendations

### claude-fable-5-1 (anthropic)

Proceed to implementation and the 12-call probe only after (a) renaming the accept/reject outcome to something like 'draft_agrees_with_contract' vs 'draft_diverges_from_contract', (b) adding hand-verified expected contracts for the six live inputs and eight replay cases that are independent of any model output, (c) adding a prose-isolation test asserting released_answer shares no free-text with model prose fields, and (d) documenting condition 2 as a compliance/copy control rather than a second reasoning condition.

Confidence: 0.70

The design is directionally sound and unusually honest about limits, but it has a structural tension: because released_answer is always rendered from the deterministic policy, the model contributes nothing to what is released, so the gate is a measurement of model/policy agreement, not a safety mechanism for model output. The deterministic Stage8 policy becomes the single oracle for both the gate and the release, with no independent check on its own correctness. The live probe's second condition (contract in context) is a copy test, not a reasoning test, and n=1 per cell means results are anecdotes. The release boundary is mostly described honestly, but the label 'accepted_structured' and the phrase 'acceptance enforced by code' invite over-reading.

### grok-4.6 (xai)

Implement the snapshot-bound code gate and the listed offline probes only after specifying canonical JSON hashing, who binds snapshot_id, extra-citation rejection, and distinct accepted-vs-rejected payloads; treat the eight-answer replay as diagnostic (not a 7-accept bar); run the 12 Qwen calls only as a labelled smoke check, without putting the precomputed contract in context if the object is to test the gate.

Confidence: 0.78

The gate is a conservative structural consistency check against an application-owned snapshot and a frozen Stage8 policy, not semantic acceptance. That release boundary is mostly honest and appropriately fail-closed, but naming, the 7/8 replay target, hash/binding underspecification, and a confounded 12-call live probe can create false confidence or implementation drift. Implement the code gate and offline probes after a few bounded clarifications; do not treat replay or live calls as quality proof.

### qwen3-coder (qwen)

Approve with clarification that upstream metadata authenticity is out-of-scope and that downstream ambiguity must be explicitly represented in rejection feedback.

Confidence: 0.75

The proposed Stage 9 metadata acceptance gate introduces a conservative, code-enforced mechanism to validate structured decision metadata against immutable snapshots. While the design appropriately isolates policy computation from model outputs and enforces strict schema compliance, it lacks clarity on handling partial or ambiguous metadata states and relies on unverified upstream ingestion integrity.

## Repeated reasons

- None detected by deterministic comparison.

## Repeated risks

- None detected by deterministic comparison.

## Disagreement themes

- If code already recomputes applicability, decision, reasons, and released prose, 'accepting' a model draft is only an audit consistency flag. Calling this an acceptance gate invites scope creep toward using model text.
  Models: grok-4.6
- If rejecting drafts solely based on structural/schema mismatches without semantic context is sufficient for operational trust
  Models: qwen3-coder
- Preserving 'explanation richness' is listed as a cost, but if the model's prose never ships, richness was never available; the real cost is that the model is currently redundant in the release path, and that should be stated plainly rather than softened.
  Models: claude-fable-5-1
- Preserving explanation richness is already forfeited; do not keep unused free-text fields in the public schema if they cannot enter release.
  Models: grok-4.6
- Replaying eight prior answers with an expected 7/1 split is not a gate spec; a stricter gate that rejects more than one of those drafts would be a success, not a failure.
  Models: grok-4.6
- Replaying eight Stage8 answers with a pre-declared 7/1 expectation is regression fitting, not evidence; if the gate produces a different split, the correct response may be to trust the gate over the expectation, and the plan should say so.
  Models: claude-fable-5-1
- The brief frames this as an acceptance gate on model answers; given the release path, it is more accurately a conformance monitor. Calling it 'acceptance enforced by code' overstates what acceptance controls.
  Models: claude-fable-5-1
- The two-condition live plan mixes prompt-engineering with gate testing and should not ship as part of the acceptance design.
  Models: grok-4.6
- Whether silent loss of explanation detail (via prose filtering) aligns with transparency goals
  Models: qwen3-coder

## Shared and unique assumptions

- All relevant edge cases can be captured through synthetic probes without live data
  Models: qwen3-coder
- Canonical JSON serialization is stable (key ordering, numeric formatting, unicode normalization) so the content hash is reproducible across runs.
  Models: claude-fable-5-1
- Immutable snapshot generation from Stage 8 is reliable and tamper-evident
  Models: qwen3-coder
- Model sampling parameters (temperature/seed) are fixed and disclosed for the 12 calls.
  Models: claude-fable-5-1
- Model-generated prose will never influence released_answer rendering
  Models: qwen3-coder
- No database, auth framework, or production path is in scope.
  Models: grok-4.6
- released_answer construction is identical in method for accept and reject: policy facts/reasons only.
  Models: grok-4.6
- Same Qwen model and Stage8 schema as prior work.
  Models: grok-4.6
- Stage8 policy code is frozen and is the sole decision oracle; the gate will reproduce policy bugs.
  Models: grok-4.6
- Synthetic cases and snapshots are human-validated fixtures, not live provenance.
  Models: grok-4.6
- The audit log is not consumed by any downstream process that treats stored prose as verified.
  Models: claude-fable-5-1
- The existing Stage8 deterministic policy is itself correct on the eight replay cases; if its computed contract differs from the gold labels used to score 7/8, the replay comparison is not like-for-like.
  Models: claude-fable-5-1

## Missing information

- A rename-invariance test showing gate output is unchanged when case names are altered.
  Models: claude-fable-5-1
- Behavior matrix for applicability-correct/decision-wrong, unknown-vs-inapplicable swap, hash mismatch with matching id, empty sources, and duplicate basis_ids.
  Models: grok-4.6
- Canonicalization rule and hash algorithm for snapshot bytes.
  Models: grok-4.6
- Canonicalization spec and a test that two independent serializations of the same case yield identical hashes.
  Models: claude-fable-5-1
- Documentation of fallback behavior when conflicting observations exist but resolution paths are available
  Models: qwen3-coder
- Empirical evidence showing how often legitimate cases are rejected due to metadata inconsistencies
  Models: qwen3-coder
- Exact request/response schemas: who supplies snapshot_id, and the labelled payloads for structurally_consistent vs rejected fallback.
  Models: grok-4.6
- Frozen Stage8 policy identifier/version bound into the snapshot.
  Models: grok-4.6
- How policy-rendered reasons preserve source text/derivation without copying model prose.
  Models: grok-4.6
- How the audit log marks model prose and who can read it, to bound the leakage risk.
  Models: claude-fable-5-1
- Independent, hand-derived expected contracts for the six live inputs and eight replay cases, written before running the policy, to detect policy errors.
  Models: claude-fable-5-1
- Precise specification of how 'unknown' applicability maps to decision sufficiency and option, and of the treatment of superfluous but valid basis_ids.
  Models: claude-fable-5-1
- Sampling configuration for the Qwen calls and whether determinism is achievable; if not, n=1 per cell should be reported as illustrative only.
  Models: claude-fable-5-1
- Whether accepted and rejected released_answer content differ, and if so how, beyond the label.
  Models: claude-fable-5-1
- Whether citations beyond the minimum set are rejected when absent from the snapshot.
  Models: grok-4.6
- Which of the eight Stage8 answers is the scope-invention case, and the per-field contract diffs for the other seven.
  Models: grok-4.6

## Arbitration note

This file groups wording deterministically. It does not establish truth or semantic consensus. Codex must arbitrate against primary evidence and the user's constraints.
