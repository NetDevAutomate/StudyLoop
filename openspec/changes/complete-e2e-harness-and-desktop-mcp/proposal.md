## Why

The Playwright representative-journey harness (added as uncommitted WIP,
inventoried in `docs/superpowers/handoffs/2026-07-12-session-handoff-e2e-harness.md`)
fails at session start with a misleading "Network error" toast. Root-caused:
the harness hosts uvicorn in a pytest-process thread, but `PTYTransport`
installs a `SIGCHLD` handler that Python only permits from the main thread —
so every session-start request 500s, and the frontend's `res.json()` masks
the non-JSON error body as "network error". This blocks verifying the two
things the user most needs confidence in: a real Socratic study session
end-to-end, and whether desktop MCP clients (Claude Desktop, Codex) can
drive the same loop without a browser. Both are currently unverified.

## What Changes

- Fix the harness's server bootstrap to run uvicorn as a real subprocess
  (main-thread-owned event loop), satisfying the `SIGCHLD` constraint, and
  fix the frontend's non-JSON-500 handling so future backend errors surface
  their real cause instead of a generic "network error".
- Extract one shared `session_dir_slug()` (built on `content.storage.slugify`)
  and route all three session-start transports (PTY, ACP, ttyd) through it,
  closing the topic→path-traversal defect.
- Complete the representative user journey: real question generation (Stub
  provider for determinism, one `live_provider`-marked variant with real
  questions), study blocks, break, flashcard/quiz review, Socratic-steering
  validation (LLM-judge scores whether the mentor asks vs. tells), session
  end + export assertions.
- Add desktop-MCP parity tools so a study loop is drivable without a
  browser: due-card serving (`get_due_cards`, `submit_card_answer`),
  Course Explorer read-parity (`get_lesson_tree`, `read_lesson`,
  `search_lessons`), and wins/streaks read tools. Register `studyloop-mcp`
  in Claude Desktop and Codex configs and document what each app can
  actually do (tools only; MCP prompts/resources deferred until spiked).

## Capabilities

### New Capabilities
- `e2e-representative-journey`: the Playwright test harness that drives a
  full real study session (start → generate → study → break → review →
  end) against a subprocess-hosted server, including the Socratic-steering
  LLM-judge assertion.

### Modified Capabilities
- `session-transports`: adds `session_dir_slug()` shared across PTY/ACP/ttyd
  start paths, closing the path-traversal requirement gap documented in
  the current spec.
- `mcp-server`: adds `get_due_cards`, `submit_card_answer`,
  `get_lesson_tree`, `read_lesson`, `search_lessons` tools; documents the
  desktop-app registration contract (tools-only today).

## Impact

- `packages/studyloop/tests/_playwright_helpers.py`,
  `packages/studyloop/tests/e2e/` (new/completed test files)
- `packages/studyloop/src/studyloop/web/static/index.html` (frontend error
  handling in `startSession()`)
- `packages/studyloop/src/studyloop/web/services/session_start.py`,
  `web/routes/session/_start.py` (shared slug helper)
- `packages/studyloop/src/studyloop/mcp/tools.py` (new tools)
- `docs/mcp.md` (desktop-app registration + capability matrix)
- Uncommitted grok-worktree lane work (§2 of the handoff doc) must be
  harvested-or-discarded before or alongside this change, not blindly
  re-implemented.
