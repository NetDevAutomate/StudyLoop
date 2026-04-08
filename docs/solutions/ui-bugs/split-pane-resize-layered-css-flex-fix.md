---
title: "Web UI Split-Pane Resize Bug — Multi-Layer Layout Failure"
date: 2026-04-08
category: ui-bugs
tags:
  - css
  - layout
  - split-pane
  - flexbox
  - fastapi
  - alpine-js
  - htmx
  - sse
  - split-js
  - tmux
  - sigwinch
  - playwright
  - test-isolation
severity: high
component: studyctl web UI (FastAPI + Alpine.js PWA)
symptoms:
  - Dragging the split-pane divider resized the terminal panel but not the dashboard panel
  - Visual gaps appeared between dashboard content and the drag gutter after resize
  - Tests passed in headless and headed Playwright but the bug was visible to the user
  - Dashboard content height remained at intrinsic content height regardless of panel size
root_cause: >
  Three compounding layout failures plus an architectural incompatibility.
  (1) calc(100vh - 60px) hardcoded header height at 60px when actual was ~63.5px.
  (2) Inner session-dashboard content did not flex-fill the Split.js panel.
  (3) Activity feed was wrapped in a classless <div hx-ext="sse"> — CSS targeted
  the nested .activity-feed instead of the wrapper flex child.
  (4) Split-pane resize sent SIGWINCH to tmux, corrupting the Claude Code agent session.
  Resolved by replacing split-pane with sidebar activity feed + full terminal + status bar.
---

# Split-Pane Resize Bug — Multi-Layer CSS/Flex Failure

## Problem

The web UI study session view used a Split.js split-pane layout with dashboard (top) and terminal (bottom) panels. Dragging the divider resized the terminal but the dashboard panel appeared not to resize — a visible gap appeared between the dashboard content and the divider.

Tests passed in all environments (headless Chromium, headed Chromium) because they measured `offsetHeight` of the panel element, which Split.js updated correctly. The bug was in the visual rendering of content *inside* the panel.

## Investigation Steps

1. Built data-driven test infrastructure with `_measure_all()` JS function capturing all DOM metrics via Playwright. Tests measured `offsetHeight`, `getBoundingClientRect()`, and computed styles for every element in the split layout.

2. Discovered tests produced **false positives** without real ttyd — the terminal iframe was absent, and the layout engine computed simpler dimensions that satisfied assertions. Switched all layout tests (R01-R12) to use real tmux + ttyd fixtures.

3. Added `dashboard_fill_ratio` measurement (content height / panel height). Even with this, the ratio was 1.0 because `session-dashboard` was correctly filling the panel — the gap was *inside* the session-dashboard, between the last content element and the bottom of the flex container.

4. Added diagnostic background colours (red=panel, blue=session-dashboard, green=activity-feed) and measured every child element. Found the activity feed was stuck at exactly 200px (`min-height`) despite having `flex: 1` applied.

5. Discovered the third child of session-dashboard had `class: ""` — it was the `<div hx-ext="sse">` wrapper, not `.activity-feed`. CSS `flex: 1` was applied to `.activity-feed` (nested inside the wrapper), not the wrapper itself.

6. After fixing all CSS issues, discovered that drag-resizing the terminal iframe sent SIGWINCH to the tmux session, corrupting the Claude Code agent running in the adjacent pane.

## Root Cause

### RC-1: Hardcoded Header Height Mismatch

```css
/* Broke layout when header rendered at 63.5px, not 60px */
.split-container {
  height: calc(100vh - 60px);
}
```

Fix: `position: absolute; inset: 0` inside a `position: relative` content-area — fills exactly regardless of header height.

### RC-2: Inner Content Not Stretching

Split.js correctly set panel `offsetHeight`, but `.session-dashboard` was a flex column that sized to content rather than filling its parent. Fix: `flex: 1; min-height: 0` on the session-dashboard.

### RC-3: Classless SSE Wrapper as Unintended Flex Child

```html
<div hx-ext="sse">           <!-- no class — actual flex child -->
  <div class="activity-feed"> <!-- CSS targeted this, not the wrapper -->
```

Fix: target the wrapper directly:

```css
.split-dashboard .session-dashboard > [hx-ext="sse"] {
  flex: 1 1 0px;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
```

### RC-4: SIGWINCH Corruption (Architectural)

Resizing the terminal iframe triggered SIGWINCH in the tmux session, corrupting the Claude Code agent. This is a fundamental incompatibility between dynamically resized iframes and interactive agent sessions.

## Solution

Replaced the split-pane architecture entirely:

```
┌─────────────────────────────────────┐
│  Header / Nav                       │
├──────────────┬──────────────────────┤
│  Sidebar     │  Full-screen         │
│  Nav buttons │  Terminal (ttyd)     │
│  Activity    │                      │
│  Feed (SSE)  │                      │
├──────────────┴──────────────────────┤
│  Status Bar: timer ⏸↺■ topic ⚡7 ✓○▲│
└─────────────────────────────────────┘
```

- **Sidebar**: fixed width, nav buttons + scrollable activity feed (SSE-driven)
- **Content area**: 100% terminal iframe — no resize, no SIGWINCH after initial load
- **Bottom status bar**: timer + pause/reset/stop + topic + energy + counters

Split.js and `splitLayout()` Alpine component remain for the body-double view (where the timer iframe doesn't interact with tmux).

### Test Infrastructure Built

- **STUDYCTL_SESSION_DIR** env var for test isolation — tests never touch `~/.config/studyctl/`
- **18 Playwright E2E tests** with real tmux + ttyd
- **`_measure_all()`** JS function captures all DOM metrics in one call
- **`results.json`** written after every run for agent loop consumption
- **16 pure verifier functions** (`verify_R01` through `verify_R16`)

## Key Learnings

1. **Test what users see, not what the DOM reports.** `offsetHeight` was correct throughout — the bug was that content didn't fill the allocated space. The right metric was fill ratio, not panel height.

2. **`min-height: 0` is mandatory for scrollable flex children.** Without it, the browser's minimum content size constraint overrides `flex: 1`.

3. **Avoid `calc(100vh - Npx)` magic numbers.** `position: absolute; inset: 0` inside a positioned parent is robust and measurement-free.

4. **Target the actual flex child, not its descendant.** HTMX/Alpine inject wrapper elements that become unintended flex children. Always verify the DOM hierarchy in DevTools before writing flex CSS.

5. **SIGWINCH and agent sessions are incompatible.** Any UI widget that resizes a terminal iframe sends SIGWINCH to every process in the underlying tmux session. Keep terminal iframes at a stable size after initial load.

6. **False positives emerge without real dependencies.** Layout tests without a live ttyd produced false positives because the iframe was absent. Always test against the full dependency stack.

## Prevention Strategies

- **Real dependencies in tests**: Use real tmux + ttyd in layout tests. If a dependency can't start in CI, skip rather than fake.
- **Name every flex child**: If a component is rendered inside a flex container, its outermost element must have an explicit class.
- **SIGWINCH complexity threshold**: If adding a feature requires cross-process signal propagation, evaluate whether the feature justifies the coupling.
- **Machine-readable results**: Emit `results.json` for any test measuring quantitative layout values.
- **Isolation fixtures**: Every test touching session state must use `STUDYCTL_SESSION_DIR` via a session-scoped fixture.

## Related Documentation

- [Four-bug-fix solutions](../integration-issues/web-ui-four-bug-fix-pomodoro-auth-ttyd-cleanup.md) — predecessor session fixes (pomodoro, auth, ttyd cleanup)
- [Data-driven test design spec](../../superpowers/specs/2026-04-07-data-driven-split-pane-tests-design.md) — autoagent-inspired test infrastructure design
- [C4 Architecture](../../architecture-c4.md) — updated to reflect sidebar+terminal+status bar layout
- [tmux session management](../../internal/solutions/tmux-session-management-and-ci-issues.md) — SIGWINCH context and tmux test isolation patterns
- [CI workflow failures](../test-failures/ci-workflow-failures-schema-init-pytest-markers.md) — false positive patterns and marker discipline
