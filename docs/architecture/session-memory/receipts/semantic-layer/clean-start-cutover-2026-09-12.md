# Clean-start cutover — 2026-09-12

Receipt for the replacement of the live `~/.config/studyloop/sessions.db`
with a filtered rebuild. Numbers here were read from the databases at the
time; nothing is estimated.

## Owner decision

> "Clean start now, archive cold, decide deletion later -- not today."
> — Andy, 2026-09-12 19:30 BST

Filter level chosen 20:12 BST: **C — real conversations, six harnesses**
(session source in {claude_code, kiro_cli, codex, opencode, pi, grok} AND the
session contains ≥1 `human` message; within kept sessions keep only `human`
and `prose` kinds). Deletion review date for the archive: **2026-12-12**.

## Why

`session-maint corpus-audit` on the live file (commit `3ddd10db`):

| kind | rows | share |
|---|---:|---:|
| tool_echo | 75,529 | 52.5% |
| prose | 42,359 | 29.4% |
| stub | 7,238 | 5.0% |
| injected | 7,021 | 4.9% |
| human | 5,345 | 3.7% |
| proxy_probe | 3,918 | 2.7% |
| brief | 1,695 | 1.2% |
| ack + other | 868 | 0.6% |

3,373 of 5,880 sessions contained no human turn. The learning tier held three
rows in total. Native Claude Code transcripts before 2026-07-10 no longer
exist on disk, so the old file is the only copy of ~2,750 of those sessions —
hence archive, not delete.

## What was built

`session-maint clean-start --dest ~/.config/studyloop/sessions.clean.db --yes`
(commits `1990ffa7`, `5dd5bf24`, `3160188f`), 3m19s:

```
sessions : keep 1,477 of 5,880
messages : keep 27,491 of 143,973   (human 4,176 · prose 23,315)
context_evidence 51,706 (of 109,978) · native links 5,565 · receipts regenerated 51,706
carried DDL (absent from migration): study_plans, study_plan_checkpoints,
  card_reviews, review_sessions, context_concept_{clock,events,schema}, context_concepts
rebuilt/empty: message_embeddings, all *_fts, ontology_* (no writer on main)
fk_check 0 · FTS rows = messages · integrity_check ok · user_version 48 · 415 MB
```

Post-swap audit of the new file: 100% learner-kind, 0 sessions without a
human turn, sources = the six harnesses only.

Two defects the live run exposed that the fixture suite could not (the reason
a source-vs-dest count follows every integrity assert): `init_db` does not
create `study_plans` / `context_concept*`, so the copy silently moved 0 rows
with FK check green; and a `NULL` session pointer on `study_sessions` was
read as "dropped". Both fixed in `5dd5bf24`.

## Cutover sequence (20:45–20:47 BST)

1. `PRAGMA wal_checkpoint(TRUNCATE)` on the old file → `(0, 0, 0)`.
2. `archive_source()` moved `sessions.db` (+`-wal`, `-shm`) to
   `~/.config/studyloop/archive/sessions-archived-20260912.db` and wrote
   `archive/README.md` with the review date.
3. Moved the derived sidecars belonging to the old rows:
   `sessions.vec.db` → `archive/sessions.vec-archived-20260912.db`,
   `explorer_fts.db` → `archive/explorer_fts-archived-20260912.db`.
4. `mv sessions.clean.db sessions.db`.
5. Pinned tool (`~/.local/bin/session-query`, `studyloop struggles`) read the
   new file correctly. Pinned `CURRENT_VERSION` is 48 — the Stage 5 "pin at
   47, capture broken" state recorded on 2026-09-11 has already been
   remedied; `export-hook.log` shows the hook running and auto-embedding.
6. `session-maint embed --model bge-small-en-v1.5 --batch-size 128` started
   on the new file (log: `~/.config/studyloop/clean-start-embed.log`).

## Known follow-ups

- A `studyloop-mcp` process serving a Codex session held the OLD inode open
  through the swap. Open descriptors follow the inode, so neither file was
  at risk, but that process reads the archived data until its session
  restarts.
- Every retrieval receipt under `receipts/semantic-layer/` was measured on
  the old corpus and does not transfer. Re-baseline on the new file before
  the SEALED run.
- `~/.config/studyloop/` still holds ~4.5 GB of `*.bak` / `*.repair-*` files
  from 2026-09-02..06. Listed, not deleted (Stage 5 item 2.5).
- Not yet done from the plan: classifier at `session-export` ingest; derived
  struggle writer (A); mentor writer tools across six harnesses (B); doctor
  `corpus_composition` check.
