# Handoff — ACP Chat UI Implementation

**Date**: 2026-05-27
**Session**: Plan authored + reviewed + PR-E hybrid landed; chat UI implementation pending
**Branch**: `main` (6 commits ahead of `origin/main`, unpushed)

---

## TL;DR

Plan landed at `docs/plans/2026-05-27-001-feat-acp-chat-ui-plan.md`. Hybrid ACP input row (PR-E) committed and works, but markdown renders raw + newlines drift right. Chat UI replaces xterm for ACP transport entirely. **Tomorrow: push commits, create worktree, start U9 + U1.**

---

## Decision Log

| Decision | Outcome |
|----------|---------|
| Replace xterm vs augment for ACP | **Replace.** Hybrid PR-E confirmed worst-of-both-worlds in browser smoke test |
| PTY future | Keep both — picker chooses. PTY untouched |
| Markdown library | Vendor `marked` + `highlight.js` + `DOMPurify` (same pattern as xterm) |
| Tool-call output panes | Inside the card, not separate persistent pane |
| Permission prompt UX | Inline blocking bubble, allow/deny buttons, hold `acpSending = true` |
| Branch strategy | Worktree on `feat/acp-chat-ui` |

---

## Commits Landed This Session (unpushed on `main`)

```
f7bc692 docs(plan): ACP chat UI implementation plan
77fd26b test(e2e): ACP input row matrix coverage (Phase 2 PR-E)
b2abab4 feat(web): hybrid ACP input row beneath xterm (Phase 2 PR-E)
25a57bf fix(acp): bump initialize/session-new timeouts for slow MCP bootstrap
8c67e7a fix(cli): force-exit watchdog on first SIGINT
d9f37e9 fix(deps): promote pexpect to runtime dependency
```

**Push when ready**: `git push origin main`

---

## Plan Summary

`docs/plans/2026-05-27-001-feat-acp-chat-ui-plan.md` — 9 implementation units, 4 phases.

### Phase 1 — Foundation (do first)
- **U1** — Vendor `marked-12.0.0` + `highlight-11.9.0` (common build) + `purify-3.1.0` + tokyo-night-dark theme CSS to `packages/studyloop/src/studyloop/web/static/vendor/`. Extend `test_web_vendor_xterm.py` with global presence checks.
- **U9** — Extend `_stub_acp_agent.py` with `STUB_ACP_PROMPT_UPDATES_SEQ` env var (array-of-arrays for per-prompt scripting). Back-compat with the single-array form. **Lands first or alongside U1** — required by U4/U5/U6/U7 multi-turn tests.
- **U2** — `_mountAcpChat` Alpine method, branch `transport === 'acp' ? _mountAcpChat() : _mountXterm()`. Initialise `acpMessages`, `toolCallsById`, `streamingMessageId`, `plan`, `pendingPermission`. **Relocate `acp-input-row` form into `.acp-chat-panel`** (not deferred to U8). `_sendAcpInput` becomes branched: `if (this._term) writeln else acpMessages.push`. **Extend `stop()`** to reset all five new fields + `terminalMode`.

### Phase 2 — Core Rendering
- **U3** — `agent_chunk` → markdown bubble. Pipeline: marked → DOMPurify → highlight.js. Streaming bubble accumulates raw chunks; finalise on `turn_end` (re-render full text so split-across-chunks fenced code renders as one block).
- **U4** — `tool_call` + `tool_call_update` collapsible cards keyed by `toolCallId`. Tool name matching `/^(bash|shell|exec|run)/i` → output in monospace exec pane. Auto-expand on `failed` status.
- **U5** — `plan` + `plan_update` tree render. Add explicit `UPDATE_KIND_MAP` entries for both (don't rely on passthrough). Live todo-list with strikethrough on completed steps.

### Phase 3 — Permission Flow
- **U6** — `request_permission` inline allow/deny prompt. Add `UPDATE_KIND_MAP` entry. **`send_permission` via `hasattr` duck-type guard**, NOT Protocol extension (Python `Protocol` cannot have optional methods). Stub agent gets a permission-response handler. Server-side `ws_to_pty` gets `{type: 'permission_response', toolCallId, optionId}` branch.

### Phase 4 — Test Migration + Cleanup
- **U7** — Migrate `TestAgentChunkRendersInXterm` to chat DOM assertions. New `test_web_acp_chat_ui.py` covering R1–R7 across kiro+gemini.
- **U8** — Remove dead `term.write` branches for ACP (now unreachable). PTY untouched.

---

## Open Decisions / Implementation-Time Unknowns

From plan §Open Questions / Deferred to Implementation:

1. **Exact ACP `request_permission` JSON-RPC method name** — pull from spec at U6 implementation time. WS frame contract is stable; only the server-side method name to ACP child may differ.
2. **`agent_thought` toggle in v1?** — lean defer. Decide when wiring U5 if cheap.
3. **highlight.js `common` build size** — start with common (~30KB); trim to bash/python/sql/json/ts/js if pressure shows up.
4. **Tool-call status transition CSS animation** — visual polish, decide while wiring U4.

---

## Blockers / Risks

| Risk | Mitigation in Plan |
|------|--------------------|
| XSS via agent markdown | DOMPurify is authoritative gate (marked v12 has no `headerIds`/`mangle` — they were removed). Negative tests in U3. |
| Stub agent can't script multi-turn | **U9 fixes this — must land before U4/U5/U6** |
| PTY → ACP → PTY state leak | U2 `stop()` reset list — explicit |
| Permission lock survives WS death | `transport_error` + WS `close` handler clear `pendingPermission` |
| `marked.setOptions({headerIds, mangle})` no-ops in v12 | Plan flags this; rely on DOMPurify as the security layer |
| Concurrent file modification by parallel subagents | U3, U4, U5 all touch `index.html` + `style.css` — **MUST run serial in same worktree, OR worktree-isolated parallel** |

---

## Hybrid Smoke Test (PR-E) — Status

| Check | Result |
|-------|--------|
| Connect Kiro ACP | ✅ |
| Connect Gemini ACP | (not tested — do tomorrow as sanity) |
| Echo `> hello` cyan | ✅ |
| First reply | ✅ |
| `[turn end_turn]` marker | ✅ |
| Multi-turn no Internal error | ✅ |
| Ctrl-C clean exit | ✅ (single press, 5s force-exit watchdog) |
| Markdown rendering | ❌ raw `**bold**` (expected — chat UI fixes) |
| Newline `\r\n` handling | ❌ cursor drift right (expected — chat UI fixes) |

Hybrid is functionally correct, visually ugly. Don't patch — chat UI replaces.

---

## Resume Steps for Next Session

```bash
# 1. Pull and verify clean state
cd /Users/taylaand/code/personal/tools/StudyLoop
git -P log --oneline -10
git -P status

# 2. Push session 1 commits to remote
git push origin main

# 3. Create worktree for chat UI (Phase 1 ce-work step 2)
git worktree add ../StudyLoop-acp-chat -b feat/acp-chat-ui main
cd ../StudyLoop-acp-chat

# 4. Re-load the plan + handoff in fresh context
#    Reference: docs/plans/2026-05-27-001-feat-acp-chat-ui-plan.md
#    Reference: docs/handoffs/2026-05-27-acp-chat-ui-handoff.md

# 5. Start U9 first (stub multi-turn) — unblocks U4/U5/U6 tests
#    Then U1 (vendor markdown libs) — independent
#    Then U2 (mount + branch + state) — depends on U1
#    Then U3, U4, U5, U6, U7, U8 in dependency order
```

---

## Task List Status (TaskCreate)

```
✅ #7  PR-E commit batch on main (5 commits)
⏳ #8  Create worktree on feat/acp-chat-ui
⏳ #9  U1: Vendor marked + highlight.js + DOMPurify
⏳ #10 U9: Stub multi-turn scripted notifications
⏳ #11 U2: _mountAcpChat + transport branch + state resets
⏳ #12 U3: agent_chunk markdown bubble pipeline
⏳ #13 U4: tool_call cards (collapsible + bash exec pane)
⏳ #14 U5: plan / plan_update tree render
⏳ #15 U6: request_permission inline allow/deny prompt
⏳ #16 U7: Migrate per-agent matrix tests + new TestAcpChatSurface
⏳ #17 U8: Cleanup dead xterm-for-ACP plumbing
```

Tasks created via Claude Code TaskCreate — do not survive session boundaries. Re-create from this list at session start.

---

## Key Files for Resume

| Purpose | Path |
|---------|------|
| The plan (authoritative) | `docs/plans/2026-05-27-001-feat-acp-chat-ui-plan.md` |
| ACP transport (don't break) | `packages/studyloop/src/studyloop/session/transports/acp.py` |
| ACP normaliser (extend in U5/U6) | `packages/studyloop/src/studyloop/session/transports/acp_normaliser.py` |
| Live agent console (modify in U2-U8) | `packages/studyloop/src/studyloop/web/static/index.html` lines ~1284-1530 |
| CSS (extend in U2+) | `packages/studyloop/src/studyloop/web/static/style.css` lines ~1495-1910 |
| WS route (extend in U6) | `packages/studyloop/src/studyloop/web/routes/session.py` lines ~1175-1218 |
| Per-agent matrix tests (migrate in U7) | `packages/studyloop/tests/test_web_acp_agent_matrix.py` |
| Vendor smoke tests (extend in U1) | `packages/studyloop/tests/test_web_vendor_xterm.py` |
| Stub agent (extend in U9 + U6) | `packages/studyloop/tests/_stub_acp_agent.py` |

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

Live ACP CLI (Kiro / Gemini) may emit kinds the normaliser passes through verbatim — U5/U6 add explicit `UPDATE_KIND_MAP` entries to make sure `plan_update` and `request_permission` don't drop on the floor if their wire-string differs from the canonical name.

---

## Conventions Confirmed

- Vendored JS goes to `packages/studyloop/src/studyloop/web/static/vendor/js/<name>-<version>.min.js`
- Test files matching `test_web_*` carry `@pytest.mark.e2e` (excluded from default run)
- `STUDYLOOP_TEST_ACP_CMD` env override drives ACP route to stub
- Conventional commits, no `--amend`, no `--no-verify`, no force push
- `term.buffer.active.translateToString()` is the **only** reliable Playwright xterm read (`.xterm-rows` empty under WebGL)
- Alpine `x-show` keeps elements in DOM; tests use `toBeVisible()` not DOM presence
- Cross-component Alpine reads need `try/catch` (init race)
- `.claude/worktrees/` should be gitignored before relying on Agent worktree isolation
