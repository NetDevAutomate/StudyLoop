# Fusion spec v1 — arms pre-declared before the first DEV look

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

## What is *not* in v1

No claims arm, no embeddings, no metadata filters, no lineage roll-up, no RRF. Each of those is a
later spec version, declared before its own first look. The `unicode61` tokenizer variant is a
separate arm (`B1_clean_u61`) that requires a second store build and is declared here only by name.

## Look accounting for Stage D

This look is the first of ≤ 4 DEV looks for the **G1** family. Improvement = the paired lower
bound vs B1 rose. It is scored on gold **DEV** (`gold-v2-dev.json`, sha `eeca2aaf…`); the SEALED
set is not touched by any Stage D activity.
