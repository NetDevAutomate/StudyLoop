## ADDED Requirements

### Requirement: Desktop MCP clients can serve due-card content for review
The system SHALL add a `get_due_cards(course, limit, kind)` tool returning
full card front/back content (joining `get_due()` with the review loader),
and a `submit_card_answer(course, card_hash, correct)` tool that records
the SM-2 outcome and returns the card's updated next-review interval, so
an MCP client can run a complete quiz turn without the browser.

#### Scenario: Desktop agent runs a review turn
- **WHEN** a Claude Desktop or Codex client calls `get_due_cards` for a
  course, presents a card to the user in chat, judges the user's answer,
  and calls `submit_card_answer`
- **THEN** the response includes the updated next-review interval so the
  agent can tell the user when the card returns — the same outcome a
  browser review session produces

### Requirement: Desktop MCP clients have Course Explorer read parity
The system SHALL add `get_lesson_tree(provider?, course?)`,
`read_lesson(lesson_id)`, and `search_lessons(query)` tools that are pure
wrappers over the existing `web/routes/explorer.py` internals, reusing the
same traversal guard as `_safe_course_dir` / the explorer's
`is_relative_to(base)` check.

#### Scenario: Desktop agent browses course material
- **WHEN** a desktop MCP client calls `get_lesson_tree` then
  `read_lesson(lesson_id)` for a specific lesson
- **THEN** the returned tree and lesson content match what
  `GET /api/explorer/tree` and `GET /api/explorer/lesson/{id}/content`
  would return in the browser, including the traversal guard rejecting
  any `lesson_id` containing `../` segments

### Requirement: docs/mcp.md documents studyloop-mcp and desktop registration
`docs/mcp.md` SHALL document `studyloop-mcp`'s full tool list (18 tools
after this change: the 13 existing plus `get_due_cards`,
`submit_card_answer`, `get_lesson_tree`, `read_lesson`, `search_lessons`),
Claude Desktop registration (`claude_desktop_config.json`), Codex
registration (`~/.codex/config.toml`), and an explicit capability matrix
stating what works via MCP today versus what still requires the browser
(WS/SSE push, audio-in-chat, custom UI — per the audit's impossible-list).

#### Scenario: A new contributor reads docs/mcp.md
- **WHEN** someone reads `docs/mcp.md` to decide whether to use StudyLoop
  from Claude Desktop instead of the browser
- **THEN** they find the studyloop-mcp tool list, both apps' registration
  snippets, and an explicit list of what desktop chat cannot do (no
  surprise gaps discovered only by trying)
