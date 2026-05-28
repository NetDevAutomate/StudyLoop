# Handoff — End-Session: U4 Complete, U5 Next + Config Cleanup

**Date**: 2026-05-28 07:50 BST
**Session**: 2 (end) — Phase 1 + U3 + U4 landed; global Claude config trimmed
**Branch**: `main` (15 commits ahead of `origin/main`, **unpushed by user choice — stay local**)
**Predecessor**: `docs/handoffs/2026-05-28-mid-session-u3-complete.md` (read it — addendum at bottom carries the U4 lessons)
**Authoritative plan**: `docs/plans/2026-05-27-001-feat-acp-chat-ui-plan.md`

---

## TL;DR

Five units now committed: **U1 vendor libs, U9 stub multi-turn, U2 chat scaffolding, U3 markdown bubbles, U4 tool_call cards**. 39+18 = `~57` chat-UI tests green; PTY 15/15; ACP matrix 12/2 (2 expected fails owned by U7/U8). Plus a global config cleanup (Amazon CLAUDE.md duplicates, AIM plugins, caveman) to reduce per-session token bloat. **Next session: dispatch subagent for U5 (`plan` / `plan_update` tree render)** using the new short-brief shape captured in the predecessor handoff addendum.

---

## Commits Landed Since Predecessor Handoff

```
8216524 docs(handoff): addendum after U4 — shorter subagent briefs lesson
48b1811 feat(web): U4 — tool_call collapsible cards + bash exec pane
3cb7c94 docs(handoff): mid-session checkpoint after U3 (Phase 2 partial)  [predecessor]
0bf6752 feat(web): U3 — streaming markdown bubbles for ACP chat
0bda195 feat(web): U2 — ACP chat surface scaffolding + transport branch
58df13a feat(stub-acp): STUB_ACP_PROMPT_UPDATES_SEQ for per-turn scripted notifications (U9)
9ef200c feat(web): vendor marked 12, highlight.js 11.9, DOMPurify 3.1 + tokyo-night theme (U1)
```

15 ahead of `origin/main`. **DO NOT push** until user explicitly says so.

---

## Plan Progress Map

```
Phase 1 — Foundation
  ✅ U1 — Vendor marked + highlight.js + DOMPurify       9ef200c
  ✅ U9 — Stub multi-turn scripted notifications         58df13a
  ✅ U2 — _mountAcpChat + transport branch + state       0bda195

Phase 2 — Core Rendering
  ✅ U3 — agent_chunk markdown bubble pipeline           0bf6752
  ✅ U4 — tool_call cards (collapsible + bash exec)      48b1811
  ⏳ U5 — plan / plan_update tree render                 ← NEXT

Phase 3 — Permission Flow
  ⏳ U6 — request_permission inline allow/deny prompt

Phase 4 — Test Migration + Cleanup
  ⏳ U7 — Migrate per-agent matrix + new TestAcpChatSurface
  ⏳ U8 — Cleanup dead xterm-for-ACP plumbing
```

---

## Test Status (cumulative, post-U4)

| Suite | Pass | Fail | Notes |
|-------|------|------|-------|
| `test_web_vendor_xterm.py` | 15 | 0 | U1 vendor coverage |
| `test_stub_acp_agent_seq.py` | 8 | 0 | U9 multi-turn stub |
| `test_web_acp_chat_ui.py` | 36 | 0 | U3 (16) + U4 (20) — chat UI matrix |
| `test_web_acp_agent_matrix.py::TestU2ChatPanelMount` | 4 | 0 | U2 mount assertions |
| `test_web_acp_agent_matrix.py` (full) | 12 | 2 | 2 pre-existing fails — owned by U7/U8 |
| `test_web_agent_matrix.py` (PTY) | 15 | 0 | No regression |

**Pre-existing failures (do NOT fix in U5):**
1. `TestAgentChunkRendersInXterm::test_agent_chunk_text_appears_in_xterm[chromium]` — xterm-buffer null since U2.
2. `TestAcpInputRow::test_submit_renders_response_and_unlocks[chromium]` — same root cause.

Both expected. U7 migrates them to chat-surface assertions; U8 deletes the dead xterm plumbing.

---

## Global Config Cleanup (this session, outside StudyLoop repo)

Reduced per-session steering bloat — applies to ALL future Claude Code sessions, not just this project.

| Action | Detail |
|--------|--------|
| Trimmed `~/.claude/CLAUDE.md` | 585 → 136 lines. Removed inline SSCL/Brazil/CRUX/Coral/Apollo/Pipelines/Taskei/IDE-Tools/Production-Safety/Inclusive-Language blocks. Backup: `~/.claude/CLAUDE.md.bak.20260528-074136`. |
| Removed Amazon rule files | Moved to `~/.claude/.removed-amazon-rules-bak.*` (reversible): `amazon-builder-context-do-not-delete.md`, `resource-amazon-builder-context.md`, `amazon-production-safety-do-not-delete.md`. |
| Disabled AIM/Amazon plugins | 16 plugins set `false` in `enabledPlugins` (each was injecting a near-identical `builder-mcp` toolset). Includes `AIPowerUserCapabilities-*`, `AmazonBuilderCoreAIAgents-*`, `AtlasAICapabilities-*`, `MeshClaw*`, `Oh-my-kiro-cli-*`, `SlackDigest*`, `LLM-wikiKit-cc`, `AmznCmuxSkillset`. |
| Removed caveman | `enabledPlugins.caveman@caveman: false`, dropped `extraKnownMarketplaces.caveman`, deleted `~/.claude/.caveman-active`. Plugin cache stays inert on disk. |
| Settings backup | `~/.claude/settings.json.bak.20260528-074136`. |

**Effect for next session**: tool catalogue and skills list at session start should be dramatically smaller. The `find-skills` skill remains available for on-demand lookup. **All changes reversible** via the backups listed above.

**If something breaks**:

```bash
# Restore CLAUDE.md
cp ~/.claude/CLAUDE.md.bak.20260528-074136 ~/.claude/CLAUDE.md

# Restore settings.json
cp ~/.claude/settings.json.bak.20260528-074136 ~/.claude/settings.json

# Restore one or more amazon rules (rename them back)
cd ~/.claude/rules
mv ../.removed-amazon-rules-bak.amazon-builder-context-do-not-delete.md amazon-builder-context-do-not-delete.md
# (etc for the other two)
```

---

## Next Session — Resume Steps

```bash
# 1. Verify clean state
cd /Users/taylaand/code/personal/tools/StudyLoop
git -P status                  # working tree clean
git -P log --oneline -10       # 15 ahead of origin/main, top is 8216524

# 2. Read this handoff. Then read the predecessor handoff and especially
#    its bottom-of-file Addendum (post-U4) — that's where the subagent
#    brief discipline rule and the carry-forward lessons live.
#    docs/handoffs/2026-05-28-mid-session-u3-complete.md

# 3. Read U5 spec from the plan:
#    docs/plans/2026-05-27-001-feat-acp-chat-ui-plan.md  §U5 (lines 374–404)

# 4. Dispatch a subagent for U5 using the SHORT-BRIEF SHAPE.
#    Target < 80 lines of brief. Do NOT paste HTML/CSS/test code.
#    Point at:
#      - Plan §U5 (374–404)
#      - Precedent for kind-based render: 48b1811 (U4 commit)
#      - Precedent for streaming text path: 0bf6752 (U3 commit)
#      - Precedent for normaliser map: existing UPDATE_KIND_MAP in
#        packages/studyloop/src/studyloop/session/transports/acp_normaliser.py
#      - Stub scripting: STUB_ACP_PROMPT_UPDATES_SEQ (U9, env var)
#    Reporting shape: summary, files+LOC, test counts, commit SHA,
#    surprises, what's next.
```

---

## U5 Spec Recap (from plan §U5)

**Goal**: Render `plan` and `plan_update` events as a live todo-list. Steps with `status === 'completed'` are struck through. Plan replaces in place when a new `plan_update` arrives.

**Files**:
- Modify: `packages/studyloop/src/studyloop/session/transports/acp_normaliser.py` — add explicit `UPDATE_KIND_MAP` entries for `plan` + `plan_update`. **Verify the live ACP CLI's wire-string discriminator before relying on passthrough.**
- Modify: `packages/studyloop/src/studyloop/web/static/index.html` — WS handler routes `plan` / `plan_update` to set `this.plan = payload`. Render via `<template x-if="plan">` + `<template x-for="step in plan.steps">`.
- Modify: `packages/studyloop/src/studyloop/web/static/style.css` — `.acp-plan`, `.acp-plan-step`, `.acp-plan-step-completed { text-decoration: line-through; opacity: 0.6 }`, status icons.
- Test: `packages/studyloop/tests/test_acp_normaliser.py` — unit tests for new map entries.
- Test: extend `packages/studyloop/tests/test_web_acp_chat_ui.py` — UI tests for plan render + replace-in-place.

**Approach (high level)**:
- Inline (in the chat scroll), NOT a sticky top panel — matches "this is what the agent is going to do next" mental model.
- Step shape: `{title, status}` with status ∈ `pending | in_progress | completed | failed`.
- Latest plan replaces previous (don't keep history).
- Use `_renderMarkdown` for step titles? **Decide at implementation time** — title likely plain text, but if ACP CLIs emit markdown there, reuse the U3 pipeline.

**Test scenarios (from plan)**:
- Stub emits `plan` with three steps `[a, b, c]`, all pending → list shows three items.
- `plan_update` with first step `completed` → first item struck through, others unchanged.
- Empty `plan.steps` array → plan panel renders empty (no error).
- `plan` with no payload (`{}`) → handled gracefully (no crash).
- New `plan` after old plan replaces, doesn't append.

**Dependencies**: U2 (state hook), U9 (multi-event stub scripting).

**Test infra reuse**:
- `STUB_ACP_PROMPT_UPDATES_SEQ` (JSON array-of-arrays env var). Each inner array is one turn's notifications.
- Playwright fixture pattern from U4: class-scoped per-test server start; ports allocated per `_playwright_helpers.py`.
- Click-via-evaluate workaround (`page.evaluate("el => el.click()", el)`) when overflow-auto containers report "not visible". Already documented in addendum.
- `pageerror` listener filter for the Alpine 3.14.8 nested `x-if` benign console error — see addendum.

---

## Carry-Forward Surprises (from U4 — re-state for U5+)

1. **Alpine 3.14.8 nested `x-if` race**: rapid `acpMessages.push` triggers a benign internal `null (reading 'type')` console error during DOM mutation. Cards still render. U4 tests filter via `pageerror` listener — copy that pattern. U8 cleanup options: bump Alpine 3.15+ OR flatten per-`kind` branches.
2. **Playwright `click()` inside `overflow:auto`**: treats children as "not visible". Use `page.evaluate("el => el.click()", el)`.
3. **Pure-Python regex tests**: don't bind to a Playwright class fixture. Run them at module level — class-scoped fixture binding to one port plus an unrelated browser test was flaky.

---

## Open Decisions / Implementation-Time Unknowns Carried Forward

From original handoff + plan §Open Questions:

1. **Live ACP CLI wire string for `plan`/`plan_update` discriminator** — verify before relying on normaliser passthrough; plan §U5 explicitly calls this out.
2. **Plan step title — plain text or markdown?** — decide while wiring U5. If markdown, reuse `_renderMarkdown` from U3.
3. **Exact ACP `request_permission` JSON-RPC method name** — pull from spec at U6 implementation time.
4. **`agent_thought` toggle in v1?** — lean defer. Decide if cheap when wiring U5.
5. **highlight.js `common` build size** (~120 KB) — trim if perf pressure shows up.
6. **Tool-call status transition CSS animation** — visual polish, deferred.

---

## Subagent Brief Discipline (the rule for U5+)

The U4 brief was ~400 lines and burned ~480k tokens / 56 tool calls on the subagent. **For U5+, the brief shape is:**

```
Goal: <1 line>
Plan section: docs/plans/2026-05-27-001-feat-acp-chat-ui-plan.md §U5 (lines 374–404)
Pattern reference: <commit SHA — e.g. 48b1811 for kind-based render, 0bf6752 for streaming bubble>
Files to modify: <bullet list, no inline code>
Constraints (must-nots): <link to handoff §"What NOT to do">
Reporting shape: summary, files+LOC, test counts, commit SHA, surprises, what's next
```

Target **< 80 lines of brief total**. The plan section + a precedent commit SHA gives the agent richer ground truth than any pasted snippet — and avoids stale-paste divergence from current code. **Do not paste HTML, CSS, or test scaffolding into the brief.**

When the brief still feels too long, ask: "what's the single tightest existing example of this pattern in the repo?" — point to that SHA + file:line.

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
- Alpine `x-show` keeps elements in DOM; `pageerror` listener filter required for the 3.14.8 nested-x-if benign error (see addendum)
- Pyright LSP errors on `pytest` / `playwright.sync_api` imports are **noise** (venv resolution, not real) — ignore
- Stale `.git/index.lock` may appear after subagent SIGINT — `rm -f .git/index.lock` is safe when no live git proc

---

## Key Files for U5 Resume

| Purpose | Path |
|---------|------|
| Authoritative plan | `docs/plans/2026-05-27-001-feat-acp-chat-ui-plan.md` |
| Predecessor handoff (READ ITS ADDENDUM) | `docs/handoffs/2026-05-28-mid-session-u3-complete.md` |
| ACP normaliser (modify — add `plan`/`plan_update` to UPDATE_KIND_MAP) | `packages/studyloop/src/studyloop/session/transports/acp_normaliser.py` |
| Live console Alpine + WS handler (modify) | `packages/studyloop/src/studyloop/web/static/index.html` |
| CSS — chat panel + bubble + tool-call styles (extend) | `packages/studyloop/src/studyloop/web/static/style.css` |
| Chat UI tests (extend) | `packages/studyloop/tests/test_web_acp_chat_ui.py` |
| Normaliser unit tests (extend OR create) | `packages/studyloop/tests/test_acp_normaliser.py` |
| Stub agent (don't modify — U9 finished) | `packages/studyloop/tests/_stub_acp_agent.py` |

---

## ACP Event Shape Reference (re-state, focused on U5)

| `AgentMessage.kind` | Source | Payload |
|---|---|---|
| `plan` | `session/update` `plan` | `{steps: [{title, status}]}` |
| `plan_update` | `session/update` `plan_update` | `{steps: [...]}` (replaces previous) |

Step `status` values observed: `pending`, `in_progress`, `completed`, `failed`. **Confirm the live ACP CLI emits exactly these strings before depending on them in CSS class names** — if they differ, normalise in the WS handler, not in CSS.

---

## What NOT to do in U5

- **Do not** remove dead xterm `agent_chunk → term.write` branches — that's U8's job.
- **Do not** migrate `TestAgentChunkRendersInXterm` or `TestAcpInputRow` failing tests — that's U7's job.
- **Do not** push `main` to origin — stay local.
- **Do not** modify `_stub_acp_agent.py` further — U9 is done; use existing env vars.
- **Do not** add a sticky top panel for the plan — inline in the chat scroll, per Approach.
- **Do not** keep plan history — latest replaces previous.
- **Do not** paste HTML/CSS/test code into the subagent brief — point at plan section + precedent SHA.

---

## Risks Carried Forward to U5

| Risk | Mitigation |
|------|------------|
| `plan_update` arrives before `plan` (out-of-order) | Defensively initialise `this.plan = {steps: []}` on first sight of either |
| Wire-string discriminator differs from `plan` / `plan_update` | Add explicit `UPDATE_KIND_MAP` entries; verify against live ACP CLI before relying on passthrough |
| Step `status` strings differ from `pending|in_progress|completed|failed` | Normalise in WS handler, not in CSS |
| Concurrent file modification by parallel subagents | Single-agent dispatch only — U5 modifies normaliser + index.html + style.css + 2 test files |
| Empty `plan.steps` array or `{}` payload | Tests cover both — guard in template (`<template x-if="plan && plan.steps">`) |
