# Handoff — Mid-Session: U1/U9/U2/U3 Complete, U4 Next

**Date**: 2026-05-28 07:10 BST
**Session**: 2 (mid-point) — Phase 1 fully landed + first Phase 2 unit (U3) landed
**Branch**: `main` (12 commits ahead of `origin/main`, **unpushed by user choice — stay local**)
**Predecessor handoff**: `docs/handoffs/2026-05-27-acp-chat-ui-handoff.md`
**Authoritative plan**: `docs/plans/2026-05-27-001-feat-acp-chat-ui-plan.md`

---

## TL;DR

4 implementation units committed locally on `main` since session start: **U1 vendor libs, U9 stub multi-turn, U2 chat scaffolding, U3 markdown bubble pipeline**. 39 tests green (vendor + stub seq + new chat UI matrix). PTY matrix unchanged at 15/15. 2 pre-existing tests fail by design (target of U7/U8). Tomorrow / next session: dispatch subagent for **U4** (tool_call cards), same dispatch shape as U2/U3.

---

## Decision Log (this session)

| Decision | Outcome |
|----------|---------|
| Worktree vs work on `main` | **Work on `main` directly, commit locally only.** No worktree. No push. User decision early in session. |
| Parallel U1+U9 dispatch | **Both dispatched in parallel** — no file overlap, both finished cleanly. Each committed separately. |
| U2 dispatch | **Single subagent.** Cross-cutting `index.html` + `style.css` — no parallelism possible. Worked. |
| U3 dispatch | **Single subagent, same shape as U2.** Worked. |
| Pre-existing 2 e2e fails (xterm-buffer assertions on null `_term`) | **Leave failing.** Plan §U7 owns migration; §U8 owns dead-code removal. Not regressions. |
| Commit cadence | One commit per implementation unit. Conventional Commits format. |
| Untracked files at session start (`.playwright-mcp/`, root `*.png`) | **Gitignored** — committed `01aef23` |
| Pyright noise (`pytest`/`playwright.sync_api` not resolved) | **Ignore.** LSP venv resolution issue. `uv run pytest` works fine. |

---

## Commits Landed This Session (all unpushed on `main`)

```
0bf6752 feat(web): U3 — streaming markdown bubbles for ACP chat
0bda195 feat(web): U2 — ACP chat surface scaffolding + transport branch
58df13a feat(stub-acp): add STUB_ACP_PROMPT_UPDATES_SEQ for per-turn scripted notifications (U9)
9ef200c feat(web): vendor marked 12, highlight.js 11.9, DOMPurify 3.1 + tokyo-night theme (U1)
01aef23 chore(gitignore): ignore .playwright-mcp cache and root *.png debug screenshots
f0ff425 docs(handoff): session 1 wrap — chat UI implementation pending  [pre-session]
f7bc692 docs(plan): ACP chat UI implementation plan                       [pre-session]
77fd26b test(e2e): ACP input row matrix coverage (Phase 2 PR-E)            [pre-session]
b2abab4 feat(web): hybrid ACP input row beneath xterm (Phase 2 PR-E)       [pre-session]
25a57bf fix(acp): bump initialize/session-new timeouts for slow MCP bootstrap  [pre-session]
8c67e7a fix(cli): force-exit watchdog on first SIGINT                      [pre-session]
d9f37e9 fix(deps): promote pexpect to runtime dependency                   [pre-session]
```

12 total ahead of `origin/main`. **DO NOT push** until user explicitly says so.

---

## Plan Progress Map

```
Phase 1 — Foundation
  ✅ U1 — Vendor marked + highlight.js + DOMPurify       9ef200c
  ✅ U9 — Stub multi-turn scripted notifications         58df13a
  ✅ U2 — _mountAcpChat + transport branch + state       0bda195

Phase 2 — Core Rendering
  ✅ U3 — agent_chunk markdown bubble pipeline           0bf6752
  ⏳ U4 — tool_call cards (collapsible + bash exec)      ← NEXT
  ⏳ U5 — plan / plan_update tree render

Phase 3 — Permission Flow
  ⏳ U6 — request_permission inline allow/deny prompt

Phase 4 — Test Migration + Cleanup
  ⏳ U7 — Migrate per-agent matrix + new TestAcpChatSurface
  ⏳ U8 — Cleanup dead xterm-for-ACP plumbing
```

---

## Test Status (cumulative)

| Suite | Pass | Fail | Notes |
|-------|------|------|-------|
| `test_web_vendor_xterm.py` | 15 | 0 | U1 added 7 chat-vendor tests |
| `test_stub_acp_agent_seq.py` | 8 | 0 | U9 new file |
| `test_web_acp_chat_ui.py` | 16 | 0 | U3 new file (8 classes × kiro+gemini) |
| `test_web_acp_agent_matrix.py::TestU2ChatPanelMount` | 4 | 0 | U2 added |
| `test_web_acp_agent_matrix.py` (full) | 12 | 2 | 2 pre-existing fails — owned by U7/U8 |
| `test_web_agent_matrix.py` (PTY) | 15 | 0 | No regression |

**Pre-existing failures** (DO NOT FIX HERE — U7/U8 own these):
1. `TestAgentChunkRendersInXterm::test_agent_chunk_text_appears_in_xterm[chromium]` — polls `_term.buffer.active`, null since U2 (ACP no longer mounts xterm).
2. `TestAcpInputRow::test_submit_renders_response_and_unlocks[chromium]` — same root cause.

Both timeout at 10000ms inside `Page.wait_for_function`. Expected by plan and confirmed in commit message of U2.

---

## Open Decisions / Implementation-Time Unknowns Carried Forward

From original handoff + plan §Open Questions:

1. **Exact ACP `request_permission` JSON-RPC method name** — pull from spec at U6 implementation time. WS frame contract is stable; only the server-side method name to ACP child may differ.
2. **`agent_thought` toggle in v1?** — lean defer. Decide when wiring U5 if cheap.
3. **highlight.js `common` build size** — vendored at full `cdn-assets@11.9.0` (~120 KB minified) per U1 agent's choice. Trim to specific languages only if perf pressure shows up.
4. **Tool-call status transition CSS animation** — visual polish, decide while wiring U4.

---

## Next Session — Resume Steps

```bash
# 1. Verify clean state (no uncommitted changes, on main, 12 ahead)
cd /Users/taylaand/code/personal/tools/StudyLoop
git -P status
git -P log --oneline -12

# 2. Read this handoff + the plan + the U3 commit (0bf6752) so the
#    chat-bubble rendering shape is fresh in your head before U4.
#    Specifically the new helper methods on liveAgentConsole:
#      _appendAgentChunk, _finaliseStreamingBubble, _renderMarkdown,
#      _escapeHtml, _scrollChatToBottom
#    And the template `<template x-for="msg in acpMessages">` block.

# 3. Read the U4 spec in the plan:
#    docs/plans/2026-05-27-001-feat-acp-chat-ui-plan.md  §U4 (~line 332-380)
#
# 4. Dispatch a subagent for U4 with the same prompt shape used for U2/U3.
#    Pattern: spec + approach + steps + constraints + report-back.
#    Use general-purpose agent (NOT Explore — that's read-only).
```

---

## U4 Spec Recap (from plan §U4 ~line 332)

**Goal**: Render `tool_call` events as collapsible cards keyed by `toolCallId`. `tool_call_update` mutates the matching card. When tool name matches `/^(bash|shell|exec|run)/i`, render output in a `<pre>`-styled exec pane styled like a terminal.

**Files**:
- Modify: `packages/studyloop/src/studyloop/web/static/index.html` (extend WS handler for `tool_call`/`tool_call_update`, add `_handleToolCall`, `_handleToolCallUpdate` methods, render `toolCallsById` in template)
- Modify: `packages/studyloop/src/studyloop/web/static/style.css` (`.acp-tool-call`, `.acp-tool-call-bash`, `.acp-tool-call-status-{pending,running,completed,failed}`, collapsible chevron)
- Tests: extend `packages/studyloop/tests/test_web_acp_chat_ui.py` with new test class for tool-call rendering (uses `STUB_ACP_PROMPT_UPDATES_SEQ` from U9 for multi-event scripting)

**State already provisioned by U2**: `toolCallsById = new Map()` keyed by `toolCallId`. U4 fills it.

**Approach (high level)**:
- New `tool_call` event creates an entry in `toolCallsById` with `{name, arguments, status: 'pending', output: null, expanded: false}`.
- `tool_call_update` finds the entry by `toolCallId` and mutates `status` / appends to `output`.
- Auto-expand the card when status transitions to `failed`.
- Render in template via `<template x-for="[id, call] of toolCallsById">` (Maps are iterable in Alpine).
- Bash-class tools (`/^(bash|shell|exec|run)/i`) use a monospace `<pre>` exec pane styled to look like terminal output.
- Other tools render arguments + output in a generic key/value layout.

**Test Scenarios** (from plan):
- Happy path: `tool_call` for `read_file` creates a card with the file path visible in args.
- Happy path: `tool_call_update` flips status `pending → running → completed`, last status sticks.
- Bash exec: `tool_call` with name `bash` renders output in `.acp-tool-call-bash` pane (monospace).
- Failure: status flips to `failed`, card auto-expands.

**Dependencies**: U2 (state field `toolCallsById`), U9 (multi-event stub scripting).

---

## Conventions Confirmed (re-state for clarity)

- Vendored JS at `packages/studyloop/src/studyloop/web/static/vendor/js/<name>-<version>.min.js`
- Vendored CSS at `packages/studyloop/src/studyloop/web/static/vendor/css/<name>.css`
- Test files matching `test_web_*` carry `@pytest.mark.e2e` (excluded from default run; `addopts` in `pyproject.toml`)
- `STUDYLOOP_TEST_ACP_CMD` env override drives ACP route to stub
- `STUB_ACP_PROMPT_UPDATES_SEQ` (U9, JSON array-of-arrays) for per-turn scripted notifications; `STUB_ACP_PROMPT_UPDATES` (legacy flat) for back-compat
- Conventional commits, no `--amend`, no `--no-verify`, no force push
- DO NOT `git push` — user is staying local until explicit go-ahead
- `term.buffer.active.translateToString()` is the **only** reliable Playwright xterm read (`.xterm-rows` empty under WebGL) — but xterm is NOT in the chat path; chat tests use DOM selectors
- Alpine `x-show` keeps elements in DOM; tests use `toBeVisible()` not `toBeHidden()` semantics carefully (cross-component reads need try/catch for init race)
- Pyright LSP errors on `pytest` / `playwright.sync_api` imports are **noise** (venv resolution, not real) — ignore
- Stale `.git/index.lock` may appear after subagent SIGINT — `rm -f .git/index.lock` is safe when no live git proc

---

## Key Files for U4 Resume

| Purpose | Path |
|---------|------|
| Authoritative plan | `docs/plans/2026-05-27-001-feat-acp-chat-ui-plan.md` |
| ACP normaliser (don't break, may need new kind passthroughs) | `packages/studyloop/src/studyloop/session/transports/acp_normaliser.py` |
| Live console Alpine + WS handler (modify) | `packages/studyloop/src/studyloop/web/static/index.html` lines ~1565-1755 |
| CSS — chat panel + bubble styles (extend) | `packages/studyloop/src/studyloop/web/static/style.css` after line ~2000 |
| Chat UI tests (extend) | `packages/studyloop/tests/test_web_acp_chat_ui.py` |
| Stub agent (don't modify — U9 finished) | `packages/studyloop/tests/_stub_acp_agent.py` |
| Per-agent matrix tests (don't break) | `packages/studyloop/tests/test_web_acp_agent_matrix.py` |

---

## ACP Event Shape Reference (from research)

| `AgentMessage.kind` | Source | Payload (excl. `sessionId`) |
|---|---|---|
| `agent_chunk` | `session/update` `agent_message_chunk` | `{content: {type, text} \| [{type, text}]}` |
| `tool_call` | `session/update` `tool_call` | `{toolCallId, name, arguments, ...}` |
| `tool_call_update` | `session/update` `tool_call_update` | `{toolCallId, status, output, ...}` |
| `plan` | `session/update` `plan` | `{steps: [{title, status}]}` |
| `plan_update` | `session/update` `plan_update` | `{steps: [...]}` |
| `request_permission` | `session/update` `request_permission` | `{toolCallId, options: [{kind, name, optionId}]}` |
| `turn_end` | RPC result synthesised in `_prompt_turn` | `{reason: stopReason}` |
| `available_commands_update` | dropped by normaliser | (never reaches UI) |
| `agent_thought` | `session/update` `agent_thought_chunk` | `{content: ...}` (deferred — hidden in v1) |

For U4, focus on `tool_call` and `tool_call_update`. Live ACP CLIs may emit additional kinds the normaliser passes through verbatim — U4 should add explicit `UPDATE_KIND_MAP` entries in `acp_normaliser.py` if needed (mirror what U5/U6 plans say about plan/plan_update + request_permission).

---

## Risk Carried Forward

| Risk | Mitigation |
|------|------------|
| `tool_call_update` arrives before `tool_call` (out-of-order) | U4 should defensively create the card on first sight of either event |
| Tool output very long (10k+ lines) | U4 should clamp display height with overflow scroll; don't break layout |
| `tool_call` event for nested tool (model calls a tool inside a tool) | Out of v1 scope — plan single-level only; document if observed |
| Concurrent file modification by parallel subagents | U4 only modifies `index.html` + `style.css` + tests file — single-agent dispatch keeps this safe |

---

## What NOT to do in U4

- **Do not** remove dead xterm `agent_chunk → term.write` branches — that's U8's job.
- **Do not** migrate `TestAgentChunkRendersInXterm` or `TestAcpInputRow` failing tests — that's U7's job.
- **Do not** push `main` to origin — stay local.
- **Do not** modify `_stub_acp_agent.py` further — U9 is done; use existing env vars.
- **Do not** add a new vendored JS lib for tool-call UI — use existing CSS-only patterns; if a tree-view library is genuinely needed, pause and ask.
