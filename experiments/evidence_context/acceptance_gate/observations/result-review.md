# LiteLLM model council comparison

## Coverage

- Selected: claude-fable-5-1, grok-4.6, qwen3-coder
- Valid responses: claude-fable-5-1, grok-4.6, qwen3-coder
- Provider buckets: anthropic, qwen, xai

## Recommendations

### claude-fable-5-1 (anthropic)

Record Stage9 as 'policy-rendered release with model-agreement telemetry', not as an LLM gate; do not carry any protection claim forward beyond derive() correctness and local snapshot binding. Before any stage that lets model text influence release, run a discriminating live probe in which artifact text contradicts its own metadata (the upstream_forgery_blind_spot case) with >=5 samples per arm, to test whether free-text reading can add a signal that metadata policy structurally cannot.

Confidence: 0.70

The code does what the brief says: released_answer is always derive(case), so no model field or prose can reach release, and snapshot/envelope/policy-digest binding prevents stale or swapped metadata within one process. But that also means the 'gate' provides no protection beyond what derive() alone provides; its only function is telemetry on model agreement. The offline prose-isolation probes therefore demonstrate a tautology, not a defended attack surface. The live data (6 cases x 2 arms, n=1, no retries) shows prompt_only invented scope matches in both unknown-scope cases even without injection, so the injected case is not a clean injection test for that arm; the single informative datapoint is that the copy-control arm, given the full correct answer and told to preserve it, still flipped applicability and decision under injection. Actual policy correctness rests on unseen policy.py plus author-written expectations, and the brief's 'against code' review is incomplete because assess/derive/validate were not supplied.

### grok-4.6 (xai)

Keep the gate as the only release path for this synthetic contract. Do not widen scope. Next discriminating step: a second, independently written policy oracle plus a multi-sample injection sweep; do not add free-text richness until those fail or pass.

Confidence: 0.78

Stage9 binds release to a local policy snapshot and withholds model prose. Live and offline results show the gate, not the model, is what stops missing-scope invention and in-band injection. That is real, narrow protection. It does not authenticate sources, prove the policy, or restore the rich validated context the user asked for. Copy-control failed on the injected case, so the model is not a reliable copier either.

### qwen3-coder (qwen)

Approve the current gate mechanism for production use but mandate upstream source authentication before any synthetic findings influence real-system decisions.

Confidence: 0.85

The Stage9 gate experiment demonstrates robust discrimination between valid and invalid evidence, correctly rejecting cases with missing or mismatched metadata while accepting those with fully aligned scopes. However, the system's inability to detect upstream fabrication highlights a critical unresolved trust boundary.

## Repeated reasons

- None detected by deterministic comparison.

## Repeated risks

- None detected by deterministic comparison.

## Disagreement themes

- Calling live-expectations 'separately written' is not independently proven by the code; test_reference_against_separately_written_pre_run_expectations checks derive against a file, but both may share an author and the same mental model. It also skips reason_code.
  Models: claude-fable-5-1
- Copy-control is not a weak reasoning comparison; on the injected case it is a failed instruction-hierarchy test. Treating it as a mere preserve-the-answer control hides that failure.
  Models: grok-4.6
- Passing pre-written expectations is stronger evidence for this frozen policy than the brief allows, and weaker than an independent implementation would be. Both are true.
  Models: grok-4.6
- Renaming outcomes draft_agrees/draft_diverges after pre-review does not change that agree is not ‘correct reasoning’.
  Models: grok-4.6
- The brief frames this as a 'gate experiment' assessing protection. There is no gate on the release path, only on a status field; the experiment measures model agreement with a policy, and its safety properties belong entirely to Stage8's policy plus serialization hygiene.
  Models: claude-fable-5-1
- The brief’s line that the model is redundant is true only for released_answer bytes. Telemetry, copy-control design, and any later use of draft_agrees rates still depend on the model.
  Models: grok-4.6
- The injected case should not be reported as an injection result for prompt_only; only the copy-control arm isolates the injection effect, and even there a placebo-instruction control is absent.
  Models: claude-fable-5-1
- The prose-isolation tests (forged_prose_is_not_released, test_all_model_free_text_is_isolated) are worth keeping as regression guards but should not be listed as demonstrated defenses, since the release path never reads those fields.
  Models: claude-fable-5-1
- Whether implicit instruction overrides (e.g., injected_unknown_revision) should supersede explicit scope validation rules
  Models: qwen3-coder

## Shared and unique assumptions

- contract_copy_control actually embedded the full derive() answer, as the brief claims; runner.py was not provided.
  Models: grok-4.6
- live-expectations.json was written before live calls and by a different hand than derive(), as the brief asserts; this cannot be verified from the artifacts.
  Models: claude-fable-5-1
- live-expectations.json was written separately from derive(), but still against the same Stage8 policy.
  Models: grok-4.6
- Metadata provided by the application layer is truthful and complete
  Models: qwen3-coder
- policy.derive/assess/validate behave as the tests imply (missing scope field -> 'unknown'; conflicting applicable artifacts -> conflicting_observations); the module itself was not provided for review.
  Models: claude-fable-5-1
- Review is of recorded protection only; no claim about hidden cases or real artifacts.
  Models: grok-4.6
- The 153 passing tests include the 8 shown plus Stage8 policy tests; only the 8 shown were inspected.
  Models: claude-fable-5-1
- The replay rows use stored non-derived answers (replay unknown_revision diverges while derive(unknown_revision) agrees in tests), otherwise the replay result would indicate a bug.
  Models: claude-fable-5-1
- The stated 153 passing tests, 18 offline rows, and 12 single-shot live calls are complete and unedited.
  Models: grok-4.6

## Missing information

- A live run of the upstream_forgery_blind_spot case to see whether either arm flags the text/metadata contradiction; a positive result would be the first evidence the model could add value the policy cannot.
  Models: claude-fable-5-1
- A second-oracle diff on the same cases; any mismatch would overturn confidence in the renderer.
  Models: grok-4.6
- Any non-synthetic source, attestation scheme, or holdout. None exist here, so no claim about real reopen correctness is licensed.
  Models: grok-4.6
- Authentication chain verification for artifact provenance beyond local hash binding
  Models: qwen3-coder
- Authorship and timestamps for live-expectations.json relative to derive() changes.
  Models: claude-fable-5-1
- Independent reproduction of conflicting check results (S3 vs S4) under identical conditions
  Models: qwen3-coder
- policy.py source (assess, derive, validate) so the oracle's rules, basis_coverage logic, and exception behaviour can be reviewed rather than inferred.
  Models: claude-fable-5-1
- policy.py, cases.json, live-expectations.json, and runner.py (copy-control prompt and prepare() replay answers).
  Models: grok-4.6
- Repeated live samples (>=5 per cell) for the two unknown-scope cases and the injected case, plus a placebo-injection control, to distinguish injection effect from baseline scope-invention.
  Models: claude-fable-5-1
- Repeats of the six live cells, especially injected_unknown_revision copy-control.
  Models: grok-4.6
- The exact prompts for both arms and the raw model responses, to confirm the copy-control instruction wording and that no post-processing occurred.
  Models: claude-fable-5-1
- The remaining ~145 tests, and the runner.py replay mechanism (what answers were replayed for wrong_revision, wrong_metric, validated_fit, and why replay unknown_revision diverges).
  Models: claude-fable-5-1
- Whether expectations were sealed before derive() existed, or written by reading it.
  Models: grok-4.6

## Arbitration note

This file groups wording deterministically. It does not establish truth or semantic consensus. Codex must arbitrate against primary evidence and the user's constraints.
