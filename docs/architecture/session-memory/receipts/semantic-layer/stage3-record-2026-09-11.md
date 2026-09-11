# Stage 3 record — embedding substrate, aligned by construction

**Date:** 2026-09-11 · **Design:** `stage3-design-2026-09-11.md` · **Commits:** `8b05f645`
(migration 48, alignment accounting, tiering fix, retirement), `c336f27d` (store, sidecar index,
CLI, doctor, export hook), lifecycle tests + this record · **Council:** three seats after this
record (addendum at the foot) · **Live DB:** never written — `~/.config/studyloop/sessions.db`
mtime `2026-09-11 18:01:17` and `PRAGMA user_version = 47` before and after every step.

## What shipped

`message_embeddings(message_id, chunk_ix)` with `model`, `dim`, `content_sha256`, `truncated`;
two triggers on `messages` that touch only that table; no session vectors. `embedding_alignment`
counts missing / orphaned / stale / model_mismatch / hidden and sweeps everything but the backlog.
`embedding_store` chunks by the model's tokenizer without truncation, encodes outside any
transaction, re-reads and hashes inside `BEGIN IMMEDIATE`, keeps the `vec0` index in a sidecar
(`<stem>.vec.db`) reconciled from the table, and returns raw KNN candidates for the caller to
filter under the visibility predicate. `session-maint embed` / `embed-check --fix`; doctor
`embeddings_alignment`; `session-export` tops the index up under a 20 s budget, offline, only
when the model is already cached. The dead migration-7 layer (`semantic_search.py`, the storage
half of `embeddings.py`, 1,174 lines, zero callers) is gone.

## Gates (design §"Gates"), measured — `stage3-alignment-clone.json`

| gate | required | measured |
|---|---|---|
| migration 48 on the live-size clone | runs, integrity ok | `0.005 s`; `integrity_check ok`; `foreign_key_check` empty |
| `AlignmentReport` after `embed` on the clone | missing 0 / orphaned 0 / stale 0 / model_mismatch 0 / hidden 0 | **0 / 0 / 0 / 0 / 0**, `complete: true` (`alignment_after_embed`) — eligible **51,742**, embedded 51,742 |
| sidecar reconciled | vec rows == table rows | **174,371 == 174,371**; a second `reconcile()` is `+0 / −0` in 0.53 s |
| lifecycle paths (lane C §1) | one test per path, real code path | **10 tests**, `test_embedding_lifecycle.py`: export add / update / identity shift (`commit_batch`), dedup merge, scrub via `session_clean` (vectors and `scrub_log` never observed apart), purge + `forget_session`, `prune_hot` evicts with hot-only vectors, `compact_database` copies 3 rows with no orphan, hidden source excluded and swept |
| gates | clean | `ruff`, `ruff format --check`, `pyright` (both packages, src + tests) clean; pre-commit green on both commits |
| suites | pass, or every failure matched on a control | `agent-session-tools` **1,823 passed, 4 failed** — the four are `TestDotenvCannotSetTheTestHatch` (sandbox `PermissionError` on `~/.kiro/crew/.env`; they pass in CI, which is the owner's push to confirm). `studyloop` **3,972 passed, 18 failed, 14 errors** in this sandbox; **all 32** failing ids re-run with production code shadowed to `c949331f` fail identically (addendum receipt `studyloop_matched_control.identical: true`) |
| live DB untouched | yes | mtime and `user_version` unchanged (receipt `clone.live_user_version_before_and_after`) |

## The rehearsal, honestly

`session-maint embed --model all-MiniLM-L6-v2 --batch-size 128` on the clone (MPS): **51,742
messages → 174,371 chunks, 3,008 hard-windowed, 476.9 s** (108 msg/s, 366 chunks/s). Sidecar
**291.9 MB (278.3 MiB)**; `sessions.db` grew 1,055.6 → 1,424.2 MB (addendum `clone_checks`). Stage 1 projected 75.8 MB for one vector per
message; chunking without truncation costs 3.4× that.

**First attempt crawled at 6 chunks/s** and was stopped. Cause, measured: the `(model, dim)`
index the migration created made the planner probe it inside the correlated `NOT EXISTS` of the
backlog query instead of the primary key — the missing-count query took **289 s with the index,
0.19 s without**; `alignment_report` 271 s vs 0.63 s. The index served no lookup (every lookup is
by `message_id`, covered by the PK; the mismatch count is an inequality scan), so migration 48
now drops it — removed after the first clone attempt, before any production database ran the
migration (receipt `first_attempt`; the live table still has migration 7's columns, addendum
`live_database_at_addendum`).

**The long tail.** 39,863 messages (77 %) are one chunk; 1,239 messages (2.4 %) have more than
20 chunks and hold **45.6 %** of all chunks; 155 messages (0.3 %) have more than 100 and hold
20.4 %; the largest single message is **1,099 chunks** (pasted output). `knn(n=20)` over 174,371
384-d vectors: **p50 40.9 ms, p95 42.9 ms** warm (Stage 1: 4.8 ms at 57,247 single vectors —
brute-force `vec0` is linear in rows). A per-message chunk cap would change this: cap 32 keeps
75 % of rows and touches 697 messages; cap 8 keeps 56 % and touches 2,775. D-3 says no
truncation and this record does not change it: a cap is a Stage 4 pre-registration question
(it trades tail recall on pasted blobs for latency), and the Stage 4 latency gate as written
("p95 ≤ Stage 1 measurement + 50 ms") was measured on single vectors, so the council is asked
below whether the gate's baseline or the substrate should move.

## Deferred, with reason

- Live migration and live backfill: owner-gated (D-9 — the pin is the gate). Recommendation
  unchanged: migrate when the next pin is installed; backfill after Stage 4 picks the model
  (this rehearsal is ~8 min for MiniLM; mpnet would be ~4× and 768-d).
- Chunk cap / tail policy: Stage 4 (above).
- `transformers` logs one "Token indices sequence length is longer…" warning per over-cap
  message during token counting (the count is what decides the split). Cosmetic; silence it in
  Stage 4 with the tokenizer's `verbose=False`.

## What Stage 4 inherits

`embedding_store.knn` + `embedding_alignment.eligible_predicate` are the semantic arm's two
calls; `retrieval.search` gains the fusion (pre-registered first), applies the same visibility
predicate and self-exclusion to KNN candidates as to FTS rows, and `RetrievalStatus.mode`
becomes `"hybrid"` only when Stage 4 establishes lift on SEALED. Clones for the bake-off come
from `VACUUM INTO` + `session-maint embed --model <candidate>`; ~8 min each for 384-d models.

## Questions for the council

1. D-2 sidecar index (`<stem>.vec.db`, disposable, reconciled): anything lost versus
   in-database?
2. D-9: is "the production pin is the gate" an honest reading of "owner-gated migration"?
3. The tail: keep D-3's no-truncation substrate and let Stage 4 pre-register a cap, or cap now?
4. Is anything in this record not supported by `stage3-alignment-clone.json` and the tests?

## Council addendum — three seats, 2026-09-11 21:49

Brief 33.7 KB (design, record, receipt, migration 48 source, `embed()`/`_write_batch()` source).
A first launch went out with an empty migration section by mistake and was superseded; the
reviews below are from the complete brief (the superseded files were overwritten by it).
Verdicts: **astra REJECT** (1 BLOCKING, 8 MAJOR, 1 MINOR) · **kimi-k2-thinking
ACCEPT-WITH-CORRECTIONS** (15 items, mostly code the brief did not quote) · **qwen3-coder
ACCEPT**. Every BLOCKING/MAJOR verified at source before acting.

| seat / id | sev. | finding | disposition |
|---|---|---|---|
| astra 1 | BLOCKING | `UPDATE messages SET id=…, content=…` with `foreign_keys=ON`: the FK cascade moves rows to `new.id` before the AFTER trigger deletes by `old.id` → old text's vectors survive under the new id | **CONFIRMED at runtime** (`stale=1` under `'b'` with FKs on; clean with FKs off). Fixed: the trigger deletes `WHERE message_id IN (old.id, new.id)`; test with FKs on and off |
| astra 2 | MAJOR | the write re-checks the hash, not eligibility: a source retired / session moved / role changed between candidate selection and the lock is still written; `embed()` swept only on model mismatch | **CONFIRMED.** `_write_batch` now re-reads through `messages JOIN sessions` under the full eligibility predicate inside `BEGIN IMMEDIATE`; `embed()` sweeps orphaned/stale/hidden unconditionally (another model's rows still only with `--replace-model`). Tests: source retired in `_after_encode` → 0 rows, `hidden 0`; planted orphan/stale/hidden → `swept 3`, report complete |
| astra 3 | MAJOR | replay: `DROP TABLE IF EXISTS session_embeddings` ran unconditionally when the message table was already aligned | **CONFIRMED by reading.** The session-table row check now runs on every migration run; test: aligned message table + one legacy session row → refuses, both tables intact |
| astra 4 | MAJOR | `owns_transaction = not conn.in_transaction` lets an ambient transaction bypass `BEGIN IMMEDIATE` and hold a lock through inference | **CONFIRMED.** `embed()` refuses a connection with an open transaction; `_write_batch` always owns its transaction. Test added |
| astra 5 | MAJOR | sidecar freshness and hidden-result guarantees unverified; raw `knn` may name scrubbed/deleted/retired rows | **ACCEPTED**: `embedding_store.candidates()` joins every KNN key to its canonical `message_embeddings` row (same message and chunk) and to `messages`/`sessions` under the eligibility predicate, over-fetching ×4. Test: scrub, delete and retire three of four neighbours without reconciling — raw `knn` names all four, `candidates` returns only the live visible one. This is the call Stage 4's fusion uses; "never returned" is scoped to it |
| astra 6 | MAJOR | numbers without receipt fields; MB/MiB; "before it reached any database" | **ACCEPTED** → `stage3-alignment-clone-addendum.json` (immutable original kept): `integrity_check ok`, `foreign_key_check` 0 rows, source bytes 1,055,576,064 via a fresh `VACUUM INTO`, full per-message chunk histogram, group totals (>20 chunks: 1,239 messages / 79,455 chunks / 45.6 %; >100: 155 / 35,485 / 20.4 %), cap simulation (4/8/16/32/64), sidecar 291,864,576 B = 291.9 MB = 278.3 MiB; wording corrected above |
| astra 7 | MAJOR | "green" with 4 failures; studyloop matched control for one test only; receipt provenance `c949331f (+ uncommitted)` | **ACCEPTED**: gate row reworded to the actual outcome; all 32 studyloop failures/errors re-run with production code shadowed to `c949331f` — identical set (addendum `studyloop_matched_control`); alignment report re-run on the clone at a named commit (addendum `alignment_report_rerun`, 8.9 s over 174,371 rows, `complete: true`); the store blob hash at the addendum commit is recorded, with the statement that the rehearsal ran the file later committed unchanged in `c336f27d` |
| astra 8 | MAJOR | do not move Stage 4's latency baseline; p50 grew 8.5× for 3.05× rows — not purely linear | **ACCEPTED**: the pre-registered gate stands; the non-linearity is recorded as unexplained (text primary key on `vec0`, chunk rows) and Stage 4 measures end-to-end (encode + over-fetch + filter + fusion) before any cap is proposed as an experiment |
| astra 9 | MAJOR | "the pin is the gate" is procedural; no mtime/WAL evidence of no-write | **ACCEPTED**: addendum `production_tool_provenance` resolves the five entry points as the owner's shell does (`~/.local/bin/* → ~/.local/share/uv/tools/…`, receipt requirement = production pin `fb606468`); `live_database_at_addendum` records db and WAL bytes/mtimes, `user_version 47`, and that the live `message_embeddings` columns are still migration 7's. The WAL was written at 20:13 — by the owner's harness exports (the DB gained 45 messages during this stage); every process of this stage opened it `?mode=ro`. D-9 is reworded in the design: the pin is the mechanism; the owner's explicit go on the live migration and backfill is the authorization |
| astra 10 | MINOR | "before it reached any database" is literally false | **ACCEPTED**, reworded above |
| kimi 4/6 | MAJOR | 51,742 vs Stage 1's 51,729 | **EXPLAINED**: the Stage 1 predicate (`visibility_sql`) and `eligible_predicate()` count **51,742 each** on the live DB at addendum time (addendum `eligibility_predicates_on_live_db`); the delta to 51,729 is corpus growth since 2026-09-10, not a predicate change |
| kimi 1,3,5,7,8,10,11,15 | BLOCKING/MAJOR | `reconcile`, `knn`, `alignment_report`, `sweep`, tiering constants, doctor, hook, pin tooling "absent" | **Brief scope, not code**: all exist in `c336f27d` / `8b05f645` (`embedding_store.py` lines 617–812 and beyond, `embedding_alignment.py`, `tiering.py:50-61`, `doctor/database.py`, `export_sessions.py`); the brief quoted only the migration and the write path. Recorded so the next brief quotes the sidecar and alignment source |
| kimi 9 | BLOCKING | confounded timeline: receipt reports a problem no committed state had | **DECLINED as written, ACCEPTED in substance**: the first attempt is exactly what the record says it is — a pre-commit diagnosis on a clone — and the receipt's `first_attempt` object is kept because deleting failed attempts from the record is the thing this programme does not do |
| kimi 7 | MINOR | migration comment "every lookup is by message_id" imprecise | **ACCEPTED**: the comment names the table's own lookups; `_write_batch` reads `messages`, a different table |
| qwen 9–11 | — | sidecar backups, pin integrity, latency gate open | agree; answered above (backups: derived, not backed up, rebuilt by `reconcile`; pin: provenance recorded; latency: gate stands) |

Stage 3 is **closed on the corrected tree** (commit that adds this addendum), with the live
migration and backfill owner-gated as before.
