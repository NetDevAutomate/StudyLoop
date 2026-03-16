# Architecture Review: Deepened Implementation Plan

**Date**: 2026-03-15
**Reviewer**: Architecture Strategist Agent
**Scope**: A1-A4, B1-B4 execution order, cross-package boundaries, schema migration, state machine design

---

## 1. Execution Order Assessment

**Proposed**: A1 -> A2 -> A3 -> migration -> A4 -> B1-B4

**Verdict**: Mostly correct, with one hidden ordering issue.

### A1 (ExportStats) and A2 (concepts.py extraction) are truly independent
Both can proceed in any order. A1 touches agent-session-tools exporters; A2 touches studyctl/history.py extraction. No shared surface.

### A3 depends on A2, not just A4
The plan states A3 -> A4 because "course name must match card_reviews records." But A3 (course picker using OptionList) also needs `discover_directories()` output, which already exists in `review_loader.py`. That dependency is satisfied. However, if the course picker is also meant to show concept counts or progress per course, it would need A2's `list_concepts()`. **Clarify whether A3 displays concept metadata.** If yes, A2 must precede A3.

### Migration must precede A4 -- confirmed correct
The `session_id` FK and `is_retry` column on `card_reviews` are prerequisites for A4's state machine to record retry context. No issue here.

### Hidden ordering risk: migration timing vs A3
If A3's course picker queries `card_reviews` for stats (e.g., "12 cards due"), it will work fine pre-migration since the new columns are additive. But if A3 reads `is_retry` to filter display, it must run post-migration. **Recommendation**: keep A3 before migration as planned, but ensure A3 queries do not reference `is_retry` or `session_id` FK columns.

---

## 2. concepts.py Extraction -- Import Cycle Risk

### Current state
`history.py` is a 300+ line module containing:
- Session management (start/end study sessions)
- Spaced repetition scheduling
- Concept/progress tracking (`record_progress`, `study_progress` table)
- Knowledge bridges and concept graph operations
- Teach-back scoring

### Extraction plan
Move concept-related functions into a new `concepts.py` with a `Concept` dataclass.

### Import cycle analysis

**No cycle risk.** Here is why:

- `history.py` imports: `sqlite3`, `uuid`, `datetime`, `config_path.get_db_path` -- all internal or stdlib.
- `concepts.py` would import the same: `sqlite3`, `config_path.get_db_path`, dataclass types.
- Neither module needs to import the other at definition time.
- The TUI (`app.py`) imports from `history` for dashboard and from `review_db` for cards. It would add `from studyctl.concepts import list_concepts` -- a clean leaf import.

**One caution**: if `concepts.py` needs `_connect()` (the private helper in `history.py`), do NOT import it cross-module. Instead, extract `_connect()` into `config_path.py` or a shared `db.py` module. This avoids the `concepts -> history` import that could create a future cycle if `history` ever imports from `concepts`.

**Recommendation**: Create a small `studyctl/db.py` with `get_connection() -> sqlite3.Connection | None` that both `history.py` and `concepts.py` import from. This is the Dependency Inversion principle -- both modules depend on an abstraction (db.py) rather than on each other.

---

## 3. Schema Migration Safety -- Nullable session_id FK

### Current card_reviews schema (studyctl-owned, CREATE TABLE IF NOT EXISTS)
```sql
card_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course TEXT NOT NULL,
    card_type TEXT NOT NULL,
    card_hash TEXT NOT NULL,
    correct BOOLEAN NOT NULL,
    reviewed_at TEXT NOT NULL,
    ease_factor REAL DEFAULT 2.5,
    interval_days INTEGER DEFAULT 1,
    next_review TEXT,
    response_time_ms INTEGER
)
```

### Proposed additions
- `session_id TEXT REFERENCES review_sessions(id)` -- nullable FK
- `is_retry BOOLEAN DEFAULT 0`

### Safety analysis

**SQLite limitation**: `ALTER TABLE ADD COLUMN` with a `REFERENCES` clause is syntactically accepted but SQLite does NOT enforce FK constraints added via ALTER TABLE on existing rows. This is safe for existing data -- NULL values in `session_id` will not cause constraint violations because:
1. FK constraints allow NULL by default (NULL means "no relationship").
2. `PRAGMA foreign_keys=ON` only validates non-NULL FK values.

**However**: The `review_sessions` table uses `INTEGER PRIMARY KEY AUTOINCREMENT` for its `id`, but the proposed FK is `TEXT`. This is a type mismatch. SQLite's type affinity system will not reject it, but it creates a semantic inconsistency. **Recommendation**: Either change `review_sessions.id` to TEXT (breaking change) or make `card_reviews.session_id` an INTEGER. The cleaner path is INTEGER, matching the existing review_sessions schema.

### Migration ownership question
This migration modifies `card_reviews` and `review_sessions`, which are studyctl-owned tables created via `review_db.ensure_tables()`. The agent-session-tools migration system (versions 1-12 in `migrations.py`) manages sessions/messages tables. **These are separate migration domains.**

**Critical recommendation**: Do NOT add this migration to agent-session-tools' `migrations.py`. Create a separate migration mechanism for studyctl-owned tables, or handle it within `review_db.ensure_tables()` using `PRAGMA table_info` column checks (the same pattern agent-session-tools uses in its v1 migration). This maintains the ownership boundary.

---

## 4. State Machine vs Screen Promotion (A4)

### Context
The TUI uses `TabbedContent` with `StudyCardsTab` mounted as a widget inside the "StudyCards" tab pane. The plan proposes a state machine for "Review Wrong Answers" flow.

### Analysis: State machine is the correct choice

**Why NOT Screen push/pop**:
- `StudyCardsTab` is a `Widget`, not a `Screen`. Promoting it to a Screen would require restructuring the entire tab composition model.
- Textual's `push_screen` creates a modal overlay that obscures the tab bar. Users lose navigation context.
- The current `_launch_study` pattern replaces widget children within the existing container -- the state machine fits this pattern naturally.

**State machine design recommendation**:

Use an enum-based state machine within `StudyCardsTab`:

```
STUDYING -> SUMMARY -> RETRY_PROMPT -> STUDYING (filtered to wrong cards)
                    -> DONE
```

States:
- `STUDYING`: Current card review loop (already exists implicitly).
- `SUMMARY`: Session complete screen with score (already exists as `_show_summary`).
- `RETRY_PROMPT`: "Review N wrong answers?" confirmation.
- `DONE`: Final state, no further transitions.

The `is_retry` flag on `card_reviews` rows distinguishes retry attempts from first-pass reviews. The state machine holds this as instance state, not DB-derived.

**Key constraint**: When transitioning SUMMARY -> STUDYING for retry, the widget must:
1. Filter `self._cards` to only wrong hashes.
2. Reset `self.current_index` and `self._result`.
3. Set `self._is_retry = True`.
4. NOT call `record_session()` again until the retry completes.

This is a simple reactive state change, not a widget remount. Clean and testable.

---

## 5. Cross-Package Boundary Ownership

### Current ownership map

| Table | Owner | Created By |
|-------|-------|------------|
| sessions | agent-session-tools | schema.sql |
| messages | agent-session-tools | schema.sql |
| messages_fts | agent-session-tools | schema.sql |
| session_tags | agent-session-tools | migrations.py v3 |
| session_notes | agent-session-tools | migrations.py v3 |
| message_embeddings | agent-session-tools | migrations.py v7 |
| study_progress | agent-session-tools | migrations.py v8/v9 |
| study_sessions | agent-session-tools | migrations.py v9 |
| teach_back_scores | agent-session-tools | migrations.py v10 |
| knowledge_bridges | agent-session-tools | migrations.py v11 |
| concepts | agent-session-tools | migrations.py v12 |
| concept_aliases | agent-session-tools | migrations.py v12 |
| concept_relations | agent-session-tools | migrations.py v12 |
| card_reviews | studyctl | review_db.ensure_tables() |
| review_sessions | studyctl | review_db.ensure_tables() |

### Boundary violations

**Problem**: `study_progress`, `study_sessions`, `concepts`, and `knowledge_bridges` are created by agent-session-tools migrations but queried by studyctl's `history.py`. This is a **shared database with split DDL ownership** -- a known architectural smell.

The proposed `concepts.py` extraction makes this worse: it will read from `concepts` (agent-session-tools-owned table) and from `card_reviews` (studyctl-owned table) in the same module.

**This works today** because both packages share the same SQLite file and there is no process isolation. But it creates these risks:
1. Agent-session-tools could migrate the `concepts` table schema without studyctl knowing.
2. No compile-time or test-time guarantee that studyctl's queries match agent-session-tools' DDL.

**Recommendation**: Document a "shared schema contract" file (e.g., `SCHEMA_CONTRACT.md`) listing tables, their owning package, and which packages have read access. Add a cross-package integration test that verifies both packages can operate on the same DB file. This is pragmatic -- a full schema registry is overkill for a two-package monorepo.

---

## 6. Not Updating SM-2 During Retries

### Current SM-2 implementation (review_db.py)
```python
if correct:
    interval = max(1, int(interval * ease))
    ease = min(ease + 0.1, 3.0)
else:
    interval = 1
    ease = max(ease - 0.2, MIN_EASE)
```

### Decision: Skip SM-2 update on retry attempts

**Architecturally sound.** Here is the reasoning:

1. **SM-2's core assumption**: Each review is an independent recall event from long-term memory. A retry 30 seconds after seeing the answer tests short-term memory, not spaced retention. Updating the schedule would artificially inflate the ease factor.

2. **Data integrity**: Recording the retry in `card_reviews` with `is_retry=True` preserves the audit trail without corrupting the scheduling algorithm. You can later analyze retry patterns separately.

3. **Alternative considered**: Some implementations use a "relearning" step that resets interval to 1 but preserves ease. This is what Anki does. The plan's approach is simpler and defensible for a study tool -- you can always add relearning logic later by querying `is_retry` rows.

**One nuance**: The `get_wrong_hashes()` function currently finds wrong cards from "the most recent session." After A4, a retry creates new rows. Ensure `get_wrong_hashes()` either:
- Only considers `is_retry=FALSE` rows, OR
- Uses the `session_id` FK to scope to the original (non-retry) session.

Without this, the next app launch could show retry failures as "wrong from last session," creating an infinite retry loop.

---

## 7. Coupling and Integration Risks

### Risk 1: _launch_study becomes a coordination bottleneck
`_launch_study` in `app.py` currently: discovers directories, loads cards, shuffles, mounts StudyCardsTab. With A3 (course picker) and A4 (retry flow), it must also: present OptionList, handle selection callback, pass retry context. This method risks becoming a god method.

**Mitigation**: Extract `_launch_study` into a dedicated `StudyLauncher` helper class or split into `_pick_course()` (async, returns selection) and `_start_session(course, mode, retry_hashes)`.

### Risk 2: card_hash as cross-cutting identifier
`card_hash` is generated in `review_loader.py`, stored in `card_reviews`, and used by `get_wrong_hashes()` to filter retry cards. If the hash algorithm changes (or card content is regenerated), all historical review data becomes orphaned.

**Mitigation**: Document the hash contract. Currently it appears to be content-derived. Add a comment in `review_loader.py` specifying the hash is stable across loads of the same content file.

### Risk 3: OptionList + async in Textual
A3 proposes using `OptionList` in `_launch_study`. Textual's `OptionList` emits `OptionList.OptionSelected` messages. The current `_launch_study` is synchronous. Adding a picker requires either:
- Converting to a callback/message pattern (Textual-idiomatic), or
- Using `push_screen` with a modal picker (contradicts the "no screen push" decision).

**Recommendation**: Use `OptionList` within the studycards TabPane itself, hidden after selection. This keeps everything in-pane and avoids modal complexity. The flow becomes: tab activates -> show picker -> user selects -> replace picker with StudyCardsTab widget.

### Risk 4: No integration test for the full A3->A4 flow
The retry flow spans: course picker (A3) -> study session -> summary -> retry prompt -> filtered retry -> final summary. This is a multi-state user journey with no current test infrastructure for TUI integration.

**Recommendation**: Add at least one `textual.testing.App` pilot test that exercises the STUDYING -> SUMMARY -> RETRY_PROMPT -> STUDYING path with mock cards.

---

## Summary of Recommendations

1. **Extract `_connect()` into `studyctl/db.py`** to prevent future import cycles between history.py and concepts.py.
2. **Fix FK type mismatch**: `review_sessions.id` is INTEGER; `card_reviews.session_id` must also be INTEGER.
3. **Keep migration in `review_db.ensure_tables()`**, not in agent-session-tools' migrations.py.
4. **State machine is correct** -- use an enum, not Screen promotion.
5. **Document shared schema contract** between the two packages.
6. **Guard `get_wrong_hashes()` against retry rows** to prevent infinite retry loops.
7. **Split `_launch_study()`** before it becomes a god method.
8. **Use in-pane OptionList** (not modal) for course picker to stay consistent with tabbed architecture.
