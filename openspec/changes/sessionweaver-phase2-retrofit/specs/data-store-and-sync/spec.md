## ADDED Requirements

### Requirement: Migration v48 installs a derived tier-1 ontology that never joins either sync-table list
`agent_session_tools.migrations` migration v48 SHALL add
`ontology_class`, `ontology_property`, `ontology_structural`,
`ontology_individual`, `ontology_relation`, and `ontology_build_state` as
additive tables with no alteration to any existing table. Every row in
these tables SHALL be reproducible from `sessions`/`messages` by a full
rebuild. `agent_session_tools.sync.SYNC_TABLES` and
`GLOBAL_SYNC_TABLES` SHALL NOT include any `ontology_*` table, now or in
any later migration. A downgrade from v48 SHALL drop exactly these six
tables and no other schema object.

#### Scenario: Fresh database reaches v48
- **WHEN** a new database is created and migrated
- **THEN** all six `ontology_*` tables exist with the exact schema
  `ontology.py` defines
- **AND** `PRAGMA user_version` reads 48 or higher

#### Scenario: Sync never touches ontology tables
- **GIVEN** a database at v48 or later with populated ontology tables
- **WHEN** `session-sync push|pull|sync` runs against any configured
  endpoint
- **THEN** no `ontology_*` row is read, written, or referenced by the sync
  SQL, verified by a positive-control test asserting the tables' absence
  from both `SYNC_TABLES` and `GLOBAL_SYNC_TABLES`

#### Scenario: Downgrade from v48
- **WHEN** the database is downgraded from v48 to v47
- **THEN** the six ontology tables are dropped
- **AND** no other table, index, or trigger is affected

### Requirement: Migration v49 installs an append-only concept lifecycle sidecar joined to context_assertions
`agent_session_tools.migrations` migration v49 SHALL add
`context_concepts`, `context_concept_events`, `context_concept_clock`,
`context_concept_fts`, and `context_concept_schema` as additive objects
with no alteration to `context_assertions` or any other existing table.
`context_concepts.assertion_id` SHALL reference `context_assertions(id)`;
no column, check constraint, or trigger on `context_assertions` SHALL
change. `context_concept_events` rows SHALL be immutable after insert. A
downgrade from v49 SHALL drop exactly these five objects and no other
schema object.

#### Scenario: Fresh database reaches v49
- **WHEN** a new database is created and migrated
- **THEN** all five sidecar objects exist with the exact schema
  `concept_schema.py` defines
- **AND** `context_concept_schema` records the pinned schema version and
  fingerprint

#### Scenario: Concept events cannot be mutated
- **GIVEN** an existing row in `context_concept_events`
- **WHEN** an `UPDATE` is attempted against that row
- **THEN** the database raises rather than applying the change

#### Scenario: Downgrade from v49
- **WHEN** the database is downgraded from v49 to v48
- **THEN** the five sidecar objects are dropped
- **AND** every `context_assertions` row and constraint is unchanged

### Requirement: Concept lifecycle events replicate through the context replication protocol using a frozen standing order
Concept lifecycle events SHALL join the existing context replication
protocol (`context_replica_peers`, `context_replica_offers`,
`context_replica_control_batches`) rather than a separate transport. A
concept's standing SHALL be computed as `max(events[concept], key=(lamport,
machine_id, event_id))`, where `lamport` is `context_concept_events
.logical_time` (advanced to at least the highest imported value before any
local allocation), `machine_id` is `context_access_state.instance`, and
`event_id` is the event's own immutable id as final tiebreaker. Replicating
the same event twice SHALL add no new row. Two replicas presenting the
same `machine_id` as distinct peers SHALL be refused with a diagnostic
error rather than merged.

#### Scenario: Opposite replication orders converge identically
- **GIVEN** two database copies with divergent concept lifecycle events
- **WHEN** copy A syncs to copy B and then B syncs to A
- **AND**, separately, B syncs to A and then A syncs to B, starting from
  the same two initial states
- **THEN** both orders leave both copies with identical event sets,
  identical ordered digests, and identical computed standing for every
  concept

#### Scenario: Replay adds no new rows
- **GIVEN** two copies that have already fully synced
- **WHEN** the same sync direction is repeated with nothing new to
  exchange
- **THEN** zero new rows are inserted on either copy

#### Scenario: Concurrent accept-on-A / retire-on-B resolves to the computed winner
- **GIVEN** copy A accepts a concept while copy B, independently and
  concurrently, retires the same concept
- **WHEN** the two copies sync in either direction
- **THEN** both copies show the standing computed from the two events'
  `(lamport, machine_id, event_id)` triple, not from which side is
  considered authoritative by convention

#### Scenario: Duplicate machine_id is refused
- **GIVEN** two peers whose `context_access_state.instance` value is
  identical
- **WHEN** a replication exchange between them is attempted
- **THEN** the exchange is refused with a structured identity-conflict
  diagnostic
- **AND** no event from either peer is merged into the other

### Requirement: Seeding a never-before-synced remote strips ontology rows and triggers a destination-local rebuild
`agent_session_tools.sync._seed_remote_db` SHALL remove every row of the
six ontology tables and `ontology_build_state` from the Online Backup
snapshot before transferring it to a remote that has never been synced. A
freshly seeded remote SHALL contain the ontology schema with zero rows
until its own local rebuild populates it.

#### Scenario: First-time seed of a new remote
- **GIVEN** a remote that has never held `sessions.db`
- **WHEN** `session-sync push <remote>` seeds it for the first time
- **THEN** the transferred database contains zero rows across all six
  ontology tables
- **AND** a subsequent local rebuild on the remote populates them from its
  own `sessions`/`messages` data, not from the source's ontology snapshot
