# Stage 3 design — embedding substrate aligned by construction

**Date:** 2026-09-11 · **Plan:** `plan-council-2026-09-11.md` §"Stage 13" · **Council:** three seats
after implementation (astra, kimi-k2-thinking, qwen3-coder), then the owner gate.

This file is the contract the implementation lanes build against. Numbers in it are
measured (Stage 1 receipts) or counted at commit time; everything else is a decision, marked
**D-n**, and each decision names what it deviates from if it deviates from the plan record.

## What "aligned by construction" means here

Every vector in `message_embeddings` describes a message that exists, is admitted, has the
same text it had when embedded, and was produced by the configured model. Two of those are
enforced by triggers (text unchanged, message exists), one by the eligibility predicate
(admitted at embed time) and a sweep (retired since), one by a stored `(model, dim)` pair.
The doctor **proves** the four with counts rather than trusting the triggers; only the
backlog (`missing`) needs the model to shrink. Lane C of the plan council (`lane-C.md` §1)
lists the write paths; §"Lifecycle tests" below maps each to a test.

## Landed in the foundation commit (this file's commit)

- **Migration 48** (`migrations.py`, `CURRENT_VERSION = 48`): drops the empty migration-7
  `message_embeddings` / `session_embeddings` (refuses if either holds rows — nothing in
  production ever wrote them, so rows mean a hand-run backfill and we do not delete data
  nobody asked us to), creates:

  ```sql
  message_embeddings(message_id TEXT REFERENCES messages(id) ON DELETE CASCADE ON UPDATE CASCADE,
                     chunk_ix INTEGER CHECK(chunk_ix >= 0), model TEXT, dim INTEGER CHECK(dim > 0),
                     content_sha256 TEXT CHECK(length = 64), truncated INTEGER CHECK IN (0,1),
                     embedding BLOB, created_at TEXT, PRIMARY KEY(message_id, chunk_ix))
  ```
  and two triggers on `messages` that reference
  only this plain table: `message_embeddings_content_changed` (AFTER UPDATE OF content, id, WHEN
  the value actually changed → delete the message's vectors) and
  `message_embeddings_message_deleted` (AFTER DELETE → delete; covers connections with
  `foreign_keys` off).
- **D-1 No session vectors.** `session_embeddings` is gone. A session is represented by its
  message vectors at query time; the dedup-merge "primary's session vector misrepresents the
  merged set" problem (lane C §1) cannot arise.
- **`embedding_alignment.py`**: `eligible_predicate()` (admitted source ∧ role ∈ {user,
  assistant} ∧ `length(content) >= 50`; the Stage 1 "embeddable" definition, 51,729 messages),
  `alignment_report()` → `AlignmentReport(eligible, embedded, missing, orphaned, stale,
  model_mismatch, hidden, rows)`, `sweep()` (deletes everything but the backlog),
  `missing_messages()` (the embed job's candidate list), `content_sha256()`.
- **Tiering / lifecycle**: `_SESSION_CHILD_TABLES` loses `session_embeddings`; the two
  embedding tables are removed from `_archive_context_complete`'s literal table set, and
  `_DERIVED_TABLES = {message_embeddings}` is subtracted from that set as a guard (closes lane
  C §4: `prune_hot` would otherwise stop evicting the moment a hot vector existed, because
  embeddings are never synced to the full tier). Lane A verified the mechanism: the literal
  removal is the fix and the subtraction alone is not load-bearing — `message_embeddings` is
  not in `records.TABLES` and does not start with `context_`, so it only ever entered the set
  through the literal. The prune test is therefore bound to the outcome (eviction happens with
  vectors present), not to either mechanism. Purge child list and the compact orphan sweep
  drop the dead table.
- **Retirement**: `semantic_search.py` (581 lines, zero production callers, migration-7 shape)
  and `tests/test_semantic_search.py` deleted; the storage half of `embeddings.py`
  (`embed_message` … `backfill_embeddings`) and its 21 tests removed; the model layer
  (`SUPPORTED_MODELS`, `get_model`, `generate_embedding`, `is_meaningful_content`) stays.
  Two scope/alias tests that drove the old module now drive `retrieval.search`. The old
  "vector candidates are scoped before similarity" test lost its subject; its requirement is
  **D-6** below and Lane B's test.

## Decisions the lanes implement

- **D-2 Derived vector index in a sidecar file, not in `sessions.db`.** `sqlite-vec`'s `vec0`
  table and its shadow tables live in `<db-stem>.vec.db` beside the database (helper
  `embedding_store.sidecar_path(db_path)`), `ATTACH`ed as `vec` only by code that has loaded
  the extension. Consequence: `sessions.db` never contains a virtual table, so compaction,
  `VACUUM INTO`, `integrity_check`, sync, replication, repair and every plain connection are
  untouched (kimi F1 / astra F2 of the plan council are closed by construction, not by care).
  The sidecar is disposable: `reconcile()` rebuilds it from `message_embeddings` and reports
  `(inserted, deleted)`; a missing or corrupt sidecar is a rebuild, never an error for the
  lexical path. Deviation from the plan record's wording ("vec0 derived + reconciled" was
  read as in-database by the seats); same guarantees, fewer moving parts.
- **D-3 Chunking is token-based per model, with no truncation.** Stage 1 measured 15.7–21.8 %
  of embeddable messages over every candidate's token cap, so a message is split into chunks
  of at most `max_tokens` tokens (the model's tokenizer counts), on paragraph/sentence
  boundaries when they exist and by hard token windows when a single span exceeds the cap;
  `truncated = 1` marks a chunk produced by a hard window (decode/encode round-trip is not
  byte-exact). Every chunk row carries the **message's** `content_sha256`, so the stale check
  is per message. Chunk order is `chunk_ix` 0..n-1.
- **D-4 The embed job hashes what it embedded, inside the write transaction.** Candidates come
  from `missing_messages()`; encoding happens outside any transaction (model inference must
  not hold a write lock against the exporters); then `BEGIN IMMEDIATE`, re-read each
  candidate's content, and insert only when `content_sha256(current) == hash of the text that
  was encoded` — otherwise skip (it is still `missing` and the next run picks it up). This is
  astra F1's disposition in the plan council: the hash is the invariant's proof, the trigger is
  the mechanism.
- **D-5 Model pin per row; mismatch is swept, never compared.** `model` and `dim` are stored per
  row and `alignment_report(model=configured)` counts `model_mismatch`. `session-maint embed`
  refuses to run while mismatched rows exist unless `--replace-model` is given, which sweeps
  them first. Stage 4's bake-off runs each candidate on its own `VACUUM INTO` clone.
- **D-6 Hidden never embedded, never returned.** Eligibility carries the admitted-source
  predicate, so a hidden session is never embedded; a source retired after embedding leaves
  `hidden` rows that `sweep()` removes. `knn()` returns raw candidates `(message_id, chunk_ix,
  distance)` from the sidecar; the **caller** (Stage 4's fusion inside `retrieval.search`) joins
  them to `messages`/`sessions` under the same visibility predicate and self-exclusion the
  lexical arm uses, over-fetching `n = k × oversample`. Lane B's test: a KNN over a corpus with
  hidden and visible neighbours, filtered by the predicate, returns no hidden id.
  **Council correction (astra 5):** the filter is now a function, `embedding_store.candidates()`,
  and it joins each KNN key to its canonical `message_embeddings` row (same message AND chunk)
  before the visibility join — so a sidecar that is stale (scrub, delete, re-key since the last
  `reconcile`) cannot surface a candidate either. Stage 4's fusion calls `candidates()`, never
  raw `knn()`.
- **D-7 `auto_embed` on export is bounded and never downloads.** `session-export` runs
  `embedding_store.embed(budget_seconds=config.semantic_search.auto_embed_budget_seconds)`
  (default 20 s) after a successful export **only if** the extension and model are already
  available locally (`availability().ready`); otherwise it prints one line naming
  `session-maint embed` and exits 0. A SessionEnd hook must not pull a 90 MB model.
- **D-8 Loud degradation.** When `sentence-transformers` or `sqlite-vec` is missing,
  `session-maint embed` exits 1 with the install line (`uv tool install
  'agent-session-tools[semantic]'`), the doctor reports `info` ("semantic layer not installed;
  0 vectors") rather than `fail`, and `retrieval.search` is unaffected (mode stays `lexical`).
  `sqlite-vec` moves into the `semantic` extra.
- **D-9 Owner gate mechanics.** Migrations run automatically on every export, context write
  and scrub (`export_sessions.py:140`, `context/records.py:45`, `mcp_server.py:642`), so the
  gate is not a flag: the live tools are a pinned production wheel
  (`~/.local/share/sessionweaver/production-pins/fb606468`, installed 2026-09-07), and every
  measurement path opens the database `?mode=ro`. Migration 48 reaches
  `~/.config/studyloop/sessions.db` only when the owner installs a new pin or runs a repo
  checkout tool against it. Stage 3 rehearses on a `VACUUM INTO` clone; the live schema
  migration and the live backfill are the owner's call, and the backfill should wait for
  Stage 4's model choice (51,742 messages: ~8 min for MiniLM-L6-v2 with chunking, ~4× for mpnet).
  **Council correction (astra 9):** the pin is the *mechanism* that keeps migration 48 off the
  live database, not the authorization. The authorization is the owner's explicit go, recorded
  in the Stage 3/4 record, before a pin that carries migration 48 is installed or any checkout
  tool is pointed at the live file. Provenance of the five entry points and the pin is in
  `stage3-alignment-clone-addendum.json`.

## Contracts (Lane B owns the implementations; Lane C codes against these names)

```python
# agent_session_tools/embedding_store.py
class Encoder(Protocol):          # injected in tests; real one wraps sentence-transformers
    name: str; dim: int; max_tokens: int
    def count_tokens(self, text: str) -> int: ...
    def encode(self, texts: Sequence[str]) -> list[bytes]   # float32 little-endian, len == dim*4

@dataclass(frozen=True) class Availability: ready: bool; model_ok: bool; extension_ok: bool; reason: str
def availability(model: str | None = None) -> Availability   # never downloads
def chunk_text(text: str, encoder: Encoder) -> list[tuple[str, bool]]  # (chunk, truncated)
@dataclass(frozen=True) class EmbedStats: model: str; dim: int; embedded_messages: int; chunks_written: int; skipped_changed: int; remaining: int; seconds: float
def embed(conn, *, model: str | None = None, encoder: Encoder | None = None,
          budget_seconds: float | None = None, batch_size: int = 64, replace_model: bool = False) -> EmbedStats
def sidecar_path(db_path: Path) -> Path
def ensure_index(conn, *, model: str, dim: int) -> None       # loads sqlite-vec, ATTACHes the sidecar, creates vec0 if absent
def reconcile(conn) -> tuple[int, int]                        # (inserted, deleted) vs message_embeddings
def knn(conn, vector: bytes, n: int) -> list[tuple[str, int, float]]   # (message_id, chunk_ix, distance)
```

CLI (`maintenance.py`, mirrors `fts-check`): `session-maint embed [--db] [--model] [--budget-seconds]
[--batch-size] [--replace-model]` and `session-maint embed-check [--db] [--fix]` (prints the
`AlignmentReport`; `--fix` = `sweep()` + `reconcile()`; exit 1 while not aligned).

Doctor (`studyloop/doctor/database.py`, Lane C): check id **`embeddings_alignment`**
(category `database`). `pass` when `report.complete`; `warn` when only `missing > 0` (remedy
`session-maint embed`, `fix_auto=False` — needs the model); `fail` when any of orphaned / stale /
model_mismatch / hidden > 0 (remedy `session-maint embed-check --fix`, `fix_auto=True`, applied in
`cli/_doctor.py` via `sweep()` + `reconcile()` when the extension loads, `sweep()` alone otherwise);
`info` when the semantic extra is not installed and `rows == 0`. Config keys
(`config_loader.py` `semantic_search`): `model`, `min_content_length`, `auto_embed`,
`auto_embed_budget_seconds` (new, default 20). `fts_weight`/`semantic_weight` stay until Stage 4
pre-registers the fusion and deletes them.

## Lifecycle tests (Lane A, `tests/test_embedding_lifecycle.py`) — one per lane-C §1 path

| path | drive it through | assert |
|---|---|---|
| export add | `exporters/base.py` `commit_batch` | new message → `missing` +1, no vectors |
| export update | `commit_batch` upsert with changed content | vectors gone in the same transaction; hash mismatch never observable |
| export identity shift | `_preserve_message_identity` re-key | no orphan; old id's vectors gone or moved |
| dedup merge | `deduplication` merge of a legacy duplicate | vectors preserved, `orphaned == 0` |
| scrub | `mcp_server.session_clean(dry_run=False)` | the scrubbed message's vectors are gone **in the same transaction** as the `scrub_log` row |
| purge | `context/lifecycle.purge_session` | vectors gone; `PRAGMA foreign_key_check` empty |
| prune_hot with vectors | hot + full DBs, vectors only in hot | eviction still happens; `_archive_context_complete` true |
| compact | `compact_database` on a DB with vectors | rows copied, no orphans, plain connection |
| hidden source | seed a retired-source session | `eligible` excludes it; `sweep()` removes its rows |

## Gates (freeze §5 style; the record reports each with the receipt field)

- `AlignmentReport` after `embed` on the **clone**: `missing 0 / orphaned 0 / stale 0 /
  model_mismatch 0 / hidden 0` — receipt `stage3-alignment-clone.json` (model, counts, chunks,
  seconds, sidecar bytes, `reconcile` deltas). Model for the rehearsal: `all-MiniLM-L6-v2`
  (fastest measured; Stage 4 picks the shipped one).
- Every lifecycle test above green; `prune_hot` evicts with vectors present.
- `ruff`, `ruff format --check`, `pyright` clean; full `agent-session-tools` suite green;
  `studyloop` suite: doctor tests green, whole suite compared with a matched control.
- No write to `~/.config/studyloop/sessions.db` (mtime and `PRAGMA user_version = 47` recorded
  before and after the stage).

## Open for the council

1. D-2 sidecar vs in-database index — the guarantees are the same; is anything lost (backup
   discipline: the sidecar is not backed up with the DB — by design, it is derived)?
2. D-9 — is "the pin is the gate" an acceptable reading of "owner-gated migration"?
3. Live backfill timing (after Stage 4's model choice) vs embedding now with MiniLM and
   re-embedding later.
