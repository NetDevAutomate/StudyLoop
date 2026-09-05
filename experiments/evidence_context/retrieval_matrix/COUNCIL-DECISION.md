# Council evidence and coordinator decision

## Coverage, including failures

All calls used the configured LiteLLM gateway with selected excerpts explicitly
authorized by the user. The same brief went to each selected provider in each round.
Raw real-data briefs and responses are private; no transcript bodies are committed.

| Round | Fable 5.1 / Anthropic | Grok 4.6 / xAI | Qwen3-Coder / Qwen |
|---|---|---|---|
| Pre-retrieval episode labels | valid | valid | valid response; Q4 label line malformed |
| Full blinded 32-answer review | not a JSON object | no text content | valid |
| Focused eight-Q3-answer retry + storage summary | not a JSON object | timeout | valid, omitted requested storage reason |

There was provider-diverse input to **labels**, but no provider-diverse consensus on
answer results. The one bounded focused retry did not repair coverage. We stopped;
we did not keep querying until reviewers agreed or returned a desired verdict.
Qwen both answered and reviewed, so its result grades carry additional dependence.

## What I accepted and rejected before retrieval

Accepted: conversation reports support reconstructions of reported decisions, not
independently authenticated outcomes. Keep episode pools independent of retrieval
rankings and preserve missing validation. Keep this a development pilot, not a holdout.

Rejected: Qwen's inference that internally consistent reports proved checks were
validated. Also rejected the reviewers' proposed “alternatives” when they described
different facts. The three-group cap was removed before ranking; Q3 needs four facets.
Q2's final summary was added as a valid alternative for its detachment fact because
it explicitly states screen was used. These choices were fixed before retrieval.
Per-reviewer sensitivity counts retain what the original labels would have scored.

A claim that merely building an unlabeled adjacency graph is supervised training
leakage would be too strong. However, known-episode question selection and related
history absolutely prevent an independent-holdout claim in this pilot.

## What I accepted and rejected after answers

Accepted: Q3 repeatedly combines different workflows and fails to distinguish plans
from completed checks. The failure is visible directly in the source/answer pairing.

Rejected: treating reported_only as sufficient protection against unsupported prose.
The focused Qwen reviewer called a combined answer partial/no-overclaim while that
answer explicitly said cleanup was conducted and cited only a plan heading. Its own
executive summary also described source-reported checks as validated. That judgment
fails the supplied evidence contract. It is retained as a reviewer disagreement, not
used to excuse the draft.

The coordinator's inspection finds material problems in all eight Q3 drafts. This is
an analyst judgment about these examples, not a human-adjudicated accuracy rate. We do
not publish one global answer-quality percentage or a retriever winner from these data.

## Next decision

Keep the prompt frozen. Use a separately reviewed complete-evidence pack as a control
for the failed episode, then test episode identity, execution state and validation
applicability on new cases. This distinguishes retrieval omission from answer misuse.
Only after independent labels and useful results should a product adapter be chosen.
Maintain work/personal boundaries, correction/forgetting, why-context explanations and
capture health as integration requirements. Nothing here relaxes those requirements.
