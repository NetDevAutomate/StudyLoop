# Amendment 004 — run the G2 population (E.2) with writer-v2 before DEV look 3

**Declared:** 2026-09-10, after receipt `g2-pilot-e1c.json`, before any E.2 writer run.
**Ruler text:** unchanged. This records a programme decision and a deviation from spec v2.

## Why

DEV look 3 is the last G1 look before the two-flat-looks stop rule fires. A `recall_claims` arm
is only able to help a question whose gold session carries at least one claim. Measured on the
DEV gold set (never SEALED):

| coverage | gold sessions | DEV questions reachable (of 91) | by stratum |
|---|---|---|---|
| pilot claims (40 sessions, writer-v2) | 3 of 60 | **6** | K 2 · P 0 · R 4 |
| full G2 population (345 sessions) — upper bound | 26 of 60 | **39** | K 15 · P 10 · R 14 |

Spending the last look on an arm that can touch 6 questions and no paraphrase item would be
flat by construction and would end the G1 looks for a reason unrelated to the architecture.

## What changes

- E.2 runs now: the remaining 302 population sessions in the pinned hash order (gold-blind by
  construction), writer-v2 (`sonnet5/writer-v2/cb45b300`), same harness, same insertion
  contract. Writer runs → 382 / 400. Sessions not in the store (3) are skipped and listed.
- `recall_claims` is declared in `fusion-spec-v2.md` **after** E.2 completes and **before**
  look 3, over all writer-v2 claims. The arm is evaluated under G1 only; G2 remains
  "not established — instrument" and no further entailment audits run.
- Deviation from spec v2 ("two prompt rounds without passing → Stage E stops"): Stage E's G2
  *measurement* is closed; the population run serves G1 coverage, which spec v2 did not consider.

## What does not change

Ruler thresholds, one-look discipline, ≤4 DEV looks, stop rule, pinned B0, corpus digest,
chained receipts, $0 external API, SEALED never touched by a builder.
