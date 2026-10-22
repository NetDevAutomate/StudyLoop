# ADR-0017: Age-based `delete` keeps sessions that own learner records; `--forget-learner-records` destroys them through the tombstone path

**Status:** Proposed · **Date:** 2026-10-22 · **Deciders:** council pass 3 of the 2026-10-21
full-repository review (five no-tool seats: kimi-k3, gpt-6-astra, grok-4.6, deepseek-r1,
mistral-large-3), arbitrated by argument by the review coordinator under the owner's standing
delegation; Andy Taylor (owner) has not yet reviewed. Accepted when the owner has read this record
and the arbitration; the release-consistency check refuses a tagged release that still says
Proposed. · **Change:** 2026-10-22 council pass 3, ruling D5 (4–1); implemented in `1f171b62`,
merge `85e4a072` (lane G, `maintenance-contracts`).

The council record (`reviews/2026-10-21-full-repo-review/`, gitignored, owner's machine only)
holds the seat transcripts; everything this record relies on is restated here. Symbols were read
at `309074c7` in `packages/agent-session-tools/src/agent_session_tools/`.

## Context

`session-maint delete --days N --confirm` deletes sessions older than N days. Some of those
sessions are **anchors for learner records**: `study_sessions`, `teach_back_scores` and
`parked_topics` reference them. Before the 2026-10-21 review, a bare `DELETE` with foreign keys
off left those rows pointing at nothing (plain `REFERENCES`) or detached them (`ON DELETE SET
NULL`); either way the learner's progress lost its session. The review's lane 4 made
`_delete_old` call `_without_learner_anchors`, which drops every anchored session from the
deletion set and prints `Kept N session(s) that own learner records.`

That left a CLI describing itself falsely: `--days N` still read as "delete sessions older than
N days" while the command silently kept some of them. The brief called the keep "silent"; one
seat corrected that (the count *is* printed), which located the defect precisely: the help text
and the summary, not the behaviour.

One more fact was corrected during implementation. The coordinator's arbitration first read the
`ON DELETE CASCADE` clauses in `migrations.py` as belonging to the learner tables; lane G showed
they belong to **session** tables (`session_tags`, `session_notes`, `session_embeddings`,
`session_learning_metadata`), and the learner anchors are plain `REFERENCES` or `SET NULL`. So
the pre-fix harm was orphaning, as the original brief said. The correction strengthened the
ruling: the override must destroy learner rows **deliberately and visibly**, never by letting a
cascade do it in silence.

## Decision

Safe default, explicit force flag, honest text, in the `rm`/`rm -f`, `git branch -d`/`-D` shape.

- **Default keeps anchored sessions** and says so: the `--days` help text names the keep; the
  final summary reports kept versus deleted counts and names the flag that would delete them.
- **`--forget-learner-records`** deletes anchored sessions **and** their learner rows, through
  `context.lifecycle.purge_session(conn, session_id, permanent=True)`, the existing tombstone
  path, so the next export cannot resurrect a deleted session. It lists what it destroyed by table
  and still requires `--confirm`. It never runs a bare cascade with foreign keys off.
- On a pre-lifecycle schema (`user_version < 41`) the flag **refuses** rather than falling back to
  a bare delete, because `purge_session` is what makes "permanent" true.

Grounding adopted: safe default plus a named force flag (Unix and git convention), and the
brief's own rule that a destructive CLI must not describe itself falsely.

## Alternatives considered

- **(a) Keep the implicit safe default; only make it visible.** Half of what was taken. Alone it
  leaves a learner who genuinely wants to forget everything older than N days with no honest way
  to do it.
- **(c) Make the keep opt-in (`--keep-learner-records`), restoring the literal meaning of
  `--days N`.** Rejected 4–1: it makes the destructive reading the default. One seat preferred it
  without an argument beyond literalness; the harm demonstrated by the pre-fix code is the answer.

## Consequences

- A default `delete --days N` can leave sessions older than N days in the database. The summary
  says which and why; this is the intended behaviour, not a bug to file.
- `--forget-learner-records` is the only path that destroys learner progress, and it goes through
  the tombstone, so an "I deleted it and it came back on the next export" report cannot arise
  from this command.
- On old-schema databases the flag is unavailable until the migration runs. Separately, a pre-41
  `delete` without the flag writes **no tombstone**, so an old-schema deletion can be re-imported
  by the next export; refusing would break a dozen existing tests. That is an **owner decision**
  recorded in the review ledger, not taken here.
- `maintenance.py` now has the learner-row counting helper (`purge_session` destroys, counted by
  table) beside `_without_learner_anchors`; both read the same anchor tables, so a new learner
  table must be added to both.

## Verification

`packages/agent-session-tools/tests/test_maintenance_delete_contract.py`: a default run keeps
anchored sessions and the summary names the flag; with the flag they are gone, the tombstone
exists and the learner rows went with their session; without `--confirm` nothing happens either
way; `PRAGMA foreign_key_check` is clean after both; on a pre-lifecycle schema the flag refuses.
Coordinator probe on the lane tree, built from the lane's own fixtures on a current-schema
database: each of those outcomes observed directly.
