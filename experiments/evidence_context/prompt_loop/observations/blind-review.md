# LiteLLM model council comparison

## Coverage

- Selected: claude-fable-5-1, grok-4.6, qwen3-coder
- Valid responses: claude-fable-5-1, grok-4.6, qwen3-coder
- Provider buckets: anthropic, qwen, xai

## Recommendations

### claude-fable-5-1 (anthropic)

Use this set only as a LIMITED development proxy for evidence-hierarchy discipline (artifact over report, recency is not evidence, insufficient when nothing is measured, scope claims to tested revision); do not use it to score real-world correctness, generalization beyond the fixture, fine-grained conflict_kind taxonomy, next_check quality, or learner usefulness, and treat the effective sample as four scenario types rather than twenty-four independent items.

Confidence: 0.80

Twenty-four answers over four synthetic scenarios (retry/deadline, cache/concurrency, storage/reopen, queue/performance), with heavy near-duplication. Where a test artifact exists (retry, storage), all answers correctly prefer the measured option and scope claims to the tested revision. Where only agent reports exist, single-report cases are correctly marked insufficient, and cache cases reasonably prefer B on the basis of A's self-declared scope mismatch while flagging the lack of benchmarks. The systematic failure is the two-report queue scenario: four answers (G06, G16, G18, G22) treat a later unbenchmarked assertion as a 'correction' that supersedes an earlier unbenchmarked assertion, directly violating the 'do not guess performance' constraint; the uncertainty caveat does not rescue a categorical recommendation built on recency alone. Twenty supported, four unsupported, none needing review.

### grok-4.6 (xai)

Use as a LIMITED dev proxy only for (1) preferring a matching test artifact over an unmeasured agent report, (2) withholding when the required check is absent, and (3) refusing unmeasured supersession; do not score taxonomy, usefulness, real products, or generalization.

Confidence: 0.82

Most answers track their own fixtures: artifact-backed B picks and withholds on missing checks are source-grounded. Four queue items treat a later unmeasured claim as a performance correction, which the no-guess constraint forbids. Heavy template duplication means n=24 overstates coverage.

### qwen3-coder (qwen)

Approve as a LIMITED development proxy metric for distinguishing evidence basis and handling corrections/conflicts, but not for validating empirical claims

Confidence: 0.85

Most answers correctly distinguish between artifact-supported and reported-only evidence, appropriately challenge unsupported recommendations, and acknowledge uncertainty where evidence is lacking. Several answers make consistent judgments about corrections, changed constraints, and insufficient evidence. However, some responses conflate recency of reports with validity, and a few miss opportunities to highlight missing empirical validation even when recommendations align with constraints.

## Repeated reasons

- G10 | supported | Single confident report with no test output for reopen correctness; insufficient is correct and next_check is apt.
  Models: claude-fable-5-1, grok-4.6
- G19 | supported | Only an unmeasured report for A; no demo-r2 result exists; insufficient is correct.
  Models: claude-fable-5-1, grok-4.6

## Repeated risks

- None detected by deterministic comparison.

## Disagreement themes

- Cache dual-report items (G03/G08/G11/G23) could be called needs_review if 'justified' is read as requiring a reliability benchmark.
  Models: grok-4.6
- conflict_kind and conditional-vs-insufficient labels differ across otherwise justified twins; those are taxonomic, not conclusion, disputes.
  Models: grok-4.6
- If repeated similar judgments indicate genuine understanding or template-following behavior
  Models: qwen3-coder
- One could argue 'conditional' (G05, G07) is a wrong label versus 'insufficient'; I treat this as immaterial because the substantive conclusion is correct.
  Models: claude-fable-5-1
- One could argue the cache-scenario B recommendations (G03, G08, G11, G23) are also unsupported since the second report is just another opinion; I accept them because A's report disqualifies itself for the stated workload and the answers label the basis as reported_only, but a stricter reviewer would mark them needs_review.
  Models: claude-fable-5-1
- Queue dual-report items might be defended as following 'later advice' wording, but that still guesses performance.
  Models: grok-4.6
- Some may accept the queue B recommendations because the uncertainty admits no benchmark exists; I reject this because a caveat does not license a categorical choice the constraint expressly forbids.
  Models: claude-fable-5-1
- Whether recency of agent reports should influence decision-making absent empirical contradiction
  Models: qwen3-coder

## Shared and unique assumptions

- Constraint-matching without a benchmark is allowed when the answer stays reported_only and does not assert measured reliability or speed.
  Models: grok-4.6
- Fixture evidence is complete and the reviewer should not assume unseen artifacts exist.
  Models: claude-fable-5-1
- Grade only support from each item's supplied evidence, not withheld expected labels or independent truth.
  Models: grok-4.6
- Near-duplicate fixtures are graded separately but do not add new behaviors.
  Models: grok-4.6
- Recommendation labels 'insufficient' and 'conditional' are both acceptable ways to decline an unsupported choice when the underlying conclusion is justified.
  Models: claude-fable-5-1
- Synthetic fixtures simulate realistic enough conditions to reflect potential model reasoning patterns
  Models: qwen3-coder
- The 'do not guess performance' constraint applies equally to a later report that offers no measurement.
  Models: claude-fable-5-1

## Missing information

- A written rubric for when constraint-matching may select B versus must return insufficient.
  Models: grok-4.6
- Additional scenarios with partial or indirectly relevant artifacts, conflicting artifacts, or misaligned revisions, needed before the proxy can claim to measure evidence weighting rather than a keyword rule 'artifact beats report'.
  Models: claude-fable-5-1
- Evidence of how these judgments correlate with downstream system reliability or performance
  Models: qwen3-coder
- Held-out non-template fixtures to test the same rules off this wording.
  Models: grok-4.6
- Independent verification of whether models can generalize beyond exact scenario matches
  Models: qwen3-coder
- Non-templated answers from the same models to test whether the observed discipline is prompt-scaffold-dependent.
  Models: claude-fable-5-1
- Whether duplicate stems are intentional weights or accidental copies.
  Models: grok-4.6
- Whether the grading rubric distinguishes 'conditional' from 'insufficient' or scores conflict_kind, which would change how G04, G05, G07 are treated.
  Models: claude-fable-5-1
- Whether the withheld expected labels treat the cache scenario as B or insufficient; if the latter, four of my 'supported' calls would become disagreements with the key rather than errors in the answers.
  Models: claude-fable-5-1

## Arbitration note

This file groups wording deterministically. It does not establish truth or semantic consensus. Codex must arbitrate against primary evidence and the user's constraints.
