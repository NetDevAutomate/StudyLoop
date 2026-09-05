# Stage 15 results

This run supports a narrow conclusion: separate event state, evidence basis and
target labels can drive an inspectable release contract. It does not establish
correct automatic annotation, general answer quality or a database advantage.

## Completed run

32 Qwen3-Coder calls, eight cases, two input arms, two repeats each. All returned
parseable drafts. Seven cases are new synthetic policy fixtures and one is a
manually annotated historical two-passage anchor from the saved StudyLoop corpus.
These are development cases, not independently labelled held-out questions.

| Measurement | Raw text | Text plus reviewed metadata |
|---|---:|---:|
| Responses / valid drafts | 16 / 16 | 16 / 16 |
| Complete expected released ID sets | 13 / 16 | 16 / 16 |
| Useful expected IDs withheld | 3 | 0 |
| Claims blocked | 3 | 0 |
| Unexpected IDs released | 0 | 0 |
| Gateway-reported answer cost, USD | 0.003430 | 0.003920 |

Costs total $0.007350 for the 32 answer calls, excluding council calls. These are
gateway-reported values, not a reconciled Bedrock bill. Counts include two negative
cases repeated twice per arm; those cases correctly release no assertion. There
are 14 expected assertion instances per arm, of which raw released 11 and annotated
released 14. Repeats are not independent new examples.

The 13/16 versus 16/16 comparison is **conditional ledger conformance**, not a fair
accuracy comparison. Annotated inputs disclose labels. Raw inputs deliberately omit
provenance, including an exactly identical-text pair with different hidden bases.
No information-theoretically impossible basis inference is scored as reasoning error.

## Where the difference came from

- **C26, historical raw anchor:** cleanup was labelled observed by the model while
  the ledger says reported. The gate withheld cleanup and still released the separate
  in-progress port correction. C17, the other raw repeat, had matching typed labels.
- **C02 and C05, raw observed fixture:** the model conservatively selected reported
  for text whose hidden fixture label was observed. Exact equality blocked those
  weaker claims. The identical raw text in C08/C20 had a reported ledger label and
  passed. This reveals missing information and a strict-policy cost.
- **Annotated anchor, C10/C30:** both selected completed/reported cleanup and
  in_progress/reported port correction. All four anchor drafts kept the correction
  in progress; no live completion-state mismatch occurred in this new stage.

Across both arms, explicit unknown state was retained; the corrected completion
claim yielded to the unknown-state correction; wrong revision and unknown target
produced empty claim lists. No live target/scope/state/correction violation was
blocked: negative controls, rather than live mistakes, exercise those gates.

## Prose remains a separate problem

C17's structured claims matched the ledger while its advisory answer said cleanup
“has been verified as completed.” C30's annotated draft used “confirmed as gone.”
The code-owned output records a conversation report and never uses that advisory
prose. Correct structured output therefore did not certify the model's whole answer.
All draft/source/claim/release distinctions are visible in the private replay.

The released output is also deliberately narrower: it retains state and attribution,
but not detailed cleanup facts or pass/fail outcome. Generic empty-selection prose
loses helpful explanations that some drafts supplied about missing revision/target.
These omissions prevent claiming that the released answers are already the richest
or most useful answers.

## Controls and verification

Twenty deterministic controls: **18 ordinary expectations matched; two deliberate
semantic forgeries were accepted**. The forgeries changed state or basis in the
reviewed ledger while preserving source text/hash. They remain demonstrated trust
gaps, not successful safety checks. A dangling correction is rejected as invalid
metadata; useful content can be withheld until that metadata is repaired.

No injected advisory prose appeared in the controls' rendered text. That is a
property of code-owned rendering, not evidence that models understood injection.
The test suite asserts both successful guards and the two known failure behaviours.

232 evidence-context tests passed, including all prior stages. Browser checks covered
32 actual draft cards, four filtered anchor cards, evidence expansion, 20 controls,
eight offline reference cards, mobile width and no page errors. The synthetic demo
runs without the private archive or gateway. New Python files passed Ruff checks.

The frozen source/prompt/bundle and private provider responses were retained. Prior
stages, production database, installed configuration and the saved exercise were
not changed. See COUNCIL-DECISION.md for review coverage and the next evidence gate.
