# Stage30: what a session note can establish

This stage keeps SQLite and adds a small data-model capability: a report can be
**about a native session** without claiming that the transcript proves the report.
It is part of the open [production contract](../delivery/GOAL.md), not a release.
The five-step runnable walkthrough shows actual CLI and MCP results, including a
conflict that has no automatic winner.

## Why this follows source grounding

Stage29 kept graph labels attached to their owned contributions. Another source of
labels was still mutable: `session-query note` and `tag` edited old tables without
an atomic access check and without preserving the previous meaning. The editor
could stay open while a session changed scope or another process corrected the note.
An old physical deduplication command could also move messages to another session,
breaking the identities used by captured evidence.

Consider a note saying “SQLite was validated everywhere”. The database can establish
that these words were recorded; it cannot infer what was tested, in which revision,
or whether the statement is correct. Like an interface description saying “tested
backup circuit”, it is an operator report until linked to applicable test evidence.

## Three choices considered

| Design | What it adds | What remains difficult | Decision |
|---|---|---|---|
| Guard existing mutable note/tag tables | Smaller patch; scope check and atomic saves | Overwrites still erase the earlier claim and conflict history | Insufficient for the context contract |
| Create separate annotation version tables | Purpose-built note/tag history | Duplicates observation binding, supersession, retirement and query machinery | No demonstrated benefit over reuse |
| Add native-session ownership to existing observations | Reuses immutable reports and correction history; session controls visibility/deletion | Schema39 migration; explicit handling of legacy values and large histories | Implemented |

The new owner is an access and deletion dependency. It is not a captured-input
relationship. An empty session can own a note: the tool creates no fictional message
or evidence row. The returned relationship is `about_session`, the authority is
`reported`, and semantic validation is `not_established`. A model interpretation
still requires actual captured inputs through the separate observation contract.

The reserved annotation kinds require the named session owner. Ownership cannot be
reassigned independently of that parent. Reclassifying the parent changes visibility;
forgetting it removes dependent annotation bodies. This local behavior does not yet
establish transport or managed-restore behavior on other machines.

## What correction means

A command captures the current version set and explicitly supersedes it. It does not
edit the old observation. If two producers have independently recorded current reports,
the MCP result identifies both; a timestamp does not choose the truth. An explicit
`--text` correction names both predecessors. Tags use the visible union as the basis
for an explicit add/remove operation; this is set editing, not semantic arbitration.

Legacy note/tag values are preserved on their first edit as unattributed reported
snapshots. The old note timestamp is retained when available; the new capture timestamp
is not backdated. Original authorship and derivation cannot be reconstructed from a
mutable value. After the transaction succeeds, the mutable shadow is removed so there
is one current versioning mechanism. Legacy learning metadata is readable as an
unattributed report; this stage does not introduce a writer for it.

Forgetting the latest report does not revive an earlier superseded report. Content-free
IDs and retirement markers preserve that instruction. A per-session/kind retirement
also prevents an old mutable shadow from being inserted again. New explicit reports
are still possible; deleting one report is different from forgetting its source session.
If a predecessor was forgotten or is unavailable, each returned version also discloses
`history_incomplete`; a complete page does not imply an intact original history.
The legacy SQL sync does not transport the new observation versions or ownership
tables. It is not a supported way to replicate this increment yet. Full scoped sync,
exporter reimport, indexes and managed restore remain open work.

## The editor transaction

1. Resolve a visible session and read its current version set within a guarded response.
2. Close the connection before opening the private temporary editor file. No database
   writer lock remains while the person is thinking.
3. On save, open a fresh connection and obtain `BEGIN IMMEDIATE`.
4. Compare the version token, full policy, resolved scope, access generation and database
   file identity. A reclassification away and back still changes the generation.
5. Write the correction, check policy/scope again, commit, then print success.

A concurrent correction makes the editor save stale. The command refuses it and removes
the temporary file; it does not silently overwrite the newer version. The current UX
requires reopening and reapplying the intended edit after a conflict. Tests inject
concurrent writes, scope changes during the editor and during the transaction, commit
failure, and cancellation. Failed writes preserve the original legacy value and leave
no half-created observation history. Config is external to SQLite, so this is a final
optimistic policy check, not an atomic lock spanning the filesystem and database.

## Why deduplication cannot move evidence

Text similarity and matching content hashes are candidate signals. They do not prove
that two harness conversations share one origin. Detection now filters scope before
reading message bodies or grouping candidates. Classified sessions and sessions with
owned/provenance/dependent records are protected from physical merge. Auto-merge reports
retained protected groups. The older operation remains available only for legacy
unclassified rows without these dependencies, inside one guarded transaction.

The tests cover missing IDs, duplicate IDs, injected deletion failure, scope change,
classified/owned retention and session IDs containing commas. The grouping code now
uses JSON aggregation to preserve those IDs. Non-destructive grouping of source
identities is not implemented here. No new similarity threshold can substitute for
that identity contract.

## Run the preserved lesson

Use the Stage30 checkpoint in [STAGES.md](../STAGES.md) when comparing historical
behavior. Choose a fresh output directory:

```sh
uv run python -m experiments.evidence_context.session_annotations.runner --output /tmp/stage30-demo
open /tmp/stage30-demo/walkthrough.html
uv run pytest packages/agent-session-tools/tests/test_annotation_commands.py packages/agent-session-tools/tests/test_annotation_migration.py packages/agent-session-tools/tests/test_context_session_owners.py packages/agent-session-tools/tests/test_deduplication.py experiments/evidence_context/tests/test_session_annotation_lesson.py -q
```

The lesson creates only fictional data in its output directory. It invokes the real
note/context/maintenance commands and a real MCP stdio server. These commands are also
available against a deliberately prepared fixture:

```sh
session-query note personal --history --db /tmp/stage30-demo/sessions.db
session-context annotations personal --kind note --max-bytes 32768 --db /tmp/stage30-demo/sessions.db
```

Set `STUDYLOOP_CONFIG=/tmp/stage30-demo/config.json` and `SESSION_CONTEXT_SCOPE=personal`
for those manual fixture commands. Otherwise the configured scope check correctly refuses.
The lesson ends with no current personal note; its earlier versions remain historical.

For a fresh wheel rehearsal:

```sh
uv build --package agent-session-tools --wheel --out-dir /tmp/stage30-wheels
uv build --package studyloop --wheel --out-dir /tmp/stage30-wheels
uv venv /tmp/stage30-runtime --python 3.13
uv pip install --python /tmp/stage30-runtime/bin/python /tmp/stage30-wheels/agent_session_tools-0.1.0-py3-none-any.whl '/tmp/stage30-wheels/studyloop-0.2.1-py3-none-any.whl[web]'
uv run python -m experiments.evidence_context.session_annotations.runner --python /tmp/stage30-runtime/bin/python --require-installed --output /tmp/stage30-installed
```

`upgrade_probe.py` additionally accepts `--source` pointing to an unretired schema38
fixture and `--output` pointing to a fresh directory. It opens the source read-only,
backs up a consistent disposable copy, upgrades the copy and compares every existing
table. Separate tests verify deliberate purging of already-forgotten annotation shadows
and full rollback/retry when migration fails.

## What the measurements say

Fresh installed CLI/MCP passed all ten walkthrough checks. An installed schema38→39
copy preserved 53 existing rows across 57 tables, with clean foreign-key and integrity
checks. These are structural guarantees, not semantic accuracy scores.

| Note history | Median read, five warm runs | Returned versions | Coverage |
|---|---:|---:|---|
| 10 versions | 9.342 ms | 10 | Complete |
| 100 versions | 66.119 ms | 75 | Partial |
| 1,000 versions | 656.72 ms | 75 | Partial |

The direct helper test uses short reports and excludes transport/startup/cold-disk cost.
Writes were prepared in one batch transaction, so its write timing is not an interactive
per-command latency estimate. The current report was retained in these fixtures.
Oversized current reports can be omitted under the byte budget; `current_count` and
`coverage` still disclose that the returned bodies are incomplete.

The result cap works, but reads verify all visible history before packing it. This is
a concrete reason to test selective current/history retrieval, work budgets and explicit
continuation next. It does not establish that a graph or another storage engine would
perform better. Preserve this baseline so an optimization must retain disagreement,
current-report coverage, exact bindings and scope behavior while reducing work.

See [OBSERVED-RESULTS.json](OBSERVED-RESULTS.json) for verification scope and
[COUNCIL-DECISION.md](COUNCIL-DECISION.md) for what was accepted and rejected from the
three-provider reviews. The full product still requires scoped transport/lifecycle,
file ownership, shared installation, capture/startup checks and release acceptance.

Final focused verification passed 173 tests in 11.75 seconds. The broader memory/experiment
run passed 1,617 with one optional skip before the final history-disclosure refinement;
StudyLoop passed 3,823 with four skips and 704 deselections. Exact verification scope is
recorded in the observed JSON.
