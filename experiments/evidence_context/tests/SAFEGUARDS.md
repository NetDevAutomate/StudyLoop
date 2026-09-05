# Independent prototype acceptance safeguards

These synthetic tests check the retrieval contract. They are not real-world
answer-quality measurements, held-out evaluation cases, or evidence that a graph
database improves decisions. Their fixtures contain no real conversation content.

| Hazard | Adversarial acceptance condition |
|---|---|
| Mutable or ambiguous references | Identical evidence imports have a stable version; changed text with the same harness/session/message ID has a distinct resolvable version. |
| False citations | Exact text spans and content hashes resolve; invalid spans or tampered relationship support are rejected. |
| Scope guessing | Work, personal, and unknown remain separate regardless of harness name. Project filters apply to evidence, traversal endpoints, neighbours, and supporting citations. |
| Hindsight leakage | Evidence time, relationship assertion time, and every supporting source time obey the same cutoff. Unknown times are excluded from historical reconstruction. |
| Counterevidence suppression | Reviewed contradiction links recover both sides within an adequate budget, including links whose assertion begins on the contrary evidence. |
| Invented authority | Inferred/unreviewed relationships cannot silently become accepted decisions, supersession, or captured verification. Agent prose saying a test passed remains conversation evidence. |
| Repeated evidence as independent corroboration | Explicit mirror/derivation lineage suppresses repeated copies while unrelated independent evidence is retained. Unknown lineage is not guessed from harness names. |
| Context overflow | The complete serialized evidence pack, including relationships and metadata, obeys the UTF-8 byte budget. Multibyte text is included in budget tests. Bytes are not reported as model tokens. |
| Unanswerable query | Empty, missing, or excluded evidence produces a clear no-evidence/insufficient-evidence result, without a fabricated answer. |
| Unrun experimental arm | Semantic arms B/D are explicitly not run when no semantic index/model exists; no synthetic estimate is passed off as measured quality, latency, or provider cost. |
| Development leakage | Real StudyLoop/MailGraph exploratory examples remain labelled development, outside held-out claims. Cases split by discussion/decision lineage, not individual messages. |

Production `sessions.db` is never modified by these tests. Each test creates a
separate temporary derived store. No provider calls, paid model requests, or
network access are required. Automatic extraction quality, model answer quality,
and dedicated graph-engine performance remain outside this test suite.

Before claiming retrieval-quality improvements, include a shuffled-edge control
alongside the curated relationship arm to detect curation bias. Keep the same
source corpus, model, scope/cutoff rules, and context budget across arms. This
control is a future evaluation requirement; the present contract tests do not
measure it. An effective text-only baseline remains a valid outcome.
