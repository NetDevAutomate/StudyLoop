# Stage 4 council review and coordinator decision

## Review provenance

Same neutral brief sent through the healthy local gateway to claude-fable-5-1,
grok-4.6 and qwen3-coder. All three returned usable structured responses: Anthropic,
xAI and Qwen provider lineages. No failures or retries this round. Models saw
measured results/limitations from stages 1–3 plus full stage-4 source and tests.
They did NOT inspect the full earlier implementations. This is not retrospective
three-provider implementation sign-off for the lifecycle adapter.

Private artifacts: context-design/council-stage-4/{brief.md,evidence-manifest.json,
results/comparison.md,results/comparison.json,results/responses/}. Actual transcript
bodies and credentials were excluded. Reviewed snapshot had 91 passing tests.
Post-review fixes below have local tests, not a second council review.

## Evidence given to the council

| Stage | Observation | What it cannot establish |
|---|---|---|
| 1: retrieval | 60 tests. Synthetic extra counterevidence; four-message private pilot returned the same two passages in both arms. MailGraph payload 3259 vs 4751 bytes; StudyLoop 4299 vs 5813. | No held-out usefulness, semantic retrieval or engine comparison. |
| 2: boundaries/explanations | 5 additional regressions, 65 total. | Retrieval filters are not transport authorization or working installation. |
| 3: lifecycle | 12 additional tests, 77 total. Two real SQLite replicas, replay/deletion, rebuild, subprocess interruption/retry. | Separate lab, not production sync, earlier evidence graph, real vectors or backup restore. |
| 4: health | Initially 14 additional tests, 91 total. Actual file import and outcome persistence; configuration and gap counts are synthetic inputs. | No live detector, capture completeness census or health-aware retrieval. |

The private pilot's payload increases are about 46% and 35%, respectively. That
small curated sample neither proves nor disproves relationship utility.

## Advice and arbitration

| Advice | Coordinator decision and why |
|---|---|
| All three recommend usefulness evaluation before more integration. | Accept. Integrity tests are necessary, but we have accumulated no independent decision-quality evidence. Change the next-stage order rather than keeping the old installation-first plan. |
| Fable: explicit UTF-8, reopening DB, out-of-order attempt handling, separate unreadable failures. | Accept and implement. Added persistence/Unicode/ordering tests and failure count. These are bounded improvements to the current experiment. |
| Fable: absent records persist; snapshot semantics unclear. | Clarify rather than introduce deletion into this lab. This is incremental upsert capture, not a replacing snapshot or the production source ledger. Added test that empty input preserves prior records. |
| Fable: SQLite side-file permissions may be unsafe. | Treat as an unverified hypothesis, not a confirmed defect. Added test of actual main DB and live rollback journal: both deny group/other access on this machine. WAL/other platforms remain untested. No global umask change. |
| Fable: require at least six wins on twenty questions and no regressions. | Reject as an unjustified universal threshold. A small pilot is useful, but report paired results, uncertainty, costs and hard integrity failures. Set meaningful success criteria before looking at held-out results. |
| Grok: score frozen cases locally before connecting lifecycle and evidence. | Accept sequencing; keep real evidence private and freeze labels/lineage split before evaluating. A scoring harness with synthetic examples alone cannot claim held-out efficacy. |
| Qwen: condition evaluation on health states. | Accept explicit missing/stale corpus scenarios, not the assumption that fixture health labels already predict answer reliability. Record coverage separately from retrieval misses. |
| Qwen: installer contracts second; Grok: lifecycle integration second. | Defer that choice until the usefulness result. Installation remains a required production gate; moving it later does not remove it. |
| SQLite is adequate for the implied scale. | Retain only as a hypothesis. No measured capacity/engine comparison exists. SQLite stays the reference, not a proven winner. |

The reviewers also misattributed some earlier choices: scope reclassification was
a coordinator/prototype scope decision, not a demonstrated Qwen recommendation.
Rejecting it is an experimental limit, not a complete user remediation policy.
Deleting then re-importing the same identity does not solve it: tombstones suppress
that import. Real reclassification needs explicit revocation and identity policy.

## Changes and validation after review

Seven additional tests cover reopened state/Unicode, out-of-order timestamps,
invalid UTF-8, records isolated by source, incremental empty inputs, duplicate IDs,
and main/live-journal permissions. Full suite: 98 passing tests. The lab records
completed attempts; a process dying before outcome persistence can leave no attempt
record. Durable start/completion events, actual capture watermarks and live detector
integration remain gaps rather than implied features.

## Decision: stage 5 is a bounded retrieval-value evaluation

1. Build a locally runnable evaluator and guide around the existing stage-1 APIs.
   Freeze the corpus snapshot, scope/cutoff, questions and relevance labels before
   testing; split by decision/discussion lineage. Keep current development examples
   out of held-out claims. Record corpus counts/bytes and missing coverage.
2. Compare keyword and reviewed relationships, with shuffled-link control and
   explicit unanswerable/counterevidence cases. Use identical budgets and format;
   measure citation validity, relevant evidence, omissions, latency and payload.
   Label semantic arms not run until real indexing exists. Retrieval metrics alone
   are not answer-quality metrics: a later answering evaluation must fix the model
   and actual token budget and assess supported decisions/abstention separately.

No graph engine, automatic extraction, production integration or public repository
extraction in this next increment. Involve the user in reviewing the meaning of a
useful answer without assuming they will write twenty questions as unpaid setup.
Choose a realistic held-out set and acknowledge limited sample size; no fabricated
labels or renamed development cases. If independent labels are not yet available,
report only evaluator correctness, not efficacy.

Re-run the council on the resulting measurements before selecting the following
integration work. Council agreement helps challenge assumptions; it is not a
substitute for independent labels, tests or the coordinator's decision.
