# Storage implementation review and arbitration

The full packet included the schema and store source. The focused follow-up included
scope SQL, source/hash reads, Unicode quote binding, transactional proposal creation
and the observed tests. Both selected Fable 5.1, Grok 4.6, Qwen3-Coder and Mistral Large3.
Only Qwen and Mistral returned valid structured reviews in either round. Fable failed
JSON parsing; Grok returned no text. This is **two-provider implementation coverage**,
not three/four-provider consensus. Original packets and responses are retained in
`.private/delivery/storage-council/{run,focused-run}`.

Several allegations did not survive code inspection and reproduction:

- Missing project assignment is mapped to `unclassified`, then compared to the
  requested scope. It does not equal personal/work. Direct/search negative tests pass.
- The source body is a Python `str`. Slicing uses Unicode code points, not raw UTF-8
  bytes. The emoji/accented-text citation test verifies the exact old quote.
- Search calls `_checked` for each result. Assertion reads call `source`, which calls
  `_checked` for each supporting source. A fault-injection test alters source text
  after deliberately dropping the immutability trigger; all three reads reject it.
- A multi-project assertion is authorized only when every citation is permitted.
  Reclassifying either project hides the whole assertion and its relationships.
  The existing explicit test reproduces this behavior, contrary to the review claim.
- A late duplicate-citation SQL failure rolls back the proposal and preserves the
  caller's outer transaction. No partial assertion remains.

I retained the original criticism rather than rewriting reviewers' answers into
agreement. These checks disprove those particular allegations; they do not establish
absence of all bugs. General advice about native-parser trust, concurrent lifecycle
work, integration and full release acceptance remains appropriate.

Independent implementation checks led to additional changes: immutable citation
updates, tombstone checking before idempotent capture, UTC event-time normalization,
per-operation FK/version checks, savepoint rollback for caller-owned migration
transactions, and refusing unsupported newer schemas. These are not claimed as
council-discovered defects.

Broader regression exposed the new-FTS compaction failure. A separate test reproduced
loss of live WAL evidence through an immutable attachment. Both paths were corrected
and now have populated-source regression coverage. The final package regression
passed 1,156 tests at this checkpoint; no real source/configuration was modified.

Decision: retain this internal canonical-storage increment and continue integration.
Do not expose a production forgetting API or claim all existing commands enforce
scope yet. Native capture, legacy reads, scoped transport, managed derived deletion,
restore and installed acceptance remain outstanding shipping requirements.
