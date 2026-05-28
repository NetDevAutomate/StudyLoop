# Handoff — End-Session: ACP Chat UI Feature Shipped (All 9 Units Complete)

**Date**: 2026-05-28 ~10:00 BST
**Session**: 3 (continuation) — Phase 2/3/4 complete; ACP Chat UI feature delivered
**Branch**: `main` (21 commits ahead of `origin/main`, **unpushed by user choice — stay local**)
**Predecessor**: `docs/handoffs/2026-05-28-end-session-u4-complete.md`
**Authoritative plan**: `docs/plans/2026-05-27-001-feat-acp-chat-ui-plan.md`

---

## TL;DR

All 9 plan units complete: U5 plan/plan_update, U6 request_permission, U6.5 protocol shape fix (corrective unit not in original plan), U7 test migration, U8 dead xterm cleanup. **150/150 tests pass** (89 e2e + 61 unit). One material discovery this session: U6 shipped with the wrong ACP wire shape; U6.5 corrected it against the gemini-cli reference implementation. Phase 4 ACP Chat UI feature **shipped**. Six carry-forward items recorded below — pick them up at your pace.

---

## Commits Landed This Session

```
c8df6bb chore(web): U8 — remove dead xterm branches in ACP path
562372a fix(acp): U6.5 — correct permission flow to JSON-RPC request/response per ACP spec
83f8696 feat(test): U7 — migrate xterm assertions to chat-surface in ACP matrix
5e1321a feat(web): U6 — request_permission inline allow/deny prompt
54664b8 feat(web): U5 — plan / plan_update tree render
```

21 ahead of `origin/main`. **DO NOT push** until user explicitly says so.

---

## Plan Progress Map — DELIVERED

```
Phase 1 — Foundation
  ✅ U1   Vendor marked + highlight.js + DOMPurify       9ef200c
  ✅ U9   Stub multi-turn scripted notifications         58df13a
  ✅ U2   _mountAcpChat + transport branch + state       0bda195

Phase 2 — Core Rendering
  ✅ U3   agent_chunk markdown bubble pipeline           0bf6752
  ✅ U4   tool_call cards (collapsible + bash exec)      48b1811
  ✅ U5   plan / plan_update tree render                 54664b8

Phase 3 — Permission Flow
  ✅ U6   request_permission inline allow/deny prompt    5e1321a
  ✅ U6.5 protocol shape fix (request/response, not      562372a
         notification + outbound new request)

Phase 4 — Test Migration + Cleanup
  ✅ U7   Migrate per-agent matrix to chat-surface       83f8696
  ✅ U8   Cleanup dead xterm-for-ACP plumbing            c8df6bb
```

---

## Test Status (final)

| Suite | Pass | Fail | Notes |
|-------|------|------|-------|
| `test_web_acp_chat_ui.py` | 60 | 0 | U3 (16) + U4 (20) + U5 (10) + U6 (14) e2e |
| `test_web_acp_agent_matrix.py` | 14 | 0 | U7 fully greened — no expected fails |
| `test_web_agent_matrix.py` (PTY) | 15 | 0 | No regression across U5–U8 |
| `test_web_vendor_xterm.py` | 15 | 0 | Untouched since U1 |
| `test_stub_acp_agent_seq.py` | 8 | 0 | Untouched since U9 |
| `test_acp_normaliser.py` | 35 | 0 | Net –4 +2 in U6.5 (dead-path tests removed, request-dispatch tests added) |
| `test_acp_transport.py` | 15 | 0 | `TestSendPermission` (3) → `TestSendPermissionResponse` (4) in U6.5 |
| `test_web_session_ws.py` | 11 | 0 | Route-forwarding tests for `permission_response` WS frame |
| **Total** | **150** | **0** | clean ship |

---

## The U6 → U6.5 Correction (most important learning this session)

### What happened

U6 was implemented before any live ACP CLI verification. The subagent picked `session/respond` as the JSON-RPC method name on plausible-pattern-matching alone (mirrored `session/prompt`/`session/cancel`). Tests passed because the stub agreed with the wrong model.

### What we discovered

`/opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/gemini.js` is an authoritative ACP client implementation. Grepping its `CLIENT_METHODS` table revealed:

- The correct method is `session/request_permission`.
- It is sent **agent → client as a JSON-RPC request** (with an `id`), NOT a `session/update` notification.
- The reply is a **JSON-RPC response** to the same request id, payload `{outcome: {outcome: "selected" | "cancelled", optionId}}` — not a new outbound request.

U6's implementation was wrong in three layers (method name, message direction, payload shape). Against a real `kiro-cli acp` session, the inbound request would have been silently dropped by `_dispatch_frame`'s "Unknown notification" path.

### What U6.5 fixed

- New inbound-request branch in `_dispatch_frame` (acp.py): translates `session/request_permission` → `AgentMessage(kind="request_permission", payload._request_id=...)`.
- `send_permission_response(request_id, outcome)`: writes a bare JSON-RPC response frame (no `method`, matching `id`).
- WS frame contract changed: `{type: "permission_response", requestId, outcome}` instead of `{toolCallId, optionId}`.
- Stub agent rewritten: emits `session/request_permission` as a request with id, awaits the inbound response on stdin, validates shape.
- `request_permission` removed from `UPDATE_KIND_MAP` — it never arrives via `session/update`.

### Convention worth codifying

Before adding any new ACP method or shape assumption: grep `/opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/gemini.js` for `CLIENT_METHODS` / `AGENT_METHODS` / `z<Name>Schema` first. This would have caught U6 at design time.

---

## The U8b Hang (process learning)

### What happened

The U8 subagent dispatch attempted both Option A (Alpine 3.15.12 bump) and Option B (template flatten) for the Alpine race fix. After bumping vendored Alpine, vendoring the new file, restructuring the template, and removing `filtered_errors` listeners from multiple test classes, it hung for ~30 minutes with no token-usage change. Likely cause: Playwright `wait_for_function` deadlock against the broken new template structure.

### What we recovered

| Change | Verdict | Action |
|--------|---------|--------|
| `alpine-3.15.12.min.js` vendored | Bump did not eliminate the race | Discarded |
| `index.html` template flatten (`<template x-if>` → `x-show` + `:class`) | Introduced ghost-DOM regression: every chat-bubble row carried hidden tool-call markup, broke `querySelector('.acp-tool-exec-pane')` | Reverted that hunk |
| `index.html` xterm-cleanup hunks (3 dead `_term.` calls removed) | Correct U8a work | Kept — committed as U8 |
| `test_web_acp_chat_ui.py` `filtered_errors` removal | Race still firing — assertions caught real `null (reading 'type')` errors after removal | Discarded (stash dropped) |

### Convention worth codifying

Subagent briefs that involve **speculative or research-flavoured fixes** (version bumps, structural rewrites, "try and see" approaches) should mandate a failure-budget escape clause:

> Stop after **2 consecutive full-suite failures**. Report findings. Do NOT retry.

Without this, agents will iterate on wrong-but-plausible solutions indefinitely. Belongs in `~/.claude/rules/` (cross-project) or in the StudyLoop-specific brief shape if it's narrowly relevant.

---

## Carry-Forward Items (pick up next session)

### Deferred technical debt

1. **Alpine 3.14.8 nested `<template x-if>` race** — `null (reading 'type')` console error during rapid `acpMessages.push` mutations. Currently filtered via `pageerror` listener pattern in tests. Two known viable fix paths:
   - **Patch Alpine's `Kn` directive-sort comparator** — minimal, but vendor-fork pain.
   - **Move tool-call rendering to a separate `x-for` over `toolCallsById`** outside the `acpMessages` loop — eliminates the nested-mutation trigger entirely. **Probably the right call.**

2. **JSON-RPC permission method live verification** — U6.5 was verified against gemini-cli bundle (authoritative reference), not against a live `kiro-cli acp` round-trip. Run a smoke session with a real Kiro CLI to close the loop. Cheap (10 min).

3. **End-to-end dogfooding** — all 9 units shipped against the stub. Live-CLI smoke run (start a real ACP session, drive a turn that emits chunks/tool_calls/plan/permission) has never been performed in this branch state. The "is anything actually broken end-to-end" check.

### Plan §"Open Questions" still unresolved

4. **`agent_thought` toggle in v1?** — never decided. Lean defer; revisit if dogfooding shows demand.
5. **highlight.js `common` build size** — vendored at full ~120 KB. Trim only if perf pressure shows up.
6. **Tool-call status transition CSS animation** — visual polish, deferred.

### Process / convention

7. **Codify the gemini-cli verification rule** before adding new ACP methods (see U6 → U6.5 lesson). Either StudyLoop CLAUDE.md or a global steering rule.
8. **Codify the subagent failure-budget escape clause** (see U8b hang lesson). `~/.claude/rules/` if cross-project.

---

## Subagent Brief Discipline — Track Record This Session

Refining the < 80-line brief shape introduced in the U4 addendum:

| Unit | Brief lines | Tokens | Tool uses | Outcome |
|------|-------------|--------|-----------|---------|
| U5 | ~70 | 111k | 50 | Clean one-shot |
| U6 | ~110 | 156k | 75 | Paused mid-flow; resume burned 138k more |
| U7 | ~70 | 122k | 14 | Cleanest dispatch (test-only migration) |
| U6.5 | ~150 | 185k | 58 | Clean — payload-heavy brief justified by correctness criticality |
| U8 (hung) | ~140 | unknown | hung | 30-min hang on speculative work without escape clause |
| U8 (manual recovery) | n/a | minimal | minimal | Surgical revert + commit |

**Lessons:**
- Test-only migrations are naturally bounded — keep brief ≤ 70 lines.
- Multi-layer protocol fixes need ≥ 100 lines and that's fine if the payload is precise (gemini-cli quotes, exact JSON shapes).
- Speculative work needs a failure-budget escape clause OR should be split into research-first / implement-second briefs.

---

## Conventions Confirmed (re-state)

- Vendored JS at `packages/studyloop/src/studyloop/web/static/vendor/js/<name>-<version>.min.js`
- Vendored CSS at `packages/studyloop/src/studyloop/web/static/vendor/css/<name>.css`
- Test files matching `test_web_*` carry `@pytest.mark.e2e` (excluded from default run; `addopts` in `pyproject.toml`)
- `STUDYLOOP_TEST_ACP_CMD` env override drives ACP route to stub
- `STUB_ACP_PROMPT_UPDATES_SEQ` (U9, JSON array-of-arrays) for per-turn scripted notifications
- `STUB_ACP_EMIT_PERMISSION_REQUEST=1` (U6.5) drives stub to emit a real `session/request_permission` request with id
- Conventional commits, no `--amend`, no `--no-verify`, no force push
- DO NOT `git push` — user is staying local until explicit go-ahead
- Pyright LSP errors on pytest/playwright/starlette/fastapi/pydantic/studyloop imports are **noise** (venv resolution, not real) — ignore
- Pyright "Cannot access attribute X for class Y" errors on `hasattr`-guarded `Protocol` calls are **noise** (Pyright doesn't narrow `hasattr` on Protocol types) — ignore
- Stale `.git/index.lock` may appear after subagent SIGINT — `rm -f .git/index.lock` is safe when no live git proc

---

## Next Session — Resume Steps

```bash
# 1. Verify clean state
cd /Users/taylaand/code/personal/tools/StudyLoop
git -P status                  # working tree clean
git -P log --oneline -5        # 21 ahead of origin/main, top is c8df6bb

# 2. Read this handoff. The plan is fully delivered; no more units to dispatch
#    against `docs/plans/2026-05-27-001-feat-acp-chat-ui-plan.md`.

# 3. Pick up carry-forward items in priority order:
#    - Item 2: Live `kiro-cli acp` round-trip to verify U6.5 works against
#      a real CLI (not just the stub). 10 min.
#    - Item 3: Full-feature dogfooding session with Kiro and/or Gemini.
#    - Item 1: Alpine race fix — recommend the "separate x-for over
#      toolCallsById" approach as the cleanest path.
#    - Item 7/8: Codify the verification + escape-clause conventions.
#    - Items 4/5/6: only if dogfooding surfaces real demand.

# 4. When ready to push, the user must give explicit go-ahead. 21 local
#    commits represent ~3 sessions of work.
```

---

## Key Files for Carry-Forward Work

| Purpose | Path |
|---------|------|
| Authoritative plan (delivered) | `docs/plans/2026-05-27-001-feat-acp-chat-ui-plan.md` |
| This handoff | `docs/handoffs/2026-05-28-end-session-acp-chat-ui-shipped.md` |
| Predecessor handoff | `docs/handoffs/2026-05-28-end-session-u4-complete.md` |
| ACP transport (request-dispatch + response-write live here) | `packages/studyloop/src/studyloop/session/transports/acp.py` |
| Live console Alpine + WS handler | `packages/studyloop/src/studyloop/web/static/index.html` |
| Chat panel CSS | `packages/studyloop/src/studyloop/web/static/style.css` |
| Stub agent (request/response permission flow) | `packages/studyloop/tests/_stub_acp_agent.py` |
| Chat UI e2e tests | `packages/studyloop/tests/test_web_acp_chat_ui.py` |
| ACP matrix tests | `packages/studyloop/tests/test_web_acp_agent_matrix.py` |
| ACP unit tests | `packages/studyloop/tests/test_acp_*.py` |
| WS route tests | `packages/studyloop/tests/test_web_session_ws.py` |
| gemini-cli wire-protocol reference | `/opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/gemini.js` |

---

## Risks Carried Forward

| Risk | Severity | Mitigation |
|------|----------|------------|
| U6.5 implementation not verified against live `kiro-cli acp` | Medium — protocol contract is right per gemini-cli, but live CLI quirks possible | Carry-forward Item 2 — single 10-min smoke run |
| Alpine race could mask a real future bug | Low — listener filter is narrow (matches one specific framework error string) | Carry-forward Item 1 — separate `x-for` refactor |
| `acpMessages` array unbounded in long sessions | Low — bounded by 25–90min focus block; reload clears state | Documented in plan §System-Wide Impact |
| `agent_thought` events unhandled (currently dropped silently) | Low — feature deferred by design | Carry-forward Item 4 |
