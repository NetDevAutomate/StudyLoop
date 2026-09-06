# Stage27 council arbitration

Decision: preserve this tested implementation increment and continue P01–P15.
No deployment or release approval follows from a council response.

Both design and result rounds used Meta `llama4-maverick`, Qwen `qwen3-coder` and
Mistral `mistral-large-3`; all three provider buckets returned valid responses.
Gateway preflight was healthy. Each round sent the same neutral brief to every
reviewer. Only code, synthetic cases and aggregate observations were sent. The
comparison Markdown/JSON and all raw result responses were read. Private artifacts
are under `studyloop-private/reviews/2026-09-06-stage27-learner-paths/`.

## Design

All three selected exact owner plus study-parent identity for parking deduplication.
This preserves the separate dependencies needed for later reclassification and
forgetting. A displayed frequency can sum visible occurrences without merging their
source bodies. Mistral also called for typed dependencies and scoped board names;
both are implemented. This agreement identifies a plausible design, not proof of
its correctness or performance.

## Results, disagreements and evidence

| Review claim | Coordinator finding |
|---|---|
| Meta/Qwen: conditionally approve the increment | Retain the tested checkpoint; reject any implication of deployment or whole-product acceptance. |
| Mistral: `bind` does not validate study-parent visibility | Not supported by the code: `bind` calls `_owner`, which calls `is_visible` before creating ownership/link records. Tests refuse excluded parents and follow reclassification of either dependency. |
| Mistral: dropping triggers during migration exposes an unprotected window | Added a direct check: during schema37 installation, another connection sees schema36, its original ownership trigger and UUID; a write is locked. Injected failure restores the old schema and all rows, then retry succeeds. Migration holds `BEGIN IMMEDIATE`; the temporary DDL is not committed independently. |
| Mistral: `ensure_study_reference` can create orphaned study references | It deliberately creates an owned application study session inside the caller transaction, then verifies visibility. Native sessions are never invented. Study links have a real parent foreign key. Existing negative/rollback tests contradict the asserted orphan path. |
| Mistral: legacy transition robustness is not established generally | Accept the limit, not a demonstrated corruption claim. Historical note/board migration and rollback/retry pass; the installed copy preserves all original values. Arbitrary schema corruption is not repaired or claimed healthy. |
| All: concurrent combined-request policy snapshots remain unresolved | Accepted and retained in the full work queue. The tested write guard and during-practice refusal do not make an external config file part of a SQLite transaction or pin every reader in one HTTP/MCP response. |
| Qwen: no observation-link detachment API is an integrity gap | Detachment would remove provenance obligations. No user unlink API is intended; correction/supersession and forgetting need explicit managed semantics. Raw SQLite mutation is outside the application access boundary. Full sync/restore must preserve these links. |
| Qwen: cross-project semantics and query costs need testing | Accepted. The new working-directory project test proves reclassification hides both attempt and progress. Same-scope assessment supersession semantics and mixed-dependency performance remain unmeasured. |
| All: practice confidence is not semantic mastery | Accepted. The response explicitly retains application-report authority and unknown validation. The inherited heuristic requires separate design/validation work. |

The review brief preceded the final full-suite result and second-connection test.
No production code was changed to satisfy a model's preferred verdict. The final
regression has 30 passing cases and workspace typing is clean. Model confidence
numbers and the two-to-one recommendation split are not correctness scores.

## Next discriminating work

Complete remaining learner-state storage/call paths; test policy consistency over
whole responses; implement protected peer transfer and deletion-aware restore;
finish shared setup/doctor and actual installed agent startup. Retain semantic
usefulness and validation applicability as separate gates. No new engine benchmark
or prompt tuning is justified by this stage's ownership results alone.
