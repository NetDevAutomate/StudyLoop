# Study Backlog Phase 1 — Software Architecture

*Source of truth for implementation and test design.*

## 1. System Overview

The Study Backlog is a **query layer** over the existing `parked_topics` table — no new tables. It surfaces pending topics across sessions via CLI commands, auto-persists struggled topics at session end, and injects backlog context into the agent at session start.

```plantuml
@startuml component-overview
skinparam componentStyle rectangle
skinparam backgroundColor #FEFEFE

package "CLI Layer (Imperative Shell)" {
    [studyctl topics list] as TopicsList
    [studyctl topics add] as TopicsAdd
    [studyctl topics resolve] as TopicsResolve
    [studyctl study] as StudyCmd
}

package "Logic Layer (Functional Core)" {
    [backlog_logic.py] as BacklogLogic
    note right of BacklogLogic
        Pure functions:
        - format_backlog_list()
        - build_backlog_summary()
        - plan_auto_persist()
    end note
}

package "Data Layer (Existing)" {
    [parking.py] as Parking
    [session_state.py] as SessionState
    [agent_launcher.py] as AgentLauncher
    database sessions.db {
        [parked_topics] as PT
    }
}

TopicsList --> BacklogLogic : query results
TopicsAdd --> Parking : park_topic()
TopicsResolve --> Parking : resolve_parked_topic()
StudyCmd --> BacklogLogic : build_backlog_summary()
StudyCmd --> AgentLauncher : inject into persona

BacklogLogic ..> Parking : reads via get_parked_topics()
StudyCmd --> Parking : auto-persist struggled

Parking --> PT : SQL
SessionState --> [session-topics.md] : IPC file

@enduml
```

## 2. Data Model

### 2.1 Current Schema (v15)

```plantuml
@startuml er-current
skinparam backgroundColor #FEFEFE

entity "parked_topics" as pt {
    * id : INTEGER <<PK, AUTOINCREMENT>>
    --
    study_session_id : TEXT <<FK → study_sessions.id>>
    session_id : TEXT <<FK → sessions.id>>
    topic_tag : TEXT
    * question : TEXT
    context : TEXT
    * status : TEXT {pending|scheduled|resolved|dismissed}
    scheduled_for : TEXT
    resolved_at : TEXT
    * parked_at : TEXT (datetime)
    created_by : TEXT (default 'agent')
}

entity "study_sessions" as ss {
    * id : TEXT <<PK>>
    --
    topic : TEXT
    energy_level : INTEGER
    started_at : TEXT
    ended_at : TEXT
    duration_minutes : INTEGER
    notes : TEXT
}

pt }o--|| ss : study_session_id

note bottom of pt
    Unique index:
    uix_parked_topics_session_question
    ON (study_session_id, question)
end note

@enduml
```

### 2.2 Migration v16 Changes

```plantuml
@startuml er-v16-changes
skinparam backgroundColor #FEFEFE

entity "parked_topics (v16)" as pt {
    * id : INTEGER <<PK, AUTOINCREMENT>>
    --
    study_session_id : TEXT <<FK, NULLABLE>>
    session_id : TEXT <<FK, NULLABLE>>
    topic_tag : TEXT
    * question : TEXT
    context : TEXT
    * status : TEXT {pending|scheduled|resolved|dismissed}
    scheduled_for : TEXT
    resolved_at : TEXT
    * parked_at : TEXT (datetime)
    created_by : TEXT (default 'agent')
    **source : TEXT {parked|struggled|manual}** <<NEW, default 'parked'>>
    **tech_area : TEXT** <<NEW, nullable>>
}

note right of pt
    v16 migration:
    1. ADD source TEXT DEFAULT 'parked'
       CHECK(source IN ('parked','struggled','manual'))
    2. ADD tech_area TEXT
    3. FKs already nullable (SET NULL on delete)
    4. Update unique index to include source
end note

@enduml
```

**Migration v16 SQL:**

```sql
-- Add source column to distinguish parked/struggled/manual entries
ALTER TABLE parked_topics
    ADD COLUMN source TEXT NOT NULL DEFAULT 'parked'
    CHECK(source IN ('parked', 'struggled', 'manual'));

-- Add tech_area for technology categorization
ALTER TABLE parked_topics
    ADD COLUMN tech_area TEXT;

-- Update unique index to allow same question from different sources
DROP INDEX IF EXISTS uix_parked_topics_session_question;
CREATE UNIQUE INDEX uix_parked_topics_session_question
    ON parked_topics (study_session_id, question, source);
```

## 3. Command Flows

### 3.1 `studyctl topics list`

```plantuml
@startuml seq-topics-list
skinparam backgroundColor #FEFEFE
actor User
participant "CLI Shell\n_topics.py" as CLI
participant "Functional Core\nbacklog_logic.py" as Logic
participant "parking.py" as Parking
database "sessions.db" as DB

User -> CLI : studyctl topics list [--tech python] [--status pending]
activate CLI

CLI -> Parking : get_parked_topics(status="pending")
activate Parking
Parking -> DB : SELECT * FROM parked_topics\nWHERE status = 'pending'\nORDER BY parked_at DESC
DB --> Parking : rows
Parking --> CLI : list[dict]
deactivate Parking

CLI -> Logic : format_backlog_list(items, filters)
activate Logic
Logic --> CLI : FormattedBacklog(items, counts, grouped_by_tech)
deactivate Logic

CLI -> User : Rich table output
deactivate CLI

@enduml
```

### 3.2 `studyctl topics add`

```plantuml
@startuml seq-topics-add
skinparam backgroundColor #FEFEFE
actor User
participant "CLI Shell\n_topics.py" as CLI
participant "parking.py" as Parking
database "sessions.db" as DB

User -> CLI : studyctl topics add "Decorators" --tech Python --note "Need deeper dive"
activate CLI

CLI -> Parking : park_topic(\n  question="Decorators",\n  topic_tag="Python",\n  context="Need deeper dive",\n  study_session_id=None,\n  created_by="cli"\n)
activate Parking
note right: source='manual' added\nby new parameter
Parking -> DB : INSERT INTO parked_topics\n(question, topic_tag, context,\nsource, tech_area, created_by)\nVALUES (...)
DB --> Parking : id
Parking --> CLI : id
deactivate Parking

CLI -> User : "Added topic #42: Decorators [Python]"
deactivate CLI

@enduml
```

### 3.3 `studyctl topics resolve`

```plantuml
@startuml seq-topics-resolve
skinparam backgroundColor #FEFEFE
actor User
participant "CLI Shell\n_topics.py" as CLI
participant "parking.py" as Parking
database "sessions.db" as DB

User -> CLI : studyctl topics resolve 42
activate CLI

CLI -> Parking : resolve_parked_topic(42)
activate Parking
Parking -> DB : UPDATE parked_topics\nSET status='resolved',\nresolved_at=datetime('now')\nWHERE id=42 AND status='pending'
DB --> Parking : rowcount
Parking --> CLI : bool (success)
deactivate Parking

alt success
    CLI -> User : "Resolved topic #42: Decorators"
else not found or already resolved
    CLI -> User : "Topic #42 not found or already resolved"
end

deactivate CLI

@enduml
```

### 3.4 Auto-persist Struggled Topics (Session End)

```plantuml
@startuml seq-auto-persist
skinparam backgroundColor #FEFEFE
participant "CLI Shell\n_study.py" as Study
participant "Functional Core\nbacklog_logic.py" as Logic
participant "session_state.py" as State
participant "parking.py" as Parking
database "sessions.db" as DB

Study -> State : parse_topics_file()
activate State
State --> Study : list[TopicEntry]
deactivate State

Study -> Logic : plan_auto_persist(topic_entries)
activate Logic
note right of Logic
    Pure logic:
    Filter for status='struggling'
    Deduplicate against existing parked
    Return list of PersistAction
end note
Logic --> Study : list[PersistAction]
deactivate Logic

loop for each PersistAction
    Study -> Parking : park_topic(\n  question=entry.topic,\n  topic_tag=entry.topic,\n  context=entry.note,\n  study_session_id=session_id,\n  source='struggled'\n)
    activate Parking
    Parking -> DB : INSERT OR IGNORE INTO parked_topics
    Parking --> Study : id | None
    deactivate Parking
end

@enduml
```

### 3.5 Agent Backlog Surfacing (Session Start)

```plantuml
@startuml seq-agent-surfacing
skinparam backgroundColor #FEFEFE
participant "CLI Shell\n_study.py" as Study
participant "Functional Core\nbacklog_logic.py" as Logic
participant "parking.py" as Parking
participant "agent_launcher.py" as Agent
database "sessions.db" as DB

Study -> Parking : get_parked_topics(status="pending")
activate Parking
Parking -> DB : SELECT * FROM parked_topics\nWHERE status='pending'
DB --> Parking : rows
Parking --> Study : list[dict]
deactivate Parking

Study -> Logic : build_backlog_summary(pending_topics, current_topic)
activate Logic
note right of Logic
    Pure function:
    - Filter by relevance to current topic
    - Format as markdown snippet
    - "You have 3 outstanding topics:
       - Decorators [Python]
       - Window Functions [SQL]"
    Returns: str | None
end note
Logic --> Study : summary_text or None
deactivate Logic

Study -> Agent : build_persona_file(\n  ...,\n  previous_notes=summary_text\n)
activate Agent
note right: Injected into the\n"Resuming Previous Session"\nsection of the persona file
Agent --> Study : persona_path
deactivate Agent

@enduml
```

## 4. Module Structure

```plantuml
@startuml package-structure
skinparam backgroundColor #FEFEFE
skinparam packageStyle rectangle

package "studyctl/cli/" {
    [_topics.py] as Topics <<NEW>>
    note bottom of Topics
        Click group: topics
        Commands: list, add, resolve
        Imperative shell only
    end note

    [__init__.py] as Init
    note bottom of Init
        Register: "topics"
        → studyctl.cli._topics:topics_group
    end note
}

package "studyctl/cli/" {
    [_study.py] as Study <<MODIFIED>>
    note bottom of Study
        _handle_start: inject backlog
        _handle_end: auto-persist
    end note
}

package "studyctl/" {
    [backlog_logic.py] as BL <<NEW>>
    note bottom of BL
        FCIS Functional Core:
        - format_backlog_list()
        - build_backlog_summary()
        - plan_auto_persist()
        Pure functions, no I/O
    end note
}

package "studyctl/" {
    [parking.py] as Parking <<MODIFIED>>
    note bottom of Parking
        park_topic(): add source param
        get_parked_topics(): add source filter
    end note
}

package "agent-session-tools/" {
    [migrations.py] as Mig <<MODIFIED>>
    note bottom of Mig
        v16: ADD source, tech_area
        to parked_topics
    end note
}

Topics --> BL : format/filter
Study --> BL : summary/persist plan
Topics --> Parking : CRUD
Study --> Parking : auto-persist + query
Parking --> Mig : schema

@enduml
```

## 5. FCIS Architecture — `backlog_logic.py`

Following the Functional Core, Imperative Shell pattern established in `_clean_logic.py`:

```plantuml
@startuml fcis-backlog
skinparam backgroundColor #FEFEFE

rectangle "Functional Core\nbacklog_logic.py" as Core #90EE90 {
    (format_backlog_list) as FBL
    (build_backlog_summary) as BBS
    (plan_auto_persist) as PAP
}

rectangle "Imperative Shell" as Shell #FFB347 {
    rectangle "CLI Commands\n_topics.py" as TopicsCLI {
        (topics list) as TL
        (topics add) as TA
        (topics resolve) as TR
    }
    rectangle "Study Command\n_study.py" as StudyCLI {
        (_handle_start) as HS
        (_handle_end) as HE
    }
}

rectangle "I/O Boundary" as IO #FFB6C1 {
    (parking.py) as P
    (session_state.py) as SS
    (agent_launcher.py) as AL
    database "sessions.db" as DB
}

TL --> FBL : plain data in
HS --> BBS : plain data in
HE --> PAP : plain data in

FBL --> TL : FormattedBacklog out
BBS --> HS : summary string out
PAP --> HE : PersistAction list out

TL --> P : gather
HS --> P : gather
HE --> SS : gather (parse topics)
HE --> P : execute (persist)
HS --> AL : execute (inject)
P --> DB

note bottom of Core
    Zero imports from parking, session_state, or DB.
    Takes data in, returns data out.
    Testable with plain asserts, no mocks.
end note

@enduml
```

### Core Data Types

```python
@dataclass
class BacklogItem:
    """A single backlog entry — pre-fetched from DB."""
    id: int
    question: str
    topic_tag: str | None
    tech_area: str | None
    source: str          # parked | struggled | manual
    context: str | None
    parked_at: str
    session_topic: str | None  # from study_sessions.topic via join


@dataclass
class FormattedBacklog:
    """Result of format_backlog_list() — ready for display."""
    items: list[BacklogItem]
    total: int
    by_tech: dict[str, list[BacklogItem]]  # grouped by tech_area
    by_source: dict[str, int]              # count per source


@dataclass
class PersistAction:
    """A struggled topic to persist to parked_topics."""
    question: str
    topic_tag: str | None
    context: str | None
    study_session_id: str
    source: str  # 'struggled'
```

### Core Functions

```python
def format_backlog_list(
    items: list[BacklogItem],
    *,
    tech_filter: str | None = None,
    source_filter: str | None = None,
) -> FormattedBacklog:
    """Filter and group backlog items for display. Pure logic."""


def build_backlog_summary(
    pending_items: list[BacklogItem],
    current_topic: str,
) -> str | None:
    """Build markdown snippet for agent persona injection.

    Returns None if no pending items. Prioritises items
    matching current_topic's tech area.
    """


def plan_auto_persist(
    topic_entries: list[TopicEntry],
    existing_questions: set[str],
    study_session_id: str,
) -> list[PersistAction]:
    """Decide which struggled topics to persist.

    Filters for status='struggling', deduplicates against
    existing_questions (already in parked_topics for this session).
    """
```

## 6. Test Architecture

```plantuml
@startuml test-architecture
skinparam backgroundColor #FEFEFE

package "Unit Tests (no mocks, no DB)" as Unit {
    [test_backlog_logic.py] as TBL
    note bottom of TBL
        Tests format_backlog_list()
        Tests build_backlog_summary()
        Tests plan_auto_persist()
        ---
        Pattern: call function with
        plain data, assert on result
        No mocks, no patches
    end note
}

package "CLI Tests (CliRunner + DB mocks)" as CLI {
    [test_topics_cli.py] as TTC
    note bottom of TTC
        Tests topics list/add/resolve
        commands via Click CliRunner
        ---
        Pattern: patch parking.py
        functions, verify CLI output
        and exit codes
    end note
}

package "Integration Tests (real DB)" as Integration {
    [test_backlog_integration.py] as TBI
    note bottom of TBI
        Tests migration v16
        Tests park_topic with source param
        Tests auto-persist end-to-end
        ---
        Pattern: tmp_path SQLite DB,
        real SQL, verify data integrity
        @pytest.mark.integration
    end note
}

TBL -[hidden]-> TTC
TTC -[hidden]-> TBI

note "Test Pyramid:\n~15 unit (fast, no I/O)\n~8 CLI (CliRunner)\n~5 integration (real DB)" as N

@enduml
```

### Test Matrix

| Test File | Layer | What It Tests | Mocks? | DB? |
|-----------|-------|---------------|--------|-----|
| `test_backlog_logic.py` | Unit | `format_backlog_list()`, `build_backlog_summary()`, `plan_auto_persist()` | None | No |
| `test_topics_cli.py` | CLI | `topics list`, `topics add`, `topics resolve` commands | parking.py functions | No |
| `test_backlog_integration.py` | Integration | Migration v16, park_topic with source, auto-persist flow | None | Yes (tmp) |

### Key Test Cases

**Unit (backlog_logic.py):**
- Empty backlog → `FormattedBacklog` with zero items
- Filter by tech_area → only matching items
- Filter by source → only matching items
- Group by tech → correct bucketing
- `build_backlog_summary` with no items → None
- `build_backlog_summary` prioritises current topic's tech
- `plan_auto_persist` filters only struggling status
- `plan_auto_persist` deduplicates against existing
- `plan_auto_persist` with no struggled → empty list

**CLI (topics commands):**
- `topics list` with no items → "No pending topics"
- `topics list` with items → table output
- `topics list --tech Python` → filtered output
- `topics add` → success message with ID
- `topics resolve 42` → success message
- `topics resolve 999` → "not found" error

**Integration (real DB):**
- Migration v16 runs cleanly on v15 schema
- `park_topic(source='manual')` with NULL session refs
- `park_topic(source='struggled')` with session ref
- `get_parked_topics()` returns source and tech_area
- Unique index allows same question from different sources
- Auto-persist end-to-end: parse topics → plan → persist → query

## 7. File Inventory

| File | Action | Description |
|------|--------|-------------|
| `agent-session-tools/.../migrations.py` | Modify | Add migration v16 (source, tech_area columns) |
| `studyctl/backlog_logic.py` | **Create** | FCIS functional core — pure logic |
| `studyctl/parking.py` | Modify | Add `source` param to `park_topic()`, `tech_area` param |
| `studyctl/cli/_topics.py` | **Create** | Click group with list/add/resolve commands |
| `studyctl/cli/__init__.py` | Modify | Register `topics` lazy command |
| `studyctl/cli/_study.py` | Modify | Inject backlog in `_handle_start`, auto-persist in `_handle_end` |
| `tests/test_backlog_logic.py` | **Create** | Unit tests for pure logic |
| `tests/test_topics_cli.py` | **Create** | CLI tests for topics commands |
| `tests/test_backlog_integration.py` | **Create** | Integration tests (marked, not CI) |

## 8. Implementation Order

```plantuml
@startuml implementation-order
skinparam backgroundColor #FEFEFE

|Phase|
:1. Migration v16;
note right: Foundation — schema must exist first
:2. parking.py updates;
note right: Add source + tech_area params
:3. backlog_logic.py + tests;
note right: FCIS core, TDD — tests first
:4. _topics.py CLI + tests;
note right: CLI shell, test with CliRunner
:5. _study.py: auto-persist at end;
note right: Persist struggled topics
:6. _study.py: backlog surfacing at start;
note right: Inject into agent persona
:7. Integration tests;
note right: End-to-end with real DB
:8. Full test suite + lint;

@enduml
```

Each phase is independently committable.
