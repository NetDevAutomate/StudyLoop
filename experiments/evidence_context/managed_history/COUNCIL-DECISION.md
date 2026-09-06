# Stage40 council and coordinator decision

Both design and result rounds returned valid Meta (`llama4-maverick`), Qwen
(`qwen3-coder`) and Mistral (`mistral-large-3`) responses through the configured gateway.
Comparison Markdown/JSON and all raw responses were inspected. Their recommendations
are independent input, not an approval vote or a proof of correctness.

## Design disagreement

The neutral brief compared an independent full replica, canonical authority over a
managed archive, consolidation into one canonical store, and other proposals. Meta
preferred consolidation because it removes dual-store complexity. Qwen and Mistral
preferred preserving the archive under canonical authority with explicit recovery.

The coordinator chose the latter as a bounded repair checkpoint: the existing product
already has archive-only history and verified hot pruning. The first failing test
showed a forgotten source returning through that path. Repairing its authority and
permanent cleanup does not require inventing peer provenance for a copied database.
Consolidation remains a candidate for completing modern copying and restore; no
measurement in this stage proves which is cheaper or gives better answers.

Rejected assumptions included treating ATTACH as sufficient cross-file atomicity,
assuming external backups preserve current controls, and deriving permission from a
harness or old receipt. Canonical intent commits first, archive cleanup can remain
pending, and current access rules govern reads in that interval. Work/personal scope
continues to come from explicit owner configuration.

## What reviewers actually received

The result packet contained eleven complete files: managed history, lifecycle, scope,
response boundary, query connection, legacy guard, observation schema, managed tests,
StudyLoop backup implementation/tests and the installed native probe. It also included
the exact tracked diff. The packet was about137k characters. The full selector/render
files were represented by their diff; other consumers and the full permission protocol
were not supplied. The response contract remained the skill's standard schema.

It disclosed the original stale-archive failure, in-memory fixture failures, backup
race-pattern failure, the disproved subject-wide purge assumption,138focused passes,
earlier15installed checks and cleanup measurements. Broad reruns and the corrected
wheel were still pending at dispatch. They subsequently passed; that later evidence
was assessed locally, not falsely attributed to the reviewers.

## Result arbitration

| Review input | Decision grounded in implementation and tests |
|---|---|
| Qwen suggested conditional production approval | Rejected. Modern full copy/refocus, fresh archive regrant coverage, managed restore, remaining consumers and installer/doctor are still required. Refusing unsafe legacy operations is not a completed replacement. |
| Qwen and Mistral warned that stale archives may reappear after regrant | Their stated exposure is not demonstrated by this implementation. All three denial statuses, including released, suppress archive-only search. The actual limitation is conservative unavailability until fresh archive coverage exists. |
| Qwen and Mistral warned that direct restore can undo current controls | StudyLoop's old restore path is explicitly refused before any backup/config/database writes; its test preserves the current tombstone and config. Arbitrary manual filesystem replacement remains outside this API. A working managed restore path is still missing. |
| Meta questioned durability/concurrency without a concrete failing trace | Retain the concern as a test boundary, not a reproduced bug. Actual child exits cover phase boundaries; archive commit failure, pinned readers, changing config and a new control before acknowledgement are tested. These do not certify power loss, every VFS or all concurrent workloads. |
| Mistral requested withdrawal plus archive-only forgetting coverage | Added assertions to each denial-status test: reads return nothing, scoped permanent forget succeeds, cleanup removes the archive source, and unrelated work survives. All47final managed/backup checks pass. |
| All reviewers identified unfinished modern archive/restore work | Accepted. Next work must preserve current retirement, denial, replica identity and exact version coverage while restoring useful access. Compare consolidation before committing to another permanent protocol layer. |
| Reviewers requested scale and response-cost evidence | Cleanup measured100/1000/5000sessions per store; final times0.572/5.653/35.389seconds. This is single-sample fictional legacy data, not concurrent native-history throughput or a database-engine comparison. Attached-read overhead and consolidation comparison remain unmeasured. |

## The most useful correction came from the unchanged tests

The first new cleanup implementation misread a subject suppression marker as authority
to purge every historical observation version. This broke a later replica transfer.
A proposed visibility change then failed an earlier test requiring historical
predecessor inspection without reactivation. Both blanket changes were removed.

Final parameterized tests distinguish exact-report retirement from whole-source
forgetting, including an archive-only additional version. Existing tests retain their
original expectations. No lifecycle/observation/ledger semantic change remains in the
final diff. This is a concrete example of arbitration against evidence: neither a new
passing test nor a model's confident recommendation outweighs the established contract.

## Completion boundary

The final wheel passes15actualCLI checks with StudyLoop absent. Combined memory and
experiment tests pass1900with1optional skip; StudyLoop passes3826with4skips and704live
or optional tests deselected. The final added assertions pass47managed/backup checks.
See [observed results](OBSERVED-RESULTS.json) for times and artifact boundaries.

The checkpoint preserves current intent during supported permanent cleanup. It does
not close P01-P15, claim full sync, or provide external-backup erasure. No owner data,
configuration, native archive, installed hook or real peer was changed. Earlier
learning checkpoints and saved exercises remain independently available.
