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

## Stage26 refresh

Stage21 now stores source-bound/explicitly owned progress observations rather than
writing new assessments into the legacy global progress aggregate. Stage26 adds
ownership for `study_sessions`, `teach_back_scores` and `knowledge_bridges`, and
uses it in their actual history/focus/MCP consumers. These increments are not a
complete learner-state inventory or an authorization to transfer old global tables.

The next learner audit must trace at least:

| Stored state | Current entry points to inspect | Required behaviour |
|---|---|---|
| `parked_topics` | `parking.py`, `session/{start,resume,cleanup}.py`, `services/backlog.py`, `logic/backlog_logic.py`, CLI and UI consumers | Explicit ownership, scoped uniqueness and links to owned study sessions; purge dependencies |
| `session_notes`, tags, learning metadata | `notes.py`, memory query/MCP writers/readers and source-derived annotations | Native-session lineage where present; no body-return or mutation bypass |
| `practice_attempts` | `learning/practice.py` and exercise/agent consumers | Attempt body and score ownership, filtering before scheduling/aggregation, source lineage |
| `concepts`, aliases, relations, message links | `history/concepts.py`, `history/bridges.py`, graph queries | Scope-safe identities and endpoints; classified bridge conversion without copying into global state |
| `concept_dependencies` | `learning/mastery.py` seed/write/read paths | Distinguish public curriculum from personal observations and work-derived edges |
| Plans and other learner state outside sessions.db | `planning/{store,index,multiplexer}.py`, `planning/exercises/store.py`, session/learning modules and their configured storage | Audit before claiming sessions.db is the only relevant state boundary; classify and protect any derivations |

This table is a work queue from current schema/SQL inspection. Table names alone
do not establish complete call-path coverage. Actual installed session startup must
also handle an explicitly source-linked assessment before exported input exists.
The current path rejects and rolls back that operation; it must not silently
drop lineage to make the write succeed.

## Stage27 refresh

`parked_topics`, `study_notes`, scoped board metadata and `practice_attempts` now
use shared ownership predicates in their actual StudyLoop APIs, CLI/HTTP readers
and mutations. Practice progress and teach-back observations retain application
record dependencies; local parent/attempt deletion purges those derivations.
The exact-owner deduplication and dual native/study-parent rules are described in
`learner_paths/GUIDE.md`. Actual HTTP routes and MCP stdio are exercised in the
installed lesson; web lifespan and full session startup are not covered.

The Stage26 row mentioning `session_notes` must not be mistaken for `study_notes`:
source annotations (`session_notes`, tags, learning metadata) still require their
own complete audit. Remaining concepts/aliases/relations/message links, dependencies,
planning storage and session state files are required work. Consumer composition
can still open several policy/DB snapshots in one response. No ownership increment
authorizes the old raw SQL sync, whole-DB seed, managed restore or tiering paths.

Practice currently checks artifact presence before a command and reports confidence
using the existing heuristic. This is attributable application output, not validated
learning. Preserve that distinction when integrating recommendation/decision logic;
review command/artifact timing and same-scope cross-project supersession explicitly.

## Stage28 refresh

Finite HTTP API GET/HEAD responses now withhold headers/body until request-local
policy/scope and participating database access generations validate. Selected
composed MCP reads and canonical native context reads have the same completion
check. The generation trigger allowlist is `context/response_schema.py:EVENTS`;
new access-affecting storage must extend it and its tests. Missing schema38 produces
an explicit policy-apply/migration diagnostic. Mutations are not wrapped as reads;
their own transactions remain responsible for truthful commit outcomes.

`/api/session/stream`, WebSockets and IPC/session files need explicit ownership and
per-event semantics. The finite response wrapper deliberately cannot buffer an
unending stream. Remaining native annotations/tags/learning metadata, concepts and
relations, dependencies, plans and session files still require storage/call-path
integration. Static inspection at this checkpoint reconfirms global concept reads
in `history/concepts.py` and concept joins in `learning/mastery.py`; these are the
next concrete learner-state entry points, not evidence of completed scope coverage.

## Stage29 refresh

`history/graph.py` is the current owned contribution adapter. `record_concept` and
modern dependency upserts persist immutable reports through the memory package;
`list_concepts` and dependency queries apply scope before payloads. Bridge conversion
in modern schemas exposes live owned contributions instead of copying to global
concept/relation tables. Contribution IDs, mappings, domains and hashes remain visible.
Legacy concept/dependency rows are withheld outside the existing unclassified boundary.

`learning/mastery.py` preserves report provenance in graph/weak-link results;
`learning/decision.py` carries IDs/bindings/validation status into recommendation
metadata. Only explicitly directional prerequisite reports enter that path. The MCP
`get_concept_context` registration calls the bounded shared helper under the response
guard; installed HTTP and MCP stdio checks pass. Graph display labels are grouping,
not entity-resolution identities or independently validated learning categories.

Config/markdown source ownership remains incomplete and cannot be bypassed by modern
seeding. Old aliases/message links are preserved, not declared publicly shared or
fully audited across external consumers. Read output is bounded but projection work
is not; the 100/1,000/5,000-row diagnostic quantifies that remaining requirement.
Native annotations/tags/learning metadata, plans, session/IPC/stream files, all managed
sync/restore/reimport paths and installer/skills/startup still require completion.


## Stage30 refresh

Native-session annotations now use `context/annotations.py`, schema39 session owners,
and existing immutable observation history. `session-query note/tag` resolves scope
inside a guarded write transaction; external editor saves recheck the version and
access snapshot after releasing the editor's connection. `session-context annotations`
and the real MCP `session_annotations` expose reported authority, current disagreement,
byte coverage and incomplete predecessor history. Legacy learning metadata is a scoped
unattributed read; this stage adds no producer for it.

The old `deduplication.py` detector now scopes candidates before reading bodies.
Physical merge refuses classified, owned or provenance-bound sources; legacy
unclassified merging validates all IDs and rolls back atomically on failure.
Migration/parent/observation retirement purges mutable annotation shadows, and stale
shadow replay is refused. These local checks do not establish remote deletion behavior.

The transport inventory is now especially consequential: existing `sync.py` still
exports old mutable annotation tables and does not carry the new observation versions,
session owners or retirement metadata. It must be replaced for the classified product
path. Tiering, managed restore, exporter reimport, config/files/live IPC and shared
installation/startup remain open. The new measured history scan cost also requires
selective retrieval with explicit completeness and work bounds.

## Stage31 refresh

`context/annotation_pages.py` now selects scope-filtered headers, checks selected
immutable report bodies, and returns an atomic current group plus history-only keyset
continuation. Policy/scope/generation/file changes invalidate continuation, and the
existing final response guard still applies. Schema40 adds the ordered history index.
Row/legacy-byte, dependency-count, candidate and SQLite VM-work bounds are explicit;
counts still scan historical headers and the VM limit is not a wall-clock deadline.

The installed benchmark, final1,646memory/experiment passes and council arbitration
are preserved in `bounded_history/`. This closes the identified annotation read-work
increment, not graph-query work or semantic acceptance. Next priority is the real
`sync.py` transfer path: unfiltered global SQL, whole-DB seeding and missing observation/
owner/retirement transport are incompatible with the protected product contract.

## Stage32 and lifecycle transition

`replication/policy.py`, `snapshot.py` and `content.py` implement the scoped content
phase. Sender SQL selects complete declared dependencies before payloads; receiver
checks exact bindings and remaps integer learner IDs by stable ownership. Generated
teach-back totals are recomputed. Conflicting edits and unsolicited local ownership
assignments refuse the phase atomically. These are internal package APIs, not the
completed CLI/SSH coordinator. Both completion flags remain explicitly false.

`replication/legacy.py` now blocks the old transport for explicit scope/peer policy,
applied classification, modern context or retirement state. Public operations check
before resolving a remote; remote metadata checks and SQL transaction guards precede
body selection/import. A modern schema cannot be whole-file seeded. This is a refusal
boundary during integration, not certification of legacy SQL or a working replacement.

Continue with `LIFECYCLE-DESIGN.md` and `LEGACY-TRANSPORT-GUARD.md`. Include native
`context_native_message_sources` in full content transport and handle legacy learner
`SET NULL` dependencies explicitly during purge. Source forgetting, reversible peer
withdrawal, durable control routing, native reimport, managed restore/indexes and actual
configured SSH process acceptance remain open, alongside shared setup/startup and
file/live-state ownership. The full P01-P15 goal remains active.
