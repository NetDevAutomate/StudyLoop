# Model council arbitration

## Design round

Three successful provider families reviewed the same neutral brief through the configured gateway: Fable 5.1 (Anthropic), Grok 4.6 (xAI), Qwen3 Coder (Qwen). Raw responses and technical briefs are private artifacts. No real conversation bodies or credentials were supplied.

Fable and Grok recommended an isolated SQLite evidence ledger with explicit identity, scope, time and abstention. Qwen challenged whether relationships would add value and preferred establishing the keyword baseline. This disagreement is useful: the prototype retains the baseline and treats relationship utility as an open hypothesis.

Accepted:

- Isolated, disposable evidence storage; no production writes.
- Source versions, exact citations and explicit scope/availability cutoffs before retrieval richness.
- Keyword versus curated-relationship comparison first; no invented semantic scores.
- Treat agent reports as reports. Model confidence or council agreement cannot grant validation status.
- Distinguish source lineage from independent corroboration.
- Add a shuffled-relationship control to the later held-out evaluation; hand-selected examples cannot establish efficacy.
- Defer semantic indexing, automatic extraction and database-engine comparison until integrity and decision-quality gates justify them.

Qualified or rejected:

- Content hash alone is insufficient as evidence identity: identical wording can have different origins, scopes or dates. Preserve full provenance and version identity.
- The corpus size alone does not prove SQLite performance is sufficient. That remains a measured deployment question.
- The existing searched-in development questions cannot become held-out gold cases by being renamed.
- Curated-link demonstration results must not be presented as evidence that automatic extraction works.

The prototype's serialized-byte budget is explicitly a byte budget, not a token-budget claim. Future answering-model comparisons must use the model's actual tokenizer and identical formatting.

## Implementation and testing review

The same implementation and synthetic-test brief was sent to all three providers. Qwen returned a usable review. Fable returned an invalid structured response and Grok returned no text; one bounded retry with the same brief and a larger response allowance produced the same failures. Implementation review therefore has **insufficient provider diversity** and is not a three-provider sign-off. This limitation is retained rather than filled with inferred approval.

Qwen raised source-lineage semantics, atomic budget checks, deterministic traversal and concurrent read consistency. The coordinator accepted the concrete snapshot concern: retrieval now holds one SQLite read transaction. A real two-connection WAL regression proves that a relationship inserted during a query appears only on the next query. Existing budget/ordering tests were retained and extended. Near-duplicate semantic matching remains deferred.

Local implementation review also found unbounded sibling-version expansion. It is now capped at 64 eligible versions, after scope/time filtering, and reports incomplete context. Tests confirm hidden future versions neither consume the visible cap nor leak their existence in diagnostics.

Final local validation: 60 synthetic contract tests passed, including concurrent writes, source/version corruption checks, scope/time filtering, relationship budget atomicity, bounded expansion and refusal to overwrite existing demo output. Ruff and focused Pyright passed. These tests establish the tested contracts; they do not establish improved real-world decisions or an optimal database engine.

The four-message private development demonstration retrieved the same passages in both arms while relationship metadata used more bytes. No answer generation, semantic retrieval, automatic extraction, held-out decision scoring or cross-engine performance comparison was run.

## Outstanding gates

- Obtain usable additional-provider implementation reviews before claiming a diverse implementation sign-off.
- Build independent held-out labels, including insufficient-evidence cases, with a shuffled-link control and fixed model/token budget.
- Measure real decision usefulness and costs before adding automatic extraction, semantic retrieval or another engine.
- Design source correction/deletion propagation and validation-artifact ingestion before considering production integration.

## StudyLoop / SessionWeave requirements extension

User-requested scope adds explicit boundaries, retrieval explanations, correction
and forgetting propagation, capture health, and shared installation ownership.
See REQUIREMENTS.md for acceptance scenarios, hard gates, unrun status and scope
ceiling. Five new regressions check whole-pack boundary disclosure and grounded
retrieval reasons; the complete suite now passes 65 tests. Focused Pyright and
Ruff pass. This extension has local validation only, not a new model council
review. Lifecycle, two-replica deletion, health and installer tests remain NOT RUN;
no production or standalone integration is claimed.
