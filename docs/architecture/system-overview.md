# System Architecture — Socratic Study Mentor

*Source of truth for the overall system architecture. Updated 2026-04-03.*

## 1. High-Level Architecture

```plantuml
@startuml system-overview
skinparam componentStyle rectangle
skinparam backgroundColor #FEFEFE

actor "User" as User
actor "AI Agent\n(Claude)" as Agent

cloud "GitHub" as GH

package "CLI (studyctl)" {
    [study] as Study
    [backlog] as Backlog
    [clean] as Clean
    [review / streaks] as Review
    [doctor / upgrade] as Doctor
    [sync / content] as Sync
    [web] as Web
}

package "MCP Server (studyctl-mcp)" {
    [Course Tools\n(6 existing)] as MCPCourse
    [Session-DB Tools\n(4 new)] as MCPSession
}

package "Logic Layer (logic/)" {
    [backlog_logic.py] as BL
    [clean_logic.py] as CL
    [break_logic.py] as BRK
    [streaks_logic.py] as SL
}

package "Data Layer" {
    [parking.py] as Parking
    [history.py] as History
    [session_state.py] as State
    [review_db.py] as ReviewDB
}

package "TUI" {
    [Textual Sidebar] as Sidebar
}

package "Web Dashboard" {
    [FastAPI + HTMX] as WebApp
    [Vendored Assets\n(HTMX, Alpine, fonts)] as Vendor
}

database "sessions.db\n(SQLite WAL, v17)" as DB
database "review.db\n(SM-2 spaced rep)" as RDB

folder "IPC Files\n(~/.config/studyctl/)" as IPC {
    file "session-state.json"
    file "session-topics.md"
    file "session-parking.md"
}

folder "tmux Session" as Tmux {
    [Agent Pane] as AP
    [Sidebar Pane] as SP
}

User --> Study
User --> Backlog
User --> Clean
User --> Review
User --> Web

Agent --> MCPCourse : tool_call
Agent --> MCPSession : tool_call
Agent --> AP : runs in

Study --> Tmux : creates
Study --> BL : backlog injection
Study --> CL : auto-clean zombies
Study --> State : IPC write
Study --> History : session CRUD

Backlog --> BL : format, score
Backlog --> Parking : CRUD
Clean --> CL : plan + execute

MCPSession --> BL : scoring
MCPSession --> Parking : queries
MCPSession --> History : queries

Sidebar --> State : polls IPC
WebApp --> State : polls IPC
WebApp --> Vendor : serves

Parking --> DB
History --> DB
ReviewDB --> RDB
State --> IPC

GH --> Doctor : CI checks

@enduml
```

## 2. Package Structure

```plantuml
@startuml package-structure
skinparam backgroundColor #FEFEFE
skinparam packageStyle rectangle

package "socratic-study-mentor (monorepo)" {

    package "packages/studyctl" {
        package "cli/" {
            [__init__.py\nLazyGroup registry]
            [_study.py — session orchestrator]
            [_topics.py — backlog CRUD]
            [_clean.py — cleanup shell]
            [_review.py — streaks, progress]
            [_session.py — park, topic]
            [_doctor.py — health checks]
        }
        package "logic/ (FCIS Cores)" {
            [backlog_logic.py]
            [clean_logic.py]
            [break_logic.py]
            [streaks_logic.py]
        }
        package "Data" {
            [parking.py]
            [history.py]
            [session_state.py]
            [tmux.py]
        }
        package "mcp/" {
            [server.py — FastMCP]
            [tools.py — 10 tools]
        }
        package "tui/" {
            [sidebar.py — Textual app]
        }
        package "web/" {
            [app.py — FastAPI]
            [static/ — HTML, CSS, JS]
            [static/vendor/ — vendored deps]
        }
        package "doctor/" {
            [core.py, config.py, database.py]
            [agents.py, deps.py, updates.py]
        }
    }

    package "packages/agent-session-tools" {
        [migrations.py — v0-v17]
        [export_sessions.py]
        [schema.sql — base tables]
    }

    package "agents/" {
        [shared/personas/ — study.md, co-study.md]
        [shared/break-science.md]
        [claude/mcp.json]
        [mcp/README.md]
    }

    package "docs/" {
        [architecture/ — PlantUML diagrams]
        [brainstorms/ — design decisions]
        [mentoring/ — FCIS, patterns]
        [handoff/ — session continuity]
        [setup-guide.md]
        [roadmap.md]
    }
}

@enduml
```

## 3. Session-DB Schema (v17)

```plantuml
@startuml session-db-schema
skinparam backgroundColor #FEFEFE

entity "sessions" as S {
    * id TEXT PK
    --
    source TEXT
    session_type TEXT
    project_path TEXT
    content_hash TEXT
    created_at TEXT
}

entity "messages" as M {
    * id TEXT PK
    --
    session_id FK
    role TEXT
    content TEXT
    model TEXT
    timestamp TEXT
    seq INTEGER
}

entity "study_sessions" as SS {
    * id TEXT PK
    --
    session_id FK
    topic TEXT
    energy_level TEXT
    started_at TEXT
    ended_at TEXT
    duration_minutes INT
    notes TEXT
}

entity "study_progress" as SP {
    * id TEXT PK (uuid5)
    --
    topic TEXT
    concept TEXT
    confidence TEXT
    last_teachback_score INT
    session_count INT
}

entity "teach_back_scores" as TBS {
    * id INT PK
    --
    concept TEXT
    topic TEXT
    session_id FK
    score_accuracy INT (1-4)
    total_score INT
}

entity "parked_topics" as PT {
    * id INT PK
    --
    study_session_id FK (nullable)
    question TEXT
    topic_tag TEXT
    status TEXT
    source TEXT (v16)
    tech_area TEXT (v16)
    priority INT (v17)
    parked_at TEXT
}

entity "concepts" as C {
    * id TEXT PK
    --
    name TEXT
    domain TEXT
    definition TEXT
}

entity "knowledge_bridges" as KB {
    * id INT PK
    --
    source_concept TEXT
    target_concept TEXT
    quality TEXT
    times_used INT
}

S ||--o{ M : session_id
S ||--o| SS : session_id
SS ||--o{ PT : study_session_id
M }|--|| "messages_fts" : FTS5
C ||--o{ KB : concepts

@enduml
```

## 4. Data Flow — Study Session Lifecycle

```plantuml
@startuml session-lifecycle
skinparam backgroundColor #FEFEFE

|studyctl study|
start
:_auto_clean_zombies();
note right: FCIS plan_clean()\nKills resurrect zombies

:_build_backlog_notes(topic);
note right: Inject pending backlog\ninto agent persona

:start_study_session(topic, energy);
note right: INSERT study_sessions

:Create tmux session\n(agent pane + sidebar pane);

|Agent (during session)|
fork
    :Park topic → park_topic(source='parked');
fork again
    :Log struggle → append_topic(status='struggling');
fork again
    :Record progress → record_progress();
fork again
    :MCP: get_topic_suggestions();
fork again
    :MCP: record_topic_progress(priority=5);
end fork

|studyctl study --end|
:parse_topics_file();
:_auto_persist_struggled();
note right: FCIS plan_auto_persist()\nPersist struggled → parked_topics

:end_study_session(notes);
note right: UPDATE study_sessions

:kill_all_study_sessions();
:Clear IPC files;
stop

@enduml
```

## 5. MCP Tools (10 total)

```plantuml
@startuml mcp-tools-overview
skinparam backgroundColor #FEFEFE

package "studyctl-mcp server (FastMCP, stdio)" {
    package "Course Tools (Phase 0)" {
        [list_courses]
        [get_study_context]
        [record_study_progress]
        [generate_flashcards]
        [generate_quiz]
        [get_chapter_text]
    }

    package "Session-DB Tools (Phase 2)" #LightGreen {
        [get_study_backlog]
        [get_topic_suggestions]
        [get_study_history]
        [record_topic_progress]
    }
}

note bottom of [get_topic_suggestions]
    Algorithmic scoring:
    60% importance + 40% frequency
    Uses backlog_logic.score_backlog_items()
end note

note bottom of [record_topic_progress]
    Agent sets priority (1-5)
    on backlog items.
    5 = foundational
    1 = niche
end note

@enduml
```

## 6. FCIS Pattern Usage

| Module | Functional Core | Imperative Shell | Tests |
|--------|----------------|-----------------|-------|
| Clean | `logic/clean_logic.py` → `plan_clean()` | `cli/_clean.py` | `test_clean.py` (17, zero mocks) |
| Backlog | `logic/backlog_logic.py` → `format_backlog_list()`, `score_backlog_items()`, `plan_auto_persist()`, `build_backlog_summary()` | `cli/_topics.py`, `cli/_study.py` | `test_backlog_logic.py` (22, zero mocks) |
| Break | `logic/break_logic.py` → `check_break_needed()`, energy-adaptive thresholds | `tui/sidebar.py` (BreakBanner widget) | `test_break_logic.py` (23, zero mocks) |
| Streaks | `logic/streaks_logic.py` → `analyze_energy_streaks()`, trend detection, duration correlation | `cli/_review.py` | `test_streaks_logic.py` (12, zero mocks) |

**Note**: All FCIS cores live in `studyctl/logic/` subpackage with an empty `__init__.py` (explicit imports, no re-exports). This was created per the 2026-04-03 architecture review recommendation.

## 7. Test Pyramid

```
CI-safe tests (no tmux, no network):     826
Integration tests (real DB):              13
UAT tests (needs tmux):                   57
─────────────────────────────────────────────
Total:                                   896
```

## 8. Current Status & Roadmap

### Completed (v2.2 partial)
- [x] `studyctl clean` command (FCIS)
- [x] tmux-resurrect compatibility (auto-clean + doctor + docs)
- [x] Study Backlog Phase 1 (CRUD, auto-persist, agent injection)
- [x] Study Backlog Phase 2 (scoring, MCP tools, integration tests)
- [x] Vendor HTMX + Alpine.js + OpenDyslexic (offline PWA)
- [x] Schema v17 (source, tech_area, priority columns)

### Completed (v2.2 polish — 2026-04-03)
- [x] **Structural cleanup**: `logic/` subpackage for FCIS cores, service layer fully wired
- [x] **Self-healing DB**: `parking.py:_connect()` two-tier fallback for schema drift
- [x] Break suggestions at timer thresholds (BreakBanner widget + IPC)
- [x] Energy streaks correlation (trend detection, duration analysis)
- [x] Register MCP tools in agent persona (10 tools documented)
- [x] Vendor Google Fonts Inter (zero CDN dependencies, offline PWA)
- [x] Nested tmux UAT test (switch_client path verified)
- [x] `--end` UAT test from outside (kill + cleanup verified)

### Architecture Debt (from 2026-04-03 review)
- [x] Unify config systems — already unified on YAML; removed dead JSON fallback from config_loader.py
- [x] Split `query_sessions.py` monolith → `query_logic.py` (717 lines) + CLI (505 lines)
- [x] Fix CI test failures — `test_cli_session.py` missing `_find_db` patch for headless environments
- [ ] Nightly CI job for UAT tests (macOS runner with tmux) — deferred to Phase 6
- [ ] Fix VSCode circular import — deferred, low priority (no active VSCode users)

### Future Phases
- Phase 6: CI/CD improvements (includes architecture debt above)
- Phase 3: Devices (ttyd + LAN)
- Multi-Agent Support
- Full MCP Agent Integration
