# Production boundary inventory

Initial static inventory after Stage18. This is a routing aid, not evidence that
all paths have been secured. Paths below are relative to `packages/`.

| Boundary | Current code entry points | Required integration |
|---|---|---|
| CLI historical reads | `agent-session-tools/.../query_db.py:get_connection,attach_full_db`; `query_logic.py:search,list_sessions,show_session,stats,export_context,continue_session`; `query_sessions.py` commands | Resolve explicit scope before any source text, direct-ID lookup, formatting or attached full DB read. Preserve useful compatibility diagnostics. |
| MCP historical reads | `agent-session-tools/.../mcp_server.py:_get_connection,_create_server` | Scope all existing tools, then add versioned evidence/decision interfaces; do not leave legacy tools as bypasses. |
| Native writes | `agent-session-tools/.../exporters/{codex,claude,kiro,grok}.py`; `base.py:commit_batch`; `export_sessions.py` | Preserve native tool events and stable IDs, derive receipt fields only from native metadata, bind source versions and explicit project config, persist capture telemetry and respect deletion suppression. |
| Semantic/derived reads | `agent-session-tools/.../semantic_search.py,embeddings.py`; attached full DB/federation | Apply policy before candidate text/payload construction; invalidate/purge managed vectors and caches on correction/forgetting. |
| Remote/local sync | `agent-session-tools/.../sync.py:_seed_remote_db,_build_dump_queries,_dump_delta_sql,_stream_sql_to_target,push,pull,sync_all` | Replace protected raw SQL fallback with a versioned scoped protocol, destination policy before staging, tombstones before content, incompatible-peer refusal. Include global StudyLoop table ownership. |
| Hot/full data movement | `agent-session-tools/.../tiering.py:sync_to_full,prune_hot,refocus`; `maintenance.py` | Source/evidence/citation ownership and deletion propagation must survive every move. Stage18 fixed compaction FTS/WAL behavior only; the other paths are not covered by that fix. |
| Snapshots/restore | `agent-session-tools/.../tiering.py:create_snapshot`; `studyloop/.../cli/_backup.py`; sync destination backups | Identify managed restore entry points; merge active tombstones before any restored content can be served. State external original/backup retention limits precisely. |
| Installation | `studyloop/.../installers.py`; CLI install/agent/tool commands | Move memory-owned setup/doctor and packaged skill registration into independent agent-session-tools; StudyLoop delegates a versioned interface. |
| Health and StudyLoop consumer | `studyloop/.../doctor/{agents,harness,database,config}.py`; session/agent startup | Distinguish installed/registered/attempt/success/lag/error states; request scoped historical bundles, expose missing validation and conflicts. |
| StudyLoop transcript consumers | `studyloop/.../cli/_extract.py`; `extractors/eval_runner.py`; `history/{sessions,search,streaks}.py` | Scope before transcript bodies, FTS snippets, latest-ID selection and aggregate activity; use shared policy owner. Live extractor calls must never receive excluded messages. |
| StudyLoop learning derivations | `studyloop/.../history/{progress,teachback,sessions}.py`; `extractors/pipeline.py`; notes, parking, bridges and backlog | Global learner tables do not currently carry complete source/scope lineage. Give these records ownership before calling the entire StudyLoop result scoped or deletable. |

The `...` in these entries denotes `src/agent_session_tools` or `src/studyloop`,
respectively. This list was obtained from current file/function discovery and must
be extended by call-path and SQL inspection before a completeness claim.

## Unresolved policies to implement and test

- Default legacy captures are unclassified. Do not silently assign the owner's real
  projects overnight. Installation/configuration must make work/personal boundaries
  explicit; missing policy must not become an unscoped fallback.
- A trusted local configuration operation can reclassify a project, but durable
  assignment/scope history now exists for Stage19 policy application. Sync conflict
  handling and a fully audited explicit per-session administrative interface remain.
- Existing SQL sync includes global learning tables and can seed a whole DB. Both
  are potential policy bypasses even if ordinary session rows are filtered.
- New context tables add references and derived text. Existing maintenance/pruning
  paths must be audited for deletion order, transitive assertion/relationship lineage
  and orphaned source versions; passing old tests is not proof of this integration.
- Tombstone triggers currently suppress inserts. They are not the actual forget
  operation, active tombstone restore mechanism or complete purge of managed copies.
- Source variants can arise from different machine/locator/parser metadata. Retrieval
  must avoid counting those as independent corroboration or additional conversations.

Stage19 covers the listed core CLI/MCP/semantic historical readers with explicit
configuration and read snapshots. That progress does not cover the separate
StudyLoop-specific consumers or transfer/lifecycle paths in this inventory.

Stage20 now covers the listed StudyLoop transcript consumers, and guards global
resume/history/stats/wins fields conservatively when ownership is absent. Classified
extractor persistence to the old global progress aggregate is refused before the
provider call. This is not complete learning-data ownership: other readers/writers
still require the source-linked observation and projection design described in
`consumer_scope/GUIDE.md` and its council decision. Current guards must not be removed
until that replacement has positive and negative persistence/lifecycle evidence.
