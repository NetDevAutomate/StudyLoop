# Lane A — Retrieval substrate on `main`

Read-only investigation, branch `main` @ `b42f334e`, 2026-09-10. No tracked file changed; the
live DB was opened only as `file:~/.config/studyloop/sessions.db?mode=ro`.

## 1. Who reaches `semantic_search.py` / `embeddings.py` today

**Nothing in production code.** The import graph terminates in tests.

- `semantic_search.py` imports `embeddings` (`semantic_search.py:20-24`) — the only production
  import of `embeddings` anywhere in `packages/*/src/`.
- Every other reference to `hybrid_search`, `find_similar_sessions`,
  `format_suggested_context`, `_fts_search`, `_vector_search` is a test
  (`tests/test_semantic_search.py:22-31`, `tests/test_context_public_scope.py:127-133,172-198`,
  `tests/test_project_aliases.py:7`) or an experiment
  (`experiments/evidence_context/retrieval_matrix/pilot.py:316`).
- `backfill_embeddings`, `embed_session`, `embed_session_messages`, `embed_message` have **no
  non-test caller**, and there is no embed command: `session-maint` exposes
  `vacuum, schema, reindex, archive, delete, find-duplicates, fts-check, sync-full` + 3 more
  (`maintenance.py:645-874`).
- `session-query search` (`query_sessions.py:90-135`) has flags `-n/--limit, --since, --before,
  --output-format, --project, --local-only`. **No `--semantic`, `--hybrid` or `--fts-only`.**
  It calls `query_logic.search` (`query_sessions.py:124-134`) → `_search_rows` →
  `escape_fts_query` → `_search_schema`, FTS5 only (`query_logic.py:160-200`, `67-117`).
- MCP `session_search` (`mcp_server.py:334-388`) builds its own FTS5 SQL inline and never
  imports `semantic_search`. `session_show` (`mcp_server.py:452`) and `session_context`
  (`mcp_server.py:484`) are id-addressed with no retrieval step.
- `config_loader.py:75-88` defines a `semantic_search` config block (`model`, `fts_weight`,
  `semantic_weight`, `min_content_length`, `auto_embed: True`). `get_semantic_config`
  (`config_loader.py:400`) has exactly one caller, `get_embedding_model`
  (`config_loader.py:432`), itself called only from `embeddings.get_configured_model`
  (`embeddings.py:95-97`) — inside the dead subtree. **`auto_embed: True` is never read.**
- Repo docs already say so (`docs/architecture/session-memory/README.md:63-65`).

Dating: `embeddings.py` landed in `84fc2536` (2026-03-06, "feat: add agent-session-tools
package") and has never been functionally touched since — its last commit is `2acab6b1`
(2026-03-06, pyright/ruff). `semantic_search.py` also landed 2026-03-06 but was last touched
`3aa1b8a4` (2026-09-05) to bolt the scope/visibility joins on. So the scope work maintains a
module with zero callers.

**Verdict: dead code with a live test suite and a maintained visibility contract.**

## 2. Where embeddings are stored

Created by **migration 7** (`migrations.py:373-401`), *not* by `schema.sql` (which stops at
`messages_fts`, `schema.sql:29-58` — no embedding DDL).

```sql
CREATE TABLE message_embeddings (
  message_id TEXT PRIMARY KEY, embedding BLOB NOT NULL,
  model TEXT DEFAULT 'all-MiniLM-L6-v2', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE)   -- migrations.py:383-390
CREATE TABLE session_embeddings (
  session_id TEXT PRIMARY KEY, ... FOREIGN KEY (session_id) REFERENCES sessions(id)
  ON DELETE CASCADE)                                                    -- migrations.py:394-401
```

Keying is **one vector per message id** and **one per session id** — there is no chunking
layer. Session vectors are built by concatenating the first 50 user/assistant messages,
truncated to 1000 chars each (`embeddings.py:509-529`), so a long session is represented by
its opening only.

Live DB (read-only): both tables **exist and hold 0 rows**. `sessions` = 5,879,
`messages` = 143,908, `PRAGMA user_version` = 47 = `CURRENT_VERSION` (`migrations.py:16`),
file size 1,067,790,336 B (1.07 GB).

Model: `DEFAULT_MODEL = "all-mpnet-base-v2"` (`embeddings.py:69`), 768 dims — *not* the
`all-MiniLM-L6-v2` (384 dims) that both tables' `model` column defaults to
(`migrations.py:386,397`). A mixed-dimension corpus is therefore possible with no schema
guard; `cosine_similarity` (`embeddings.py:320-343`) does no dimension check, and a 384/768
`np.dot` would raise, caught only by the broad `except Exception` at
`semantic_search.py:130-134`.

`SUPPORTED_MODELS` (`embeddings.py:22-63`): `nomic-embed-text-v1.5` (768),
`all-mpnet-base-v2` (768), `bge-base-en-v1.5` (768), `all-MiniLM-L6-v2` (384),
`codebert-base` (768).

Dev venv: `sentence_transformers` **5.2.3 imports OK**, `numpy` 2.4.2, `torch` 2.13.0,
`einops` 0.8.2, `sqlite_vec` **0.1.6 imports OK**. Note `sqlite-vec` is declared under the
`test` extra, not `semantic` (`packages/agent-session-tools/pyproject.toml:82-84`;
`semantic = [sentence-transformers, numpy, einops]` at lines 65-69), and **no code loads the
extension** — the only mention is the aspirational comment at `semantic_search.py:279-280`.

## 3. Ranking and fusion, and what it would cost

`hybrid_search` (`semantic_search.py:81-152`) runs FTS with `limit * 3` candidates
(line 113), then `_vector_search` with `limit * 3` (line 120), then `_fusion_rank`.

`_fusion_rank` (`semantic_search.py:311-378`) is RRF with **k = 60** (line 320), keyed on
`(session_id, message_id)`, then a weighted sum
`combined = fts_weight * 1/(k+fts_rank) + semantic_weight * 1/(k+vec_rank)`
(lines 344-350), defaults `0.4 / 0.6` (`semantic_search.py:86-87`, matching
`config_loader.py:83-84`). Weighting *after* RRF is unusual — the weights act on
already-rank-normalised values, so they mostly tilt tie-breaks. The confidence bands in
`format_suggested_context` (`> 0.015` high, `semantic_search.py:492-494`) are hard-coded
against those constants; the max for a rank-1-in-both hit is `1/61 = 0.0164`, so "high
confidence" means "top ~2 in both arms".

**`_vector_search` has no ANN index and no SQL `LIMIT`.** It selects every visible
`message_embeddings` row joined to `messages`+`sessions` (`semantic_search.py:230-243`),
pulls each 3,072-byte BLOB into Python, and calls `cosine_similarity` per row in a loop
(lines 283-290), sorting afterwards. The `limit` argument is applied only at line 292 —
*after* the full scan.

Measured cost basis: 57,247 rows qualify for embedding today (user/assistant,
`length(content) >= 50`, matching the `embed_session_messages` pre-filter,
`embeddings.py:456-470`). At the measured 1.9 µs/call that is **~109 ms of pure Python cosine
per query**, plus **176 MB of BLOBs** read out of SQLite per query, plus ~140 ms warm
query-embedding and a 2.8 s cold model load. Storage would add ~176 MB + ~18 MB to the 1.07 GB
DB. Against a measured **6-10 ms** FTS query the naive semantic arm is 20-40× slower before
BLOB I/O — so `sqlite-vec` (already importable) or a prefilter is not optional if this becomes
the default.

## 4. The FTS5 crash class — exact mechanism

Two entry points, one root cause: `escape_fts_query` (`query_utils.py:171-193`).

```python
if any(op in query.upper() for op in [" AND ", " OR ", " NOT "]):
    return query          # query_utils.py:180-182  ← RAW, unescaped
```

The guard is a **word match on the English conjunctions "and", "or", "not"**, case-insensitive
via `.upper()`. Any ordinary question containing the word *and* or *or* is misclassified as
hand-written FTS5 syntax and the **entire raw question string** — punctuation included — is
handed to `messages_fts MATCH`.

- **MCP path**: `_session_search_queries` (`mcp_server.py:73-93`) checks the same three
  operators (line 78) plus any `"` (lines 80-82); on either it returns
  `escape_fts_query(query)` and **skips the planner entirely** (line 84). Only when neither
  fires does it reach `query_planner.plan`.
- **CLI path**: `query_logic._search_rows` calls `escape_fts_query` unconditionally
  (`query_logic.py:166`) and **never** consults the planner. `session-query search` is
  therefore *more* exposed than the MCP tool.

Does `query_planner.py` sanitise? **Yes, and it is correct** — but it is bypassed. `_TERM =
re.compile(r"[a-zA-Z0-9_./-]+")` (`query_planner.py:18`) treats every other character as a
separator, drops stop words (which include *and*, *or*, *not*, *what*, *why* —
`query_planner.py:11-16`) and tokens ≤ 2 chars, then double-quotes each survivor
(`query_planner.py:26-28`). Its output cannot contain unescaped punctuation. The planner is
the fix that already exists; the operator heuristic routes around it.

Measured, in-process, against a real FTS5 table:

| Input | MATCH string produced | FTS5 verdict |
|---|---|---|
| `` What did we decide about `message_embeddings` and why? `` | *identical raw string* | `OperationalError: fts5: syntax error near "` "` |
| `Should I use FTS5 or embeddings for retrieval?` | *identical raw string* | `fts5: syntax error near "?"` |
| `Which harnesses are supported, and where is the registry?` | *identical raw string* | `fts5: syntax error near ","` |
| `Is sqlite-vec wired in, or not?` | *identical raw string* | `no such column: vec` |
| `Why did we drop gemini?` (no and/or/not) | `"drop" AND "gemini"` then `"drop" OR "gemini"` | OK |

The `no such column: vec` case is the same bug wearing a different hat: with the hyphen as a
token boundary FTS5 reads `sqlite-vec` as a column-filter expression. So all four symptom
classes Stage 4 saw (backtick, `?`, comma, `no such column`) are one defect — the operator
heuristic at `query_utils.py:180`, mirrored at `mcp_server.py:78`.

The MCP tool's AND→OR widening (`mcp_server.py:88-93`) also only exists on the planner branch,
so a question containing "and" loses both the escaping *and* the recall fallback.

## 5. Deleted / hidden / retired sessions vs embeddings

Not "none" — there is real handling, but it is all *deletion-side*, and one gap is on the
write side.

- **Purge**: `context/lifecycle.py:132-142` deletes `session_embeddings` by session id
  alongside `session_notes`/`session_tags`/etc., then asserts FK integrity
  (`lifecycle.py:243-245`). `message_concepts` is deleted explicitly
  (`lifecycle.py:125-128`) but `message_embeddings` is **not** in that per-session list — it
  relies on the reconcile sweep below or on `ON DELETE CASCADE`.
- **Reconcile/orphan sweep**: `lifecycle.py:249-253` runs
  `DELETE FROM message_embeddings WHERE message_id NOT IN (SELECT id FROM messages)` and the
  session-level equivalent, in the transaction that rebuilds `messages_fts`.
- **Tiering/prune**: `_SESSION_CHILD_TABLES`/`_MESSAGE_CHILD_TABLES` (`tiering.py:50-51`) list
  both tables and are unioned into FK-discovered dependents (`tiering.py:272-278`), so a
  pruned session takes its vectors with it. Embeddings are deliberately excluded from
  `_SYNCED_TABLES` (`tiering.py:53-56`) — "derived data … can be regenerated" — so semantic
  search can never reach tiered-out history.
- **Query-time visibility**: `_vector_search` (`semantic_search.py:224-227,236`) and
  `find_similar_sessions` (`semantic_search.py:400-407,418-425`) both apply `visibility_sql`.
  This is what `3aa1b8a4` added.
- **Gap — no visibility filter on the write side**: `backfill_embeddings`
  (`embeddings.py:566-576`) selects `FROM sessions s LEFT JOIN session_embeddings` with **no
  scope predicate**, so a backfill would also embed the ~1,285 legacy-source rows. Cost, not
  correctness (reads filter), but vectors spent on rows the reader never returns.
- **No trigger anywhere.** `messages_fts` has insert/update/delete triggers
  (`schema.sql:36-58`); embeddings have none. Nothing keeps vectors aligned as messages
  arrive or change — an edited message keeps a stale vector for ever — and
  `ON DELETE CASCADE` only fires on connections that set `PRAGMA foreign_keys=ON`
  (`query_db.py:48`, `context/public.py:81` do; not every path does).

## 6. Measured latency (live DB, read-only)

- FTS, exactly the `_search_schema` shape, `LIMIT 10`, on 143,908 messages:
  `"embeddings" AND "retrieval"` → 10 rows in **6.3 ms**;
  `"embeddings" OR "retrieval"` → 10 rows in **10.1 ms**.
- `_vector_search` called for real against the read-only live DB: **0 results in 693 ms** —
  all of it query-embedding, none of it search, because the table is empty. It did not raise;
  the scope join is satisfied.
- Cold `all-mpnet-base-v2` load **2,770 ms**; warm query embedding mean **140 ms**
  (min 9, max 376); `cosine_similarity` **1.9 µs/call** over 20,000 calls.

## What it would take to become the default query path

1. Fix the operator heuristic once, in `escape_fts_query` (`query_utils.py:180`), and route
   both `_session_search_queries` (`mcp_server.py:78-84`) and `query_logic._search_rows`
   (`query_logic.py:166`) through `query_planner.plan` for anything not *unambiguously*
   hand-written FTS5. Addresses the 42/91 crash set independently of embeddings.
2. Populate the vectors: `backfill_embeddings` exists but has no CLI. Needs a
   `session-maint embed` entry point, a scope filter, and batch/resume — 57,247 messages at
   ~140 ms warm each is ~2.2 h single-threaded before batching.
3. Keep them aligned: nothing does today. Either triggers mirroring the `messages_fts` set (via
   a dirty-queue table, since a trigger cannot embed), or an export-time hook honouring the
   already-declared `auto_embed` key, plus a content-hash staleness column.
4. Replace the full-scan cosine with `sqlite-vec` (already importable, already a declared dep —
   under the wrong extra) or a hard FTS prefilter.
5. Pin one model + dimension and enforce it: the table default (`all-MiniLM-L6-v2`, 384) and
   the code default (`all-mpnet-base-v2`, 768) disagree.

## Numbers measured

| Quantity | Value | How |
|---|---|---|
| sessions / messages (live) | 5,879 / 143,908 | `sqlite3 …?mode=ro` count(*) |
| `message_embeddings` / `session_embeddings` rows | 0 / 0 | ditto |
| `PRAGMA user_version` vs `CURRENT_VERSION` | 47 vs 47 | ditto / `migrations.py:16` |
| live DB size | 1,067,790,336 B (1.07 GB) | `ls -la` |
| embeddable messages (user/assistant, len ≥ 50) | 57,247 | count(*), 133 ms |
| FTS `AND` query, LIMIT 10 | 6.3 ms | `time.perf_counter` |
| FTS `OR` query, LIMIT 10 | 10.1 ms | ditto |
| `_vector_search` on live DB (empty table) | 693 ms, 0 results | ditto |
| cold model load `all-mpnet-base-v2` | 2,770 ms | ditto |
| warm query embedding | mean 140 ms (9-376) | 5 calls after warm-up |
| `cosine_similarity` | 1.9 µs/call | 20,000 calls |
| embedding dims / bytes | 768 / 3,072 | `generate_embedding` output |
| projected `message_embeddings` size | 176 MB | 57,247 × 3,072 |
| projected `session_embeddings` size | 18 MB | 5,879 × 3,072 |
| projected cosine cost per query | ~109 ms | 57,247 × 1.9 µs |
| `sentence_transformers` / `sqlite_vec` importable | 5.2.3 / 0.1.6 — both yes | `uv run --group dev python -c import` |
| FTS5 crash inputs reproduced | 4 of 4 classes | in-process, scratch FTS5 table |

## Open questions

1. Is the 42/91 Stage 4 failure set entirely the `escape_fts_query:180` heuristic, or does some
   fraction come from the planner's stop-word list eating every token of a short question
   ("why not?" → empty plan → `_session_search_queries` returns `()` → silent empty result,
   `mcp_server.py:89-90`)? Silent-empty is a distinct defect; I did not enumerate the 91.
2. Should the default path be hybrid at all, given
   `docs/architecture/session-memory/README.md:70-76` records the concept-fusion lift as *not
   statistically established* (0.60 vs 0.48 control, Wilson CI [0.41, 0.77], n = 25)? Fixing
   the FTS crash may recover most of the loss at zero storage cost.
3. `all-mpnet-base-v2` caps at 512 tokens (`embeddings.py:36`) and `generate_embedding`
   truncates at `max_tokens * 4` chars (`embeddings.py:274-277`). One vector per message, no
   chunking, so long assistant turns are represented by their first ~2 KB. Is per-message
   keying the right grain?
4. Who owns realignment — a dirty-queue table driven by triggers, or export-time hooks (which
   skip externally-modified rows)? Not decided anywhere in the tree I read.
5. `sqlite-vec` sits under the `test` extra
   (`packages/agent-session-tools/pyproject.toml:82-84`) while `semantic` omits it. Deliberate
   (test-only benchmarking) or a misplacement?
