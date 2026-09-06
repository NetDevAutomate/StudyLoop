# Stage30 council arbitration

Two rounds used the configured LiteLLM gateway after a healthy non-billable preflight.
Each round returned three successful provider buckets: Meta (`llama4-maverick`),
Qwen (`qwen3-coder`) and Mistral (`mistral-large-3`). The briefs contained code and
fictional fixture evidence, not owner transcripts. Comparison Markdown/JSON and the
outlying raw Mistral responses were reviewed. Full private artifacts are retained in
`studyloop-private/reviews/2026-09-06-stage30-session-annotations`.

## Design round

All three favoured adding native-session ownership to existing immutable observations.
That reduces duplicate machinery while distinguishing an annotation's access owner
from evidence inputs. We retained exclusive ownership and reported authority. The
suggestion that immutable versions alone remove the need for transaction guards is
incorrect: versions still need coherent predecessor selection and atomic access checks.
The implementation uses both.

Mistral proposed deferring deduplication to a separate non-destructive-grouping RFC.
We deferred the new grouping representation but guarded the existing destructive path
now. Otherwise a current command could reparent the very sources this contract relies
on. Meta's suggestion that a more innovative storage system might help supplied no
comparative evidence. The assumed quarterly team capacity was not an established fact.

## Result round

All three supported preserving the increment with bounded history retrieval next.
The measured scan cost is real: roughly 666 ms for 1,000 short versions on the installed
helper, despite an approximately 32 KiB response. We accepted that as a follow-up
performance requirement. Real workload relevance, mixed concurrency and recoverable
partial history still require testing; synthetic timing is not representative by decree.

Several council claims did not survive comparison with code and tests:

- Mistral described a failed-edit window losing the mutable shadow. Version creation
  and shadow deletion share one transaction; injected commit and policy failures retain
  the old value and roll back all observations. No trace supporting that claim was given.
- Qwen requested editor lock-release tests. They already exercise another connection
  writing while the editor is open, then verify rejection of the stale save. This does
  not prove every concurrency interleaving, but it directly tests the stated mechanism.
- Mistral suggested protected auto-merges remained permitted. Classified and dependent
  sessions are refused or counted as retained; tests and the actual maintenance CLI prove
  that behavior. We did not weaken the guard to satisfy a desired merge example.
- Result omission is disclosed through `coverage` and counts, though the UX and access
  to omitted history need improvement. It is not evidence of complete context.
- “Approve for production” exceeds this evidence. Scoped sync/restore, files, installed
  startup, shared setup and full release acceptance remain open. Local retirement
  triggers do not prove forgetting across machines or managed backups.

Our decision is to retain this independently runnable stage, keep the full delivery
contract active, and test bounded retrieval without losing provenance, explicit conflict
or completeness information. Reviewer agreement was advisory; it did not establish truth.
