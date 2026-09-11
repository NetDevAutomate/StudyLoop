# Council record — the semantic retrieval layer (plan council, 2026-09-11)

**Owner requirements (00:40–00:52):** query without exact phrasing; semantic layer and DB(s) aligned so
pruning reflects in the embeddings; the agent's interface is the semantic layer; council-validated plan,
implementation plans with unit and integration layers, and test results; a comprehensive unit /
integration / validation harness producing retrieval metrics.

**Evidence:** four read-only investigation lanes (`semantic-layer/lane-{A,B,C,D}.md`) and two probes run
in-session; brief `semantic-layer/plan-brief.md` (21 KB). **Seats:** `openai.gpt-6-astra`
APPROVE-WITH-CHANGES (10 findings), `kimi-k2-thinking` APPROVE-WITH-CHANGES (10; 1 BLOCKING),
`qwen3-coder` APPROVE-WITH-CHANGES (5; 1 BLOCKING). Reviews committed beside this record.

## Baselines measured in-session (read-only; these are the Stage 11 anchors)

| measurement | result | how |
|---|---|---|
| Gold DEV 91 through the **real** MCP `session_search` (`FastMCP.call_tool`) on `main` @ `b42f334e` | **crashes 42/91** — backtick 31, `?` 8, `no such column` 2, comma 1; **every one of the 42 contains "or"/"and"/"not" as a word** (OR 35, AND 5, NOT 2); recall@5 K 6/33 · P 1/29 · R 3/29 = **macro 0.1066**, MRR@5 0.084; 0 silent-empties; p50 20 ms, p95 96 ms | in-process `call_tool`, gold from `feat/knowledge-proof` |
| Cross-validation of the Stage 4 scorer | 0.1066 = PR #18's pinned B1 to four digits — the hand-issued-SQL scorer and the real tool agree | same run |
| `sqlite-vec` under uv's Python (3.12.8, SQLite 3.47.1) | loads; 57,247 × 384-d indexed in **1.56 s**; KNN top-20 in **4.8 ms** (FTS query 6–10 ms; naive full-scan cosine ~109 ms + 176 MB BLOB read) | scratch `vec0` table |
| kimi F1 — does `vec0` honour ROLLBACK? | **Yes**: messages 0 / plain vectors 0 / vec0 0 after `ROLLBACK` | scratch file DB |
| astra F2 — plain connection without the extension | update, delete, `integrity_check` ok, `foreign_key_check` 0, `VACUUM INTO` all succeed when triggers reference only the plain `message_embeddings` table; touching `vec0` → `no such module: vec0` | scratch file DB |

## Dispositions

| seat / id | sev. | finding | disposition |
|---|---|---|---|
| kimi F1 | BLOCKING | `vec0` may bypass the journal | **CLOSED by measurement** (rollback honoured). Design rule added: the plain `message_embeddings` table is the alignment source of truth; the `vec0` index is derived from it and reconciled by extension-aware code; **triggers never reference `vec0`** (so every ordinary connection keeps working — astra F2 also closed). |
| qwen F2 | BLOCKING | plan omits a content hash | **Already in the plan** (`content_sha256 NOT NULL` in the Stage 13 schema, §3). Made explicit in acceptance: doctor's `stale` count is computed from the hash, and `stale == 0` is a Stage 13 gate. |
| astra F1 | MAJOR | "stale can never exist" over-claims: `-rev-` re-keying and concurrent embed-after-scrub races | **ACCEPT.** Re-keying orphans → covered by the delete trigger on the old row? No — the old row is *inserted anew*, so add: trigger AFTER INSERT on `messages` does nothing (no vector yet) and the orphan sweep stays; the embed job re-reads content **inside the same transaction** it writes the vector and stores the hash of what it embedded; doctor `stale` (hash mismatch) is the invariant's proof, not the trigger alone. |
| astra F3 | MAJOR | PK cannot represent chunks; 2 KB is not a token measure | **ACCEPT.** PK becomes `(message_id, chunk_ix)`; Stage 11 measures overflow with each candidate model's tokenizer against its cap, not bytes. |
| astra F4 / lane B Q6 | MAJOR | "candidate source + re-ranker" ≠ ADR-0011's precision-gated candidate source | **ACCEPT.** Stage 14 pre-registers, before any look: N per arm, RRF k, weights, aggregation, and a **precision gate** on the semantic arm (admit only hits above a distance threshold tuned on the toy corpus, never on gold). |
| astra F5 | MAJOR | DEV becomes tuning data after model/fusion selection; 57 clusters | **ACCEPT.** Confirmation on a held-out set: the SEALED 84 (owner holds it; sha committed) scored **once** at Stage 14 by the owner, or a fresh split of new questions. DEV is for iteration only. |
| astra F6 / qwen F3 / kimi Q5 | MAJOR | "winnable ceiling" from byte-identical twins is not an oracle; self-exclusion must apply to semantic inputs | **ACCEPT.** Ceiling = per question, count of distinct sessions holding an identical text; unwinnable iff > 5 equally-ranked targets; report both absolute and ceiling-relative; the semantic arm excludes the question's own row exactly as the lexical arm does. |
| astra F7 / kimi F2 | MAJOR | "non-inferior on every stratum" and "noise band" are not executable; no `sessions.db` census baseline exists | **ACCEPT.** Census gate = single paired delta of self-retrieval@5 with cluster bootstrap CI (cluster = session), non-inferiority margin −0.01; the `sessions.db` census baseline is a **Stage 11 deliverable** and the number is never compared with 61.08%. |
| astra F8 / kimi F3 / qwen Q9 | MAJOR | a shared planner is not one service; a semantic arm shipped off-by-default contradicts R3 | **ACCEPT — owner decision required (below).** Plan text amended: R3 is satisfied only when every agent entry point (MCP, CLI, `memory_search`'s retrieval half) returns identical ordered ids for identical requests via one `retrieval.search`, and the hybrid arm is **on by default**. If Stage 14 fails to establish lift, the honest outcome is "lexical layer only, semantic deferred", stated as such, not "semantic layer delivered". |
| qwen F1 | MAJOR | "crash count on 91" ambiguous vs lane D's 5/5 | **CLOSED by measurement**: 42/91 via `call_tool`; the 5 probe questions happened to contain none of the three words. |
| qwen F4 | MAJOR | seam must carry message ids for fusion | **ACCEPT**: `search(query, k) -> list[Hit(session_id, message_ids, score, method)]`. |
| kimi F4 | MAJOR | excluding embeddings from `_archive_context_complete` might evict a tier whose vectors are not regenerated | **REFUTED in part**: vectors are derived and, by the codebase's own ruling (`tiering.py:53-56`), regenerated locally, so their absence in the full tier is not an integrity loss; **ACCEPT the test**: an integration test proves eviction still happens *and* the full tier's embed backlog is reported by doctor afterwards. |
| kimi F5/F6, astra F9 | MINOR | latency target unmeasured; throughput/storage per model unmeasured; "byte-stable" conflicts with timings | **ACCEPT**: Stage 11 measures p95 hybrid on the live-size clone and sets the target as measured + 50 ms; throughput and bytes per model are Stage 11 outputs; receipts separate **metrics (byte-stable)** from **timings (reported, not compared)**; DB fingerprint includes visibility and session membership. |
| kimi F7/F8/F9/F10, qwen F5 | MINOR | all-stop-word fallback test; define "material"; three missing integration tests; receipt schema; CLI natural-question equivalence | **ACCEPT all**: added to §4 of the plan (tests: hidden→never returned; scrub→vector gone in-transaction; export UPDATE→re-embedded; all-stop-word → non-empty; CLI ≡ MCP on the 91); "material" = > 5% of embeddable messages exceed the model's token cap; receipt JSON schema versioned and regenerated in CI on the toy corpus. |
| astra F10 | MINOR | one backup window is not a dependency; cadence wording inconsistent | **ACCEPT**: Stage 6's DROP and Stage 13's migration stay separate logical migrations with separate owner approvals, run in one rehearsal window if the owner prefers; cadence: three seats on this plan, 13, 14, 15; single seat on 11, 12; escalate on BLOCKING/MAJOR. |

Unanimous on the judgement calls: lexical fix first (D1), fold Stages 6/8/10 (D8, with astra's
separate-approval condition), gold + `sessions.db` census as the ruler pair (with the ceiling as an
investigation, not a promise).

## The plan as amended (Stages 11–15)

11 **Instruments + baselines** (no product change; single seat): harness with the `Hit` seam and arms
{shipped-frozen, lexical-fixed, semantic, hybrid, **mcp** (gating), cli}; port `score.py` + gold DEV to
`main`; `sessions.db` census adapter + twin-aware ceiling; toy corpus; committed baseline receipts
(the table above becomes receipt #1); token-cap overflow per candidate model; throughput/bytes per model;
p95 hybrid on a live-size clone. Freeze: question ids, scope, exclusions, arm commits, metric definitions.
12 **One lexical service; crash class dies** (single seat): `retrieval.search` used by MCP + CLI (+
`memory_search` retrieval half); planner for all natural language, explicit-syntax door only; all-stop-word
fallback; `retrieval_status`. Gate: 0/91 crashes on mcp and cli arms; CLI ≡ MCP ordered ids on the 91;
paired gold delta vs the frozen shipped arm reported; golden file unchanged.
13 **Embedding substrate, aligned by construction** (three seats; **owner-gated migration**): schema per
§3 with `(message_id, chunk_ix)` PK, `model`, `dim`, `content_sha256`; triggers on `messages` (update →
delete vectors; delete → delete vectors) touching only the plain table; `vec0` derived + reconciled;
embed job hashes what it embedded in-transaction; scope to admitted sources; `session-export` honours
`auto_embed` with a time budget; `session-maint embed`; doctor `embeddings_alignment` (missing / orphaned
/ stale / model-mismatch); embeddings excluded from `_archive_context_complete`; `sqlite-vec` → `semantic`
extra; loud degradation when the extension or model is unavailable. Gate: on the clone, missing 0 /
orphaned 0 / stale 0 after `embed`; one integration test per lifecycle path in lane C §1; `prune_hot`
evicts with vectors present.
14 **Hybrid, measured** (three seats): pre-registered fusion spec + precision gate; model bake-off on DEV;
confirmation once on SEALED (owner) — established = CI95 lower ≥ +0.05 macro recall@5; census paired
delta non-inferior (margin −0.01); p95 ≤ Stage 11 measurement + 50 ms; hidden never returned. Ships **on
by default** if established (R3); otherwise "semantic deferred", stated plainly.
15 **Close-out** (three seats): ADR-0012 with the measured status; docs drift removed; Stage 8 openspec
retirement; Stage 10 gates; owner hand-off.

## Owner decisions needed before Stage 11 starts

1. **R3 if lift is not established at Stage 14** — ship the hybrid arm off-by-default and call the layer
   "lexical, semantic deferred" (honest, agents keep a working interface), or hold Stage 15 until a
   semantic arm *is* established (R3 as written). The plan assumes the first; astra, kimi and qwen all
   flagged that it does not satisfy R3 as worded.
2. **Sub-agent budget** — this session's spawn rounds are exhausted; Stages 11–14 can be built in-session
   (slower, my context) or with fresh lanes (needs your go). Either way every lane's claim is verified from
   the diff before commit.
