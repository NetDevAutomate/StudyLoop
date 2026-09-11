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
| suites | green | `agent-session-tools` **1,823 passed**, 4 failed = `TestDotenvCannotSetTheTestHatch` (sandbox `PermissionError` on `~/.kiro/crew/.env`; pass in CI). `studyloop` 3,972 passed / 18 failed / 14 errors in this sandbox — matched control: the one doctor failure (`test_doctor_second_brain::test_rows_vault_missing_warns`) fails identically on `c949331f`; the rest are tmux, vault-path and dotenv environment classes seen at Stage 2 |
| live DB untouched | yes | mtime and `user_version` unchanged (receipt `clone.live_user_version_before_and_after`) |

## The rehearsal, honestly

`session-maint embed --model all-MiniLM-L6-v2 --batch-size 128` on the clone (MPS): **51,742
messages → 174,371 chunks, 3,008 hard-windowed, 476.9 s** (108 msg/s, 366 chunks/s). Sidecar
**278 MB**; `sessions.db` grew 1,055 → 1,424 MB. Stage 1 projected 75.8 MB for one vector per
message; chunking without truncation costs 3.4× that.

**First attempt crawled at 6 chunks/s** and was stopped. Cause, measured: the `(model, dim)`
index the migration created made the planner probe it inside the correlated `NOT EXISTS` of the
backlog query instead of the primary key — the missing-count query took **289 s with the index,
0.19 s without**; `alignment_report` 271 s vs 0.63 s. The index served no lookup (every lookup is
by `message_id`, covered by the PK; the mismatch count is an inequality scan), so migration 48
now drops it, before it reached any database (receipt `first_attempt`).

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
