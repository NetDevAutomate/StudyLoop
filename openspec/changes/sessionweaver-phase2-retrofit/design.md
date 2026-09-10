## Context

This design freezes eight seams that six later tasks (B1–B6) implement
against, per `EXECUTION-ERRATA.md` execution-order correction #3 and council
ruling R2 ("acceptance is not `spec-check` alone" —
`reviews/2026-09-07-status-and-completion-plan/COUNCIL/ARBITRATION.md`). It
does not itself change code; every path, table and function named below is
verified against the current checkout (`git rev-parse HEAD` at write time:
`fb606468`, `agent_session_tools.migrations.CURRENT_VERSION = 47`) or against
the SessionWeaver PoC/Phase-A reference being lifted
(`/Users/ataylor/code/personal/tools/session_weaver/.worktrees/sessionweaver-phase2/src/session_weaver/{ontology,concept_schema,concepts,okf,winddown,projection,safe_fs}.py`,
read-only).

Two authorities bind this design and are not reopened here: the design
council's Q1–Q6 rulings
(`reviews/2026-09-07-phase2-design-council/ARBITRATION.md`) decide *what*
ships (derived ontology, concepts-as-assertions, a new recall surface with
no embeddings, code-enforced wind-down, explicit fresh-install scope, a
two-level acceptance gate on the concept-only PoC row); the completion-plan
council's R1–R20 rulings
(`reviews/2026-09-07-status-and-completion-plan/COUNCIL/ARBITRATION.md`)
decide *how the work is sequenced and proven*, and R2 specifically is this
document's charter: freeze the cross-machine standing order and its
two-copy test matrix in B-OS, not in B3 under implementation pressure.

`agent-session-tools` already owns two adjacent, currently-independent
identity/ordering mechanisms this design must reconcile rather than
duplicate:

- **`context_access_state.instance`** — a UUID hex generated once per
  database at first use
  (`packages/agent-session-tools/src/agent_session_tools/context/response_schema.py:31`)
  and already relied upon as the stable per-database replica identity by
  the context replication protocol (`replication/policy.py`,
  `replication/retention.py`, `replication/reconcile.py`, and
  `replication/ledger_schema.py`'s `context_replica_peers.local_instance`).
- **`agent_session_tools.sync`'s `updated_at`-only last-writer-wins**,
  which backlog item BL-1 (`reviews/sessionweaver-plans/BACKLOG-phase-2.md`)
  already recorded as unable to converge a both-sides-divergent session in
  one pass, with a fix direction already decided: "stable `machine_id` +
  per-machine `seq` as LWW tiebreak."

Both mechanisms name the same underlying need — a stable per-replica
identity for conflict resolution — and this design's first decision is that
the concept sidecar's `machine_id` **is** `context_access_state.instance`,
not a new identifier, and that BL-1's planned `machine_id` (when B5
implements it) must resolve to the same value rather than inventing a
second one.

## Goals / Non-Goals

**Goals:**

- Give B2 and B3 exact, additive migration contracts (schema, rollback,
  required safety tests) so schema-version ownership is reserved before
  either task edits `migrations.py` (`EXECUTION-ERRATA.md` correction #4).
- Give B3 a total, testable order for resolving concurrent replicated
  concept-lifecycle events, so "record a backlog item" is not mistaken for
  "solved" (`EXECUTION-ERRATA.md` decision #8).
- Give B2 a named, non-destructive failure seam for incremental ontology
  refresh, consistent with "session capture is authoritative"
  (`EXECUTION-ERRATA.md` decision #7).
- Give B4 a byte-for-byte frozen recall contract so its acceptance
  condition (identical hit lists to A4's already-measured library call,
  ruling R6) is checkable without re-deriving the shape from prose.
- Give B1 an exhaustive list of the sites that currently let a missing
  scope classification escape as an unhandled exception, and the one
  diagnostic shape all of them return.
- Name the compatibility seam (`ConceptService`'s public surface) that must
  not move once B4 depends on it, and the cross-stage gate that keeps A7,
  B6 and both release stages checking the same thing.

**Non-Goals:**

- Choosing *whether* to ship embeddings, fusion retrieval, or automatic
  concept distillation — Q3/Q4 already closed those (no embeddings ship;
  automatic distillation is deferred behind experiment gates not yet run).
  This design does not reopen them.
- Specifying B1–B6's task sequencing, effort, or test-writing order — that
  is `COMPLETION-PLAN.md` §3 and each task's own brief.
- Designing the OKF-usage or concept-embedding pre-registered experiments
  (Q3 §4) — those follow B5, not this change.
- Redesigning the existing context replication protocol
  (`context_replica_peers`/`context_replica_offers`/
  `context_replica_control_batches`) — this design reuses its identity
  primitive; it does not alter its transport or acceptance/acknowledgement
  state machine.

## Decisions

### Migrations: v48 tier-1 ontology, v49 concept sidecar

Both migrations are additive-only against the current `agent-session-tools`
schema (`CURRENT_VERSION = 47`); neither alters an existing table, column,
or index. `agent_session_tools.migrations` reserves both version numbers
before B2 or B3 edits `migrations.py`, per `EXECUTION-ERRATA.md` correction
#4 — B2 owns v48, B3 owns v49, and neither task may claim the other's
number.

**v48 — tier-1 ontology**, lifted unchanged from the reference
`ontology.py`'s six schema objects, atomically swapped in via staging
tables (`__ontology_*_next`) so a rebuild never leaves a partial live
graph:

| Table | Purpose |
| --- | --- |
| `ontology_class` | T-Box: class hierarchy (name, parent, description) |
| `ontology_property` | T-Box: typed relations with domain/range classes |
| `ontology_structural` | Extracted per-session structural facts (project/testrun/artifact/command), keyed by a 64-char id, `UNIQUE(session_id, type, key)` |
| `ontology_individual` | A-Box: individuals with a class, label, JSON attrs |
| `ontology_relation` | A-Box: `(subject, predicate, object)` triples, `WITHOUT ROWID` |
| `ontology_build_state` | Singleton build receipt: extraction version, logical hash, mode, source/candidate counts |

Every row in `ontology_structural`, `ontology_individual` and
`ontology_relation` is derived from `sessions`/`messages` and is
byte-for-byte reproducible by a full rebuild; none is user-authored or
carries independent provenance. This is why Q1(a) rules the ontology
**derived, never synced** (below), and why its migration's rollback is
trivial: **downgrade drops exactly these six objects and nothing else.**
No other migration, table, or index references an `ontology_*` table by
foreign key, so the drop is unconditionally safe.

**v49 — concept sidecar**, lifted unchanged from the reference
`concept_schema.py`'s exact DDL (`SCHEMA_VERSION = 2`,
`UPSTREAM_SCHEMA_VERSION` pinned to the migration number that installs it):

| Object | Kind | Purpose |
| --- | --- | --- |
| `context_concepts` | table | Immutable concept roots: bound (assertion-linked) or legacy-unbound, with the origin/binding-state invariant `CHECK` that enforces which fields a given origin may set |
| `context_concept_events` | table | Append-only lifecycle events (`proposed`→`accepted`\|`retired`), each carrying `origin_instance`, `origin_seq`, `logical_time` and a 64-char immutable `id` |
| `context_concept_clock` | table | Singleton per-database logical clock: `(origin_instance, origin_seq, logical_time)` |
| `context_concept_fts` | virtual table (FTS5) | Derived search index over title/statement/tags/kind, rebuildable from `context_concepts` |
| `context_concept_schema` | table | Immutable schema-identity marker (`schema_version`, `schema_fingerprint`) verified on every open, so drift between the sidecar's exact DDL and the installed DDL is detected rather than silently tolerated |

`context_concepts.assertion_id` references `context_assertions(id)`; no
existing `context_assertions` column, check, or trigger is altered —
`proposed_state` keeps its current execution-state vocabulary
(`planned`/`in_progress`/`completed`/`unknown`), and concept kind/lifecycle
live only in the sidecar (`EXECUTION-ERRATA.md` decision #3). **Rollback:
downgrade drops exactly these five objects.** `context_concept_events` and
`context_concept_clock` are new tables with no inbound foreign keys from
outside the sidecar, so the drop is unconditionally safe; `context_concepts`
carries an FK *to* `context_assertions`, never the reverse, so dropping it
cannot orphan an assertion.

**Migration-safety tests required for both v48 and v49** (ruling R7):

1. **Fresh creation** — a database created from empty reaches v48/v49
   directly (no intermediate state ever half-applies the schema).
2. **Real upgrade** — a SQLite Online Backup copy of a live v47 database
   upgrades to v48 then v49; an upgraded-copy schema receipt (object list +
   fingerprint) is retained as evidence.
3. **Interrupted-migration recovery** — a fault is injected mid-migration
   (after some but not all of a migration's statements commit, using the
   same per-migration transactional boundary `agent_session_tools.migrations`
   already guarantees); a rerun converges to the target version with no
   partial schema left behind.
4. **Repeated refresh idempotence** — running the ontology rebuild (v48) or
   opening the sidecar (v49, via the existing `_ensure_schema` fingerprint
   check) twice in a row produces no schema drift and no duplicate rows.

### Cross-machine standing order (frozen)

> **B3 verification note (design review, minor #2):** the reference `_ConceptRepository._allocate()` already takes a table-wide `MAX(logical_time)` over `context_concept_events` with no `origin_instance` filter, so imported rows may already advance the next local allocation. B3 must run two-copy matrix item 4 against the unmodified allocator first and add an explicit advance-on-import step only if that experiment fails.

```
standing(concept) = max(events[concept], key=(lamport, machine_id, event_id))
```

- **`lamport`** is `context_concept_events.logical_time`. At insert:
  `lamport = 1 + max(local_clock, max(lamport over every event imported for
  this database so far))`. The reference `_ConceptRepository._allocate()`
  today computes `logical_time = max(local max over
  context_concept_events.logical_time, context_concept_clock.logical_time) +
  1` — correct for a single, non-replicating database. B3's replication
  apply path must extend this: **importing any foreign event with lamport
  `L` first advances `context_concept_clock.logical_time` to at least `L`**
  (a clock-tick observation with no accompanying local event), so that the
  next *local* insert's `1 + max(...)` term already accounts for every
  lamport value this database has ever seen, imported or local. This is the
  standard Lamport-clock rule; it is the one behavioural change this design
  requires beyond what `_allocate()` already does, and it is a required
  assertion in the two-copy matrix (below, item 4).
- **`machine_id`** is `context_access_state.instance` — the stable,
  UUID-hex, per-database replica identity created once at first use
  (`context/response_schema.py:31`) and already read by
  `replication/policy.py`, `replication/retention.py`,
  `replication/reconcile.py`, and stored per-peer in
  `context_replica_peers.local_instance`
  (`replication/ledger_schema.py`). This is the same identifier BL-1's
  planned `machine_id` + per-machine `seq` sync tiebreak
  (`reviews/sessionweaver-plans/BACKLOG-phase-2.md`) must resolve to when
  B5 implements it — B3 does not mint a second replica identity, and BL-1's
  fix must reuse this one rather than add a third. The sidecar's existing
  `context_concept_events.origin_instance` column *is* this value, recorded
  once per event at insert time; B3 does not rename the column, it
  specifies what it must contain.
- **`event_id`** is `context_concept_events.id` — A3a's immutable 64-char
  identity, a deterministic hash of the event's own payload (concept id,
  parent event id, standing, actor, reason, display timestamp,
  `origin_instance`, `origin_seq`, `logical_time`). It is the final,
  content-derived tiebreaker: two events can only collide on it if every
  other field — including `machine_id` and `lamport` — is identical, which
  the schema's `UNIQUE(id, concept_id)` and `UNIQUE(origin_instance,
  origin_seq)` constraints already make a genuine duplicate rather than a
  real conflict.
- **Duplicate `machine_id` is diagnosed and refused, never merged.** If
  replication ever observes two live peers reporting the same
  `context_access_state.instance` (a cloned database presented as a second
  replica, not a legitimate additional one), that is an identity
  violation, not an ordering case: the reconcile step raises a structured,
  named error and refuses the exchange rather than interleaving the two
  peers' `origin_seq` sequences as if they were one honest replica.
- **Rows are append-only.** `context_concept_events` already forbids
  `UPDATE` (`context_concept_events_immutable` trigger) and this design
  adds no delete path; replication only ever inserts events it does not
  already have (by `id`), never rewrites one.
- **No wall-clock timestamp participates in ordering.** `display_timestamp`
  is retained purely as a human-readable label; the standing order is a
  pure function of `(lamport, machine_id, event_id)`, consistent with
  `EXECUTION-ERRATA.md` decision #5 ("timestamp-only latest-state
  resolution is forbidden").

**How the per-database clock maps onto this order:** `context_concept_clock`
is not itself part of the standing-order key — it is the *local allocator's*
state, one row per database, advanced under every insert (local or
clock-tick) and never read cross-database. The order above is computed
purely from `context_concept_events` rows already present after a sync
exchange; the clock only has to guarantee that the *next* local event this
database creates gets a `lamport` no replica has already used for a
causally-prior event.

### Two-copy test matrix (normative)

B3 must pass every scenario below before its acceptance line is satisfied
(ruling R2); each is a required test, not an illustrative example:

1. **Opposite replication orders converge identically** — running A→B then
   B→A produces the same final event set on both copies as running B→A
   then A→B does (starting from the same two pre-sync states each time).
   Both orders yield identical event sets, identical ordered digests
   (canonical serialization of the event set, hashed), and identical
   computed standing for every concept.
2. _(covered by 1 — the two orders are the two runs of the same
   assertion.)_
3. **Replay is idempotent** — re-running either sync direction a second
   time, with nothing new to exchange, adds zero new rows on either copy.
4. **A causally-later local event outranks prior concurrent ones** — after
   two replicas have converged, a new event created on either copy
   receives a `lamport` strictly greater than both of the concurrent events
   that caused convergence, and that new event is the current standing on
   *both* copies once they resync.
5. **Read-model rebuild is hash-equivalent** — deterministically
   recomputing each concept's current standing from its full event history
   (not from any cached "current" pointer) produces an identical digest on
   copy A and copy B.
6. **Accept-on-A / retire-on-B (concurrent) resolves to the computed
   winner** — the test independently computes the expected winning event
   from the `(lamport, machine_id, event_id)` triple of the two concurrent
   events (not from which side "should" win by narrative), then asserts
   that both copies show that exact computed standing after sync — in
   either sync direction.
7. **Accept then retire (causal) resolves to `retired` on both** — accept
   on one copy, sync, retire (chained from the synced accept event) on the
   other, sync again: both copies show `retired`, because the retire
   event's `parent_event_id` chains from the already-synced accept event,
   giving it a strictly later causal position by construction, not by
   ordering luck.

### Refresh-failure seam for B2

A named, monkeypatchable hook is called from
`agent_session_tools.export_sessions._run_export`, after the per-source
export loop's `conn.commit()` that persists captured sessions and before
the function returns. The hook triggers an *incremental* ontology rebuild
scoped to the sessions this run touched. Its contract:

- **The hook is a single, separately-named call** (not inlined into the
  export loop), so a test can monkeypatch it to raise without touching any
  export/exporter code.
- **A hook failure never rolls back the capture.** The already-committed
  session and message rows from this run remain committed and unchanged —
  there is no shared transaction between session capture and the ontology
  refresh, and the hook call is wrapped so any exception it raises is
  caught, not propagated, consistent with `EXECUTION-ERRATA.md` decision
  #7 ("session capture is authoritative").
- **The failure is surfaced as a structured warning on a named
  channel/field** — not merely printed — so `session-maint`, `doctor`, and
  a caplog-based test can all observe it the same way: a log record from a
  stable, named logger/field pair (e.g. an `ontology_refresh_failed` event
  field), not a free-text string a future refactor could silently reword
  out of existence.
- **`session-maint ontology-rebuild` recovers.** Running the existing
  maintenance sweep after a refresh failure brings the ontology back to a
  healthy, fully-covered state — the failure is a staleness window, never
  a permanent gap, matching Q1(a)'s "idempotent `session-maint` sweep for
  missed rows."

Required tests assert all three facts together on one fault injection: the
captured session rows are present and unchanged; the structured warning
fired on the named channel/field; and a follow-up `session-maint
ontology-rebuild` call converges the ontology to the same state a
failure-free run would have reached.

### Seed sanitization

`agent_session_tools.sync._seed_remote_db` already takes a SQLite Online
Backup of the local database into a temporary snapshot file before `scp`
seeds a never-before-synced remote
(`packages/agent-session-tools/src/agent_session_tools/sync.py:456`). This
design adds one step to that snapshot, before the `scp`: **every row of the
six v48 ontology tables, and the `ontology_build_state` singleton, is
stripped from the snapshot.** The remote is seeded with every table's
schema present (so it opens without error) but zero ontology rows.
Immediately after a successful seed, the destination is expected to run its
own local ontology rebuild (the same incremental/full rebuild B2 wires into
`_run_export`, or an explicit `session-maint ontology-rebuild`) before it is
considered ready — the remote's tier-1 ontology is *derived on the remote*,
never inherited from the source's snapshot. This is a direct consequence of
Q1(a) (never synced) applied to the one code path that currently moves a
whole-database snapshot between machines: an unsanitized seed would make
the remote's first-ever ontology state a *copy*, not a *derivation*, which
is exactly the property Q1(a) forbids.

### Recall contract (frozen for B4)

B4 implements `memory_recall` in `agent_session_tools.mcp_server` against
the shape A4 measures its retrieval benchmark against; B4's acceptance
condition is that this tool's hit lists are identical, not merely similar,
to A4's library call (`recall(db, question, ...)`) on the same backup and
visibility (ruling R6 — "same planner + same DB must be deterministic;
'noise' launders defects"). The frozen `RecallReport` shape, to be pinned
byte-for-byte by a JSON-schema test (`docs/data/recall-contract.json`,
produced once by A4 and never hand-edited afterward):

```
RecallReport
├── concepts[]
│   ├── concept_id            -- context_concepts.id
│   ├── kind                  -- Decision | Finding | Problem | Preference | Procedure
│   ├── title
│   ├── statement
│   ├── standing              -- current computed standing (proposed | accepted | retired-excluded upstream)
│   ├── binding_state         -- bound | legacy-unbound
│   ├── confidence
│   ├── source_session_id | null
│   ├── provenance_label      -- e.g. "legacy-unbound" surfaced explicitly, never blended with bound results
│   └── citations[]           -- evidence_id, start, end, quote
├── sessions[]
│   ├── session_id
│   ├── source
│   ├── project_path
│   ├── updated_at
│   └── preview                -- ≤ 300 chars, the existing session_search preview contract, unchanged
└── plan
    ├── terms
    ├── and_query
    ├── or_query
    └── fallback_used
```

This design fixes three additional properties B4 must preserve, all
already decided upstream of this change:

- **The AND→OR planner semantics** apply identically inside
  `memory_recall`'s own query construction and inside `session_search`'s
  planner addition — one planner, ported once, not reimplemented per
  surface (Q3(b), "a new surface, not a new store").
- **`session_search`'s existing 300-character preview contract is
  untouched.** The planner change only widens which rows a query can match
  (implicit AND → AND-with-OR-fallback); it does not touch how a matched
  row is rendered.
- **Session results are deduplicated against concept source sessions** —
  a session already cited by a returned concept is not repeated as a bare
  session hit, so the report never double-counts the same evidence under
  two shapes.

### Fresh-install scope

Two independent config writers currently default `memory.default_scope` to
absent/`None`, and both must instead write `unclassified` explicitly on a
fresh install, while the *runtime* default (read when no config exists at
all, or when the key is omitted from a hand-edited file) stays unset —
`EXECUTION-ERRATA.md` decision #9 is deliberate: an unset runtime default
forces a structured diagnostic instead of silently guessing a scope, while
a freshly *generated* file should never leave a new user in that
undiagnosed state.

- `packages/studyloop/src/studyloop/settings.py::generate_default_config()`
  — the commented YAML template a fresh `studyloop` install writes — gains
  a `memory:` block with `default_scope: unclassified` and the existing
  work/personal comment convention this file already uses for other
  optional sections.
- `packages/agent-session-tools/src/agent_session_tools/config_loader.py`'s
  `DEFAULT_CONFIG` (written verbatim by `ensure_config_dir()` when no
  config file exists) changes its `memory.default_scope` value from `None`
  to `"unclassified"`. `config_loader.py`'s in-memory fallback for a
  *missing key* on an existing file remains `None` — only the
  freshly-written file's content changes.
- Runtime behaviour is unchanged: `ScopePolicy.from_config()`
  (`context/scope.py`) still accepts `default_scope: null` and still raises
  `ScopeError` when no default and no matching project root resolve a
  scope. Nothing in this design relaxes that raise; it changes what a
  *generated* file contains, not what an *absent* setting means.

**Every currently-unguarded `request_scope()` call site returns the same
structured diagnostic** instead of letting `ScopeError` propagate as an
unhandled exception or traceback. The plan (`COMPLETION-PLAN.md` §3, B1)
names eight call sites under the heading "the seven `request_scope()`
sites" — this design carries the list forward exactly as named, flagging
the count mismatch rather than silently resolving it, since correctness of
the list matters more than the label:

1. `packages/studyloop/src/studyloop/parking.py:40-58` (`_connect()`'s
   board-seeding read)
2. `mcp/tools.py::log_struggle`
3. `mcp/tools.py::get_study_backlog`
4. `mcp/tools.py::get_active_topics`
5. `mcp/tools.py::get_next_action`
6. `mcp/tools.py::record_topic_progress`
7. `mcp/tools.py::get_concept_context`
8. `mcp/tools.py::get_study_history`

Each of the above, plus every tool registered by
`agent_session_tools.mcp_server` (`session-db-mcp`) and by
`studyloop.mcp.server` (`studyloop-mcp`), returns one structured diagnostic
shape on a missing/invalid scope — a stable error code plus a one-line,
actionable message (e.g. "run `studyloop config init` to classify this
project") — never a bare traceback. `agent_session_tools.context.public
.open_context()`'s existing "never silently migrate an agent request"
posture is the model this diagnostic follows: fail closed, explain why,
name the fix. `session-db-mcp`'s `open_context()` on a database that does
not exist yet returns this same diagnostic shape, not a distinct
file-not-found error.

### Compatibility seams

- **`ConceptService`'s public surface is frozen before B4 depends on it**
  (`EXECUTION-ERRATA.md` correction #5: "freeze the B3 service interface
  before B4 edits MCP registration/retrieval"). The reference
  implementation's seam (`concepts.py::ConceptService`) exposes
  `project()`, `winddown()`, `transition()`, `bind_legacy()`, and
  `import_okf()` as the only methods a caller outside the sidecar's own
  module needs; B3 lifts this surface unchanged in shape (return types
  `BatchResult`/`TransitionResult`/`BindResult`/`ProjectionReport`, one
  method per lifecycle verb), and B4 is only ever a caller of it, never a
  second implementation of concept transitions.
- **A named cross-stage package/API compatibility gate spans A7, B6, and
  both release stages** (ruling R8): wheel builds, installs clean from a
  fresh venv, every public import and CLI entry point the previous release
  exposed still resolves (or is removed with a recorded deprecation
  message, never silently), `pyproject`/CHANGELOG/tag agree, and the tag
  SHA equals a green CI SHA. This design does not restate R8's stage
  ordering (A7 → B-OS → … → R-SL → B6 → R-SW, `COMPLETION-PLAN.md` §3) — it
  names the one gate all of those stages check the same way, so a
  compatibility regression caught at B6 cannot be blamed on "that's A7's
  gate, not mine."

## Risks / Trade-offs

- **The Lamport-advance-on-import step is new behaviour, not present in
  the reference `_allocate()`.** Without it, a database that only ever
  imports events and never creates its own could keep allocating
  `lamport` values below imported ones, silently reintroducing
  timestamp-shaped bugs through the back door. Mitigated by making the
  advance-on-import assertion an explicit, required item in the two-copy
  matrix (item 4) rather than trusting code review alone to catch its
  absence.
- **`context_access_state.instance` was designed for the existing context
  replication protocol, not for concept-event ordering.** Reusing it
  avoids a second identity primitive, but ties the concept sidecar's
  correctness to that identity never being cloned or reset independently
  of the database it names. The "duplicate `machine_id` is diagnosed,
  never merged" rule exists specifically to fail loudly rather than
  silently interleave two histories if that assumption is ever violated
  (e.g. a database file copied instead of replicated).
- **Ontology seed-sanitization adds a second post-processing step to an
  already-fragile cross-host path** (`_seed_remote_db` shells out to `ssh`
  and `scp`). Mitigated by scoping the change to the snapshot file only
  (never the live local database) and by requiring the destination to
  self-heal via its own rebuild rather than depending on the sanitization
  step being perfect — an imperfectly-stripped seed still self-corrects on
  the next `session-maint ontology-rebuild`.
- **Freezing the recall contract before A4's JSON schema file exists**
  (A4 precedes B-OS in `COMPLETION-PLAN.md`'s stage order, but this design
  is written from the plan's own frozen field list, not from a file on
  disk yet) risks a mismatch if A4's actual implementation differs in a
  field name. Mitigated by requiring B4's JSON-schema test to diff against
  `docs/data/recall-contract.json` verbatim — any drift between this
  design and A4's shipped shape fails that test immediately rather than
  surfacing as a silent behavioural difference.
- **The eight-item "seven sites" list is carried forward with its label
  intact rather than silently corrected**, so a future reader comparing
  this design against `COMPLETION-PLAN.md` sees the same list and can
  verify the count discrepancy independently rather than wondering which
  document is authoritative.
