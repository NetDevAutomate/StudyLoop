# Planning brief — the semantic retrieval layer for StudyLoop session memory

Three-seat council on a PLAN, before any implementation is cut. Read the evidence, then critique the plan:
sequencing, decisions D1–D8, the test harness, the rulers and acceptance rules. Cite the evidence lines
you rely on; mark anything you cannot settle from this material UNVERIFIED. Do not restate the brief.

## 1. Owner requirements (verbatim, 2026-09-11 00:40–00:52)

> "The key function missing is the abstracted semantic layer to allow query without exact phrasing; the
> semantic layer and db(s) must be aligned, so pruning of the db must also reflect in the embeddings — the
> interface for the agent must be the semantic layer."
> "Please use the council of models for planning, implementation plans including unit and integration
> layers and test results."
> "Please ensure a comprehensive test harness is built for unit, integration and validation testing to
> produce retrieval metrics."

Decomposed: **R1** retrieval robust to paraphrase, not merely tolerant of natural-language tokens.
**R2** embeddings derived from `sessions.db` and kept aligned through EVERY create/update/hide/delete/
scrub/merge/prune/sync path, with alignment checkable (doctor) and repairable; hidden sessions hidden in
semantic results too. **R3** the agent's query surfaces (MCP `session_search`, its CLI fallback, and
ideally `memory_search`) route through ONE retrieval service with identical semantics; skills/mandates
updated. **R4** a three-tier harness (unit / integration / validation) that produces retrieval metrics
as committed receipts.

Context: StudyLoop is local-first (macOS/Linux, `uv`), six harnesses, 5,879 sessions / 143,908 messages in
`~/.config/studyloop/sessions.db` (1.07 GB, `user_version` 47), shared across machines by row-level sync,
not by file. Stages 6 (owner-gated DROP of 31 orphaned ontology objects), 8 (openspec retirement) and 10
(close-out) of the previous plan are still pending.

## 2. Evidence (four read-only investigation lanes, 2026-09-11; full reports on disk)

### 2.1 What exists on `main` @ `b42f334e`
- `embeddings.py` (593 lines, sentence-transformers) and `semantic_search.py` (581 lines, FTS5 + vector
  + RRF k=60, weights applied AFTER rank normalisation, `semantic_search.py:311-378`) have **zero
  production importers** — only 3 test files (lane A §1, lane D §5). Landed 2026-03-06, never wired.
- Migration 7 (`migrations.py:373-401`) created `message_embeddings(message_id PK FK CASCADE, embedding
  BLOB, model DEFAULT 'all-MiniLM-L6-v2')` and `session_embeddings`; both hold **0 rows** in the live DB.
  Code default model is `all-mpnet-base-v2` (768-d) — **disagrees** with the table default (384-d); no
  dimension column; `cosine_similarity` does no dim check (lane A §2, lane C §4).
- `_vector_search` has **no ANN index and no SQL LIMIT**: full scan, per-row Python cosine. Priced at
  57,247 embeddable messages (user/assistant, len ≥ 50): ~109 ms cosine + 176 MB BLOB read per query vs
  a measured **6–10 ms** FTS query; cold mpnet load 2.8 s, warm query embedding ~140 ms (lane A §3, §6).
- `sqlite_vec` 0.1.6 **imports** in the dev venv but nothing loads the extension; it is declared under the
  `test` extra, not `semantic` (lane A §2). `sentence_transformers` 5.2.3 imports.
- Config block `semantic_search{model, fts_weight 0.4, semantic_weight 0.6, auto_embed: True}` exists;
  **`auto_embed` is read by nothing**; `docs/cli-reference.md:653` advertises the `[semantic]` extra
  (lane D §5 — docs-vs-reality drift).

### 2.2 The crash class has ONE root cause (lane A §4, reproduced 4/4)
`query_utils.escape_fts_query:180`: `if any(op in query.upper() for op in [" AND ", " OR ", " NOT "]):
return query` — a word match on the English conjunctions; any question containing "and"/"or"/"not" is
handed RAW to `MATCH`. MCP `_session_search_queries` (`mcp_server.py:78-84`) mirrors the heuristic and
skips the planner; the CLI `query_logic._search_rows:166` calls `escape_fts_query` unconditionally and
never consults the planner. `query_planner.plan` (`query_planner.py:18-28`) sanitises correctly
(`[a-zA-Z0-9_./-]+`, 62 stop-words, ≤2-char drop, quote each token) but is bypassed. All four Stage 4
symptom classes (backtick ×31, `?` ×8, `,` ×1, `no such column`) are this defect. Distinct second defect:
a short question whose tokens are all stop-words plans to `()` → **silent empty** result
(`mcp_server.py:89-90`). Lane D's 5-question probe through the real MCP tool (`call_tool`) returned
results 5/5 (none contained "and/or/not"); the CLI phrase path returned **0/5**.

### 2.3 Alignment today (lane C §1 — the table to mirror)
`messages_fts` is kept aligned by three triggers (`schema.sql:42-62`). Embeddings: **deletion-side only**.
Purge (`context/lifecycle.py:87-149`) deletes `session_embeddings` explicitly and relies on FK CASCADE for
`message_embeddings` (CASCADE fires only on connections with `foreign_keys=ON` — not every path sets it);
compact (`lifecycle.py:225-253`) sweeps orphans; `prune_hot` child-table lists include both tables
(`tiering.py:50-51`). **Unhandled:** export UPDATE (`exporters/base.py:167-175` rewrites `content` in
place → vector stale, no signal), dedup merge (`deduplication.py:218-224`, session vector misrepresents
the merged set), scrub (`mcp_server.py:693-695` — **a redacted secret would survive in its vector**),
`_preserve_message_identity` re-keying (`base.py:267-321`, orphans the old vector). **No content hash is
written anywhere**: `messages.content_hash` populated 0/143,908 (`base.py:157-166` omits it).
Embeddings are **deliberately not synced** ("derived data … regenerated", `tiering.py:53-56`), not in
`sync.py` tables, not in `replication/snapshot.py:TABLES`. **Latent blocker:** `_archive_context_complete`
(`tiering.py:850-860`) requires both embedding tables row-identical in the full-tier DB before eviction,
but `_SYNCED_TABLES` never copies them → the moment vectors exist, `prune_hot` **silently stops evicting**.
Hidden = read predicate (`context/scope.py:325-337`, admitted = `SUPPORTED_SOURCES`); 1,279 retired-source
sessions never deleted. Doctor pattern to mirror: `_check_fts_drift` (`doctor/database.py:226-266`) +
`repair_fts`; embeddings need THREE counts (missing / orphaned / stale), and stale cannot be SQL-repaired.

### 2.4 Rulers (lane B)
- **Gold DEV** `receipts/gold-v2-dev.json`: 91 items, 57 clusters (= source session, the bootstrap unit),
  strata K33/P29/R29, sha `5632cd2b…`. Metric: recall@5 per question, macro over strata; MRR@5 reported.
  Paired cluster bootstrap 10,000 draws seed 20260910; "established lift" = CI95 lower ≥ +0.05
  (`score.py:38-40,132-158`). Arm seam exists: `Arm = Callable[[sqlite3.Connection, str], list[str]]`
  (`score.py:36`). **`score_stage4.py` does NOT use FastMCP `call_tool`** — it re-issues the shipped SQL
  by hand (correction to the Stage 4 record). 3 items unwinnable (gold sessions are hidden litellm-proxy
  rows); denominator stays 91. B0 (pre-planner main) **0.000**; B1 (planner) **0.1066**; both arms
  crash on the same 42/91. A DEV run ≈ **0.7–3 s** per arm; bootstrap 0.09 s.
- **Paraphrase census** (`scripts/knowledge_proof/paraphrase_census.py`): every real learner turn
  (≤200 words, ≥3 content tokens; 3,299 in v2) is a question about its own session; self-retrieval@5,
  vocab-gap (overlap 0), ranking miss. Ran on the learning-memory store (61.08% / 5.70% / 33.22%),
  **not** on `sessions.db`. **No arm seam** — planner+SQL inlined (`census:284-299`). Running it on
  `sessions.db` needs: user-role questions from `messages`, a prose predicate, self-exclusion by rowid,
  `visibility_sql` scope — yields an **incomparable** but honest number. **14.4%** of eligible questions
  have byte-identical twins in other sessions → part of the ranking bucket is unwinnable; the winnable
  ceiling has never been computed. Census run ≈ **4 m 50 s**.
- The lever: `plan_prose_query` (`learning_memory/store.py:229-255`) is pure `(str)->str`: whitespace
  split, strip Cc/Cs, keep tokens with an alphanumeric, quote each, OR-join, no stop-words. +0.142 on the
  store's ruler when replacing the shipped planner. Liftable unchanged; two deltas: no stop-words (recall
  widens) and it neutralises explicit FTS syntax (needs an explicit-syntax door).
- ADR-0011 does **not** authorise embeddings as settled: G4 sits under open questions "to be settled by
  measurement"; a fused claims arm was **worse** than the prose control (−0.154); non-lexical arms must
  be pre-registered as re-ranker or precision-gated candidate source (ADR-0011:337-344).

### 2.5 Agent interface (lane D §1–§3)
Four free-text entry points over two FTS corpora: MCP `session_search` (planner AND→OR, `ORDER BY bm25`,
300-char preview), CLI `session-query search` (strict adjacency phrase), MCP `memory_search` +
`session-context search` (OR of ≤16 quoted words over `context_evidence_fts`, 100-candidate cap, returns
`reason.method="lexical_match"`). studyloop's `get_study_history` is Python substring over course names,
not transcript search. Skill text: "Prefer the `session_search` MCP tool … if unavailable, `session-query
search "<topic or error>"` … the CLI is the deterministic fallback" (`SKILL.md:16-29`) — the fallback
degrades to exact phrase. Tests: `test_mcp_server.py::TestServerCreation::test_server_has_all_tools`
pins **16** tool names; 9 node ids in `test_session_search_planner.py` pin planner semantics incl. a
frozen golden file; 0 tests exercise the CLI end-to-end with a natural question; 0 pin `memory_search`.

## 3. Proposed plan (for critique)

Programme = Stages 11–15, replacing the tail of the old plan; each stage ends with a committed receipt
and a council check (cadence in §7). Every number in a receipt comes from a command output.

**Stage 11 — Instruments and baselines (no product change).**
Build the harness (§4). Port `score.py` to `main` (it exists only on `feat/knowledge-proof`); add an
**MCP arm that goes through FastMCP `call_tool`** (the agent's real interface) and a CLI arm; census
adapter for `sessions.db` with the winnable ceiling (dup-twin intersection); planted-paraphrase toy corpus
for CI. Measure and commit baselines on current `main`: crash count on the 91 through `call_tool`,
gold recall@5 (macro) + MRR, census hit/vocab-gap/ranking + ceiling, latency p50/p95, message-length
distribution (share > 2 KB), `sqlite-vec` loadability under uv's Python, batched embedding throughput of
3 candidate models on a 2,000-message sample. Done-when: receipts exist and re-run byte-stable on metrics.

**Stage 12 — One lexical retrieval service; the crash class dies (R1-lexical, R3).**
`agent_session_tools/retrieval.py`: `search(query, *, project, source, limit, mode) -> RetrievalResult`
used by MCP `session_search` AND the CLI (same semantics). Natural language ALWAYS goes through the
planner; explicit FTS5 syntax only via an explicit door (`raw=True` / `fts:` prefix), never by guessing
from the words "and/or/not". Fix the silent-empty case (all-stop-word query → fall back to unfiltered
tokens). Keep the AND→OR widening; evaluate lifting `plan_prose_query`'s OR arm as the fallback (measured
on gold+census, not assumed). Result rows carry `method` and a `retrieval_status` string. Skill/mandate
text: "ask in your own words". Done-when: 0 crashes on 91 via `call_tool`; gold ≥ B1 (0.1066) — expected
far higher once 42 crashers resolve; golden file unchanged; CLI ≡ MCP on the 91.

**Stage 13 — Embedding substrate with alignment by construction (R2).**
Migration 48 (owner-gated, on a `VACUUM INTO` clone first; fold Stage 6's DROP into the same moment: one
backup, one rehearsal, one ASK): drop the two empty tables; create `message_embeddings(message_id TEXT PK
REFERENCES messages(id) ON DELETE CASCADE, model TEXT NOT NULL, dim INTEGER NOT NULL, content_sha256
TEXT NOT NULL, chunk_ix INTEGER NOT NULL DEFAULT 0, truncated INTEGER NOT NULL DEFAULT 0, created_at)`
plus a `sqlite-vec` `vec0` KNN table keyed to it; **triggers on `messages`**: AFTER UPDATE OF content →
DELETE the message's vectors (so "stale" cannot exist — scrub is covered in the same transaction), AFTER
DELETE → DELETE vectors (covers connections without `foreign_keys=ON`). No session vectors (session score
derived at query time), which also removes the dedup-merge misrepresentation. Write-side scope: embed
only admitted sources. Realignment ownership: triggers delete; "missing" is filled by (a) `session-export`
honouring `auto_embed` with a time budget (hooks have 3–10 s), (b) `session-maint embed` (batched,
resumable, `--rebuild` on model change), (c) doctor check `embeddings_alignment` reporting
missing/orphaned/stale/model-mismatch with `fix_auto`. Rulings: not synced, not replicated ("regenerate
locally", `tiering.py:53-56`); **exclude embeddings from `_archive_context_complete`** (kills the prune
blocker); `session-sync` import → doctor backlog, not transport. Move `sqlite-vec` into the `semantic`
extra; when the extension cannot load, the semantic arm reports unavailable rather than falling back to a
full scan silently. Done-when: on the clone, `missing=0 orphaned=0 stale=0` after `embed`; every lifecycle
path in lane C's table has an integration test asserting the vector state after it; `prune_hot` still
evicts with vectors present; index build time and size recorded.

**Stage 14 — Hybrid retrieval, measured (R1-semantic).**
Semantic arm = query embedding → KNN top-N messages (visibility predicate applied) → sessions; fuse with
the lexical arm by RRF at message level, aggregate to sessions (max). Pre-registered per ADR-0011: the
semantic arm is a candidate source + re-ranker; lexical-fixed (Stage 12) is the control. Model bake-off
on the ruler (MiniLM-L6-v2 384, bge-small-en-v1.5 384, mpnet 768); pin one; enforce model+dim per row.
`retrieval_status` reports e.g. `semantic: 57,247/57,247 aligned` or `semantic unavailable: model not
installed`. Acceptance (§5). If lift is not established the arm ships **off by default** with the receipt
saying so — an honest lexical layer beats a flattering hybrid.

**Stage 15 — Close-out.** ADR-0012 "Semantic retrieval layer" (status = what was measured), docs drift
removed (`[semantic]` extra honest, `auto_embed` real), Stage 8 openspec retirement, Stage 10 gates,
three-seat sign-off, owner hand-off (pushes, `doctor --fix`, real-Grok observation).

### Decisions and recommendations
- **D1 order:** lexical fix (12) BEFORE embeddings (13/14) — one root cause, zero storage cost, measurable
  in seconds, and it is the honest control for the semantic arm. Recommend yes.
- **D2 vector store:** `sqlite-vec` inside `sessions.db` (transactional with the rows it describes; KNN in
  SQL) vs numpy sidecar (a second alignment problem). Recommend sqlite-vec; numpy only as an explicit
  degraded mode.
- **D3 grain:** per-message vectors (the unit that gets updated/scrubbed/deleted); chunk messages over the
  model's token cap only if Stage 11 shows a material share > 2 KB, else truncate and record `truncated`.
- **D4 model:** pin after the bake-off; default MiniLM-L6-v2 unless bge-small wins by an established
  margin at equal cost. mpnet only if its lift justifies 2× storage and ~5× query-embed latency.
- **D5 alignment ownership:** triggers delete on change/delete (cannot embed); export/maint/doctor fill.
  Alternative: dirty-queue table. Recommend delete-on-change (stale can never exist; simplest invariant).
- **D6 session vectors:** drop them. Alternative: keep and recompute on merge. Recommend drop.
- **D7 `memory_search`:** Stage 12 gives it the same planner (lexical consistency); full unification with
  `session_search` is a later decision — the graph walk is its value, not its matching.
- **D8 sequencing vs old stages:** fold Stage 6 into Stage 13's migration moment; Stage 8 and 10 into 15.

## 4. Test harness (R4) — three tiers, one seam

- **Seam:** `Retriever` protocol `search(query, k) -> list[session_id]` (+ optional per-hit message ids);
  arms: `lexical-shipped` (pre-fix, frozen as a pinned commit or vendored copy), `lexical-fixed`,
  `semantic-only`, `hybrid`, and **`mcp`** (through FastMCP `call_tool` on the real server — this is the
  agent's interface and the arm that gates acceptance) and `cli` (subprocess `session-query search`).
- **Unit (hermetic, < 1 s each, no model download):** planner adversarial inputs including all 42 Stage 4
  crashers as fixtures; explicit-syntax door; silent-empty fallback; content-sha256; dim/model pinning
  (mismatch rejected); trigger semantics on a tmp DB (update → vector gone; delete → gone; scrub → gone
  in the same transaction); RRF fusion arithmetic; doctor three-count logic; a **fake embedder**
  (deterministic hash-based vectors) so every unit test runs without sentence-transformers.
- **Integration (tmp DB + `VACUUM INTO` clone of the live DB; real small model behind
  `@pytest.mark.model`):** export → embed → search → update → search (vector regenerated) → forget → prune
  (hot/full pair: eviction still happens) → dedup merge → scrub; migration 48 applied to the clone
  (`integrity_check`, `foreign_key_check`, counts); MCP `session_search` end-to-end via `call_tool`; CLI
  end-to-end with 5 natural questions; `doctor --fix` fills a backlog; `session-sync` import leaves a
  reported backlog, not stale vectors; hidden sessions never returned by any arm.
- **Validation → metrics (committed receipts):** gold DEV 91 and census-on-sessions.db for every arm;
  paired cluster bootstrap deltas with CI95; crash count; MRR@5; latency p50/p95 per arm; index build time
  and size; DB fingerprint (sorted message ids + content hashes) and model id. **Toy corpus** with planted
  paraphrase pairs and known answers so CI computes the same metrics on public data and asserts
  `hybrid ≥ lexical`, `crashes == 0`, `hidden never returned`.
- **Ruler discipline** (metric-design): question sets frozen at Stage 11 before any tuning; noise band from
  3 repeated runs; guardrails fail the run: crashes > 0, explicit-syntax golden file changed, any hidden
  session returned, exact-match regression on the K stratum beyond the noise band.

## 5. Acceptance rules (proposed)
- Stage 12: crashes 0/91 (mcp and cli arms); gold macro recall@5 ≥ 0.1066 and CLI ≡ MCP on all 91;
  golden file unchanged.
- Stage 13: on the clone after `embed`: missing 0, orphaned 0, stale 0; every lifecycle integration test
  green; `prune_hot` evicts with vectors present; build time and size in the receipt.
- Stage 14: hybrid vs lexical-fixed on gold **established** (CI95 lower ≥ +0.05, macro recall@5) AND
  census self-retrieval@5 non-inferior on every stratum; programme goal census ≥ 0.70 of the **winnable**
  ceiling (report absolute too); p95 warm hybrid latency ≤ 250 ms on the live-size clone. Not established
  → ship off-by-default, receipt says so.

## 6. Risks
Fusion can hurt (ADR-0011's claims arm −0.154); storage +176 MB on a 1.07 GB DB; full backfill CPU time
(batched estimate unmeasured — Stage 11 measures); `sqlite-vec` loadability under python-build-standalone;
model download on first use (offline machines → semantic unavailable, must degrade loudly, never crash);
vectors of secrets (trigger-on-scrub closes it, but backfill must run AFTER scrub, and doctor must count
stale=0); `prune_hot` blocker if D5/D6 are not adopted; census on `sessions.db` is a new number — no
comparability with 61.08% and must not be presented as one; the spawn budget for implementation lanes is
exhausted for this session (owner guidance needed before more sub-agents; in-session work is available).

## 7. Council cadence proposed
Three seats: this plan; Stage 13 (schema + live DB); Stage 14 (acceptance); Stage 15 (sign-off). Single
seat with artefacts: Stages 11, 12. Escalate on any BLOCKING/MAJOR. Spend cap unchanged.

## 8. Questions
Q1. Is the decomposition R1–R4 faithful to the owner's words? What did we miss?
Q2. D1 — lexical fix first: agree? Name what the semantic arm cannot fix that the lexical fix does, and
    vice versa.
Q3. D2/D5/D6 — sqlite-vec in-DB, delete-on-change triggers, no session vectors: the strongest alignment
    story or an over-simplification? Name a lifecycle path in §2.3 the design still leaves stale.
Q4. D3/D4 — grain and model: what single Stage 11 measurement should decide each?
Q5. The rulers: is macro recall@5 on gold + census-on-sessions.db the right pair to gate on? Is "≥ 0.70 of
    the winnable ceiling" a sound programme goal or a moving target? What guardrail is missing?
Q6. The harness: which tier is under-specified? Which integration test would you insist on that §4 lacks?
Q7. Is the `mcp` arm through `call_tool` the right gating arm, given the agent's real interface?
Q8. Sequencing vs Stages 6/8/10 (D8): fold or finish first? Any dependency we have inverted?
Q9. What would make "the interface for the agent is the semantic layer" a false claim at Stage 15?
Q10. Anything that should be BLOCKING before Stage 11 starts?

## Required answer format
First line exactly: `VERDICT: APPROVE` | `VERDICT: APPROVE-WITH-CHANGES` | `VERDICT: REJECT`.
Then `## Findings` table: id | severity (BLOCKING/MAJOR/MINOR) | plan item | claim | check | proposed change.
Then `## Answers` Q1–Q10, each ≤ 120 words, evidence-first, citing §/lane lines.
