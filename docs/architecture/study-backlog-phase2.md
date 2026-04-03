# Study Backlog Phase 2 — AI Prioritization + Session-DB Integration

*Source of truth for implementation, MCP integration, and test design.*

## 1. System Overview

Phase 2 adds AI-driven topic prioritization and full session-db MCP integration. The agent gains direct read/write access to the session database, enabling real-time topic scoring and study history queries during live sessions.

```plantuml
@startuml system-overview
skinparam componentStyle rectangle
skinparam backgroundColor #FEFEFE

actor "User" as User
actor "AI Agent\n(Claude)" as Agent

package "CLI Layer (Imperative Shell)" {
    [studyctl backlog list] as BList
    [studyctl backlog add] as BAdd
    [studyctl backlog resolve] as BResolve
    [studyctl backlog suggest] as BSuggest
    [studyctl study] as StudyCmd
}

package "MCP Server (studyctl-mcp)" {
    [get_study_backlog] as MCPBacklog
    [get_topic_suggestions] as MCPSuggest
    [get_study_history] as MCPHistory
    [record_topic_progress] as MCPRecord
    [list_courses] as MCPCourses
    [get_study_context] as MCPContext
    [record_study_progress] as MCPProgress
}

package "Logic Layer (Functional Core)" {
    [backlog_logic.py] as BacklogLogic
    note bottom of BacklogLogic
        Pure functions:
        - format_backlog_list()
        - build_backlog_summary()
        - plan_auto_persist()
        - score_backlog_items() <<NEW>>
    end note
}

package "Data Layer" {
    [parking.py] as Parking
    [history.py] as History
    [session_state.py] as SessionState
    [agent_launcher.py] as AgentLauncher
}

database "session.db\n(SQLite WAL)" as DB {
    [study_sessions]
    [parked_topics]
    [study_progress]
    [teach_back_scores]
    [concepts]
    [knowledge_bridges]
    [sessions]
    [messages]
}

User --> BList
User --> BAdd
User --> BSuggest
User --> StudyCmd

Agent --> MCPBacklog : tool_call
Agent --> MCPSuggest : tool_call
Agent --> MCPHistory : tool_call
Agent --> MCPRecord : tool_call

MCPBacklog --> Parking
MCPSuggest --> BacklogLogic
MCPHistory --> History
MCPRecord --> History

BList --> BacklogLogic
BSuggest --> BacklogLogic
StudyCmd --> BacklogLogic

BacklogLogic ..> Parking : reads (via shell)
BacklogLogic ..> History : reads (via shell)
Parking --> DB
History --> DB

@enduml
```

## 2. Session-DB Architecture

The session database is the **central data store** for all study state. It uses SQLite WAL mode for concurrent read/write from CLI, MCP server, and background processes.

```plantuml
@startuml session-db-architecture
skinparam backgroundColor #FEFEFE

database "~/.config/studyctl/sessions.db" as DB {

    package "Core Tables (v0-v8)" {
        entity "sessions" as S {
            id TEXT PK
            source TEXT
            session_type TEXT
            project_path TEXT
            created_at TEXT
        }
        entity "messages" as M {
            id TEXT PK
            session_id FK
            role TEXT
            content TEXT
            timestamp TEXT
        }
        entity "messages_fts" as FTS {
            (FTS5 virtual table)
            content TEXT
        }
    }

    package "Study Tables (v9-v13)" {
        entity "study_sessions" as SS {
            id TEXT PK
            session_id FK
            topic TEXT
            energy_level TEXT
            started_at TEXT
            ended_at TEXT
            duration_minutes INT
            notes TEXT
        }
        entity "study_progress" as SP {
            id TEXT PK (uuid5)
            topic TEXT
            concept TEXT
            confidence TEXT
            last_teachback_score INT
            session_count INT
        }
        entity "teach_back_scores" as TBS {
            id INT PK
            concept TEXT
            topic TEXT
            score_accuracy INT (1-4)
            score_own_words INT (1-4)
            score_structure INT (1-4)
            total_score INT
        }
        entity "concepts" as C {
            id TEXT PK
            name TEXT
            domain TEXT
            definition TEXT
        }
        entity "knowledge_bridges" as KB {
            id INT PK
            source_concept TEXT
            target_concept TEXT
            quality TEXT
            times_used INT
        }
    }

    package "Backlog Tables (v14-v17)" {
        entity "parked_topics" as PT {
            id INT PK
            study_session_id FK
            question TEXT
            topic_tag TEXT
            status TEXT
            source TEXT
            tech_area TEXT
            **priority INT** <<v17>>
            parked_at TEXT
        }
    }
}

S ||--o{ M : session_id
S ||--o| SS : session_id
SS ||--o{ PT : study_session_id
M }|--|| FTS : content sync
SP }o--o{ TBS : concept+topic
C ||--o{ KB : source/target

@enduml
```

## 3. Session Types and Data Flow

```plantuml
@startuml session-lifecycle
skinparam backgroundColor #FEFEFE

|User|
start
:studyctl study "Python Decorators"\n--energy 7 --mode study;

|CLI (_study.py)|
:_auto_clean_zombies();
note right: Kill resurrect zombies\n(FCIS plan_clean)

:_build_backlog_notes(topic);
note right: Inject pending backlog\ninto agent persona

:start_study_session(topic, energy);
note right: INSERT study_sessions

:create tmux session;
:launch agent + sidebar;

|Agent (Claude)|
:Study session active;

fork
    :Agent parks topic;
    :park_topic(question, source='parked');
    note right: INSERT parked_topics
fork again
    :Agent logs struggle;
    :append_topic(status='struggling');
    note right: Write to session-topics.md\n(IPC file)
fork again
    :Agent records progress;
    :record_progress(topic, concept, confidence);
    note right: INSERT/UPDATE study_progress
fork again
    :Agent queries backlog (MCP);
    :get_study_backlog();
    note right: SELECT parked_topics\nWHERE status='pending'
fork again
    :Agent gets suggestions (MCP);
    :get_topic_suggestions();
    note right: Algorithmic scoring\nvia backlog_logic.py
end fork

|CLI (_study.py)|
:User presses Q or --end;

:_auto_persist_struggled(topic_entries);
note right: Scan session-topics.md\nPersist struggled → parked_topics\nwith source='struggled'

:end_study_session(study_id, notes);
note right: UPDATE study_sessions\nSET ended_at, duration

:kill tmux session;
stop

@enduml
```

### Session Types

| Mode | CLI Flag | Timer Default | Description |
|------|----------|--------------|-------------|
| `study` | `--mode study` (default) | elapsed | Solo study with AI mentor |
| `co-study` | `--mode co-study` | pomodoro | Collaborative study session |

Both modes flow through the same data pipeline — the mode affects only the agent persona and timer behaviour, not the DB schema.

### Imported Session Types

`sessions.session_type` is auto-classified by `classifier.py` post-import:

| Type | Source |
|------|--------|
| `claude_code` | Claude Code conversations |
| `kiro_cli` | Kiro CLI sessions |
| `gemini` | Gemini CLI |
| `aider` | Aider chat history |
| `litellm` | LiteLLM proxy logs |

## 4. Scoring Pipeline (FCIS)

```plantuml
@startuml scoring-pipeline
skinparam backgroundColor #FEFEFE

rectangle "Imperative Shell" as Shell #FFB347 {
    (studyctl backlog suggest) as CLI
    (get_topic_suggestions MCP) as MCP
}

rectangle "Functional Core\nbacklog_logic.py" as Core #90EE90 {
    (score_backlog_items) as Score
    note bottom of Score
        Pure function:
        Input: list[ScoringInput]
        Output: list[TopicSuggestion]
        No I/O, no DB calls
    end note
}

rectangle "Data Gathering" as Gather #FFB6C1 {
    (parking.py) as P
    (history.py) as H
    database "sessions.db" as DB
}

CLI --> P : get_parked_topics(status='pending')
CLI --> H : get_study_session_stats()
MCP --> P : same queries
MCP --> H : same queries

CLI --> Score : ScoringInput (pre-gathered)
MCP --> Score : ScoringInput (pre-gathered)

Score --> CLI : list[TopicSuggestion]
Score --> MCP : list[TopicSuggestion]

P --> DB
H --> DB

@enduml
```

### Scoring Model

```python
@dataclass
class ScoringInput:
    """Pre-gathered data for a single backlog item."""
    item: BacklogItem
    frequency: int           # count of times this topic appears in parked_topics
    priority: int | None     # agent-assessed importance (1-5), None = unassessed
    last_studied: str | None # ISO datetime from study_sessions


@dataclass
class TopicSuggestion:
    """A scored and ranked topic suggestion."""
    item: BacklogItem
    score: float             # 0.0 - 1.0, higher = study this next
    frequency: int
    priority: int            # effective priority (default 3 if unassessed)
    reasoning: str           # human-readable explanation of the score
```

**Score formula:**

```
effective_priority = priority if priority is not None else 3
normalized_frequency = min(frequency / max_frequency, 1.0)  # 0-1 range
normalized_priority = effective_priority / 5.0               # 0-1 range

score = (0.4 * normalized_frequency) + (0.6 * normalized_priority)
```

Importance weighs 60%, frequency 40% — fundamental topics rank higher even if they've only been parked once.

## 5. MCP Tools Specification

```plantuml
@startuml mcp-tools
skinparam backgroundColor #FEFEFE
skinparam packageStyle rectangle

package "studyctl-mcp server" {

    package "Existing Tools (Phase 0)" {
        [list_courses] as LC
        [get_study_context] as GSC
        [record_study_progress] as RSP
        [generate_flashcards] as GF
        [generate_quiz] as GQ
        [get_chapter_text] as GCT
    }

    package "New Tools (Phase 2)" #LightGreen {
        [get_study_backlog] as GSB
        note bottom of GSB
            Read: pending backlog items
            Params: tech_area?, source?, limit?
            Returns: list of items with scores
        end note

        [get_topic_suggestions] as GTS
        note bottom of GTS
            Read: ranked suggestions
            Params: limit?, current_topic?
            Returns: scored + sorted items
        end note

        [get_study_history] as GSH
        note bottom of GSH
            Read: study history for topic
            Params: topic, days?
            Returns: sessions, progress, scores
        end note

        [record_topic_progress] as RTP
        note bottom of RTP
            Write: update progress + priority
            Params: topic_id, confidence?,
                    priority?, teach_back_scores?
            Returns: success boolean
        end note
    }
}

database "sessions.db" as DB
[parking.py] as P
[history.py] as H
[backlog_logic.py] as BL

GSB --> P
GTS --> BL
GTS --> P
GTS --> H
GSH --> H
RTP --> H
RTP --> P

P --> DB
H --> DB

@enduml
```

### Tool Signatures

```python
@mcp.tool()
def get_study_backlog(
    tech_area: str | None = None,
    source: str | None = None,
    status: str = "pending",
    limit: int = 20,
) -> dict[str, Any]:
    """Get study backlog items with optional filters."""


@mcp.tool()
def get_topic_suggestions(
    limit: int = 10,
    current_topic: str | None = None,
) -> dict[str, Any]:
    """Get AI-ranked topic suggestions based on frequency and importance."""


@mcp.tool()
def get_study_history(
    topic: str,
    days: int = 30,
) -> dict[str, Any]:
    """Get study history for a topic: sessions, progress, teach-back scores."""


@mcp.tool()
def record_topic_progress(
    topic_id: int,
    priority: int | None = None,
    confidence: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Update a backlog topic's priority or mark progress."""
```

## 6. Test Architecture

```plantuml
@startuml test-architecture
skinparam backgroundColor #FEFEFE

package "Unit Tests (no mocks, no DB)" as Unit {
    [test_backlog_logic.py] as TBL
    note bottom of TBL
        Existing: format, summary, persist
        New: score_backlog_items()
        ---
        ~15 tests, plain data in/out
    end note
}

package "CLI Tests (CliRunner + mocks)" as CLI {
    [test_topics_cli.py] as TTC
    note bottom of TTC
        Existing: list, add, resolve
        New: suggest command
        ---
        ~12 tests, mock parking.py
    end note
}

package "MCP Tests (FastMCP test client)" as MCP {
    [test_mcp_session_tools.py] as TMT
    note bottom of TMT
        New: all 4 MCP tools
        ---
        ~8 tests, real temp DB
    end note
}

package "Integration Tests (real DB)" as Integration {
    [test_session_db_integration.py] as TSDI
    note bottom of TSDI
        New: full pipeline tests
        - study session lifecycle
        - co-study session lifecycle
        - park → score → suggest flow
        - struggled auto-persist → scoring
        - migration v17
        ---
        ~12 tests, @pytest.mark.integration
    end note
}

@enduml
```

### Test Matrix

| Test File | Layer | What It Tests | Mocks? | DB? |
|-----------|-------|---------------|--------|-----|
| `test_backlog_logic.py` | Unit | scoring, formatting, persist planning | None | No |
| `test_topics_cli.py` | CLI | suggest command output + args | parking.py | No |
| `test_mcp_session_tools.py` | MCP | 4 new tools via test client | None | Yes (tmp) |
| `test_session_db_integration.py` | Integration | Full session lifecycle for all types | None | Yes (tmp) |

## 7. Implementation Order

```plantuml
@startuml implementation-order
skinparam backgroundColor #FEFEFE

|Phase|
:1. Architecture doc (this file);
note right: Source of truth — done
:2. Migration v17 (priority column);
note right: Schema foundation
:3. Scoring logic + unit tests;
note right: FCIS core, TDD
:4. suggest CLI command + tests;
note right: CLI shell
:5. 4 MCP tools + tests;
note right: Agent integration
:6. Session-db integration tests;
note right: All session types
:7. Full suite + lint;

@enduml
```

## 8. File Inventory

| File | Action | Description |
|------|--------|-------------|
| `agent-session-tools/.../migrations.py` | Modify | Add migration v17 (priority column) |
| `studyctl/backlog_logic.py` | Modify | Add `score_backlog_items()`, `ScoringInput`, `TopicSuggestion` |
| `studyctl/parking.py` | Modify | Add `update_topic_priority()`, `get_topic_frequency()` |
| `studyctl/cli/_topics.py` | Modify | Add `suggest` subcommand |
| `studyctl/mcp/tools.py` | Modify | Register 4 new MCP tools |
| `tests/test_backlog_logic.py` | Modify | Add scoring tests |
| `tests/test_topics_cli.py` | Modify | Add suggest CLI tests |
| `tests/test_mcp_session_tools.py` | **Create** | MCP tool tests |
| `tests/test_session_db_integration.py` | **Create** | Full lifecycle integration tests |
| `tests/test_parking.py` | Modify | Update fixture for v17 |
| `tests/test_cli_session.py` | Modify | Update fixture for v17 |
