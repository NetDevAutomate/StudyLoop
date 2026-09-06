# Stage33 council and arbitration

The authorized LiteLLM gateway was healthy at preflight. The design and result rounds
each received three successful provider-diverse responses: Meta `llama4-maverick`, Qwen
`qwen3-coder`, and Mistral `mistral-large-3`. All received the same brief within each
round. The result brief contained implementation source and fixture-test findings,
not the owner's transcripts or credentials. Private raw responses and comparisons
are retained under the Stage33 lifecycle review directory.

## Design decision

Use a transactional distinction between permanent forgetting and reversible local
eviction, plus monotonic artifact identities. A later peer protocol must track delivery,
withdrawal and regrant separately. Reject the proposed reversible flag in permanent
tombstones because existing importers treat table membership as permanent retirement.
The complete design and deferred obligations are in
[LIFECYCLE-DESIGN.md](../delivery/LIFECYCLE-DESIGN.md).

## Result review

All three reviewers requested changes before advancing the checkpoint. Their findings
were uneven: none supplied the exact executable interleaving that ultimately reproduced
the compaction defect. We do not equate the recommendation or confidence number with
a verified defect, nor describe this checkpoint as unanimously approved afterward.

| Review concern | Arbitration and evidence |
|---|---|
| Qwen: revision read outside the cleanup transaction can lose work | Accepted after constructing a concrete second-writer interleaving. The old function incorrectly returned complete; the repaired transaction leaves pending work and succeeds on retry. |
| Mistral/Qwen: insufficient archival coverage | Accepted as an area to inspect. Local review found missing legacy payload tables and session metadata in the retention proof; added comparisons and tests for unarchived notes/metadata. |
| Qwen: concurrent writers may inherit eviction mode | Not reproduced. The mode is transactional; a second connection sees ordinary mode and its write is locked until eviction ends. Added a directed two-connection test. |
| Mistral: a process crash can lose the pending cleanup job | Tested at the VACUUM boundary with real process exit. The previously committed pending row survives and a retry clears it after successful cleanup. No claim of exhaustive crash-point or disk-failure testing. |
| Meta: busy/locked databases are unhandled | Rejected as stated. The supplied function already checks checkpoint busy status and catches operational errors; the pinned-reader test preserves pending work and proves retry. |
| Meta: repeated purge/reconciliation creates inconsistent duplicates | Not established. Permanent IDs use immutable primary keys and idempotent insertion; reconciliation deletes only present rows. The public second forget is unavailable after source removal, rather than falsely claiming a second complete operation. |
| Mistral: FTS rebuild needs a hash of the index | Not adopted. The relevant invariant is reconstruction from canonical live rows, exercised with an orphan-body marker. An extra hash alone would not prove correct lineage or deletion. |
| Both: all tiering, restore and concurrency behavior is proven | No reviewer actually established this; it remains outside the bounded evidence. Full-copy/refocus, hot/full consumers, peer acknowledgements and managed restore still need integration tests. |

The final engineering decision is to preserve this as a reviewed, corrected local
lifecycle checkpoint and continue the full goal. Targeted refinements followed the
council; there was no second result-council approval. The fresh installed demo and
post-fix tests, not model agreement, are the acceptance evidence for the bounded stage.
