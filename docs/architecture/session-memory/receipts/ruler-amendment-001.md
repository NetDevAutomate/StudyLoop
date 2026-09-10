# Ruler amendment 001 — PoC overnight run

**Authorised by:** Andy, 2026-09-10T02:17 BST: "Forget past constraints — we must get to the best
architecture for the requirement, to get to this we must have PoC data to prove it. Please use
representative data from the sessions.db if possible, the council of models methodology and 'remove
the human from the loop' for an overnight run to make progress with recorded data."

**The frozen file `validation-ruler.md @ a98331af` is not edited.** This receipt records the
amendment and is chained into every later receipt.

## Lifted (programme-level operating constraints)

| Clause | Was | Now |
|---|---|---|
| Elapsed-time cap | 7 days from 2026-09-09 23:40 | none for the PoC; wall-clock spend is reported per stage |
| Stage-3 writer runs | ≤ 400 | uncapped for the PoC; every run counted and reported per stage |
| Council runs | ≤ 60 | uncapped; every run counted and reported (tally at amendment: 9) |
| Candidate | PR #18's concept sidecar | ADR-0011 PoC (`packages/learning-memory`), scored by the same gates |

## Unchanged (measurement discipline — these are what make the data proof)

Every gate threshold and statistic (G1, G2, G3, G4, G5, G6, budgets); gold v2 DEV/SEALED split with
**one** sealed look per gate; ≤ 4 DEV looks per gate and the two-flat-looks stop rule; the
factorial control (B0 pinned at 031dbab9); content corpus digest; claim matrix; council review of
every gate receipt by ≥ 2 model families; hash-chained receipts; $0 external API; the live
`~/.config/studyloop/sessions.db` is never written; merge to `main` stays human; sealed gold path
is never passed to a builder agent.

## Representative data

The archive adapter ingests the real `sessions.db` (read-only) — all 5,879 sessions — so every PoC
number is measured on the learner's actual history, not fixtures. Golden-file fixtures for native
adapters are scrubbed excerpts and exist only to pin parser behaviour.
