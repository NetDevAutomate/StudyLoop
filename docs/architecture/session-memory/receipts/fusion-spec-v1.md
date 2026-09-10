# Fusion spec v1.1 — arms pre-declared before each DEV look (v1 declared before look 1; v1.1 adds the B1_planner control before look 2)

**Declared:** 2026-09-10, before any DEV look on `learning-memory.db`. Ruler clause: "the fused
arm's algorithm, per-source candidate budget, dedup rule and tie-break are versioned in
`receipts/fusion-spec-v<N>.md` before the first DEV look; every arm returns exactly five results
within the same byte budget." No arm below fuses more than one source yet; the spec exists so the
retrieval configuration in force is on record before the number is seen.

## Controls (ruler, unchanged)

- **B0** — shipped `session_search` at pin `031dbab9`: `_session_search_queries` (AND then OR),
  `bm25(messages_fts)`, scope visibility, LIMIT 200 message rows → first 5 distinct session ids.
- **B1** — the same path at the candidate commit. Non-inferiority of B1 vs B0 gates everything.

## Arm `B1_clean` (Stage D, "what cleaning buys")

*Question it answers:* does removing tool echo and exporter duplicates from the indexed text —
and planning natural language so the query cannot throw — lift session recall, before any
derivation, claims, embeddings or ontology exist?

- **Store:** `~/.local/share/studyloop/knowledge-proof/learning-memory.db`, schema v2, ingested by
  `archive-v1` / `archive-classifier-v1` (receipt `ingest-archive-v1.json`). Opened read-only.
- **Index:** `prose_fts` — external content over `prose_events` (`user`, `assistant_prose` only),
  tokenizer `porter unicode61` (the schema default; `unicode61` is a later, separate arm).
- **Query planning:** `Store.search_prose` planner — every whitespace token phrase-quoted, OR-joined,
  control/surrogate code points stripped. No AND stage (a deliberate difference from B1: the
  AND→OR fallback is the part of the shipped planner that crashes; measured, not assumed, by the
  42 DEV errors in the baseline receipt).
- **Ranking:** `bm25(prose_fts)` ascending over event rows; **candidate budget 200 event rows**;
  session id = the event's `session_id`; first **5 distinct session ids** in rank order.
- **Dedup rule:** by session id, first occurrence wins. **Tie-break:** bm25 then `events.id`
  ascending (ingest order).
- **Byte budget:** identical to B1 — the arm returns ids only; payload budgets apply at Stage G.
- **Latency:** measured cold on a fresh connection per receipt run; p95 ≤ 500 ms and ≤ 2 × B1.

## Arm `B1_planner` (control, declared in v1.1 before look 2)

*Question it answers:* how much of `B1_clean`'s lift is the planner not throwing, and how much is
the index holding prose only? Council finding F6 on look 1 asked this; it is answered by
measurement, not wording.

- **Index:** the shipped `messages_fts` over **every** archive row (tool echo, duplicates, all
  roles) — unchanged from B1.
- **Query planning:** `plan_prose_query` — identical to `B1_clean`; the *only* change from B1.
- **Ranking / budget / dedup / tie-break:** the shipped `bm25(messages_fts), m.timestamp DESC`,
  200 message rows, first 5 distinct session ids — identical to B1.
- **Reading:** `B1_planner ≈ B1_clean` → the lift is the planner. `B1_planner ≈ B1` on the
  questions B1 answered → the lift is the clean index. Anything between is apportioned.

## What is *not* in v1 / v1.1

No claims arm, no embeddings, no metadata filters, no lineage roll-up, no RRF. Each of those is a
later spec version, declared before its own first look. The `unicode61` tokenizer variant is a
separate arm (`B1_clean_u61`) that requires a second store build and is declared here only by name.

## Look accounting for Stage D

Look 1 (`ca55c653`) was **voided for provenance** by the receipt council (ruler-amendment-002) and
**still counts** as DEV look 1 of ≤ 4 for the **G1** family — the number was seen. Look 2 re-scores
B0, B1, `B1_clean` and adds `B1_planner` under the corrected harness (fusion-spec sha, store sha,
aggregate non-inferiority recorded); B0/B1/`B1_clean` must reproduce look 1's numbers exactly, which
is the regression check that the harness edits changed no statistic. Improvement = the paired lower
bound vs B1 rose. Scored on gold **DEV** (`gold-v2-dev.json`, file sha `5632cd2b…`, digest
`9aa2b495…` per `gold-v2-receipt-r2.json`); the SEALED set is not touched by any Stage D activity.
