# Stage 11 pre-run contract

Twelve coordinator-authored synthetic cases: three earlier development cases, nine
fresh development case conditions (eight distinct fresh source/target pairs). C01 and
C10 intentionally share source and target; one proposal omits a present revision.
There are eleven distinct source/target pairs overall. These conditions are not a real-world or independently authored holdout.
Council reviewers label source/target pairs without coordinator labels, condition
names, previous scores or metadata interventions. Freeze a label ledger with all
reviewer disagreements and coordinator arbitration before the first experiment call.
Council review is not human ground truth. No majority vote silently overrides policy.

The answer prompt is byte-identical to Stage 10. Twelve sources, two calls each,
24 calls maximum, qwen3-coder, temperature zero, 1500 output tokens, 90-second timeout,
no application retries. The checked proposal is scripted, not a new LLM extraction.
Fields are drawn by the narrow reference grammar, then a declared field edit is applied.
This isolates the decision boundary and cannot measure extraction quality. No case
labels, gold decisions, description keys or condition identifiers enter model messages.
The question, source, target and checked-metadata rendering follow Stage 10 exactly.

Each single model draft is compared with two offline deterministic outputs on the same
immutable evidence snapshot; there are no distinct model treatments for the gates:

- advisory: model draft with checked metadata; original source remains visible;
- checked_only: Stage 8 measured-decision policy uses only matched candidate fields;
- source_adapter: explicitly parse original structured source into a NEW derivation,
  then feed the same policy. The rejected proposal remains unchanged in the trace.

Stage 9 Snapshot freezes the normalized policy input. An outer snapshot additionally
binds original source text, source kind, target and proposal; evidence locators include
origin, source/target version and exact offsets or field keys. This does not authenticate
source kind. Both gate outputs are policy-rendered; model prose is never released.
Draft choice agreement is telemetry, not acceptance of the full model answer.

## Parsing and measurements fixed before execution

Keep strict JSON parsing success separately from the predeclared complete-fence-only
parser. The latter removes a single complete Markdown JSON fence and makes no other
repairs. Both statuses and exact original text remain available. Invalid model outputs
are a separate coverage metric, not counted as abstentions or supported decisions.

For each path, measure unsupported A/B outputs against frozen expected choices, none
outputs on A/B-labelled cases (false blocks), and correctly permitted A/B outputs.
Report counts with eligible denominators and case-level results; two repeats are not
independent scenarios. Existing cases and fresh cases are separate strata. Scripted
always-none and always-A/B baselines are descriptive controls. Pair differences by
case; do not infer statistical confidence from these twelve cases.

Verify locator origin/version/span resolution separately from semantic support.
An exact quote can still support a wrong inference. Missing/ambiguous declarations
cite the source inspected and the applicable target, never an invented field quote.
Measure structured issue/next-check presence as coverage only; usefulness, explanation
entailment and learner understanding need independent review, not keyword scores.

## Stop and interpretation rules

No prompt tuning, case rewriting, label changes or live retries after seeing model
results. Correct implementation defects before execution and document any pre-run
changes. Preserve defects found afterwards and distinguish diagnostic replays. Freeze
current code, cases, labels, prompt, dependencies and protocol hashes in each run.

Perfect release agreement would demonstrate policy conformance on reviewed fixtures,
not model intelligence, authentic provenance, general safety or product efficacy.
Both deterministic paths use related parser/policy code and can share defects.
Do not select a database engine, edit sessions.db or modify earlier exercises/stages.

Before execution the coordinator retained the C01/C10 counterfactual pair despite
reviewer suggestions to replace it, clarified its denominator, and froze GRAMMAR.md.
Additional parser edge cases are tested offline, not added to the live comparison.
C05 has recorded reviewer dissent: Qwen counted outside-block fields, contrary to the
written rule. The coordinator label A follows that rule, not a majority-vote override.
