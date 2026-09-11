# Lane C — Data lifecycle and alignment semantics of the sessions DB (`main`)

Read-only investigation. All paths under
`packages/agent-session-tools/src/agent_session_tools/` unless stated.

**Headline:** an embeddings layer already exists and is wired into the *destructive*
paths but not the *mutating* ones. `message_embeddings` / `session_embeddings` were
added by migration 7 (`migrations.py:373-402`) and are currently **empty (0 rows)**.
They are swept on purge and prune, but nothing invalidates them when message content
is rewritten, and nothing recomputes them. Two latent blockers are recorded in §4 and
§7.

## 1. Write paths and how the FTS index is kept aligned

FTS is `messages_fts` (`schema.sql:33-39`), a **standalone** (not
`content=`-external) FTS5 table, kept aligned by three triggers:
`messages_fts_insert` (`schema.sql:42-47`), `messages_fts_update`
(`schema.sql:49-57`, reinstalled with NULL-transition handling by
`migrations.py:49-60`), `messages_fts_delete` (`schema.sql:59-62`).

| Path | Code | What changes | FTS alignment | Embeddings alignment |
|---|---|---|---|---|
| Export add | `exporters/base.py:56` `commit_batch`; session upsert `base.py:114-131`, message upsert `base.py:157-176` | INSERT sessions/messages | `messages_fts_insert` trigger | **none** — no hook |
| Export update | same upserts, `ON CONFLICT(id) DO UPDATE SET role, content, model, timestamp, metadata, seq` (`base.py:167-175`) | `messages.content` rewritten in place, id unchanged | `messages_fts_update` trigger | **none — vector goes stale silently** |
| Export identity shift | `_preserve_message_identity` (`base.py:267-321`) | a positional id whose stored content differs is re-keyed to `<id>-rev-<sha256[:24]>`, original recorded as `metadata.source_record_id` | insert trigger on the new row | new id ⇒ **old row's embedding orphaned** |
| Export stale reconcile | `base.py:178-204`, guarded by `_message_is_referenced` (`base.py:245-265`) | DELETEs only empty/NULL-content messages absent from the batch | `messages_fts_delete` | FK `ON DELETE CASCADE` (`migrations.py:388`) |
| Dedup merge | `deduplication.py:196` → `_merge_legacy_rows:203`; `UPDATE messages SET session_id` (`:218-224`), `DELETE FROM sessions` (`:281`) | messages reparented, duplicate session row removed | update trigger rewrites `messages_fts.session_id` | `message_embeddings` unaffected (no session_id); duplicate's `session_embeddings` cascades; **primary's session embedding now misrepresents the merged set** |
| Scrub | `mcp_server.py:631` `session_clean`; `UPDATE messages SET content=?` (`:693-695`) + `scrub_log` insert (`:696-701`) | secret text replaced with placeholders | update trigger | **none — the vector still encodes the secret** |
| Retire / hide | `context/scope.py:325-337` (read predicate only) | nothing written | n/a | n/a |
| Delete (session) | `context/lifecycle.py:87` `purge_session`, entry point `forget_session:154` | explicit `DELETE FROM messages_fts WHERE session_id=?` (`:129`) *before* `DELETE FROM messages` (`:130`) — deliberately also sweeps orphans left by legacy `INSERT OR REPLACE`; `session_embeddings` in the explicit child list (`:138`); `DELETE FROM sessions` (`:141`) | explicit DELETE + trigger | `session_embeddings` explicit; `message_embeddings` by FK cascade (requires `foreign_keys=ON`, asserted `:88-93`, verified by `PRAGMA foreign_key_check` `:145-149`) |
| Compact (canonical) | `context/lifecycle.py:225` | full rebuild | `DELETE FROM messages_fts` + reinsert from `messages` (`:240-244`) — *not* FTS5 `('rebuild')`, which would preserve orphans | **explicit orphan sweeps**: `:248-250` and `:251-253`. The only existing embedding-alignment precedent, and it is a sweep, not a recompute |
| Prune (hot tier) | `tiering.py:654` `prune_hot`; CLI `session-maint prune` (`maintenance.py:874`) | modern path calls `purge_session(..., permanent=False)` inside `eviction()`; legacy path `_prune_legacy_rows` (`tiering.py:880-900`) | via `purge_session` / message DELETE trigger | legacy path uses `_dependent_tables` = dynamic FK discovery ∪ `_MESSAGE_CHILD_TABLES` / `_SESSION_CHILD_TABLES` (`tiering.py:50-51`), which **already name both embedding tables** |
| Sync to full DB | `tiering.py:435` `sync_to_full`; `_SYNCED_TABLES` (`:56`) | changed sessions' messages deleted then recopied | destination triggers (`:490-495`) | **deliberately excluded**: "Embeddings are derived data and deliberately NOT synced" (`tiering.py:53-55`) |
| Sync-in (cross machine) | `sync.py` SQL delta over SSH; `SYNC_TABLES` (`:34-41`), `GLOBAL_SYNC_TABLES` (`:44-55`) | row-level upserts | `_FTS_REPAIR_SQL` appended to **every** import (`sync.py:947-960`): wholesale DELETE + reinsert from `messages` | not synced, not repaired |
| Replication | `replication/snapshot.py:29-56` `TABLES = NATIVE + records.TABLES + CONTEXT` | row-level object transfer | n/a (rebuilt locally) | not in `TABLES` |
| Repair | `repair.py`, `session-repair` (`pyproject.toml:47`); `SESSION_COLUMNS`/`MESSAGE_COLUMNS` (`repair.py:25-43`) | re-reads native transcripts into a disposable snapshot, then applies | via triggers | not considered |
| Migration backfill | `@migration` decorator (`migrations.py:22-29`), `CURRENT_VERSION = 47` (`:16`), whole sequence in one `BEGIN IMMEDIATE`, `PRAGMA_ONLY_VERSIONS` (`:71`); legacy convergence in `export_sessions.py:65-112` | DDL + backfill | migration 8 dropped conflicting legacy triggers (`migrations.py:~443`) | migration 7 created the tables with FK CASCADE |

**The gap in one line:** every path that *deletes* is covered; the three paths that
*mutate content in place* (export update, dedup merge, scrub) realign FTS via trigger
and leave embeddings stale with no detectable signal.

## 2. Identity

- **Session** — `sessions.id TEXT PRIMARY KEY` (`schema.sql:4`), harness-supplied.
  Stable across re-export (upsert on id) and across machines: the temp trigger
  `sync_session_identity` aborts an import whose `id` arrives with a different
  `source` (`sync.py:~988-991`).
- **Message** — `messages.id TEXT PRIMARY KEY` (`schema.sql:18`). Cross-session
  collision is refused twice: `commit_batch` (`base.py:139-155`) and
  `sync_message_identity` (`sync.py:~984-987`). `sync_content_conflict`
  (`sync.py:~992-995`) records an id when both sides hold differing non-empty content
  rather than silently picking a winner.
- **`rowid` is not an identity.** `messages_fts` joins on `rowid`
  (`query_logic.py:88-90`), and `compact_database` copies the column intersection
  only (`tiering.py:281-305`), so rowids are reassigned in a compacted DB. An
  embeddings table must key on the TEXT `message_id`, as migration 7 already does.
- **There is no usable per-message content hash.** `messages.content_hash` and
  `sessions.content_hash` exist (`migrations.py:206-216`) but **nothing writes them** —
  `commit_batch`'s insert column list omits `content_hash` (`base.py:157-166`), and
  measured population is 0 / 143,908 and 0 / 5,879. Only the per-file
  `import_fingerprint` (`mtime:size`) is populated, used by each exporter's skip check
  (`exporters/claude.py:97`, `codex.py:188`, `grok.py:48`, `kiro.py:230`).
  ⇒ An embeddings table must carry **its own `content_sha256` of the text it
  embedded**. That is self-contained; reviving `messages.content_hash` instead would
  change a path every harness runs through.

## 3. Hidden vs deleted

**Hidden** is a read predicate, appended last so its placeholders bind after the
project-scope ones (`context/scope.py:325-337`):

```sql
AND EXISTS (SELECT 1 FROM main.sessions scoped_src
            WHERE scoped_src.id = <session_col>
              AND scoped_src.source IN (<admitted…>))
```

`admitted` = `sources.SUPPORTED_SOURCES` (`sources.py:41-45`), *derived* from
`EXPORTERS` source names ∪ `{study_mentor}` — so a harness cannot be registered and
forgotten here. Hidden rows are reachable only by earning it:
`visibility_sql(..., include_retired_sources=True)` (`scope.py:342-373`), used by
explicit forget and by replication ("carries history rather than returning it",
`scope.py:227-233`). `sources.py:1-20` records the ruling: retired-label rows are
"hidden at product read paths and never deleted".

**Deleted** happens only in `context/lifecycle.py:purge_session` (via
`forget_session`, or eviction from `prune_hot`).

**'Prune' today** = `session-maint prune` → `tiering.prune_hot` (`tiering.py:654`):
evict hot sessions older than a cutoff **only after** proving they exist in the full
DB — id present, content_hash equal, full message count ≥ hot count
(`tiering.py:735-745`), plus for modern schemas `_archive_context_complete`
(`tiering.py:705`) and a row-level `EXCEPT` comparison. Sessions owning learner
records are never candidates (`tiering.py:718-724`). The `content_hash` equality term
is vacuous today (both sides NULL ⇒ `'' = ''`), so the message-count and `EXCEPT`
comparisons are the real gates.

## 4. Cross-machine sync — and the blocker

Two distinct mechanisms, **both row-level, neither file-level**:

1. `session-sync` (`sync.py`) streams SQL `INSERT`/upsert deltas over SSH
   (`sync.py:1-5`), table-scoped by `SYNC_TABLES` / `GLOBAL_SYNC_TABLES`, with
   identity/conflict temp triggers and `_FTS_REPAIR_SQL` appended to every import.
2. `replication/` transfers scope-checked object closures (`snapshot.py:TABLES`,
   `content.py`), refusing divergent rows rather than claiming convergence
   (`content.py:1-4`).

The DB file itself does **not** travel, so an embeddings table needs its own rules:
either replicate it (then model + dimension must be pinned per row and agreed
between machines) or **regenerate locally** — which is what the codebase already
decided for the existing tables (`tiering.py:53-55`). Regenerate-locally is the
cheaper and safer default: it makes model choice a per-machine concern and removes
dimension negotiation entirely. `model` is already stored per row
(`migrations.py:385`, `396`) but the *dimension* is not; `embeddings.py` derives it
from `SUPPORTED_MODELS` at read time (`embeddings.py:266-277`) and
`cosine_similarity` (`embeddings.py:300-324`) would happily compare two different
dimensions' bytes via `np.frombuffer`. A dimension column, or a rejection of rows
whose `model` differs from the configured one, is required.

**Blocker (latent, currently masked by 0 rows):** `_archive_context_complete`
requires `message_embeddings` and `session_embeddings` to be present **and
row-identical** in the full DB before eviction is permitted
(`tiering.py:850-860`), yet `_SYNCED_TABLES` (`tiering.py:56`) never copies them
there. The moment embeddings are populated in the hot DB, that `EXCEPT` returns a
row, `verified` is emptied (`tiering.py:786-789`), and **`prune_hot` silently stops
evicting anything**. Both tables are empty today, so the comparison passes trivially
and the contradiction is invisible.

## 5. Doctor — the pattern to mirror

`packages/studyloop/src/studyloop/doctor/database.py:226-266` `_check_fts_drift`:
compare `COUNT(*) FROM messages WHERE content IS NOT NULL` against
`COUNT(*) FROM messages_fts`; `OperationalError` ⇒ fresh DB, return no checks;
`drift == 0` ⇒ pass; else severity `fail` when `abs(drift) > max(100, messages // 10)`
else `warn`, remedy string `session-maint fts-check --fix`, `fix_auto=True`.
`packages/studyloop/src/studyloop/cli/_doctor.py:230-243` honours it by calling
`tiering.repair_fts` directly. The check id is **`sessions_fts`** while the table is
`messages_fts` (`database.py:247`, `:260`) — a pre-existing naming mismatch to avoid
copying. A sibling `legacy-sources` check reports retired-source counts as `info`
(`database.py:~180-224`).

The invariant is documented as first-class in `tiering.py:23-24`, with
`fts_integrity` (`tiering.py:311-325`) / `repair_fts` (`tiering.py:327-345`) as the
check/repair pair and `session-maint fts-check --fix` (`maintenance.py:739-777`) as
the CLI. The embeddings mirror needs **three** counts, not one, because a vector
index has a state FTS cannot have: missing (eligible message, no embedding row),
orphaned (`message_id` gone), and **stale** (`content_sha256` ≠ hash of current
content). Only the first two are sweep-repairable; the third needs re-embedding, so
`repair_embeddings` cannot be a pure-SQL analogue of `repair_fts`, and must no-op
when `sentence-transformers` is absent (`embeddings.py:123-133`).

## Numbers measured

Live DB opened read-only (`file:$HOME/.config/studyloop/sessions.db?mode=ro`),
2026-09-10:

| Metric | Value |
|---|---|
| `PRAGMA user_version` | 47 (= `CURRENT_VERSION`, `migrations.py:16`) |
| Sessions | 5,879 |
| Messages | 143,908 (all with non-NULL content) |
| `messages_fts` rows | 143,908 — **drift 0, index aligned** |
| Distinct `source` values | 14 |
| Retired-source sessions | **1,279** = repoprompt 440, aider 422, kilocode_cli 131, litellm-proxy 124, gemini_cli 87, bedrock_proxy 71, omp 4 |
| Admitted-source sessions | 4,600 = claude_code 3,603, kiro_cli 614, codex 307, grok 53, opencode 14, study_mentor 6, pi 3 |
| `messages.content_hash` non-NULL | **0** of 143,908 |
| `sessions.content_hash` non-NULL | **0** of 5,879 |
| `messages.seq` non-NULL | 143,230 of 143,908 |
| `message_embeddings` / `session_embeddings` rows | **0 / 0** (orphans 0 / 0) |
| DB size | 1,067,790,336 B main (≈1.02 GiB) + 267,651,712 B WAL |

## Open questions

1. **`_archive_context_complete` vs `_SYNCED_TABLES`** (§4) — does populating
   embeddings deliberately block `prune_hot`, or is including them in the retention
   proof an oversight? Decide *before* any backfill; the fix is one of: exclude
   embeddings from the proof, or add them to `_SYNCED_TABLES`.
2. **Scrub ordering** — should `session_clean` invalidate affected embedding rows in
   the same transaction, or is a doctor-detected stale count acceptable? A vector
   encoding a redacted secret is arguably an egress issue, not just drift.
3. **Reuse or replace migration 7?** The tables exist, are empty, and lack
   `content_sha256` and a dimension column. `_reconcile_legacy_base_tables`
   (`export_sessions.py:65-112`) cannot add NOT NULL to a populated table — moot at
   0 rows, so now is the cheap moment.
4. **`session_embeddings` is absent from the dedup protected-table list**
   (`deduplication.py:167-181`) — should a session vector block a physical merge, or
   just be recomputed after one?
5. **Does `_preserve_message_identity`'s `-rev-` re-keying fire in practice?** If so
   it orphans embeddings on ordinary re-export, caught only at compact time.
6. **`repair.py` and `sync.py` have no embeddings awareness** — is "regenerate
   locally, never transport" the ruling for both, matching `tiering.py:53-55`?
