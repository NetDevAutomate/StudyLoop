## Purpose

Expose StudyLoop's study/review state to any MCP-compatible client (desktop
apps, other agent CLIs) as a set of stdio tools, independent of the browser
UI. Backed by `FastMCP` (`mcp[cli]` SDK) with lifespan-managed DB/settings
access. This is one of two MCP servers in the repo; `session-db-mcp`
(cross-agent session memory, 7 tools, documented in `docs/mcp.md`) is
separate and out of scope for this capability.

## Requirements

### Requirement: studyloop-mcp registers a fixed set of study tools
The system SHALL register the following 18 tools via
`register_tools(mcp)` (`mcp/tools.py`): `list_courses`,
`get_study_context`, `record_study_progress`, `generate_flashcards`,
`generate_quiz`, `get_chapter_text`, `get_study_backlog`,
`get_topic_suggestions`, `get_study_history`, `list_session_options`,
`end_session`, `record_topic_progress`, `log_topic`, plus the review-loop
and lifecycle parity tools added in `e3070be`: `get_due_cards`,
`log_review_outcome`, `get_next_action`, `get_active_topics`,
`log_struggle`.

#### Scenario: Client lists available tools
- **WHEN** an MCP client connects to the `studyloop-mcp` stdio server and
  requests its tool list
- **THEN** exactly these 18 tools are returned, matching the table in
  `docs/mcp.md` (verified 2026-07-12; the earlier state where `docs/mcp.md`
  documented only the separate `session-db-mcp` server was closed in
  `4f7bf6f`). The full stdio handshake + tools/list + tools/call round-trip
  is locked by `tests/test_mcp_stdio_smoke.py` (integration-marked)

### Requirement: Review-loop tools enable a complete quiz cycle without the browser
`get_due_cards(course=None, limit=20)` SHALL return real serialized
`CardProgress` entries (per-course via `get_due(course)`, or aggregated
across `list_course_summaries()` when no course is given);
`log_review_outcome(course, card_type, card_hash, correct, ...)` SHALL
delegate to `record_review()` and reject `card_type` outside
`{"flashcard","quiz"}` with `ToolError`; `get_next_action(...)` SHALL
delegate to `learning.decision.build_now_plan()` (the same engine as
`/api/now`); `get_active_topics()` SHALL split pending backlog items at
`MAX_ACTIVE_TOPICS`; `log_struggle(...)` SHALL park with
`source="struggled"`.

#### Scenario: Desktop client runs a full review loop
- **WHEN** an MCP client calls `get_due_cards` → presents cards →
  `log_review_outcome` per answer → `get_next_action`
- **THEN** each outcome is persisted through the same SM-2 path the web UI
  uses, and the next-action recommendation comes from the shared decision
  engine, not a hardcoded string

### Requirement: Course paths are validated against traversal
The system SHALL resolve any tool-supplied `course` argument through
`_safe_course_dir(base, course, subdir)` (`mcp/tools.py:26`), which
resolves the joined path and rejects it via `ToolError` if the result is
not `is_relative_to(base.resolve())`.

#### Scenario: Tool called with a traversal-shaped course argument
- **WHEN** a tool such as `get_chapter_text` is called with
  `course: "../../etc"`
- **THEN** `_safe_course_dir` raises `ToolError("Invalid course path: ...")`
  before any filesystem read occurs

### Requirement: get_study_context aggregates review state for one course
`get_study_context(course)` SHALL call `get_due()` and `get_stats()`
(`services/review.py`) and return `due_cards`, `total_reviews`,
`unique_cards`, `mastered`, and `due_today` — a summary, not the card
content itself.

#### Scenario: Agent checks a course before starting a session
- **WHEN** an MCP client calls `get_study_context("python")`
- **THEN** the response contains counts only (no card front/back text);
  retrieving actual due-card content requires a separate, currently
  unimplemented tool (tracked as the highest-value desktop-MCP gap in
  `docs/audit/2026-07-11-comprehensive-review.md` §6)

### Requirement: Generation tools save agent-authored content, not pipeline output
`generate_flashcards(course, chapter, content)` and
`generate_quiz(course, chapter, content)` SHALL persist LLM-agent-supplied
JSON directly to disk; they SHALL NOT invoke the provider pipeline in
`content/generators/` (that pipeline is triggered only via the CLI and the
web Generate panel).

#### Scenario: MCP client calls generate_flashcards
- **WHEN** an MCP client calls `generate_flashcards` with a `content`
  payload it authored itself
- **THEN** that payload is written to the course's flashcards directory
  as-is; no Bedrock/OpenAI/Anthropic/Ollama/Stub provider call occurs
