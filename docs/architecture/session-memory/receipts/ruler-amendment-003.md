# Ruler amendment 003 — the G2 "348 PoC sessions" pinned as a reproducible artefact

**Trigger:** Stage E.0 (claims-writer specification) must bind G2 to a concrete session set, and
the ruler names "the 348 PoC sessions" without a committed list. **The frozen ruler is not
edited.** No threshold, statistic or stop rule changes.

## What the ruler binds to, and what survives

The 348 is the blind subset the earlier OKF authoring run was scored on
(`docs/architecture/session-memory/RESULTS-final.md:139`: "updated ≥ 2026-08-01, ≥ 10 messages →
348 sessions"). No id list was committed. The run's own frozen corpus snapshot survives at
`~/.local/share/sessionweaver/poc-storage-decision/corpus-20260906-clean.db`, and its SHA-256
(`216770af…`) matches the run's adjacent `SHA256SUMS` — so the input is hash-pinned.

## Reproduction

`scripts/knowledge_proof/pin_poc_set.py` re-runs the recorded rule against the snapshot and
writes `receipts/poc-set-g2.json`. It yields **345**, not 348: the snapshot was passed through
`clean-empty-rows.py` (deletes empty-content message rows) *after* the 348 was counted, and 39
sessions sit at 7–9 messages, three of which evidently crossed below the threshold. Applying the
same rule to the live DB today yields 606 — the corpus has grown since; the snapshot, not the live
DB, is the right input. All 345 exist in the live DB; **342** are in the learning-memory store
(the other 3 are prose-less and rejected by the citable-evidence invariant).

## Two denominators, both reported

The ruler's "sessions with ≥ 10 messages" was written when a message could be tool echo. Under
typed events the same words mean prose events. G2 is reported against both, and the amendment
declares which is primary:

| denominator | n | meaning |
|---|---|---|
| `n_messages_ge10` | **345** | ≥ 10 archive messages of any role — the ruler's literal wording |
| `n_prose_ge10` | **200** | ≥ 10 `user`/`assistant_prose` events in the store — the same words under typed events |

**Primary for the G2 pass/fail clause: `n_prose_ge10 = 200`.** A session with fewer than ten
prose events has little for a writer to cite, and counting it against the writer would measure
the archive's tool-echo ratio, not binding. The literal-wording figure is reported alongside so
the choice is visible, and a claim of "≥ 90 %" must hold on the primary denominator.

## Consequence for Stage E

The writer population for G2 is the 342 ingested PoC sessions, processed in **hash order**
(`sha256(session_id)` ascending) so no gold-awareness can shape selection. Because the gold was
deliberately drawn ~42 % from inside the PoC set (ruler: "≥ 50 % of clusters outside"), **26 of the
60 DEV gold sessions lie inside this population** (17 inside the prose ≥ 10 subset; 39 of 91 DEV
items touch it), and a 40-session hash-order pilot contains 5 of them. This is not leakage — the
writer never sees the gold, the questions, or which sessions are gold, and the population order is
fixed by hash before any look — but it is why the writer must be **gold-blind by construction**
(no gold file readable from the writer's environment; asserted by test) rather than by
instruction. The SEALED set is never consulted for population; its overlap with the population is
deliberately not computed by any builder run.
