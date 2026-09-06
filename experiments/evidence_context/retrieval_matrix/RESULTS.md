# Stage 12 results — a failure signal, not a retrieval winner

Run date: 2026-09-05. Four real-development questions, four retrieval arms, two answer
calls each. All 32 responses parsed as original JSON and passed the schema. This is
not an answer-quality score. All 1,019 retained passages matched their original message
digest and exact character span in a subsequent read-only integrity check.

## Required facts returned

Under the coordinator's pre-retrieval labels:

| Question | Keyword | Semantic | Relationships | Combined |
|---|---:|---:|---:|---:|
| Q1: voice rationale and recorded checks | 2/3 | 2/3 | 2/3 | 2/3 |
| Q2: rebuild reason, detachment, progress | 3/3 | 3/3 | 3/3 | 3/3 |
| Q3: unsafe default, CRUD, reload, cleanup | 0/4 | 0/4 | 0/4 | 0/4 |
| Q4: unsupported benchmark | no fact denominator | no fact denominator | no fact denominator | no fact denominator |

Q4 produced appropriate insufficient-evidence categories in all eight calls. This
checks abstention on one constructed negative, not absence of every possible benchmark
in the user's wider history. No retained passage contains the literal name Ladybug.

These are ties on the reviewed facts, not statistical equivalence of retrieval methods.
Label sensitivity matters: Fable/Grok's original groups credit the early port warning
for Q3 and give keyword/semantic an additional Q2 detachment hit; Qwen's original groups
favor semantic on Q1. Some proposed groups confused partial facts with alternatives.
The full body-free per-reviewer counts are in reviewer-sensitivity.json. This instability
is a reason to seek human labels, not select whichever labels make an arm look best.

## Where answers went wrong

**Q3 is the clearest diagnostic.** The corpus contains the reported Parking card checks
and cleanup, but none of the four packs returned the four required passages. They
returned plans, earlier study-plan workflows, and nearby safety discussion instead.
Answers then promoted goals into completed checks or mixed different workflows. All
eight Q3 drafts have such material problems in the coordinator's source inspection;
see COUNCIL-DECISION.md for the separate model judgments and their coverage.

One combined-arm answer cites the exact words `Cleanup verification` from a handover
outline to support a claim that cleanup was performed. The quote exists. The claim
does not follow. Its evidence_status is reported_only, so the category check passes.
This is the missing distinction between **locatable provenance** and **decision support**.

The relationship arm also supplied unrelated repository test counts to both Q1 answers.
Those answers included those counts as recorded validation without clearly explaining
why they were not validation of the browser-voice decision. Adding nearby context can
increase misleading evidence as well as useful evidence. The frozen prompt was not
tuned after these observations, and no answer was regenerated to improve the result.

## Mechanical and cost measurements

| Arm | Mean evidence tokens | Exact quotes / citations | Validated-status violations | Answer-call cost, USD |
|---|---:|---:|---:|---:|
| keyword | 1,269 | 18/22 | 0 | 0.007840 |
| semantic | 1,093.25 | 23/24 | 0 | 0.007903 |
| relationships | 1,241.25 | 18/21 | 0 | 0.007615 |
| combined | 1,159 | 23/24 | 0 | 0.007806 |

Nine quotes across eight answers did not match the supplied text exactly, sometimes
because punctuation/backticks changed. These are locator failures, not automatically
fabricated facts. Conversely, 82 exact quotes are not 82 supported conclusions.
No draft used the validated status; prose still overclaimed. No universal acceptance
gate was attached to these advisory drafts.

Gateway-reported answering cost totals **$0.031164 for 32 calls**. This excludes council
review costs, which the council wrapper did not retain; it is not the total experiment
bill. Local embedding preparation took 17.38 seconds. Mean answer latency by arm was
2.87–3.60 seconds. Context uses one shared token ceiling rather than equal actual tokens.
The ranking timing fields record component searches, not full end-to-end arm latency.

## Decision and next experiment

Keep SQLite as the canonical store and keep retrieval indexes replaceable. This pilot
gives no convincing reason to add this structural graph or embedding fusion as the
product default. It also does not disprove a reviewed, typed knowledge graph.

The next useful experiment is an **evidence-completeness and episode-applicability
control**: compare the same failed question with the original retrieved pack and a
separately reviewed, budget-matched pack containing the actual result passages. Keep
prompt/model/scorer fixed. If the answer improves, retrieval or packing is a bottleneck;
if it still promotes plans into results, answer acceptance remains a bottleneck. Then
carry the rule to new independently labelled episodes before claiming general value.

Do not let a question-specific repair become prompt optimization on the same examples.
An eventual product needs source kind, event/episode identity, plan-versus-result state,
applicable validation target, and code-owned acceptance checks. The present measurements
motivate testing those fields; they do not prove automatic extraction is reliable.

For rich context, the current priority is **the right evidence with the right meaning**.
Stage 13 separately examines whether storing those same records elsewhere helps.
